"""Tests du module Paie & DTS « 9421 » (P1.4).

Verifie les criteres de recette du CDC § 3.4 : **IR d'un cas de reference au
dirham** (bareme 2026 historisé), **CNSS plafonnee**, charges patronales,
**ecriture de paie equilibree**, **Σ bulletins = ecriture = declaration DTS**,
oppositions et net saisissable, verrouillage de periode (P1.6), etats (livre,
journal, cotisations, recapitulatif) et generation de la **DTS « 9421 »**
(modele, XML EDI, etat de saisie EFI, registre des declarations).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.rates_ma import (
    BaremeIndisponible,
    compute_ir_monthly,
    deduction_charges_famille,
    frais_professionnels_mensuels,
)
from app.models import Entry
from app.services import edi_dts, payroll
from app.services.accounting import PeriodLockedError
from app.services.period_locks import verrouiller_periode

pytestmark = pytest.mark.usefixtures("ctx")

PERIODE = "2026-01"


def _salarie(db, ctx, **kwargs):
    """Salarie type : marie, 2 enfants, 10 000 DH + 500 DH de transport."""
    parametres = {
        "company": ctx["company"],
        "matricule": "S001",
        "nom": "ALAMI Youssef",
        "cin": "BK123456",
        "cnss": "987654321",
        "situation_familiale": "marie",
        "enfants": 2,
        "date_entree": date(2024, 1, 15),
        "fonction": "Comptable",
    }
    parametres.update(kwargs)
    employe = payroll.creer_employe(db, **parametres)
    payroll.ajouter_contrat(
        db,
        employe,
        salaire_base="10000",
        prime_transport="500",
        date_effet=date(2026, 1, 1),
    )
    db.commit()
    return employe


def _paie_validee(db, ctx, periode: str = PERIODE, mode: str = "virement"):
    """Prepare, valide et paie une periode (parcours complet)."""
    ctx["company"].cnss_number = ctx["company"].cnss_number or "1234567"
    db.commit()
    run = payroll.preparer_paie(db, ctx["company"], periode, user_id=ctx["user"].id)
    payroll.valider_paie(db, run, user_id=ctx["user"].id)
    db.commit()
    if mode:
        payroll.payer_paie(db, run, mode=mode, user_id=ctx["user"].id)
        db.commit()
    return run


# ---------------------------------------------------------------------------
# Baremes (IR mensuel, frais professionnels, charges de famille)
# ---------------------------------------------------------------------------
def test_bareme_mensuel_2026_reference():
    """Cas de reference : 10 000 DH bruts, marie, 2 enfants."""
    assert frais_professionnels_mensuels(10000) == Decimal("2500.00")  # 25 % plafonne
    assert frais_professionnels_mensuels(5000) == Decimal("1750.00")  # 35 %
    assert deduction_charges_famille(2) == Decimal("1200.00")
    assert deduction_charges_famille(9) == Decimal("3600.00")  # plafond 6 personnes
    # Net imposable = brut - cotisations salariales - frais professionnels
    assert compute_ir_monthly(Decimal("7005.20"), 2) == Decimal("501.56")
    assert compute_ir_monthly(Decimal("7005.20"), 0) == Decimal("601.56")


def test_bareme_non_parametre_refuse():
    """Aucun bareme n'est devine : un exercice absent est refuse."""
    with pytest.raises(BaremeIndisponible):
        compute_ir_monthly(5000, 0, 2027)
    with pytest.raises(payroll.PayrollError):
        payroll.valider_periode("2027-01")


# ---------------------------------------------------------------------------
# Fiches salaries et contrats
# ---------------------------------------------------------------------------
def test_fiche_salarie_et_unicite_matricule(db, ctx):
    employe = _salarie(db, ctx)
    assert employe.matricule == "S001"
    assert employe.personnes_a_charge == 3  # conjoint + 2 enfants
    with pytest.raises(payroll.PayrollError) as erreur:
        _salarie(db, ctx, nom="Doublon")
    assert "existe déjà" in str(erreur.value)
    with pytest.raises(payroll.PayrollError):
        payroll.creer_employe(
            db,
            company=ctx["company"],
            matricule="S002",
            nom="Test",
            date_entree=date(2026, 1, 1),
            situation_familiale="concubin",
        )


