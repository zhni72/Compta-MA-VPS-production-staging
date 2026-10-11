"""Tests du module Immobilisations & amortissements (P1.2).

Verifie : derivation des comptes CGNC (2xxx -> 28x / 619x), amortissements
lineaire et degressif, prorata temporis (CGI art. 10), dotations comptabilisees,
cessions et mises au rebut (sortie d'actif soldee), regularisation de TVA
(CGI art. 106), etats du module et controles de coherence.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Account, Entry, FiscalYear, Invoice, InvoiceLine
from app.services import assets as svc
from app.services.accounting import AccountingError, create_entry, get_journal
from app.services.invoicing import create_invoice, validate_invoice
from app.services.parties import create_third_party
from app.services.reporting import movements

pytestmark = pytest.mark.usefixtures("ctx")


def _fiche(db, ctx, **kwargs):
    """Cree une fiche d'immobilisation amortissable type (materiel et outillage)."""
    parametres = {
        "company": ctx["company"],
        "label": "Materiel informatique",
        "account_number": "2332",
        "acquisition_date": date(2026, 1, 5),
        "valeur_origine": Decimal("12000.00"),
        "duree_annees": 5,
        "service_date": date(2026, 1, 5),
    }
    parametres.update(kwargs)
    return svc.creer_immobilisation(db, **parametres)


def _exercice(db, ctx, annee: int) -> FiscalYear:
    """Ajoute un exercice comptable ouvert (pour les plans pluriannuels)."""
    exercice = FiscalYear(
        company_id=ctx["company"].id,
        year=annee,
        start_date=date(annee, 1, 1),
        end_date=date(annee, 12, 31),
        status="open",
    )
    db.add(exercice)
    db.flush()
    return exercice


def _solde_compte(db, ctx, compte: str) -> Decimal:
    """Solde d'un compte (cumul depuis l'origine) d'apres les ecritures validees."""
    lignes = movements(
        db, ctx["company"].id, date(1900, 1, 1), date(2030, 12, 31), prefix=compte
    )
    return sum((ligne["solde"] for ligne in lignes), Decimal("0"))


# ---------------------------------------------------------------------------
# Derivation des comptes CGNC
# ---------------------------------------------------------------------------
def test_derivation_des_comptes_structurelle(db, ctx):
    """Toute immobilisation du plan derive un 28x et un 619x existants (ou est exclue)."""
    comptes = list(
        db.execute(
            select(Account.number, Account.label).where(
                Account.number.like("2%"),
                ~Account.number.like("28%"),
                ~Account.number.like("29%"),
            )
        ).all()
    )
    assert len(comptes) > 30
    non_amortissables = 0
    for numero, _ in comptes:
        info = svc.comptes_immobilisation(db, numero)
        if not info["amortissable"]:
            non_amortissables += 1
            assert info["motif"], f"{numero} non amortissable sans motif"
            continue
        assert db.execute(
            select(Account.number).where(Account.number == info["amortissement"])
        ).scalar_one_or_none(), f"amortissement {info['amortissement']} absent ({numero})"
        assert db.execute(
            select(Account.number).where(Account.number == info["dotation"])
        ).scalar_one_or_none(), f"dotation {info['dotation']} absent ({numero})"
        assert numero[1:3] == info["amortissement"][2:]
    assert non_amortissables >= 5  # immobilisations financieres et en cours


def test_derivation_cas_particuliers():
    """Comptes derives, immobilisations financieres et immobilisations en cours."""
    assert svc.comptes_amortissement("2332")["amortissement"] == "2833"
    assert svc.comptes_amortissement("2332")["dotation"] == "61933"
    assert svc.comptes_amortissement("2340")["dotation"] == "61934"
    assert svc.comptes_amortissement("23512")["amortissement"] == "2835"
    assert svc.comptes_amortissement("2220")["dotation"] == "61922"
    assert svc.comptes_amortissement("2410")["amortissable"] is False
    assert svc.comptes_amortissement("2392")["amortissable"] is False
    assert svc.est_immeuble("2321") is True
    assert svc.est_immeuble("2332") is False
    assert svc.compte_vna("2340") == "6513"
    assert svc.compte_produit_cession("2220") == "7512"


