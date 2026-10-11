"""P1B V7B — tests reglementaires cibles 2025 (correction du moteur).

Couvre les exigences du cahier V7B :

- **AMO** : non-regression 2,26 % salarie / 4,11 % employeur / 6,37 % total,
  assiette brute sans plafond (V7A-CORR) ;
- **CM** : assiette **hors TVA** (TVA exclue), contenu complet (CA, autres
  produits d'exploitation, produits financiers, subventions/dons), taux 0,25 %
  et plancher 3 000 DH 2025, exoneration 36 mois, **butee 60 mois** depuis la
  constitution, cas d'une societe recente (debut d'exploitation 2025) ;
- **IS 2025** : cas courant deja conforme (17,5 % / 20 %), 2026 inchange (les
  taux corriges 31,25 % / 39,25 % / 18,75 % et le refus 2024 sont verifies
  dans `tests/test_rates_ma_2025.py`) ;
- **paie 2025** : parametres reels corriges (frais professionnels, CNSS/AMO) —
  calculs en memoire uniquement, **aucune paie creee en base**.

Aucune donnee comptable n'est modifiee : les ecritures sont passees sur la base
SQLite **en memoire** du fixture `db` (compta_ma.db n'est jamais ouvert).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import rates_ma
from app.db.seed import get_or_create_fiscal_year
from app.models import Account
from app.services.accounting import create_entry, get_journal
from app.services import fiscal_liasse

pytestmark = pytest.mark.usefixtures("ctx")

ANNEE = 2025


# ---------------------------------------------------------------------------
# Utilitaires : ecritures en memoire (aucune donnee reelle)
# ---------------------------------------------------------------------------
def _compte(db, numero: str, libelle: str) -> None:
    """Ajoute un compte absent du plan charge (comptes de produits 76x/77x)."""
    if db.execute(
        select(Account).where(Account.number == numero)
    ).scalar_one_or_none() is None:
        db.add(Account(number=numero, label=libelle, account_class=7))
        db.flush()


def _ecriture(db, ctx, lignes: list[dict], *, journal: str = "VE", label: str):
    exercice = get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    return create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=exercice,
        journal=get_journal(db, ctx["company"].id, journal),
        entry_date=date(ANNEE, 6, 15),
        label=label,
        lines=lignes,
        validate=True,
    )


def _ca_hors_tva(db, ctx, ht: str = "333333.33", tva: str = "66666.67", ttc: str = "400000"):
    """Vente : TTC encaisse, CA HT credit 7111, TVA credit 4455."""
    return _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "label": "Encaissement", "debit": ttc},
            {"account_number": "7111", "label": "Ventes", "credit": ht},
            {"account_number": "4455", "label": "TVA collectee", "credit": tva},
        ],
        journal="VE",
        label="Vente de l'exercice",
    )


# ---------------------------------------------------------------------------
# AMO — non-regression seule (aucune modification V7B)
# ---------------------------------------------------------------------------
def test_amo_2025_non_regression_totaux():
    """AMO 2025 : 2,26 % salarie / 4,11 % employeur / 6,37 % total, sans plafond."""
    cot = rates_ma.compute_cnss(10000, 2025)
    # Parts salariale et patronale (V7A-CORR : 4,52 % a parts egales + 1,85 %).
    assert cot["employee_amo"] == Decimal("226.00")  # 2,26 % de 10 000
    assert cot["employer_amo"] == Decimal("411.00")  # 4,11 % de 10 000
    total_amo = cot["employee_amo"] + cot["employer_amo"]
    assert total_amo == Decimal("637.00")  # 6,37 % du brut
    # Assiette AMO = brut integral (sans plafond) alors que la CNSS est plafonnee.
    assert cot["assiette_plafonnee"] == Decimal("6000.00")
    assert cot["employee_amo"] == rates_ma.money(Decimal("10000") * Decimal("0.0226"))
    # Non-regression : 2026 identique.
    cot_2026 = rates_ma.compute_cnss(10000)
    assert cot_2026["employee_amo"] == cot["employee_amo"]
    assert cot_2026["employer_amo"] == cot["employer_amo"]


# ---------------------------------------------------------------------------
# CM — assiette hors TVA (CM-1) et contenu complet (CM-2)
# ---------------------------------------------------------------------------
def test_base_cm_hors_tva(db, ctx):
    """La base de la CM exclut la TVA : 333 333,33 HT et non 400 000 TTC."""
    _ca_hors_tva(db, ctx)
    affaires = fiscal_liasse.chiffre_affaires(db, ctx["company"].id, ANNEE)
    assiette = fiscal_liasse.assiette_cotisation_minimale(db, ctx["company"].id, ANNEE)
    # Figure comptable (informationnelle) : CA TTC = HT + TVA.
    assert affaires["chiffre_affaires_ht"] == Decimal("333333.33")
    assert affaires["tva_collectee"] == Decimal("66666.67")
    assert affaires["chiffre_affaires_ttc"] == Decimal("400000.00")
    # Base CM : montant **hors TVA** — la TVA (4455) n'y entre pas.
    assert assiette["base_hors_tva"] == Decimal("333333.33")
    assert assiette["base_hors_tva"] != affaires["chiffre_affaires_ttc"]


def test_assiette_cm_complete_produits_financiers_subventions(db, ctx):
    """Assiette CM complete (CGI art. 144-I-B) : CA + 75x + 76x + 77x."""
    _ca_hors_tva(db, ctx)  # 71x : 333 333,33 HT
    # Autres produits d'exploitation (7512) et subvention (7561) : racine 75.
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "label": "Encaissement", "debit": "5000"},
            {"account_number": "7512", "label": "Autres produits", "credit": "3000"},
            {"account_number": "7561", "label": "Subvention d'exploitation", "credit": "2000"},
        ],
        journal="OD",
        label="Autres produits et subvention",
    )
    # Produits financiers (76x) et dons reus (77x) : comptes crees en memoire.
    _compte(db, "7611", "Interets et produits assimiles")
    _compte(db, "7711", "Dons et cadeaux recus")
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "5141", "label": "Encaissement", "debit": "7000"},
            {"account_number": "7611", "label": "Produits financiers", "credit": "5000"},
            {"account_number": "7711", "label": "Dons recus", "credit": "2000"},
        ],
        journal="OD",
        label="Produits financiers et dons",
    )
    assiette = fiscal_liasse.assiette_cotisation_minimale(db, ctx["company"].id, ANNEE)
    assert assiette["detail"]["71"] == Decimal("333333.33")
    assert assiette["detail"]["75"] == Decimal("5000.00")
    assert assiette["detail"]["76"] == Decimal("5000.00")
    assert assiette["detail"]["77"] == Decimal("2000.00")
    # 333 333,33 + 5 000 + 5 000 + 2 000 = 345 333,33 (sans la TVA 66 666,67).
    assert assiette["base_hors_tva"] == Decimal("345333.33")
    # La TVA collectee n'est jamais agregee a la base CM.
    assert assiette["base_hors_tva"] != Decimal("410000.00")


# ---------------------------------------------------------------------------
# CM — taux/plancher 2025, exoneration 36 mois, butee 60 mois
# ---------------------------------------------------------------------------
def test_cm_2025_taux_et_plancher_via_calculer_is(db, ctx):
    """CM 2025 : 0,25 % de l'assiette hors TVA, plancher 3 000 DH applique."""
    _ca_hors_tva(db, ctx)  # assiette 333 333,33 -> 0,25 % = 833,33 < 3 000
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    ctx["company"].date_constitution = date(2019, 1, 1)
    ctx["company"].date_debut_exploitation = date(2021, 1, 1)
    db.commit()
    calcul = fiscal_liasse.calculer_is(db, ctx["company"], ANNEE)
    assert calcul["base_cotisation_minimale"] == Decimal("333333.33")  # hors TVA
    assert calcul["cotisation_minimale"] == Decimal("3000.00")  # plancher
    assert calcul["exoneration_cotisation_minimale"]["exoneree"] is False
    # Meme assiette avec une saisie de 48 mois : 0,25 % x 333 333,33 = 833,33.
    calcul = fiscal_liasse.calculer_is(db, ctx["company"], ANNEE, mois_activite=48)
    assert calcul["cotisation_minimale"] == Decimal("3000.00")
    # Assiette au-dela du plancher : 0,25 % x 1 000 000 = 2 500 -> plancher 3 000.
    assert (
        rates_ma.compute_cotisation_minimale(1000000, months_of_activity=48, annee=2025)
        == Decimal("3000.00")
    )
    assert (
        rates_ma.compute_cotisation_minimale(4000000, months_of_activity=48, annee=2025)
        == Decimal("10000.00")
    )  # 0,25 %


