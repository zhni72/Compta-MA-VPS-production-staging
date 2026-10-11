"""Tests de la cessation / cession d'activité (P2.2).

Verifie les **régimes TVA 3 et 4** (annexe 1 EDI Simpl-TVA « correspondance balise
RD V4.0 » : régime 3 = cessation temporaire, régime 4 = cession ou cessation,
**période 1**), les **délais légaux** (CGI art. 114 : 30 jours ; art. 150-I : 45
jours ; art. 150 bis : mois suivant la clôture), la **TVA de la période de sortie**,
la **régularisation des déductions** (immobilisations : art. 102 / 104-II-1° ;
stocks : montant saisi), le **relevé des déductions EDI** au régime 3/4 et le
**registre des déclarations** (`tax_declarations`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.rates_ma import money
from app.db.seed import get_or_create_fiscal_year
from app.models import (
    Asset,
    AuditLog,
    DELAI_DECLARATION_TVA_JOURS,
    REGIME_TVA_CESSATION_TEMPORAIRE,
    REGIME_TVA_CESSION_CESSATION,
    TYPE_CESSATION,
    TYPE_CESSATION_TEMPORAIRE,
    TYPE_CESSION,
    regime_tva_pour_type,
)
from app.services import activity_events as activite
from app.services import edi_tva
from app.services.accounting import create_entry, get_journal
from app.services.invoicing import create_invoice, register_payment, validate_invoice
from app.services.parties import create_third_party

pytestmark = pytest.mark.usefixtures("ctx")

ANNEE = 2026
JOUR_CESSION = date(2026, 6, 30)


def _tiers(db, ctx, kind: str, nom: str, **extra):
    """Fiche client ou fournisseur (identifiants requis pour les contrôles EDI)."""
    parametres = {
        "company": ctx["company"],
        "kind": kind,
        "name": nom,
        "ice": "001524628000001",
        "fiscal_id": "1086826",
        "payment_terms_days": 0,
    }
    parametres.update(extra)
    return create_third_party(db, **parametres)


def _vente(db, ctx, *, jour: date = date(2026, 2, 10), ht: str = "10000"):
    """Facture de vente validée (TVA collectée au 4455)."""
    client = _tiers(db, ctx, "client", "Client Cession SARL")
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=jour,
        payment_mode="virement",
        lines=[
            {
                "designation": "Prestation de services",
                "quantity": 1,
                "unit_price": Decimal(ht),
                "vat_rate": Decimal("20"),
                "account_number": "7121",
            }
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    return facture


def _achat_regle(db, ctx, *, jour: date = date(2026, 3, 10), reglement: date = date(2026, 6, 15)):
    """Facture d'achat validée et réglée (TVA déductible + ligne de relevé EDI)."""
    fournisseur = _tiers(db, ctx, "fournisseur", "Fournisseur Cession SARL")
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=jour,
        payment_mode="espece",
        lines=[
            {
                "designation": "Fournitures de bureau",
                "quantity": 1,
                "unit_price": Decimal("2000"),
                "vat_rate": Decimal("20"),
                "account_number": "61455",
            }
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    register_payment(db, facture, amount="2400.00", payment_date=reglement, method="espece")
    db.commit()
    return facture


def _immobilisation(db, ctx, *, tva: str = "12000", acquisition: date = date(2024, 1, 1), duree: int = 5):
    """Fiche d'immobilisation avec TVA déductible (régularisation art. 102 / 104).

    La fiche est créée directement en base : le parcours de création complet est
    couvert par les tests du module immobilisations (J2).
    """
    bien = Asset(
        company_id=ctx["company"].id,
        code="IM202600001",
        label="Matériel de bureau",
        account_number="2333",
        acquisition_date=acquisition,
        service_date=acquisition,
        valeur_origine=Decimal("72000"),
        duree_annees=duree,
        tva_montant=Decimal(tva),
        tva_compte="34551",
    )
    db.add(bien)
    db.commit()
    return bien


def _evenement(db, ctx, type_evenement: str, jour: date = JOUR_CESSION, **extra):
    """Crée un événement de vie (motif et repreneur fournis par défaut)."""
    parametres = {
        "type": type_evenement,
        "date_effet": jour,
        "motif": extra.pop("motif", "Cessation d'activité pour raison personnelle"),
        "repreneur_nom": extra.pop("repreneur_nom", "Repreneur SARL"),
        "user_id": ctx["user"].id,
    }
    parametres.update(extra)
    return activite.creer_evenement(db, ctx["company"], **parametres)


# ---------------------------------------------------------------------------
# Regimes TVA et création des evenements
# ---------------------------------------------------------------------------
def test_regime_tva_par_type_d_evenement():
    """Régime 3 = cessation temporaire ; régime 4 = cession ou cessation."""
    assert regime_tva_pour_type(TYPE_CESSATION_TEMPORAIRE) == REGIME_TVA_CESSATION_TEMPORAIRE == 3
    assert regime_tva_pour_type(TYPE_CESSION) == REGIME_TVA_CESSION_CESSATION == 4
    assert regime_tva_pour_type(TYPE_CESSATION) == REGIME_TVA_CESSION_CESSATION
    with pytest.raises(ValueError):
        regime_tva_pour_type("fusion")


def test_creation_cessation_temporaire_regime_3_et_delais(db, ctx):
    """La cessation temporaire porte le régime 3, période 1, et ses délais légaux."""
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    db.commit()
    evenement = _evenement(
        db, ctx, TYPE_CESSATION_TEMPORAIRE, date(2026, 12, 31), repreneur_nom=None
    )
    assert evenement.regime_tva == 3
    assert evenement.periode == 1
    assert evenement.type_libelle.startswith("Cessation temporaire")
    delais = activite.delais(evenement)
    # CGI art. 114 : 30 jours ; CGI art. 150 bis : mois suivant la clôture
    assert delais["echeance_tva"] == date(2027, 1, 30)
    assert delais["echeance_cessation_temporaire"] == date(2027, 1, 31)
    assert delais["delai_tva_jours"] == DELAI_DECLARATION_TVA_JOURS == 30
    assert delais["echeance_declaration_art_150"] == date(2027, 2, 14)
    assert "régime 3" in delais["reference_regime"]
    journal = db.execute(
        select(AuditLog).where(AuditLog.action == "ACTIVITY_EVENT_CREATED")
    ).scalars().all()
    assert len(journal) == 1


def test_creation_cessation_temporaire_exige_un_motif(db, ctx):
    """CGI art. 150 bis : la déclaration doit indiquer les motifs de la cessation."""
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    db.commit()
    with pytest.raises(activite.ActiviteError) as erreur:
        activite.creer_evenement(
            db,
            ctx["company"],
            type=TYPE_CESSATION_TEMPORAIRE,
            date_effet=date(2026, 12, 31),
        )
    assert "motif" in str(erreur.value)


def test_creation_cession_exige_le_repreneur_et_type_valide(db, ctx):
    """Une cession est nominative ; un type inconnu ou un exercice absent sont refusés."""
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    db.commit()
    with pytest.raises(activite.ActiviteError):
        activite.creer_evenement(
            db, ctx["company"], type=TYPE_CESSION, date_effet=JOUR_CESSION
        )
    with pytest.raises(activite.ActiviteError):
        _evenement(db, ctx, "fusion")
    with pytest.raises(Exception):
        _evenement(db, ctx, TYPE_CESSION, date(2019, 6, 30))
    evenement = _evenement(db, ctx, TYPE_CESSION)
    assert evenement.regime_tva == 4
    assert evenement.repreneur_nom == "Repreneur SARL"


def test_chronologie_des_evenements_est_controlee(db, ctx):
    """Deux événements à la même date, ou dans le désordre, sont refusés."""
    _evenement(db, ctx, TYPE_CESSION)
    with pytest.raises(activite.ActiviteError) as erreur:
        _evenement(db, ctx, TYPE_CESSION)
    assert "déjà enregistré" in str(erreur.value)
    with pytest.raises(activite.ActiviteError) as erreur:
        _evenement(db, ctx, TYPE_CESSATION, date(2026, 3, 31))
    assert "antérieure" in str(erreur.value)
    assert [evenement.type for evenement in activite.list_evenements(db, ctx["company"].id)] == [
        TYPE_CESSION
    ]


def test_periode_declaration_du_debut_de_l_exercice_a_la_date_effet(db, ctx):
    """La période part du 1ᵉʳ janvier, ou du lendemain du dernier événement."""
    premier = _evenement(db, ctx, TYPE_CESSION, date(2026, 6, 30))
    assert activite.periode_declaration(db, ctx["company"].id, premier) == (
        date(2026, 1, 1),
        date(2026, 6, 30),
    )
    second = _evenement(db, ctx, TYPE_CESSATION, date(2026, 9, 30), repreneur_nom=None)
    assert activite.periode_declaration(db, ctx["company"].id, second) == (
        date(2026, 7, 1),
        date(2026, 9, 30),
    )


# ---------------------------------------------------------------------------
# TVA de la periode de sortie et regularisation des deductions
# ---------------------------------------------------------------------------
def test_declaration_tva_de_la_periode_de_sortie(db, ctx):
    """La déclaration reprend la TVA collectée, déductible et nette de la période."""
    _vente(db, ctx)
    _achat_regle(db, ctx)
    evenement = _evenement(db, ctx, TYPE_CESSION)
    declaration = activite.declaration_tva_sortie(db, ctx["company"], evenement)
    assert declaration["regime"] == 4
    assert declaration["periode"] == 1
    assert declaration["date_from"] == date(2026, 1, 1)
    assert declaration["date_to"] == JOUR_CESSION
    # Vente 10 000 HT -> 2 000 de TVA collectée ; achat 2 000 HT -> 400 déductibles
    assert declaration["tva_collectee"] == Decimal("2000.00")
    assert declaration["tva_deductible"] == Decimal("400.00")
    assert declaration["tva_nette"] == Decimal("1600.00")
    assert declaration["delais"]["echeance_tva"] == date(2026, 7, 30)


def test_regularisation_des_immobilisations_en_service(db, ctx):
    """Régularisation des biens amortissables (CGI art. 102 et 104-II-1°)."""
    _immobilisation(db, ctx, tva="12000", acquisition=date(2024, 1, 1))
    _achat_regle(db, ctx)
    evenement = _evenement(db, ctx, TYPE_CESSION)
    regularisation = activite.regularisation_deductions(db, ctx["company"], evenement)
    assert len(regularisation["lignes_immobilisations"]) == 1
    ligne = regularisation["lignes_immobilisations"][0]
    assert ligne["code"] == "IM202600001"
    assert ligne["annees_restantes"] == 3  # 5 ans, utilisée depuis 2024
    assert ligne["montant"] == Decimal("7200.00")  # 12 000 × 3/5
    assert regularisation["total_immobilisations"] == Decimal("7200.00")
    assert regularisation["montant_stocks_a_saisir"] is True
    assert regularisation["total"] == Decimal("7200.00")
    assert "art. 114" in regularisation["references"]
    assert "A23" in regularisation["avertissement"]


def test_regularisation_ignore_les_biens_deja_sortis(db, ctx):
    """Un bien déjà cédé a été régularisé lors de sa sortie : il n'est pas repris."""
    bien = _immobilisation(db, ctx, acquisition=date(2024, 1, 1))
    bien.disposal_date = date(2026, 2, 28)
    db.commit()
    _achat_regle(db, ctx)
    evenement = _evenement(db, ctx, TYPE_CESSION)
    regularisation = activite.regularisation_deductions(db, ctx["company"], evenement)
    assert regularisation["lignes_immobilisations"] == []
    assert regularisation["total"] == Decimal("0.00")


def test_regularisation_stocks_saisie_et_total(db, ctx):
    """La TVA sur stocks est saisie : elle s'ajoute au total à payer."""
    _immobilisation(db, ctx, tva="12000", acquisition=date(2024, 1, 1))
    _vente(db, ctx)
    _achat_regle(db, ctx)
    evenement = _evenement(db, ctx, TYPE_CESSION)
    declaration = activite.declaration_tva_sortie(
        db, ctx["company"], evenement, montant_stocks="500"
    )
    assert declaration["regularisation"]["montant_stocks"] == Decimal("500.00")
    assert declaration["regularisation"]["montant_stocks_a_saisir"] is False
    assert declaration["regularisation_totale"] == money(Decimal("7200.00") + Decimal("500"))
    # TVA nette 1 600 + régularisations 7 700 = total à payer
    assert declaration["total_a_payer"] == Decimal("9300.00")


# ---------------------------------------------------------------------------
# Controles, registre et fichier EDI
# ---------------------------------------------------------------------------
def test_controles_activite_signalent_les_points_a_traiter(db, ctx):
    """Motif, régularisation des stocks, déclaration non déposée, écritures après effet."""
    _vente(db, ctx)
    _achat_regle(db, ctx)
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    db.commit()
    # Écriture postérieure à la date d'effet (reprise d'activité simulée)
    create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_or_create_fiscal_year(db, ctx["company"], ANNEE),
        journal=get_journal(db, ctx["company"].id, "OD"),
        entry_date=date(2026, 9, 15),
        label="Achat consommable",
        lines=[
            {"account_number": "61455", "debit": "100", "label": "Consommables"},
            {"account_number": "4411", "credit": "100", "label": "Fournisseur"},
        ],
        validate=True,
    )
    db.commit()
    evenement = _evenement(db, ctx, TYPE_CESSION, date(2026, 6, 30))
    codes = {
        controle["code"]: controle
        for controle in activite.controles_activite(db, ctx["company"], evenement)
    }
    assert codes["activite.regularisation_stocks_a_examiner"]["niveau"] == "avertissement"
    assert codes["activite.tva_non_declaree"]["niveau"] == "avertissement"
    assert codes["activite.ecritures_apres_effet"]["niveau"] == "avertissement"
    assert codes["activite.recap"]["niveau"] == "information"
    assert "total à payer" in codes["activite.recap"]["message"]
    assert activite.controles_bloquants(list(codes.values())) == []