def test_coefficient_degressif_parametrable():
    """Le coefficient du degressif depend de la duree et reste parametrable (A4)."""
    assert svc.coefficient_degressif(3) == Decimal("1.5")
    assert svc.coefficient_degressif(5) == Decimal("2.0")
    assert svc.coefficient_degressif(10) == Decimal("2.5")


# ---------------------------------------------------------------------------
# Fiche d'immobilisation
# ---------------------------------------------------------------------------
def test_creation_fiche_et_numero_automatique(db, ctx):
    """Creation d'une fiche : numero automatique, compte TVA 34551, evenement trace."""
    fiche = _fiche(db, ctx)
    assert fiche.code == "IM202600001"
    assert fiche.tva_compte == "34551"
    assert fiche.statut == "en_service"
    assert fiche.prorata_temporis is True
    assert [e.event_type for e in fiche.events] == ["acquisition"]
    assert svc.comptes_immobilisation(db, fiche.account_number)["dotation"] == "61933"


def test_creation_immobilisation_avec_ecriture_acquisition(db, ctx):
    """Acquisition comptabilisee : 2xxx + TVA au 34551 (jamais au 34552)."""
    fiche = _fiche(
        db,
        ctx,
        valeur_origine=Decimal("50000.00"),
        tva_montant=Decimal("10000.00"),
        comptabiliser=True,
        compte_contrepartie="4411",
    )
    evenement = [e for e in fiche.events if e.event_type == "acquisition"][0]
    assert evenement.entry_id is not None
    ecriture = db.get(Entry, evenement.entry_id)
    lignes = {
        ligne.account_number: (ligne.debit, ligne.credit) for ligne in ecriture.lines
    }
    assert lignes["2332"] == (Decimal("50000.00"), Decimal("0.00"))
    assert lignes["34551"] == (Decimal("10000.00"), Decimal("0.00"))
    assert lignes["4411"] == (Decimal("0.00"), Decimal("60000.00"))
    assert "34552" not in lignes  # la TVA d'immobilisation n'est jamais au 34552
    assert ecriture.is_balanced is True
    assert ecriture.entry_number


def test_controles_bloquants_de_la_fiche(db, ctx):
    """Refus : duree nulle, valeur residuelle, mise en service anterieure, hors 2xxx."""
    with pytest.raises(AccountingError, match="duree d'amortissement"):
        _fiche(db, ctx, duree_annees=0)
    with pytest.raises(AccountingError, match="valeur residuelle"):
        _fiche(db, ctx, valeur_residuelle=Decimal("12000.00"))
    with pytest.raises(AccountingError, match="mise en service"):
        _fiche(db, ctx, service_date=date(2025, 12, 31))
    with pytest.raises(AccountingError, match="classe 2"):
        _fiche(db, ctx, account_number="6111")
    with pytest.raises(AccountingError, match="degressif"):
        _fiche(db, ctx, account_number="2410", mode="degressif", duree_annees=0)
    with pytest.raises(AccountingError, match="valeur d'origine"):
        _fiche(db, ctx, valeur_origine=Decimal("0"))


# ---------------------------------------------------------------------------
# Plan d'amortissement
# ---------------------------------------------------------------------------
def test_plan_lineaire_avec_prorata_temporis(db, ctx):
    """Prise en service en octobre : 3/12 la premiere annee, plan sur 6 exercices."""
    fiche = _fiche(db, ctx, service_date=date(2026, 10, 1))
    plan = svc.plan_amortissement(fiche)
    annuites = [ligne["annuite"] for ligne in plan]
    assert annuites == [
        Decimal("600.00"),
        Decimal("2400.00"),
        Decimal("2400.00"),
        Decimal("2400.00"),
        Decimal("2400.00"),
        Decimal("1800.00"),
    ]
    assert [ligne["exercice"] for ligne in plan] == [2026, 2027, 2028, 2029, 2030, 2031]
    assert plan[-1]["cumul"] == Decimal("12000.00")
    assert plan[-1]["vnc"] == Decimal("0.00")
    # Critere d'acceptation : Σ amortissements cumules + VNC = valeur d'origine
    for ligne in plan:
        assert ligne["cumul"] + ligne["vnc"] == fiche.valeur_origine


