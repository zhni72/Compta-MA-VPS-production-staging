"""Tests de la TVA : periodes, echeances, regime et declaration."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.invoicing import create_invoice, validate_invoice
from app.services.parties import create_third_party
from app.services.vat import (
    period_bounds,
    suggested_vat_regime,
    vat_deadline,
    vat_return,
    vat_summary_by_rate,
)

pytestmark = pytest.mark.usefixtures("ctx")

FIRST_QUARTER_2026 = (date(2026, 1, 1), date(2026, 3, 31))


def test_bornes_de_periode():
    assert period_bounds(2026, month=3) == (date(2026, 3, 1), date(2026, 3, 31))
    assert period_bounds(2026, month=2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds(2026, quarter=1) == (date(2026, 1, 1), date(2026, 3, 31))
    assert period_bounds(2026, quarter=4) == (date(2026, 10, 1), date(2026, 12, 31))


def test_echeance_le_20_du_mois_suivant():
    assert vat_deadline(date(2026, 3, 31)) == date(2026, 4, 20)
    assert vat_deadline(date(2026, 12, 31)) == date(2027, 1, 20)


def test_regime_declaration_selon_le_chiffre_d_affaires():
    assert suggested_vat_regime(1200000) == "mensuel"
    assert suggested_vat_regime(999999) == "trimestriel"


def _parties(db, ctx):
    client = create_third_party(
        db, company=ctx["company"], kind="client", name="Client TVA", ice="004567890000013"
    )
    fournisseur = create_third_party(
        db,
        company=ctx["company"],
        kind="fournisseur",
        name="Fournisseur TVA",
        ice="005678901000010",
    )
    return client, fournisseur


def test_declaration_tva_collectee_et_deductible(db, ctx):
    client, fournisseur = _parties(db, ctx)
    vente = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 3, 5),
        lines=[
            {"designation": "Vente a 20 %", "quantity": 1, "unit_price": 1000, "vat_rate": 20},
            {"designation": "Vente a 10 %", "quantity": 1, "unit_price": 1000, "vat_rate": 10},
        ],
    )
    validate_invoice(db, vente, user_id=ctx["user"].id)
    achat = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 3, 10),
        lines=[{"designation": "Achat", "quantity": 1, "unit_price": 500, "vat_rate": 20}],
    )
    validate_invoice(db, achat, user_id=ctx["user"].id)

    declaration = vat_return(db, ctx["company"].id, *FIRST_QUARTER_2026)
    assert declaration["tva_collectee"] == Decimal("300.00")  # 200 (20 %) + 100 (10 %)
    assert declaration["tva_deductible"] == Decimal("100.00")
    assert declaration["tva_nette"] == Decimal("200.00")
    assert declaration["tva_a_payer"] == Decimal("200.00")
    assert declaration["credit_tva_a_reporter"] == Decimal("0.00")
    assert declaration["echeance"] == date(2026, 4, 20)

    # Un autre trimestre ne contient aucune operation.
    empty = vat_return(db, ctx["company"].id, *period_bounds(2026, quarter=2))
    assert empty["tva_collectee"] == Decimal("0.00")
    assert empty["tva_nette"] == Decimal("0.00")


def test_credit_de_tva_a_reporter(db, ctx):
    _, fournisseur = _parties(db, ctx)
    achat = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 2, 15),
        lines=[{"designation": "Achat", "quantity": 1, "unit_price": 1000, "vat_rate": 20}],
    )
    validate_invoice(db, achat, user_id=ctx["user"].id)

    declaration = vat_return(db, ctx["company"].id, *FIRST_QUARTER_2026)
    assert declaration["tva_collectee"] == Decimal("0.00")
    assert declaration["tva_deductible"] == Decimal("200.00")
    assert declaration["tva_nette"] == Decimal("-200.00")
    assert declaration["tva_a_payer"] == Decimal("0.00")
    assert declaration["credit_tva_a_reporter"] == Decimal("200.00")


def test_recapitulatif_des_ventes_par_taux(db, ctx):
    client, _ = _parties(db, ctx)
    vente = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 3, 5),
        lines=[
            {"designation": "Vente a 20 %", "quantity": 1, "unit_price": 1000, "vat_rate": 20},
            {"designation": "Vente a 10 %", "quantity": 1, "unit_price": 1000, "vat_rate": 10},
        ],
    )
    validate_invoice(db, vente, user_id=ctx["user"].id)

    rows = vat_summary_by_rate(
        db, ctx["company"].id, date(2026, 1, 1), date(2026, 12, 31)
    )
    par_taux = {row["vat_rate"]: row for row in rows}
    assert par_taux[Decimal("20.00")]["base_ht"] == Decimal("1000.00")
    assert par_taux[Decimal("20.00")]["tva"] == Decimal("200.00")
    assert par_taux[Decimal("10.00")]["tva"] == Decimal("100.00")
    assert par_taux[Decimal("20.00")]["ttc"] == Decimal("1200.00")