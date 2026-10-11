"""Tests du module IS & liasse fiscale (P2.1 — etape 1 : resultat fiscal, IS/CM).

Verifie les criteres du CDC § 4.1 : **resultat fiscal** (reintegrations et
deductions, hors impot sur les resultats), **IS** au taux de l'exercice,
**cotisation minimale** comparee a l'IS (CGI art. 144), **report deficitaire**
(art. 114), **acomptes** (compte 3453) et **controles** (exercice clos P1.6,
balance equilibree, preparation de la reconciliation « Σ liasses = balance »).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.seed import get_or_create_fiscal_year
from app.services import fiscal_liasse as fiscal
from app.services.accounting import create_entry, get_journal

pytestmark = pytest.mark.usefixtures("ctx")

ANNEE = 2026


def _ecriture(db, ctx, lignes: list[dict], *, jour: date, label: str, journal: str = "OD"):
    """Passe une ecriture validee (journal des operations diverses par defaut)."""
    exercice = get_or_create_fiscal_year(db, ctx["company"], jour.year)
    ecriture = create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=exercice,
        journal=get_journal(db, ctx["company"].id, journal),
        entry_date=jour,
        label=label,
        lines=lignes,
        validate=True,
    )
    db.commit()
    return ecriture


def _socle(db, ctx, *, amende: str = "5000", acomptes: str = "8000", impot: str = "10000"):
    """Exercice type : vente 100 000 HT + TVA 20 %, achat 40 000, amende, IS, acomptes."""
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "3421", "debit": "120000", "label": "Client"},
            {"account_number": "7111", "credit": "100000", "label": "Ventes"},
            {"account_number": "4455", "credit": "20000", "label": "TVA collectée"},
        ],
        jour=date(ANNEE, 2, 10),
        label="Facture de vente",
        journal="VE",
    )
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6111", "debit": "40000", "label": "Achats"},
            {"account_number": "4411", "credit": "40000", "label": "Fournisseur"},
        ],
        jour=date(ANNEE, 3, 5),
        label="Facture d'achat",
        journal="AC",
    )
    if Decimal(amende) > 0:
        _ecriture(
            db,
            ctx,
            [
                {"account_number": "6583", "debit": amende, "label": "Amende fiscale"},
                {"account_number": "4411", "credit": amende, "label": "État"},
            ],
            jour=date(ANNEE, 4, 1),
            label="Amende et pénalités",
        )
    if Decimal(impot) > 0:
        _ecriture(
            db,
            ctx,
            [
                {"account_number": "6701", "debit": impot, "label": "IS"},
                {"account_number": "4411", "credit": impot, "label": "État"},
            ],
            jour=date(ANNEE, 12, 31),
            label="Impôt sur les bénéfices",
        )
    if Decimal(acomptes) > 0:
        _ecriture(
            db,
            ctx,
            [
                {"account_number": "3453", "debit": acomptes, "label": "Acompte IS"},
                {"account_number": "5141", "credit": acomptes, "label": "Banque"},
            ],
            jour=date(ANNEE, 6, 30),
            label="Acompte d'IS",
            journal="BQ",
        )


def _cloturer(db, ctx, annee: int = ANNEE):
    """Cloture l'exercice (condition du depot IS / liasse)."""
    exercice = get_or_create_fiscal_year(db, ctx["company"], annee)
    exercice.status = "closed"
    db.commit()
    return exercice


# ---------------------------------------------------------------------------
# Resultat comptable / resultat fiscal
# ---------------------------------------------------------------------------
def test_resultat_avant_impot_exclut_l_impot_sur_les_societes(db, ctx):
    """L'IS comptabilise (67x) n'est pas deductible : il est retire du CPC."""
    _socle(db, ctx)
    resultat = fiscal.resultat_avant_impot(db, ctx["company"].id, ANNEE)
    # Produits 100 000 - charges (40 000 + 5 000 + 10 000) = 45 000 (CPC)
    assert resultat["resultat_comptable"] == Decimal("45000.00")
    assert resultat["impots_resultats_comptabilises"] == Decimal("10000.00")
    # Resultat avant impot = 45 000 + 10 000 = 55 000 (CGI art. 11)
    assert resultat["resultat_avant_impot"] == Decimal("55000.00")