def test_controle_bloquant_si_echeance_de_30_jours_depassee(db, ctx):
    """Sans accusé de réception, le dépassement des 30 jours est bloquant."""
    evenement = _evenement(db, ctx, TYPE_CESSION, date(2026, 6, 30))
    assert activite.echeance_tva(evenement) == date(2026, 7, 30)  # < aujourd'hui
    activite.enregistrer_declaration_tva(db, ctx["company"], evenement)
    db.commit()
    codes = {
        controle["code"]: controle
        for controle in activite.controles_activite(db, ctx["company"], evenement)
    }
    assert codes["activite.echeance_tva_depassee"]["niveau"] == "bloquant"
    assert "art. 114" in codes["activite.echeance_tva_depassee"]["message"]


def test_enregistrer_declaration_tva_au_registre_et_figeage(db, ctx):
    """Le registre porte le régime, la période 1 et l'impôt à payer ; puis figeage."""
    _vente(db, ctx)
    evenement = _evenement(db, ctx, TYPE_CESSION)
    registre = activite.enregistrer_declaration_tva(db, ctx["company"], evenement)
    db.commit()
    assert registre.type == "TVA"
    assert registre.periode == "2026"
    assert registre.regime == "4"
    assert registre.statut == "brouillon"
    assert registre.montant == Decimal("2000.00")
    assert evenement.declaration_id == registre.id
    assert "régime 4 / période 1" in (registre.notes or "")

    # Idempotence, puis figeage après dépôt et accusé de réception
    activite.enregistrer_declaration_tva(db, ctx["company"], evenement)
    db.commit()
    assert activite.declaration_registre(db, ctx["company"].id, evenement).id == registre.id
    activite.soumettre_declaration(db, registre, jour=date(2026, 7, 10))
    activite.soumettre_declaration(db, registre, accuse_le=date(2026, 7, 15))
    db.commit()
    assert registre.statut == "acceptee"
    assert registre.accuse_le == date(2026, 7, 15)
    with pytest.raises(activite.ActiviteError):
        activite.enregistrer_declaration_tva(db, ctx["company"], evenement)


