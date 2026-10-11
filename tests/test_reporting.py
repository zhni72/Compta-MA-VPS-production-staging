"""Tests des etats comptables : balance, grand livre, CPC, bilan, journaux."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.invoicing import create_invoice, validate_invoice
from app.services.parties import create_third_party
from app.services.reporting import (
    balance_generale,
    balance_sheet,
    grand_livre,
    income_statement,
    journal_entries,
    year_bounds,
)

pytestmark = pytest.mark.usefixtures("ctx")

START_OF_YEAR, END_OF_YEAR = year_bounds(2026)


@pytest.fixture()
def operations(db, ctx) -> dict:
    """Une vente de 1 500 HT (TVA 20 %) et un achat de 1 000 HT (TVA 20 %)."""
    client = create_third_party(
        db, company=ctx["company"], kind="client", name="Client Etats", ice="006789012000017"
    )
    fournisseur = create_third_party(
        db,
        company=ctx["company"],
        kind="fournisseur",
        name="Fournisseur Etats",
        ice="007890123000014",
    )
    vente = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 6, 15),
        lines=[{"designation": "Ventes", "quantity": 1, "unit_price": 1500, "vat_rate": 20}],
    )
    validate_invoice(db, vente, user_id=ctx["user"].id)
    achat = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 6, 20),
        lines=[{"designation": "Achats", "quantity": 1, "unit_price": 1000, "vat_rate": 20}],
    )
    validate_invoice(db, achat, user_id=ctx["user"].id)
    return {"client": client, "fournisseur": fournisseur, "vente": vente, "achat": achat}


def test_balance_generale_equilibree(db, ctx, operations):
    balance = balance_generale(db, ctx["company"].id, START_OF_YEAR, END_OF_YEAR)
    assert balance["equilibre"] is True
    assert balance["total_debit"] == balance["total_credit"]
    comptes = {line["account_number"]: line for line in balance["lines"]}
    assert comptes["7111"]["solde"] == Decimal("-1500.00")
    assert comptes["6111"]["solde"] == Decimal("1000.00")
    assert comptes["4455"]["solde"] == Decimal("-300.00")
    assert comptes["34552"]["solde"] == Decimal("200.00")


def test_cpc_et_resultat(db, ctx, operations):
    cpc = income_statement(db, ctx["company"].id, START_OF_YEAR, END_OF_YEAR)
    assert cpc["total_produits"] == Decimal("1500.00")
    assert cpc["total_charges"] == Decimal("1000.00")
    assert cpc["resultat"] == Decimal("500.00")
    assert cpc["nature_resultat"] == "benefice"


def test_bilan_equilibre(db, ctx, operations):
    bilan = balance_sheet(db, ctx["company"].id, START_OF_YEAR, END_OF_YEAR)
    assert bilan["equilibre"] is True
    assert bilan["total_actif"] == bilan["total_passif_avec_resultat"]
    assert bilan["resultat_exercice"] == Decimal("500.00")
    # La banque n'a pas ete mouvementee : seuls clients, fournisseurs et TVA.
    comptes_actif = {line["account_number"] for line in bilan["actif"]}
    assert "34552" in comptes_actif


def test_grand_livre_du_compte_client(db, ctx, operations):
    client = operations["client"]
    livre = grand_livre(db, ctx["company"].id, client.account_number, START_OF_YEAR, END_OF_YEAR)
    assert livre["solde"] == Decimal("1800.00")  # 1 500 HT + 300 TVA
    assert livre["lines"][0]["solde_cumule"] == Decimal("1800.00")


def test_journal_des_ventes(db, ctx, operations):
    lignes = journal_entries(db, ctx["company"].id, START_OF_YEAR, END_OF_YEAR, "VE")
    assert len(lignes) == 1
    assert lignes[0]["debit"] == Decimal("1800.00")
    assert lignes[0]["credit"] == Decimal("1800.00")
    # Le journal des achats contient l'autre facture.
    achats = journal_entries(db, ctx["company"].id, START_OF_YEAR, END_OF_YEAR, "AC")
    assert len(achats) == 1
    assert achats[0]["credit"] == Decimal("1200.00")


def test_balance_auxiliaire_par_tiers(db, ctx, operations):
    from app.services.parties import auxiliary_balance

    lignes = auxiliary_balance(db, ctx["company"].id, kind="client")
    assert len(lignes) == 1
    assert lignes[0]["solde"] == Decimal("1800.00")
    fournisseurs = auxiliary_balance(db, ctx["company"].id, kind="fournisseur")
    assert fournisseurs[0]["solde"] == Decimal("-1200.00")