def test_charges_non_deductibles_detectees_avec_reference_cgi(db, ctx):
    """Les amendes et penalites (6583) sont proposees en reintegration."""
    _socle(db, ctx)
    propositions = fiscal.charges_non_deductibles(db, ctx["company"].id, ANNEE)
    assert len(propositions) == 1
    proposition = propositions[0]
    assert proposition["code"] == "AMENDES_PENALITES"
    assert proposition["montant"] == Decimal("5000.00")
    assert proposition["reference"] == "CGI art. 11"
    assert proposition["detail"] == [{"compte": "6583", "montant": Decimal("5000.00")}]


def test_chiffre_affaires_ht_tva_et_ttc(db, ctx):
    """CA HT (71x) + TVA collectee (4455) = CA TTC (figure comptable).

    Le CA TTC n'est **plus** la base de la cotisation minimale : celle-ci est
    assise sur les produits hors TVA (V7B) — voir `test_base_cm_hors_tva`.
    """
    _socle(db, ctx)
    affaires = fiscal.chiffre_affaires(db, ctx["company"].id, ANNEE)
    assert affaires["chiffre_affaires_ht"] == Decimal("100000.00")
    assert affaires["tva_collectee"] == Decimal("20000.00")
    assert affaires["chiffre_affaires_ttc"] == Decimal("120000.00")


def test_resultat_fiscal_reintegrations_et_report_deficitaire(db, ctx):
    """Resultat fiscal = avant impot + reintegrations - deductions - report."""
    _socle(db, ctx)
    calcul = fiscal.calculer_is(db, ctx["company"], ANNEE, report_deficitaire="20000")
    assert calcul["resultat_avant_impot"] == Decimal("55000.00")
    assert calcul["total_reintegrations"] == Decimal("5000.00")
    assert [ligne["origine"] for ligne in calcul["detail_reintegrations"]] == [
        "détection automatique"
    ]
    assert calcul["resultat_avant_report"] == Decimal("60000.00")
    assert calcul["report_deficitaire_utilise"] == Decimal("20000.00")
    assert calcul["report_deficitaire_restant"] == Decimal("0.00")
    assert calcul["resultat_fiscal"] == Decimal("40000.00")
    # Report superieur au benefice : il est plafonne au benefice de l'exercice.
    plafonne = fiscal.calculer_is(
        db, ctx["company"], ANNEE, report_deficitaire="200000"
    )
    assert plafonne["report_deficitaire_utilise"] == Decimal("60000.00")
    assert plafonne["report_deficitaire_restant"] == Decimal("140000.00")
    assert plafonne["resultat_fiscal"] == Decimal("0.00")
    assert plafonne["is_theorique"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# IS, cotisation minimale et acomptes (CGI art. 144)
# ---------------------------------------------------------------------------
def test_is_du_et_solde_apres_acomptes(db, ctx):
    """IS 20 % du resultat fiscal ; les acomptes (3453) viennent en deduction."""
    _socle(db, ctx)
    calcul = fiscal.calculer_is(db, ctx["company"], ANNEE)  # CM 0 (36 premiers mois)
    assert calcul["resultat_fiscal"] == Decimal("60000.00")
    assert calcul["is_theorique"] == Decimal("12000.00")
    assert calcul["cotisation_minimale"] == Decimal("0.00")
    assert calcul["cotisation_minimale_due"] == Decimal("0.00")
    assert calcul["impot_du"] == Decimal("12000.00")
    assert calcul["acomptes_verses"] == Decimal("8000.00")
    assert calcul["solde_a_payer"] == Decimal("4000.00")
    assert calcul["excedent_a_reporter"] == Decimal("0.00")
    assert calcul["taux_effectif"] == Decimal("20.00")


def test_acomptes_superieurs_a_l_impot_donnent_un_excedent(db, ctx):
    """Acomptes > impot du : aucun solde, l'excedent est reporte (ou restitue)."""
    _socle(db, ctx, acomptes="15000")
    calcul = fiscal.calculer_is(db, ctx["company"], ANNEE)
    assert calcul["impot_du"] == Decimal("12000.00")
    assert calcul["solde_a_payer"] == Decimal("0.00")
    assert calcul["excedent_a_reporter"] == Decimal("3000.00")


def test_cotisation_minimale_due_meme_en_deficit(db, ctx):
    """CGI art. 144 : la CM (plancher 3 000 DH) est due malgre un deficit."""
    _socle(db, ctx, acomptes="0")
    # Charge complementaire de 62 000 : l'exercice devient deficitaire.
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6111", "debit": "62000", "label": "Achats"},
            {"account_number": "4411", "credit": "62000", "label": "Fournisseur"},
        ],
        jour=date(ANNEE, 5, 5),
        label="Achats complémentaires",
        journal="AC",
    )
    calcul = fiscal.calculer_is(db, ctx["company"], ANNEE, mois_activite=48)
    assert calcul["resultat_fiscal"] == Decimal("-2000.00")
    assert calcul["deficit_constate"] == Decimal("2000.00")
    assert calcul["nature_resultat_fiscal"] == "deficit"
    assert calcul["is_theorique"] == Decimal("0.00")
    assert calcul["chiffre_affaires_ttc"] == Decimal("120000.00")
    assert calcul["cotisation_minimale"] == Decimal("3000.00")  # plancher
    assert calcul["cotisation_minimale_due"] == Decimal("3000.00")
    assert calcul["impot_du"] == Decimal("3000.00")
    assert calcul["solde_a_payer"] == Decimal("3000.00")


