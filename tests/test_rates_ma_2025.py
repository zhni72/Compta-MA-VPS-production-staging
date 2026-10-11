"""P1B V7B — referentiels 2025 : bareme IR 2025, grille IS 2025 corrigee, CM.

Verifie que les referentiels 2025 sont **histories et documentes** (aucun taux
devine) et que l'exercice 2026 n'est pas affecte :

- IR 2025 : bareme 6 tranches et deduction pour charges de famille de **500 DH**
  par personne (6 au maximum), contre 600 DH en 2026 ;
- IS 2025 : grille transitoire corrigee en V7B (17,5 % si benefice net fiscal
  <= 300 000 DH, 20 % au-dela, **31,25 %** >= 100 M DH, **39,25 %** etablissements
  de credit, **18,75 %** CFC/ZAI) ;
- cotisation minimale 2025 : 0,25 % des produits **hors TVA**, plancher 3 000 DH,
  exoneration 36 mois avec **butee 60 mois depuis la constitution** ;
- paie 2025 : barème complet documente (frais professionnels art. 59, CNSS/AMO)
  et calculable ; les années non parametrees restent refusees.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import rates_ma


def test_bareme_ir_2025_et_deduction_familiale():
    """Bareme IR 2025 identique en tranches, deduction familiale de 500 DH."""
    assert rates_ma.compute_ir_annual(40000, 2025) == Decimal("0.00")
    assert rates_ma.compute_ir_annual(60000, 2025) == Decimal("2000.00")
    assert rates_ma.compute_ir_annual(200000, 2025) == Decimal("46600.00")
    assert rates_ma.deduction_charges_famille(2, 2025) == Decimal("1000.00")
    assert rates_ma.deduction_charges_famille(9, 2025) == Decimal("3000.00")  # 6 max
    assert rates_ma.deduction_charges_famille(2, 2026) == Decimal("1200.00")
    # L'IR mensuel 2025 est calcule avec le bareme 2025 (aucun taux en dur).
    assert rates_ma.compute_ir_monthly(15000, 0, 2025) > 0
    assert rates_ma.compute_ir_monthly(15000, 0, 2025) == rates_ma.compute_ir_monthly(
        15000, 0, 2026
    )


def test_is_2025_grille_transitoire():
    """IS 2025 : 17,5 % jusqu'a 300 000 DH, 20 % au-dela, taux sectoriels corriges.

    Taux specifiques 2025 corriges en V7B au referentiel V6 (CGI 2025
    art. 247-XXXVII p. 470-472) : 31,25 % / 39,25 % / 18,75 %.
    """
    taux = rates_ma.IS_RATES_BY_YEAR[2025]
    assert taux["small_profit"] == Decimal("0.175")
    assert taux["standard"] == Decimal("0.20")
    assert taux["large_company"] == Decimal("0.3125")
    assert taux["financial"] == Decimal("0.3925")
    assert taux["cfc"] == Decimal("0.1875")
    assert rates_ma.IS_SMALL_PROFIT_THRESHOLD_2025 == Decimal("300000")
    # 2026 : grille inchangee (droit commun 20 %, grandes entreprises 35 %).
    assert rates_ma.IS_RATES_BY_YEAR[2026]["standard"] == Decimal("0.20")
    assert rates_ma.IS_RATES_BY_YEAR[2026]["large_company"] == Decimal("0.35")
    assert "small_profit" not in rates_ma.IS_RATES_BY_YEAR[2026]


def test_cotisation_minimale_2025():
    """CM 2025 : 0,25 % hors TVA, plancher 3 000 DH, exo 36 mois / butee 60 mois."""
    parametres = rates_ma.COTISATION_MINIMALE_BY_YEAR[2025]
    assert parametres["rate"] == Decimal("0.0025")
    assert parametres["minimum"] == Decimal("3000")
    assert parametres["exemption_months"] == 36
    assert parametres["exemption_butee_months"] == 60
    # La donnee d'entree est une assiette hors TVA : 0,25 % x 400 000 = 1 000.
    assert (
        rates_ma.compute_cotisation_minimale(400000, months_of_activity=48, annee=2025)
        == Decimal("3000.00")
    )  # plancher
    assert (
        rates_ma.compute_cotisation_minimale(4000000, months_of_activity=48, annee=2025)
        == Decimal("10000.00")
    )  # 0,25 % de l'assiette
    # 2026 : meme mecanisme, inchange.
    assert rates_ma.COTISATION_MINIMALE_BY_YEAR[2026]["exemption_butee_months"] == 60


def test_parametres_2025_documentes_sont_complets():
    """Frais professionnels et CNSS/AMO 2025 : documentes par P1B V6 (V7B).

    Le barème 2025 est complet (plus aucun `a_fournir`) ; un exercice **absent**
    du registre (2027) reste liste comme incomplet — aucune valeur devinee.
    """
    assert rates_ma.parametres_paie_manquants(2025) == []
    assert rates_ma.parametres_paie_manquants(2026) == []
    assert rates_ma.referentiel_complet(2025) is True
    assert rates_ma.referentiel_complet(2026) is True
    assert rates_ma.parametres_paie_manquants(2027) != []
    assert rates_ma.referentiel_complet(2027) is False


def test_paie_2025_calculee_avec_ses_propres_taux():
    """Paie 2025 : CNSS/AMO/frais professionnels calcules avec le bareme 2025.

    Aucun taux n'est devine : les valeurs 2025 (identiques aux taux 2026
    confirmes par V6) viennent de `BAREMES_PAIE[2025]`. Un exercice non
    parametre (2027) reste refuse (`BaremeIndisponible`).
    """
    # Cotisations 2025 : 4,48 % / 8,98 % plafonnees a 6 000 DH, AMO 2,26 %/4,11 %.
    cotisations_2025 = rates_ma.compute_cnss(10000, 2025)
    assert cotisations_2025["assiette_plafonnee"] == Decimal("6000.00")
    assert cotisations_2025["employee_social"] == Decimal("268.80")
    assert cotisations_2025["employee_amo"] == Decimal("226.00")  # 2,26 %
    assert cotisations_2025["employer_amo"] == Decimal("411.00")  # 4,11 %
    assert cotisations_2025["employer_family"] == Decimal("640.00")  # 6,40 %
    assert cotisations_2025["employer_tfp"] == Decimal("160.00")  # 1,60 %
    assert cotisations_2025["total_employee"] == Decimal("494.80")
    assert cotisations_2025["total_employer"] == Decimal("1749.80")
    # Frais professionnels 2025 : 35 % / 25 %, seuil 78 000 DH, plafond 35 000 DH.
    assert rates_ma.frais_professionnels_mensuels(5000, 2025) == Decimal("1750.00")
    assert rates_ma.frais_professionnels_mensuels(10000, 2025) == Decimal("2500.00")
    assert rates_ma.compute_professional_expenses(60000, 2025) == Decimal("21000.00")
    assert rates_ma.compute_professional_expenses(78000, 2025) == Decimal("27300.00")
    assert rates_ma.compute_professional_expenses(200000, 2025) == Decimal("35000.00")
    # L'exercice 2026 reste inchange.
    assert rates_ma.compute_cnss(10000)["total_employee"] == Decimal("494.80")
    assert rates_ma.frais_professionnels_mensuels(5000) == Decimal("1750.00")
    # Aucun bareme n'est devine : 2027 (absent) est refuse.
    with pytest.raises(rates_ma.BaremeIndisponible):
        rates_ma.compute_cnss(10000, 2027)
    with pytest.raises(rates_ma.BaremeIndisponible):
        rates_ma.frais_professionnels_mensuels(5000, 2027)


def test_compute_is_2025_applique_le_taux_transitoire():
    """IS 2025 : 17,5 % <= 300 000 DH, 20 % au-dela, **31,25 %** >= 100 M DH."""
    from decimal import Decimal

    from app.core.rates_ma import compute_is

    assert compute_is(Decimal("92000"), annee=2025) == Decimal("16100.00")
    assert compute_is(Decimal("300000"), annee=2025) == Decimal("52500.00")  # 17,5 %
    assert compute_is(Decimal("300001"), annee=2025) == Decimal("60000.20")  # 20 %
    # Taux grandes entreprises 2025 corrige : 31,25 % (V6 : 35 % etait non conforme).
    assert compute_is(Decimal("200000000"), annee=2025) == Decimal("62500000.00")
    # Categories sectorielles 2025 corrigees : 39,25 % / 18,75 %.
    assert compute_is(Decimal("1000000"), category="financial", annee=2025) == Decimal(
        "392500.00"
    )
    assert compute_is(Decimal("1000000"), category="cfc", annee=2025) == Decimal(
        "187500.00"
    )
    # 2026 inchange : 35 % au-dela de 100 M (taux de droit commun sectoriels).
    assert compute_is(Decimal("200000000"), annee=2026) == Decimal("70000000.00")
    assert compute_is(Decimal("1000000"), category="financial", annee=2026) == Decimal(
        "400000.00"
    )
    # Une annee sans bareme reste refusee (aucun taux devine).
    with pytest.raises(ValueError) as erreur:
        compute_is(Decimal("92000"), annee=2024)
    assert "2024" in str(erreur.value)


def test_compute_is_2026_inchange():
    """2026 : aucun taux transitoire, le taux de droit commun reste 20 %."""
    from decimal import Decimal

    from app.core.rates_ma import compute_is

    assert compute_is(Decimal("92000"), annee=2026) == Decimal("18400.00")
    assert compute_is(Decimal("92000")) == Decimal("18400.00")  # appel historique


def test_exoneration_cotisation_minimale_par_dates_reelles(db, ctx):
    """CM non exigible pendant les 36 premiers mois d'activite (CGI art. 144).

    La fenetre d'exoneration est en plus **butee a 60 mois depuis la
    constitution** (art. 144-I-C-1°, CM-3 V7B).
    """
    from datetime import date

    from app.services import fiscal_liasse

    company = ctx["company"]
    company.date_constitution = None
    company.date_debut_exploitation = date(2025, 1, 1)
    db.commit()
    etat = fiscal_liasse.exoneration_cotisation_minimale(db, company, 2025)
    assert etat["exoneree"] is True
    assert etat["date_debut_activite"] == date(2025, 1, 1)
    assert etat["duree_exoneration_mois"] == 36

    company.date_debut_exploitation = date(2018, 1, 1)
    db.commit()
    etat = fiscal_liasse.exoneration_cotisation_minimale(db, company, 2025)
    assert etat["exoneree"] is False

    # Butee 60 mois : constitution 2018, debut d'exploitation 2025 (12 mois
    # d'activite seulement) — l'exoneration est deja epuisee au 31/12/2025.
    company.date_constitution = date(2018, 1, 1)
    company.date_debut_exploitation = date(2025, 1, 1)
    db.commit()
    etat = fiscal_liasse.exoneration_cotisation_minimale(db, company, 2025)
    assert etat["mois_activite"] == 12
    assert etat["butee_constitution_mois"] == 60
    assert etat["fin_butee_constitution"] == date(2023, 1, 1)
    assert etat["fin_exoneration"] == date(2023, 1, 1)  # min(2028-01, 2023-01)
    assert etat["exoneree"] is False

    # Constitution 2024 : la butee (fin 2029) n'est pas encore atteinte en 2025.
    company.date_constitution = date(2024, 1, 1)
    company.date_debut_exploitation = date(2025, 1, 1)
    db.commit()
    etat = fiscal_liasse.exoneration_cotisation_minimale(db, company, 2025)
    assert etat["fin_exoneration"] == date(2028, 1, 1)  # debut + 36 mois
    assert etat["exoneree"] is True


def test_sources_2025_documentees():
    """Les sources 2025 sont toutes documentees (V6) ; CM = base hors TVA."""
    sources = rates_ma.sources_referentiel(2025)
    assert sources  # exercice 2025 parametre
    statuts = {entree["element"]: entree["statut"] for entree in sources}
    assert any(statut.startswith("documente") for statut in statuts.values())
    # Plus aucune donnee « a fournir » apres la correction V7B.
    assert not any(statut == "a_fournir" for statut in statuts.values())
    assert any("CNSS" in element for element in statuts)
    # Terminologie CM : la base est hors TVA (plus « CA TTC »).
    entree_cm = next(
        entree for entree in sources if entree["element"].startswith("Cotisation minimale")
    )
    assert "hors TVA" in entree_cm["valeur"]
    assert "hors TVA" in entree_cm["base"]