def test_plan_lineaire_annuite_pleine_sans_prorata(db, ctx):
    """Option comptable « annee pleine » : la premiere annuite n'est pas reduite."""
    fiche = _fiche(db, ctx, service_date=date(2026, 10, 1), prorata_temporis=False)
    plan = svc.plan_amortissement(fiche)
    assert [ligne["annuite"] for ligne in plan] == [Decimal("2400.00")] * 5
    assert plan[-1]["cumul"] == Decimal("12000.00")


def test_plan_degressif_avec_bascule_lineaire(db, ctx):
    """Degressif : coefficient 2 (duree 5 ans), bascule en lineaire quand favorable."""
    fiche = _fiche(
        db,
        ctx,
        label="Machine industrielle",
        valeur_origine=Decimal("10000.00"),
        duree_annees=5,
        mode="degressif",
        acquisition_date=date(2026, 1, 1),
        service_date=date(2026, 1, 1),
    )
    assert fiche.coefficient == Decimal("2.00")
    plan = svc.plan_amortissement(fiche)
    assert [ligne["annuite"] for ligne in plan] == [
        Decimal("4000.00"),
        Decimal("2400.00"),
        Decimal("1440.00"),
        Decimal("1080.00"),
        Decimal("1080.00"),
    ]
    assert plan[-1]["cumul"] == Decimal("10000.00")
    assert plan[-1]["vnc"] == Decimal("0.00")


def test_plan_respecte_la_valeur_residuelle_et_le_plafond(db, ctx):
    """La derniere annuite est plafonnee : la VNC ne passe pas sous la valeur residuelle."""
    fiche = _fiche(
        db,
        ctx,
        valeur_origine=Decimal("10000.00"),
        valeur_residuelle=Decimal("1000.00"),
        duree_annees=3,
    )
    plan = svc.plan_amortissement(fiche)
    assert plan[-1]["cumul"] == Decimal("9000.00")  # base amortissable
    assert plan[-1]["vnc"] == Decimal("1000.00")  # valeur residuelle
    assert all(ligne["annuite"] > 0 for ligne in plan)
    assert svc.dotation_exercice(fiche, 2029) == Decimal("0.00")  # au-dela du plan


def test_plan_non_amortissable_est_vide(db, ctx):
    """Une immobilisation financiere (24x) ne produit aucun plan d'amortissement."""
    fiche = _fiche(
        db,
        ctx,
        account_number="2441",
        label="Pret immobilise au personnel",
        duree_annees=0,
        service_date=None,
    )
    assert svc.plan_amortissement(fiche) == []
    assert svc.dotation_exercice(fiche, 2026) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Dotations aux amortissements
# ---------------------------------------------------------------------------
def test_comptabiliser_dotation_ecriture_et_idempotence(db, ctx):
    """Dotation : ecriture 61933 / 2833 validee, ligne de plan, refus du doublon."""
    fiche = _fiche(db, ctx)
    operation = svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)
    assert operation["annuite"] == Decimal("2400.00")
    assert operation["compte_dotation"] == "61933"
    assert operation["compte_amortissement"] == "2833"
    ecriture = operation["entry"]
    assert ecriture.is_balanced is True
    assert ecriture.entry_number
    lignes = {ligne.account_number: (ligne.debit, ligne.credit) for ligne in ecriture.lines}
    assert lignes["61933"] == (Decimal("2400.00"), Decimal("0.00"))
    assert lignes["2833"] == (Decimal("0.00"), Decimal("2400.00"))

    ligne_plan = svc.dotation_constatee(fiche, 2026)
    assert ligne_plan is not None and ligne_plan.entry_id == ecriture.id
    assert ligne_plan.cumul == Decimal("2400.00")
    assert ligne_plan.vnc == Decimal("9600.00")
    assert svc.amortissements_cumules(fiche) == Decimal("2400.00")
    assert svc.valeur_nette_comptable(fiche) == Decimal("9600.00")
    assert [e.event_type for e in fiche.events] == ["acquisition", "dotation"]

    with pytest.raises(AccountingError, match="deja constatee"):
        svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)