def test_reintegration_saisie_prime_sur_la_detection(db, ctx):
    """Le montant saisi par le comptable remplace la proposition detectee."""
    _socle(db, ctx)
    calcul = fiscal.calculer_is(
        db,
        ctx["company"],
        ANNEE,
        reintegrations={"AMENDES_PENALITES": "5000", "CHARGES_NON_JUSTIFIEES": "2500"},
        detection_automatique=False,
    )
    origines = {ligne["code"]: ligne["origine"] for ligne in calcul["detail_reintegrations"]}
    assert origines == {
        "AMENDES_PENALITES": "saisie",
        "CHARGES_NON_JUSTIFIEES": "saisie",
    }
    assert calcul["total_reintegrations"] == Decimal("7500.00")
    assert calcul["resultat_fiscal"] == Decimal("62500.00")


def test_montant_negatif_refuse(db, ctx):
    """Un report deficitaire negatif est une saisie invalide."""
    _socle(db, ctx)
    with pytest.raises(fiscal.FiscalError):
        fiscal.calculer_is(db, ctx["company"], ANNEE, report_deficitaire="-1")


# ---------------------------------------------------------------------------
# Controles : exercice clos (P1.6), CM, deficit, reconciliation balance
# ---------------------------------------------------------------------------
def test_controles_exercice_non_clos_bloquant_puis_leve_apres_cloture(db, ctx):
    """P1.6 : le depot IS / liasse exige un exercice clos."""
    _socle(db, ctx)
    controles = fiscal.controles_fiscaux(db, ctx["company"], ANNEE)
    par_code = {controle["code"]: controle for controle in controles}
    assert par_code["fiscal.exercice_non_clos"]["niveau"] == "bloquant"
    assert "Exercice" in par_code["fiscal.exercice_non_clos"]["message"]
    assert "fiscal.recap" in par_code
    # L'amende est deja reintegree (detection automatique) : plus d'alerte.
    assert "fiscal.reintegrations_a_examiner" not in par_code
    assert fiscal.controles_bloquants(controles) != []

    _cloturer(db, ctx)
    controles_apres = fiscal.controles_fiscaux(db, ctx["company"], ANNEE)
    assert fiscal.controles_bloquants(controles_apres) == []