def test_exoneration_36_mois_et_butee_60_mois(db, ctx):
    """Exoneration 36 mois epuisee par la butee 60 mois depuis la constitution."""
    _ca_hors_tva(db, ctx)
    company = ctx["company"]
    company.date_constitution = date(2018, 1, 1)  # +60 mois -> fin janv. 2023
    company.date_debut_exploitation = date(2025, 1, 1)  # 12 mois d'activite
    db.commit()

    etat = fiscal_liasse.exoneration_cotisation_minimale(db, company, ANNEE)
    assert etat["mois_activite"] == 12  # encore dans les 36 mois d'activite
    assert etat["butee_constitution_mois"] == 60
    assert etat["fin_butee_constitution"] == date(2023, 1, 1)
    assert etat["exoneree"] is False  # ... mais la butee 60 mois a expire

    calcul = fiscal_liasse.calculer_is(db, company, ANNEE)
    assert calcul["exoneration_cotisation_minimale"]["exoneree"] is False
    assert calcul["cotisation_minimale"] == Decimal("3000.00")  # CM due (plancher)


def test_cm_non_exigible_societe_recente(db, ctx):
    """Cas societe actuelle : debut d'exploitation 2025-01-01 -> CM = 0,00 DH."""
    _ca_hors_tva(db, ctx)
    company = ctx["company"]
    company.date_constitution = date(2025, 1, 1)
    company.date_debut_exploitation = date(2025, 1, 1)
    db.commit()

    calcul = fiscal_liasse.calculer_is(db, company, ANNEE)
    assert calcul["mois_activite"] == 12
    exoneration = calcul["exoneration_cotisation_minimale"]
    assert exoneration["exoneree"] is True
    assert exoneration["duree_exoneration_mois"] == 36
    assert exoneration["butee_constitution_mois"] == 60
    assert exoneration["fin_exoneration"] == date(2028, 1, 1)  # debut + 36 mois
    assert calcul["base_cotisation_minimale"] == Decimal("333333.33")  # hors TVA
    assert calcul["cotisation_minimale"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# IS 2025 — cas courant (les taux corriges 31,25 % / 39,25 % / 18,75 % et le
# refus d'une annee non configuree sont verifies dans tests/test_rates_ma_2025.py)
# ---------------------------------------------------------------------------
def test_is_2025_cas_courant_conforme_via_calculer_is(db, ctx):
    """Cas courant 2025 : deficit -> IS nul, CM due ; bornes 17,5 % / 20 %."""
    _ca_hors_tva(db, ctx)  # produits 333 333,33 HT (aucune TVA dans la base CM)
    get_or_create_fiscal_year(db, ctx["company"], ANNEE)
    company = ctx["company"]
    company.date_constitution = date(2020, 1, 1)
    company.date_debut_exploitation = date(2020, 1, 1)
    db.commit()
    # Charges superieures aux produits : resultat fiscal negatif -> pas d'IS.
    _ecriture(
        db,
        ctx,
        [
            {"account_number": "6111", "label": "Achats", "debit": "500000"},
            {"account_number": "4411", "label": "Fournisseur", "credit": "500000"},
        ],
        journal="AC",
        label="Achats de l'exercice",
    )
    calcul = fiscal_liasse.calculer_is(db, company, ANNEE)
    assert calcul["taux_is_exercice"] == "0.20"  # taux de droit commun 2025
    assert calcul["is_theorique"] == Decimal("0.00")  # deficit -> pas d'IS
    assert calcul["resultat_fiscal"] < 0
    assert calcul["cotisation_minimale"] == Decimal("3000.00")  # CM due (art. 144)
    # Borne transitoire conservee : 17,5 % <= 300 000 DH (2025) vs 20 % (2026).
    assert rates_ma.compute_is(Decimal("92000"), annee=2025) == Decimal("16100.00")
    assert rates_ma.compute_is(Decimal("92000"), annee=2026) == Decimal("18400.00")


# ---------------------------------------------------------------------------
# Paie 2025 — parametres reels corriges (aucune paie creee en DB)
# ---------------------------------------------------------------------------
def test_paie_2025_parametres_corriges_en_memoire():
    """Frais pro 2025 (35/25 % - 78 000 - plafond 35 000) et CNSS/AMO 2025."""
    # Frais professionnels (CGI 2025 art. 59) : 35 % jusqu'a 78 000 DH.
    assert rates_ma.compute_professional_expenses(78000, 2025) == Decimal("27300.00")
    assert rates_ma.compute_professional_expenses(200000, 2025) == Decimal("35000.00")
    assert rates_ma.frais_professionnels_mensuels(5000, 2025) == Decimal("1750.00")
    # CNSS plafonnee 6 000 / AMO sans plafond / PF 6,40 % / TFP 1,60 %.
    cot = rates_ma.compute_cnss(20000, 2025)
    assert cot["assiette_plafonnee"] == Decimal("6000.00")
    assert cot["employee_social"] == Decimal("268.80")
    assert cot["employee_amo"] == Decimal("452.00")  # 2,26 % de 20 000 (sans plafond)
    assert cot["employer_amo"] == Decimal("822.00")  # 4,11 % de 20 000
    assert cot["employer_family"] == Decimal("1280.00")  # 6,40 % de 20 000
    assert cot["employer_tfp"] == Decimal("320.00")  # 1,60 % de 20 000
    # IR 2025 : tranche haute 37 %, deduction 500 DH/personne (6 max).
    assert rates_ma.compute_ir_annual(200000, 2025) == Decimal("46600.00")
    assert rates_ma.deduction_charges_famille(2, 2025) == Decimal("1000.00")
    assert rates_ma.deduction_charges_famille(9, 2025) == Decimal("3000.00")
    # Exercice non parametre : refuse (aucun taux devine).
    with pytest.raises(rates_ma.BaremeIndisponible):
        rates_ma.compute_cnss(10000, 2027)
    with pytest.raises(rates_ma.BaremeIndisponible):
        rates_ma.compute_ir_monthly(5000, 0, 2027)