def test_contrat_en_vigueur_a_une_date(db, ctx):
    employe = _salarie(db, ctx)
    payroll.ajouter_contrat(db, employe, salaire_base="12000", date_effet=date(2026, 7, 1))
    db.commit()
    assert payroll.contrat_a(employe, date(2026, 6, 30)).salaire_base == Decimal("10000.00")
    assert payroll.contrat_a(employe, date(2026, 7, 1)).salaire_base == Decimal("12000.00")
    calcul = payroll.calculer_bulletin(db, employee=employe, periode="2026-07")
    assert calcul["salaire_base"] == Decimal("12000.00")


# ---------------------------------------------------------------------------
# Calcul du bulletin
# ---------------------------------------------------------------------------
def test_bulletin_reference_2026(db, ctx):
    """Bulletin de reference : brut, cotisations, IR, net et cout employeur."""
    employe = _salarie(db, ctx)
    calcul = payroll.calculer_bulletin(db, employee=employe, periode=PERIODE)
    assert calcul["brut_imposable"] == Decimal("10500.00")
    assert calcul["base_cnss"] == Decimal("6000.00")  # plafond CNSS
    assert calcul["cnss_salariale"] == Decimal("268.80")  # 4,48 % plafonne
    assert calcul["amo_salariale"] == Decimal("237.30")  # 2,26 % sans plafond
    assert calcul["frais_professionnels"] == Decimal("2625.00")
    assert calcul["net_imposable"] == Decimal("7368.90")
    assert calcul["ir"] == Decimal("560.67")
    assert calcul["cotisations_salariales"] == Decimal("506.10")
    assert calcul["net"] == Decimal("9433.23")
    assert calcul["cnss_patronale"] == Decimal("538.80")
    assert calcul["amo_patronale"] == Decimal("431.55")
    assert calcul["prestations_familiales"] == Decimal("672.00")
    assert calcul["taxe_formation"] == Decimal("168.00")
    assert calcul["cout_employeur"] == Decimal("12310.35")
    comptes = {
        rubrique["compte"] for rubrique in calcul["rubriques"] if rubrique["compte"]
    }
    assert {"61711", "61713", "4441", "4452"} <= comptes


def test_exoneration_art_57_20(db, ctx):
    """Nouveau recrutement exonere (art. 57-20° CGI) : IR retenu nul."""
    employe = _salarie(db, ctx, matricule="S003", exoneration_art_57_20=True)
    calcul = payroll.calculer_bulletin(db, employee=employe, periode=PERIODE)
    assert calcul["ir"] == Decimal("0.00")
    assert calcul["exonere_art_57_20"] is True
    assert calcul["net"] == Decimal("9993.90")


def test_oppositions_et_avances_controlees(db, ctx):
    """Une opposition ne peut exceder le net saisissable ; le net reste positif."""
    employe = _salarie(db, ctx)
    with pytest.raises(payroll.PayrollError) as erreur:
        payroll.calculer_bulletin(
            db, employee=employe, periode=PERIODE, variables={"oppositions": "20000"}
        )
    assert "excède le net saisissable" in str(erreur.value)
    calcul = payroll.calculer_bulletin(
        db,
        employee=employe,
        periode=PERIODE,
        variables={"oppositions": "1500", "avances": "1000", "primes": "500"},
    )
    assert calcul["brut_imposable"] == Decimal("11000.00")
    assert calcul["oppositions"] == Decimal("1500.00")
    assert calcul["avances"] == Decimal("1000.00")
    attendu = (
        Decimal("11000.00")
        - calcul["cotisations_salariales"]
        - calcul["ir"]
        - Decimal("2500.00")
    )
    assert calcul["net"] == attendu
    with pytest.raises(payroll.PayrollError) as erreur:
        payroll.calculer_bulletin(
            db, employee=employe, periode=PERIODE, variables={"avances": "50000"}
        )
    assert "négatif" in str(erreur.value)


def test_absences_et_heures_supplementaires(db, ctx):
    """Absences (1/30e) et heures supplementaires ajustent le brut imposable."""
    employe = _salarie(db, ctx)
    calcul = payroll.calculer_bulletin(
        db,
        employee=employe,
        periode=PERIODE,
        variables={"jours_absence": "2", "heures_sup": "800"},
    )
    assert calcul["absences"] == Decimal("666.67")
    assert calcul["brut_imposable"] == Decimal("10633.33")