def test_dotation_refusee_si_exercice_clos(db, ctx):
    """Aucune dotation sur un exercice clos ou verrouille (P1.6 : verrouillage)."""
    fiche = _fiche(db, ctx)
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == ctx["company"].id, FiscalYear.year == 2026
        )
    ).scalar_one()
    exercice.status = "closed"
    db.flush()
    with pytest.raises(AccountingError, match="saisie interdite"):
        svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)


def test_dotation_en_masse_par_exercice(db, ctx):
    """Traitement en masse : une erreur sur une fiche n'empeche pas les autres."""
    fiche1 = _fiche(db, ctx, label="Fiche A")
    fiche2 = _fiche(db, ctx, label="Fiche B", account_number="2351")
    # La fiche 1 a deja sa dotation : elle sera en erreur, la fiche 2 doit passer.
    svc.comptabiliser_dotation(db, fiche1, 2026, user_id=ctx["user"].id)
    resultats = svc.comptabiliser_dotations(db, ctx["company"], 2026, user_id=ctx["user"].id)
    assert len(resultats) == 2
    par_code = {r["asset"].code: r for r in resultats}
    assert par_code[fiche1.code]["erreur"] is not None
    assert par_code[fiche2.code]["erreur"] is None
    assert par_code[fiche2.code]["compte_dotation"] == "61935"
    assert par_code[fiche2.code]["compte_amortissement"] == "2835"


def test_dotations_sur_deux_exercices_cumulent(db, ctx):
    """Deux exercices consecutifs : le cumul et la VNC se suivent au centime."""
    _exercice(db, ctx, 2027)
    fiche = _fiche(db, ctx)
    svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)
    svc.comptabiliser_dotation(db, fiche, 2027, user_id=ctx["user"].id)
    assert svc.amortissements_cumules(fiche) == Decimal("4800.00")
    assert svc.valeur_nette_comptable(fiche) == Decimal("7200.00")
    plan = svc.plan_amortissement(fiche)
    assert plan[0]["constatee"] is True and plan[1]["constatee"] is True
    assert plan[2]["constatee"] is False
    assert _solde_compte(db, ctx, "2833") == Decimal("-4800.00")
    assert _solde_compte(db, ctx, "61933") == Decimal("4800.00")
    assert svc.dotation_exercice(fiche, 2032) == Decimal("0.00")  # apres le plan



# ---------------------------------------------------------------------------
# Cession, mise au rebut et regularisation de TVA (art. 106)
# ---------------------------------------------------------------------------
def test_cession_ecriture_complete_et_comptes_soldes(db, ctx):
    """Cession : produit, reprise des amortissements, VNA et comptes solde a zero."""
    _exercice(db, ctx, 2027)
    fiche = _fiche(
        db,
        ctx,
        tva_montant=Decimal("0.00"),
        comptabiliser=True,
        compte_contrepartie="4411",
    )
    svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)
    resultat = svc.ceder_immobilisation(
        db,
        fiche,
        date_cession=date(2027, 6, 30),
        prix=Decimal("9000.00"),
        motif="Vente a un tiers",
        user_id=ctx["user"].id,
    )
    assert resultat["cumul"] == Decimal("2400.00")
    assert resultat["vnc"] == Decimal("9600.00")
    assert resultat["resultat_cession"] == Decimal("-600.00")  # moins-value
    assert resultat["comptes"]["vna"] == "6513"
    assert resultat["comptes"]["produit"] == "7513"
    ecriture = resultat["entry"]
    assert ecriture.is_balanced is True
    lignes = {l.account_number: (l.debit, l.credit) for l in ecriture.lines}
    assert lignes["3481"] == (Decimal("9000.00"), Decimal("0.00"))
    assert lignes["2833"] == (Decimal("2400.00"), Decimal("0.00"))
    assert lignes["6513"] == (Decimal("9600.00"), Decimal("0.00"))
    assert lignes["2332"] == (Decimal("0.00"), Decimal("12000.00"))
    assert lignes["7513"] == (Decimal("0.00"), Decimal("9000.00"))

    # Apres cession, le compte d'immobilisation et son amortissement sont soldes.
    assert _solde_compte(db, ctx, "2332") == Decimal("0.00")
    assert _solde_compte(db, ctx, "2833") == Decimal("0.00")
    assert fiche.statut == "cede"
    assert fiche.disposal_price == Decimal("9000.00")
    assert [e.event_type for e in fiche.events] == ["acquisition", "dotation", "cession"]
    with pytest.raises(AccountingError, match="deja sortie de l'actif"):
        svc.comptabiliser_dotation(db, fiche, 2027, user_id=ctx["user"].id)
    with pytest.raises(AccountingError, match="deja sortie de l'actif"):
        svc.ceder_immobilisation(
            db, fiche, date_cession=date(2027, 7, 1), prix=Decimal("1000.00")
        )