def test_releve_des_deductions_edi_au_regime_4(db, ctx):
    """Le fichier EDI porte `<regime>4</regime>` et `<periode>1</periode>`."""
    _achat_regle(db, ctx)
    evenement = _evenement(db, ctx, TYPE_CESSION)
    fichier = activite.construire_rd_sortie(db, ctx["company"], evenement)
    assert fichier["regime"] == 4
    assert fichier["periode"] == 1
    assert "<regime>4</regime>" in fichier["xml"]
    assert "<periode>1</periode>" in fichier["xml"]
    assert "<annee>2026</annee>" in fichier["xml"]
    assert fichier["nom_fichier"] == "ReleveDeductions_2026_CessionCessation_1.xml"
    assert fichier["releve"]["totaux"]["nb_lignes"] == 1


def test_releve_edi_refuse_sans_ligne_et_periodes_des_regimes_activite(db, ctx):
    """Un relevé vide est refusé ; la période doit être 1 pour les régimes 3 et 4."""
    evenement = _evenement(db, ctx, TYPE_CESSION)
    with pytest.raises(edi_tva.EdiTvaError):
        activite.construire_rd_sortie(db, ctx["company"], evenement)
    edi_tva.validate_period(3, 1)
    edi_tva.validate_period(4, 1)
    with pytest.raises(edi_tva.EdiTvaError):
        edi_tva.validate_period(3, 4)
    assert edi_tva.xml_filename(2026, 1, 3) == "ReleveDeductions_2026_CessationTemporaire_1.xml"
    assert edi_tva.xml_filename(2026, 1, 4) == "ReleveDeductions_2026_CessionCessation_1.xml"


def test_situation_de_l_activite(db, ctx):
    """La situation restitue l'événement, la déclaration, le registre et les références."""
    _vente(db, ctx)
    assert activite.situation(db, ctx["company"], annee=ANNEE)["en_activite"] is True

    evenement = _evenement(db, ctx, TYPE_CESSION)
    activite.enregistrer_declaration_tva(db, ctx["company"], evenement)
    db.commit()
    situation = activite.situation(db, ctx["company"], annee=ANNEE)
    assert situation["en_activite"] is False
    assert situation["evenement"].id == evenement.id
    assert situation["registre"].regime == "4"
    assert situation["declaration"]["regime"] == 4
    assert "CGI art. 114" in situation["references"]["evenements"]
    assert "art. 150 bis" in situation["references"]["cessation_temporaire"]
    assert [evenement.id for evenement in situation["evenements"]] == [evenement.id]