# ---------------------------------------------------------------------------
# Ecriture de paie, validation, paiement
# ---------------------------------------------------------------------------
def test_ecriture_de_paie_equilibree(db, ctx):
    """Le debit de l'ecriture = cout employeur ; credit = dettes + net."""
    _salarie(db, ctx)
    run = payroll.preparer_paie(db, ctx["company"], PERIODE, user_id=ctx["user"].id)
    db.commit()
    ecriture = payroll.valider_paie(db, run, user_id=ctx["user"].id)
    db.commit()
    debit = sum((ligne.debit for ligne in ecriture.lines), Decimal("0"))
    credit = sum((ligne.credit for ligne in ecriture.lines), Decimal("0"))
    assert debit == credit == Decimal("12310.35")
    par_compte = {
        ligne.account_number: (ligne.debit, ligne.credit) for ligne in ecriture.lines
    }
    assert par_compte["61711"][0] == Decimal("10000.00")
    assert par_compte["61713"][0] == Decimal("500.00")
    assert par_compte["61741"][0] == Decimal("970.35")  # CNSS + AMO patronales
    assert par_compte["61744"][0] == Decimal("672.00")
    assert par_compte["61768"][0] == Decimal("168.00")
    assert par_compte["4441"][1] == Decimal("2316.45")  # parts salariales + patronales
    assert par_compte["4452"][1] == Decimal("560.67")  # IR retenu a la source
    assert par_compte["4432"][1] == Decimal("9433.23")  # net a payer (dette)
    assert ecriture.source == "payroll"
    assert run.entry_id == ecriture.id
    assert run.statut == "valide"


def test_paie_payee_et_figee(db, ctx):
    """Le reglement solde 4432 par la banque ; la paie n'est plus recalculable."""
    _salarie(db, ctx)
    run = _paie_validee(db, ctx)
    assert run.statut == "paye"
    paiement = db.get(Entry, run.paiement_entry_id)
    assert {ligne.account_number for ligne in paiement.lines} == {"4432", "5141"}
    assert run.total_net == Decimal("9433.23")
    with pytest.raises(payroll.PayrollError) as erreur:
        payroll.preparer_paie(db, ctx["company"], PERIODE)
    assert "ne peut plus" in str(erreur.value)
    with pytest.raises(payroll.PayrollError):
        payroll.valider_paie(db, run)


def test_paiement_en_especes_utilise_la_caisse(db, ctx):
    """Un reglement en especes passe par la caisse (5161)."""
    _salarie(db, ctx)
    run = _paie_validee(db, ctx, mode="especes")
    paiement = db.get(Entry, run.paiement_entry_id)
    assert "5161" in {ligne.account_number for ligne in paiement.lines}
    assert run.mode_paiement == "especes"


def test_periode_verrouillee_refusee(db, ctx):
    """P1.6 : aucune paie retroactive sur une periode verrouillee."""
    _salarie(db, ctx)
    verrouiller_periode(
        db, company_id=ctx["company"].id, year=2026, periode=1, user_id=ctx["user"].id
    )
    db.commit()
    run = payroll.preparer_paie(db, ctx["company"], PERIODE, user_id=ctx["user"].id)
    db.commit()
    with pytest.raises(PeriodLockedError):
        payroll.valider_paie(db, run, user_id=ctx["user"].id)
    db.rollback()
    controles = payroll.controles_paie(db, ctx["company"].id, PERIODE)
    assert "paie.periode_verrouillee" in {c["code"] for c in controles}


# ---------------------------------------------------------------------------
# Controles et etats
# ---------------------------------------------------------------------------
def test_controles_paie_cnss_manquant_bloquant(db, ctx):
    """Un n° CNSS manquant bloque la DTS (controle bloquant n° 6 du CDC)."""
    employe = _salarie(db, ctx, cnss=None)
    run = payroll.preparer_paie(db, ctx["company"], PERIODE, user_id=ctx["user"].id)
    db.commit()
    controles = payroll.controles_paie(db, ctx["company"].id, PERIODE)
    codes = {controle["code"] for controle in controles}
    assert "paie.cnss_manquant" in codes
    assert "paie.recap" in codes
    assert employe.cnss is None