def test_cession_avec_tva_de_cession(db, ctx):
    """Cession soumise a TVA : produit HT au 7513 et TVA collectee au 4455."""
    fiche = _fiche(db, ctx)
    resultat = svc.ceder_immobilisation(
        db,
        fiche,
        date_cession=date(2026, 12, 31),
        prix=Decimal("24000.00"),
        tva_taux=Decimal("20"),
        user_id=ctx["user"].id,
    )
    assert resultat["produit_ht"] == Decimal("20000.00")
    assert resultat["tva_cession"] == Decimal("4000.00")
    lignes = {l.account_number: (l.debit, l.credit) for l in resultat["entry"].lines}
    assert lignes["3481"] == (Decimal("24000.00"), Decimal("0.00"))
    assert lignes["7513"] == (Decimal("0.00"), Decimal("20000.00"))
    assert lignes["4455"] == (Decimal("0.00"), Decimal("4000.00"))


def test_cession_exige_un_prix_ou_un_motif(db, ctx):
    """Une cession sans prix ni motif est refusee (controle bloquant)."""
    fiche = _fiche(db, ctx)
    with pytest.raises(AccountingError, match="prix de cession"):
        svc.ceder_immobilisation(db, fiche, date_cession=date(2026, 12, 31), prix=0)
    resultat = svc.ceder_immobilisation(
        db,
        fiche,
        date_cession=date(2026, 12, 31),
        prix=0,
        motif="Cession gratuite exceptionnelle",
        user_id=ctx["user"].id,
    )
    assert resultat["prix"] == Decimal("0.00")
    assert resultat["entry"].is_balanced is True



def test_regularisation_tva_art106_meubles(db, ctx):
    """TVA d'immobilisation deduite : regularisation de 3/5 apres 2 ans (art. 106)."""
    _exercice(db, ctx, 2028)
    fiche = _fiche(db, ctx, tva_montant=Decimal("20000.00"))
    regularisation = svc.regularisation_tva_art106(fiche, date(2028, 6, 30))
    assert regularisation["applicable"] is True
    assert regularisation["annees_regularisation"] == 5
    assert regularisation["annees_utilisees"] == 2
    assert regularisation["annees_restantes"] == 3
    assert regularisation["montant"] == Decimal("12000.00")
    assert "A5" in regularisation["avertissement"]  # ambiguite tracee

    resultat = svc.ceder_immobilisation(
        db,
        fiche,
        date_cession=date(2028, 6, 30),
        prix=Decimal("5000.00"),
        user_id=ctx["user"].id,
    )
    lignes = {l.account_number: (l.debit, l.credit) for l in resultat["entry"].lines}
    assert lignes["6513"][0] >= Decimal("12000.00")  # VNA + regularisation
    assert lignes["34551"] == (Decimal("0.00"), Decimal("12000.00"))
    assert resultat["entry"].is_balanced is True
    assert "regularisation_tva" in [e.event_type for e in fiche.events]


