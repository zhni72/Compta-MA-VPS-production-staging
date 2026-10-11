"""Tests des baremes marocains 2026 (IR, CNSS, IS, cotisation minimale)."""

from decimal import Decimal

from app.core.rates_ma import (
    compute_cnss,
    compute_cotisation_minimale,
    compute_ir_annual,
    compute_is,
    compute_professional_expenses,
)


def test_ir_2026_bareme_progressif():
    assert compute_ir_annual(0) == Decimal("0.00")
    assert compute_ir_annual(40000) == Decimal("0.00")
    assert compute_ir_annual(60000) == Decimal("2000.00")  # 10 % - 4 000
    assert compute_ir_annual(80000) == Decimal("6000.00")  # 20 % - 10 000
    assert compute_ir_annual(100000) == Decimal("12000.00")  # 30 % - 18 000
    assert compute_ir_annual(180000) == Decimal("39200.00")  # 34 % - 22 000
    assert compute_ir_annual(200000) == Decimal("46600.00")  # 37 % - 27 400


def test_frais_professionnels_2026():
    assert compute_professional_expenses(60000) == Decimal("21000.00")  # 35 %
    assert compute_professional_expenses(78000) == Decimal("27300.00")  # 35 %
    assert compute_professional_expenses(200000) == Decimal("35000.00")  # 25 % plafonne


def test_cnss_amo_2026_avec_plafond():
    cotisations = compute_cnss(10000)
    assert cotisations["assiette_plafonnee"] == Decimal("6000.00")
    assert cotisations["employee_social"] == Decimal("268.80")  # 4,48 % plafonne
    assert cotisations["employee_amo"] == Decimal("226.00")  # 2,26 % sans plafond
    assert cotisations["total_employee"] == Decimal("494.80")  # 6,74 %
    assert cotisations["employer_social"] == Decimal("538.80")  # 8,98 % plafonne
    assert cotisations["employer_amo"] == Decimal("411.00")  # 4,11 %
    assert cotisations["employer_family"] == Decimal("640.00")  # 6,40 %
    assert cotisations["employer_tfp"] == Decimal("160.00")  # 1,60 %
    assert cotisations["total_employer"] == Decimal("1749.80")  # 21,09 %
    assert cotisations["net_a_payer"] == Decimal("9505.20")


def test_is_2026_par_categorie():
    assert compute_is(1000000) == Decimal("200000.00")  # 20 %
    assert compute_is(200000000) == Decimal("70000000.00")  # 35 % au-dela de 100 M
    assert compute_is(1000000, category="financial") == Decimal("400000.00")  # 40 %


def test_cotisation_minimale_et_exoneration_36_mois():
    # Exoneration totale pendant les 36 premiers mois d'activite.
    assert compute_cotisation_minimale(400000) == Decimal("0.00")
    assert compute_cotisation_minimale(4000000, months_of_activity=36) == Decimal("0.00")
    # Au-dela : 0,25 % de l'assiette hors TVA avec un plancher de 3 000 MAD.
    assert compute_cotisation_minimale(400000, months_of_activity=48) == Decimal("3000.00")
    assert compute_cotisation_minimale(4000000, months_of_activity=48) == Decimal("10000.00")