def test_etats_de_paie_coherents(db, ctx):
    """Livre, journal, cotisations et recapitulatif s'accordent au dirham."""
    _salarie(db, ctx)
    _paie_validee(db, ctx, periode="2026-01")
    _salarie(db, ctx, matricule="S002", nom="BENNANI Salma", situation_familiale="celibataire", enfants=0)
    _paie_validee(db, ctx, periode="2026-02")

    journal = payroll.journal_de_paie(db, ctx["company"].id, "2026-02")
    # En fevrier, les deux salaries sont presents (10 500 + 10 500).
    assert journal["totaux"]["brut"] == Decimal("21000.00")
    assert len(journal["bulletins"]) == 2
    assert journal["rubriques"]

    livre = payroll.livre_de_paie(db, ctx["company"].id, 2026)
    assert livre["periodes"] == ["2026-01", "2026-02"]
    assert livre["totaux"]["brut"] == Decimal("31500.00")
    assert len(livre["salaries"]) == 2

    cotisations = payroll.etat_cotisations(db, ctx["company"].id, 2026)
    # Trois bulletins a 10 500 DH bruts (janvier : S001 ; fevrier : S001 + S002).
    assert cotisations["totaux"]["total_cnss"] == Decimal("2316.45") * 3
    assert cotisations["totaux"]["ir"] == livre["totaux"]["ir"]

    recap = payroll.recapitulatif_annuel(db, ctx["company"].id, 2026)
    assert recap["nb_salaries"] == 2
    assert recap["nb_periodes"] == 2
    assert recap["totaux_salaires"]["cout_employeur"] == livre["totaux"]["cout_employeur"]


def test_bulletin_pdf_et_journal_pdf(db, ctx):
    """Le bulletin est produit par le PDF de J1 (interface inchangee)."""
    from app.services.pdf_documents import pdf_bulletin_paie

    _salarie(db, ctx)
    run = _paie_validee(db, ctx)
    bulletin = payroll.list_bulletins(db, run)[0]
    pdf = pdf_bulletin_paie(payroll.bulletin_dict(db, ctx["company"], bulletin))
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


# ---------------------------------------------------------------------------
# DTS « 9421 » : modele, XML EDI, etat EFI, registre des declarations
# ---------------------------------------------------------------------------
def _dts(db, ctx, annee: int = 2026):
    """Prepare une DTS sur l'exercice (paie de janvier et fevrier validee)."""
    _salarie(db, ctx)
    _paie_validee(db, ctx, periode="2026-01")
    _paie_validee(db, ctx, periode="2026-02")
    return edi_dts.construire_dts(db, ctx["company"], annee)


def test_dts_modele_et_reconciliation_comptable(db, ctx):
    """Σ bulletins = comptabilite : la DTS se reconcilie avec les comptes 617x."""
    modele = _dts(db, ctx)
    assert modele["totaux"]["nb_salaries"] == 1
    assert modele["totaux"]["brut_imposable"] == Decimal("21000.00")
    assert modele["totaux"]["ir_retenu"] == Decimal("1121.34")
    # CNSS/AMO (salariales + patronales + prestations + formation) sur 2 mois.
    assert modele["totaux"]["cnss_total"] == Decimal("2316.45") * 2
    assert modele["declarant"]["identifiant_fiscal"] == "1234567"
    assert [s["matricule"] for s in modele["personnel_permanent"]] == ["S001"]
    reconciliation = next(
        controle
        for controle in modele["controles"]
        if controle["code"] == "dts.reconciliation_comptable"
    )
    assert reconciliation["niveau"] == "information"
    assert "617x" in reconciliation["message"]
    assert not edi_dts.controles_bloquants(modele["controles"])


def test_dts_xml_structure_et_validation_xsd_absente(db, ctx):
    """Le XML suit le modele officiel V5.1 ; le XSD manquant est signale."""
    modele = _dts(db, ctx)
    xml = edi_dts.build_dts_xml(modele)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    for balise in (
        "<TraitementEtSalaire ",
        'xsi:noNamespaceSchemaLocation="traitementSalaire.xsd"',
        "<identifiantFiscal>1234567</identifiantFiscal>",
        "<raisonSociale>Atlas Test SARL</raisonSociale>",
        "<exerciceFiscalDu>2026-01-01</exerciceFiscalDu>",
        "<exerciceFiscalAu>2026-12-31</exerciceFiscalAu>",
        "<nbrPersoPermanent>1</nbrPersoPermanent>",
        "<nbrPersoOccasionnel>0</nbrPersoOccasionnel>",
        "<nbrStagiaires>0</nbrStagiaires>",
        "<listPersonnelPermanent>",
        "<PersonnelPermanent>",
        "<numCE>987654321</numCE>",
        "<totalMtIrPrelevePP>1121.34</totalMtIrPrelevePP>",
        "<totalMtRevenuBrutImposablePP>21000.00</totalMtRevenuBrutImposablePP>",
        "<listPersonnelOccasionnel>",
        "<listStagiaires>",
    ):
        assert balise in xml
    assert "<declarant>" not in xml  # modele officiel : balises plates
    assert edi_dts.controle_taille(xml) == len(xml.encode("utf-8"))
    assert edi_dts.xml_filename(ctx["company"], 2026) == "DTS_1234567_2026.xml"
    validation = edi_dts.valider_xsd(xml)
    assert validation["valide"] is None  # aucun XSD : jamais declare conforme
    assert "écart n° 6" in validation["message"]
    assert "dts.schema_absent" in {c["code"] for c in modele["controles"]}