def test_regularisation_tva_immeuble_et_periode_achevee(db, ctx):
    """Immeuble : regularisation sur 10 ans ; apres la periode, aucun reversement."""
    _exercice(db, ctx, 2028)
    immeuble = _fiche(
        db,
        ctx,
        label="Batiment administratif",
        account_number="2321",
        valeur_origine=Decimal("500000.00"),
        duree_annees=20,
        tva_montant=Decimal("50000.00"),
    )
    regularisation = svc.regularisation_tva_art106(immeuble, date(2028, 1, 15))
    assert regularisation["annees_regularisation"] == 10
    assert regularisation["annees_restantes"] == 8
    assert regularisation["montant"] == Decimal("40000.00")
    assert svc.comptes_amortissement("2321")["dotation"] == "61932"

    achevee = svc.regularisation_tva_art106(immeuble, date(2036, 6, 30))
    assert achevee["applicable"] is False
    assert "achevee" in achevee["motif"]

    sans_tva = _fiche(db, ctx, label="Sans TVA", tva_montant=Decimal("0.00"))
    assert svc.regularisation_tva_art106(sans_tva, date(2027, 1, 1))["applicable"] is False


def test_mise_au_rebut_exige_un_motif_et_solde_l_actif(db, ctx):
    """Mise au rebut : motif obligatoire, aucun produit, VNA en charge (6513)."""
    fiche = _fiche(db, ctx, comptabiliser=True, compte_contrepartie="4411")
    svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)
    with pytest.raises(AccountingError, match="motif"):
        svc.mettre_au_rebut(db, fiche, date_rebut=date(2026, 12, 31), motif="")
    resultat = svc.mettre_au_rebut(
        db,
        fiche,
        date_rebut=date(2026, 12, 31),
        motif="Materiel hors service",
        user_id=ctx["user"].id,
    )
    assert resultat["type"] == "rebut"
    assert resultat["prix"] == Decimal("0.00")
    lignes = {l.account_number: (l.debit, l.credit) for l in resultat["entry"].lines}
    assert lignes["2833"] == (Decimal("2400.00"), Decimal("0.00"))
    assert lignes["6513"] == (Decimal("9600.00"), Decimal("0.00"))
    assert "7513" not in lignes
    assert fiche.statut == "rebut"
    assert _solde_compte(db, ctx, "2332") == Decimal("0.00")
    assert _solde_compte(db, ctx, "2833") == Decimal("0.00")



# ---------------------------------------------------------------------------
# Etats du module
# ---------------------------------------------------------------------------
def test_etat_immobilisations_brut_amortissements_net(db, ctx):
    """Etat des immobilisations : brut/amortissements/net par poste + reconciliation."""
    atelier = _fiche(
        db,
        ctx,
        label="Atelier",
        account_number="2321",
        valeur_origine=Decimal("100000.00"),
        duree_annees=20,
        comptabiliser=True,
        compte_contrepartie="4411",
    )
    fiche = _fiche(db, ctx, comptabiliser=True, compte_contrepartie="4411")
    svc.comptabiliser_dotation(db, atelier, 2026, user_id=ctx["user"].id)
    svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)

    etat = svc.etat_immobilisations(db, ctx["company"].id, 2026)
    assert etat["total_brut"] == Decimal("112000.00")
    assert etat["total_amortissements"] == Decimal("7400.00")  # 5000 (2321) + 2400
    assert etat["total_vnc"] == Decimal("104600.00")
    assert {poste["compte"] for poste in etat["postes"]} == {"2321", "2332"}
    # Σ amortissements cumules + VNC = valeur d'origine (critere d'acceptation)
    assert etat["total_amortissements"] + etat["total_vnc"] == etat["total_brut"]
    # Reconciliation avec le grand livre : aucun ecart entre fiches et comptabilite
    assert etat["comptabilite"]["brut"] == Decimal("112000.00")
    assert etat["comptabilite"]["amortissements"] == Decimal("7400.00")
    assert etat["ecarts"] == {"brut": Decimal("0.00"), "amortissements": Decimal("0.00")}