def test_controle_reintegrations_a_examiner(db, ctx):
    """Charges non deductibles detectees mais non retenues : alerte (CGI art. 11)."""
    _socle(db, ctx)
    calcul = fiscal.calculer_is(db, ctx["company"], ANNEE, detection_automatique=False)
    assert calcul["total_reintegrations"] == Decimal("0.00")
    par_code = {
        controle["code"]: controle
        for controle in fiscal.controles_fiscaux(
            db, ctx["company"], ANNEE, calcul=calcul
        )
    }
    assert par_code["fiscal.reintegrations_a_examiner"]["niveau"] == "avertissement"
    assert "art. 11" in par_code["fiscal.reintegrations_a_examiner"]["message"]


def test_controles_cotisation_minimale_et_deficit_art_144_et_114(db, ctx):
    """La CM superieure a l'IS et le deficit a reporter sont signales."""
    _socle(db, ctx, acomptes="0")
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6111", "debit": "62000", "label": "Achats"},
            {"account_number": "4411", "credit": "62000", "label": "Fournisseur"},
        ],
        jour=date(ANNEE, 5, 5),
        label="Achats complémentaires",
        journal="AC",
    )
    calcul = fiscal.calculer_is(db, ctx["company"], ANNEE, mois_activite=48)
    par_code = {
        controle["code"]: controle
        for controle in fiscal.controles_fiscaux(
            db, ctx["company"], ANNEE, calcul=calcul
        )
    }
    assert par_code["fiscal.cotisation_minimale_due"]["niveau"] == "avertissement"
    assert "art. 144" in par_code["fiscal.cotisation_minimale_due"]["message"]
    assert "art. 114" in par_code["fiscal.deficit_reportable"]["message"]
    assert par_code["fiscal.solde_a_payer"]["niveau"] == "information"


def test_reconciliation_balance_preparee_pour_la_liasse(db, ctx):
    """La balance sert de reference a la reconciliation « Σ liasses = balance »."""
    _socle(db, ctx)
    balance = fiscal.reconciliation_balance(db, ctx["company"].id, ANNEE)
    assert balance["equilibre"] is True
    assert balance["total_soldes"] == Decimal("0.00")
    assert balance["pret_pour_liasse"] is True
    assert set(balance["classes"]) == {3, 4, 5, 6, 7}
    assert balance["total_produits"] == Decimal("100000.00")
    assert balance["total_charges"] == Decimal("55000.00")
    assert balance["resultat"] == Decimal("45000.00")
    assert balance["nb_lignes"] > 0


def test_dossier_is_agrege_calcul_balance_et_controles(db, ctx):
    """Le dossier fiscal agrege calcul, balance et controles (entree etape 2)."""
    _socle(db, ctx)
    _cloturer(db, ctx)
    dossier = fiscal.dossier_is(db, ctx["company"], ANNEE, report_deficitaire="10000")
    assert set(dossier) == {"annee", "calcul", "balance", "controles"}
    assert dossier["calcul"]["resultat_fiscal"] == Decimal("50000.00")
    assert dossier["calcul"]["is_theorique"] == Decimal("10000.00")
    assert dossier["calcul"]["solde_a_payer"] == Decimal("2000.00")
    assert dossier["balance"]["equilibre"] is True
    assert fiscal.controles_bloquants(dossier["controles"]) == []


def test_exercice_sans_ecriture_signale(db, ctx):
    """Aucune ecriture sur l'exercice : impossible de declarer."""
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    db.commit()
    par_code = {
        controle["code"]: controle
        for controle in fiscal.controles_fiscaux(db, ctx["company"], ANNEE)
    }
    assert par_code["fiscal.exercice_sans_ecriture"]["niveau"] == "bloquant"
    balance = fiscal.reconciliation_balance(db, ctx["company"].id, ANNEE)
    assert balance["pret_pour_liasse"] is False