def test_dts_refusee_si_cnss_salarie_manquant(db, ctx):
    """Un salarie sans n° CNSS fait refuser la generation du fichier EDI."""
    employe = _salarie(db, ctx, cnss=None)
    _paie_validee(db, ctx)
    modele = edi_dts.construire_dts(db, ctx["company"], 2026)
    assert "dts.cnss_salarie_manquant" in {
        controle["code"] for controle in modele["controles"]
    }
    with pytest.raises(edi_dts.DtsError) as erreur:
        edi_dts.build_dts_xml(modele)
    assert "contrôles bloquants" in str(erreur.value)
    assert employe.cnss is None
    # Le mode EFI reste preparable (saisie assistee) : l'etat liste le salarie.
    assert edi_dts.etat_de_saisie_efi(modele)[0]["numero_cnss"] is None


def test_dts_etat_efi_et_registre_des_declarations(db, ctx):
    """Enregistrement, depot, accuse : le cycle de la declaration est trace."""
    from app.models import TaxDeclaration

    modele = _dts(db, ctx)
    lignes = edi_dts.etat_de_saisie_efi(modele)
    assert len(lignes) == 1
    assert lignes[0]["onglet"] == "personnel permanent"
    assert lignes[0]["ir_retenu"] == Decimal("1121.34")

    xml = edi_dts.build_dts_xml(modele)
    declaration = edi_dts.enregistrer_declaration(
        db, ctx["company"], modele, xml=xml, user_id=ctx["user"].id
    )
    db.commit()
    assert declaration.statut == "brouillon"
    assert declaration.fichier_nom == "DTS_1234567_2026.xml"
    assert len(declaration.fichier_hash) == 64
    assert declaration.fichier_taille == len(xml.encode("utf-8"))
    assert declaration.type == "DTS" and declaration.periode == "2026"
    assert declaration.montant == Decimal("1121.34")

    edi_dts.soumettre_declaration(
        db, declaration, accuse_le=date(2026, 4, 20), user_id=ctx["user"].id
    )
    db.commit()
    assert declaration.statut == "acceptee"
    assert declaration.accuse_le == date(2026, 4, 20)
    with pytest.raises(edi_dts.DtsError):
        edi_dts.enregistrer_declaration(db, ctx["company"], modele, xml=xml)
    registre = edi_dts.list_declarations(db, ctx["company"].id, type_declaration="DTS")
    assert len(registre) == 1
    assert db.query(TaxDeclaration).count() == 1


def test_dts_rejet_motive_et_exercice_sans_paie(db, ctx):
    """Un rejet est motive ; une DTS sans bulletin valide est refusee."""
    modele = _dts(db, ctx)
    declaration = edi_dts.enregistrer_declaration(db, ctx["company"], modele)
    db.commit()
    edi_dts.soumettre_declaration(
        db, declaration, motif_rejet="CNSS d'un salarie inconnu de la caisse"
    )
    db.commit()
    assert declaration.statut == "rejetee"
    assert "inconnu" in (declaration.motif_rejet or "")
    with pytest.raises(edi_dts.DtsError) as erreur:
        edi_dts.construire_dts(
            db, ctx["company"], 2025
        )
    assert "Aucun bulletin" in str(erreur.value)


def test_dts_fiche_pdf(db, ctx):
    """Fiche recapitulative de la DTS (piece jointe du depot)."""
    modele = _dts(db, ctx)
    pdf = edi_dts.pdf_bordereau_dts(modele)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000