def test_tableau_cessions_de_l_exercice(db, ctx):
    """Tableau des cessions : VNC, prix, plus/moins-value et regularisation TVA."""
    fiche = _fiche(
        db,
        ctx,
        tva_montant=Decimal("2400.00"),
        comptabiliser=True,
        compte_contrepartie="4411",
    )
    svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)
    svc.ceder_immobilisation(
        db,
        fiche,
        date_cession=date(2026, 12, 31),
        prix=Decimal("9000.00"),
        user_id=ctx["user"].id,
    )
    tableau = svc.tableau_cessions(db, ctx["company"].id, 2026)
    assert len(tableau["lignes"]) == 1
    ligne = tableau["lignes"][0]
    assert ligne["valeur_origine"] == Decimal("12000.00")
    assert ligne["amortissements"] == Decimal("2400.00")
    assert ligne["vnc"] == Decimal("9600.00")
    assert ligne["prix"] == Decimal("9000.00")
    assert ligne["resultat"] == Decimal("-600.00")
    # Cession dans l'annee de mise en service : aucune annee ecoulee, la TVA est
    # regularisee en totalite (CGI art. 106).
    assert ligne["regularisation_tva"] == Decimal("2400.00")
    assert tableau["total_resultat"] == Decimal("-600.00")
    assert tableau["total_regularisation"] == Decimal("2400.00")
    # Un bien sorti ne figure plus dans l'etat des immobilisations de l'exercice
    etat = svc.etat_immobilisations(db, ctx["company"].id, 2026)
    assert etat["total_brut"] == Decimal("0.00")


def test_amortissements_deductibles_de_l_exercice(db, ctx):
    """Amortissements fiscalement deductibles : dotation constatee ou theorique."""
    _exercice(db, ctx, 2027)
    constate = _fiche(
        db, ctx, label="Constate", comptabiliser=True, compte_contrepartie="4411"
    )
    theorique = _fiche(db, ctx, label="Theorique", account_number="2351")
    svc.comptabiliser_dotation(db, constate, 2026, user_id=ctx["user"].id)

    etat = svc.amortissements_deductibles(db, ctx["company"].id, 2026)
    assert len(etat["lignes"]) == 2
    assert etat["total_dotation"] == Decimal("4800.00")
    assert etat["nb_non_constatees"] == 1
    par_code = {ligne["code"]: ligne for ligne in etat["lignes"]}
    assert par_code[constate.code]["constatee"] is True
    assert par_code[constate.code]["dotation"] == Decimal("2400.00")
    assert par_code[theorique.code]["constatee"] is False
    assert par_code[theorique.code]["vnc"] == Decimal("12000.00")
    assert par_code[theorique.code]["vnc"] + par_code[theorique.code]["cumul"] == Decimal(
        "12000.00"
    )



# ---------------------------------------------------------------------------
# Controles de coherence
# ---------------------------------------------------------------------------
def test_controle_tva_immobilisation_mal_ventilee(db, ctx):
    """La TVA d'immobilisation doit etre au 34551 : une TVA au 34552 est signalee."""
    fournisseur = create_third_party(
        db,
        company=ctx["company"],
        kind="fournisseur",
        name="Fournisseur Machine",
        ice="001524628000001",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 3, 1),
        lines=[
            {
                "designation": "Machine de production",
                "quantity": 1,
                "unit_price": Decimal("100000.00"),
                "vat_rate": 20,
                "account_number": "2332",
            }
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    ecriture = db.execute(
        select(Entry).where(Entry.source == "invoice", Entry.source_id == facture.id)
    ).scalar_one()
    comptes_tva = {l.account_number for l in ecriture.lines}
    assert "34551" in comptes_tva  # ventilation CGNC automatique (invoicing)
    assert "34552" not in comptes_tva
    codes = {c["code"] for c in svc.controles_immobilisations(db, ctx["company"].id, 2026)}
    assert "TVA_34552_SUR_IMMOBILISATION" not in codes

    # Ecriture erronee simulee : TVA d'immobilisation logee au 34552.
    journal = get_journal(db, ctx["company"].id, "OD")
    exercice = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == ctx["company"].id, FiscalYear.year == 2026
        )
    ).scalar_one()
    create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=exercice,
        journal=journal,
        entry_date=date(2026, 3, 2),
        label="TVA d'immobilisation mal ventilee",
        source="invoice",
        source_id=facture.id,
        validate=True,
        lines=[
            {"account_number": "34552", "label": "TVA sur charges", "debit": Decimal("20000.00")},
            {"account_number": "4411", "label": "Fournisseur", "credit": Decimal("20000.00")},
        ],
    )
    alertes = [
        controle
        for controle in svc.controles_immobilisations(db, ctx["company"].id, 2026)
        if controle["code"] == "TVA_34552_SUR_IMMOBILISATION"
    ]
    assert len(alertes) == 1
    assert alertes[0]["niveau"] == "bloquant"
    assert "34551" in alertes[0]["message"]
    assert "2332" in alertes[0]["message"]


def test_controles_signalent_les_fiches_incompletes(db, ctx):
    """Une immobilisation amortissable sans mise en service est un controle bloquant."""
    _fiche(db, ctx, label="Sans service", service_date=None)
    fiche = _fiche(db, ctx, label="Complete")
    svc.comptabiliser_dotation(db, fiche, 2026, user_id=ctx["user"].id)

    controles = svc.controles_immobilisations(db, ctx["company"].id, 2026)
    codes = {controle["code"] for controle in controles}
    assert "SANS_MISE_EN_SERVICE" in codes
    assert all(
        controle["niveau"] in ("bloquant", "avertissement") for controle in controles
    )
    bloquants = [c for c in controles if c["niveau"] == "bloquant"]
    assert any("Sans service" in c["message"] for c in bloquants)
    # Une dotation est refusee sur la fiche incomplete (mise en service manquante).
    incomplete = [a for a in svc.list_assets(db, ctx["company"].id) if a.label == "Sans service"][0]
    with pytest.raises(AccountingError, match="mise en service"):
        svc.comptabiliser_dotation(db, incomplete, 2026, user_id=ctx["user"].id)


def test_controles_detectent_les_ecarts_avec_la_comptabilite(db, ctx):
    """Une immobilisation comptabilisee sans fiche est signalee (ecart fiches/compta)."""
    # Achat d'immobilisation comptabilise par facture, sans fiche associee.
    fournisseur = create_third_party(
        db,
        company=ctx["company"],
        kind="fournisseur",
        name="Fournisseur Outillage",
        ice="001524628000002",
    )
    facture = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 4, 1),
        lines=[
            {
                "designation": "Outillage",
                "quantity": 1,
                "unit_price": Decimal("8000.00"),
                "vat_rate": 20,
                "account_number": "2332",
            }
        ],
    )
    validate_invoice(db, facture, user_id=ctx["user"].id)
    controles = svc.controles_immobilisations(db, ctx["company"].id, 2026)
    ecarts = [c for c in controles if c["code"] == "ECART_FICHES_COMPTABILITE"]
    assert ecarts, "l'ecart entre fiches et comptabilite doit etre signale"
    assert any("8000" in c["message"].replace(" ", "") or "8 000" in c["message"] for c in ecarts)
    assert ecarts[0]["niveau"] == "avertissement"

    # Ajout de la fiche correspondante : l'ecart de valeurs brutes disparait.
    fiche = svc.creer_immobilisation(
        db,
        company=ctx["company"],
        label="Outillage",
        account_number="2332",
        acquisition_date=date(2026, 4, 1),
        service_date=date(2026, 4, 1),
        valeur_origine=Decimal("8000.00"),
        duree_annees=5,
        tva_montant=Decimal("1600.00"),
        invoice_id=facture.id,
    )
    assert fiche.invoice_id == facture.id
    etat = svc.etat_immobilisations(db, ctx["company"].id, 2026)
    assert etat["ecarts"]["brut"] == Decimal("0.00")

