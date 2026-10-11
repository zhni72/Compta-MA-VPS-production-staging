"""Tests de la facturation : totaux, numerotation, comptabilisation, reglements."""

from datetime import date
from decimal import Decimal

import pytest

from app.models import Entry
from app.services.accounting import AccountingError, ComplianceError
from app.services.invoicing import (
    add_line,
    cancel_invoice,
    create_invoice,
    register_payment,
    validate_invoice,
)
from app.services.parties import create_third_party

pytestmark = pytest.mark.usefixtures("ctx")


def make_client(db, ctx, **kwargs):
    params = {
        "company": ctx["company"],
        "kind": "client",
        "name": "Client Test SARL",
        "ice": "002345678000019",
        "payment_terms_days": 30,
    }
    params.update(kwargs)
    return create_third_party(db, **params)


def make_supplier(db, ctx, **kwargs):
    params = {
        "company": ctx["company"],
        "kind": "fournisseur",
        "name": "Fournisseur Test SARL",
        "ice": "003456789000016",
    }
    params.update(kwargs)
    return create_third_party(db, **params)


def account_map(entry: Entry) -> dict[str, Decimal]:
    """Solde par compte d'une ecriture (debit - credit)."""
    balances: dict[str, Decimal] = {}
    for line in entry.lines:
        balances[line.account_number] = (
            balances.get(line.account_number, Decimal("0")) + line.debit - line.credit
        )
    return balances


def test_facture_vente_multi_taux_comptabilisee(db, ctx):
    client = make_client(db, ctx)
    invoice = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 4, 10),
        lines=[
            {
                "designation": "Prestation de service",
                "quantity": 1,
                "unit_price": 1000,
                "vat_rate": 20,
            },
            {"designation": "Transport", "quantity": 1, "unit_price": 500, "vat_rate": 10},
        ],
    )
    assert invoice.total_ht == Decimal("1500.00")
    assert invoice.total_vat == Decimal("250.00")
    assert invoice.total_ttc == Decimal("1750.00")
    assert invoice.number is None  # numero attribue seulement a la validation

    validate_invoice(db, invoice, user_id=ctx["user"].id)
    assert invoice.number == "FV202600001"
    assert invoice.status == "validated"

    entry = db.get(Entry, invoice.entry_id)
    assert entry is not None and entry.is_balanced
    assert entry.total_debit == Decimal("1750.00")
    assert entry.total_credit == Decimal("1750.00")
    soldes = account_map(entry)
    assert soldes[client.account_number] == Decimal("1750.00")  # 3421 clients (TTC)
    assert soldes["7111"] == Decimal("-1500.00")  # produit HT
    assert soldes["4455"] == Decimal("-250.00")  # TVA facturee (20 % + 10 %)
    assert entry.entry_date == date(2026, 4, 10)
    assert invoice.due_date == date(2026, 5, 10)  # 30 jours de delai de reglement


def test_ice_obligatoire_sur_facture_de_vente(db, ctx):
    client = make_client(db, ctx, name="Client Sans ICE", ice=None)
    invoice = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 4, 10),
        lines=[{"designation": "Prestation", "quantity": 1, "unit_price": 1000, "vat_rate": 20}],
    )
    with pytest.raises(ComplianceError):
        validate_invoice(db, invoice, user_id=ctx["user"].id)
    assert invoice.number is None  # aucun numero consomme : pas de trou

    # Un particulier est dispense d'ICE : la facture est validee normalement.
    particulier = make_client(db, ctx, name="Particulier", ice=None, is_individual=True)
    invoice_particulier = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=particulier,
        invoice_date=date(2026, 4, 11),
        lines=[{"designation": "Vente au comptant", "quantity": 1, "unit_price": 300, "vat_rate": 20}],
    )
    validate_invoice(db, invoice_particulier, user_id=ctx["user"].id)
    assert invoice_particulier.number == "FV202600001"


def test_numerotation_continue_sans_trou(db, ctx):
    client = make_client(db, ctx)
    premiere = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 5, 2),
        lines=[{"designation": "Vente", "quantity": 1, "unit_price": 1000, "vat_rate": 20}],
    )
    validate_invoice(db, premiere, user_id=ctx["user"].id)
    assert premiere.number == "FV202600001"

    cancel_invoice(db, premiere, reason="Erreur de client", user_id=ctx["user"].id)
    assert premiere.status == "cancelled"

    deuxieme = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 5, 3),
        lines=[{"designation": "Vente", "quantity": 1, "unit_price": 2000, "vat_rate": 20}],
    )
    validate_invoice(db, deuxieme, user_id=ctx["user"].id)
    assert deuxieme.number == "FV202600002"  # le numero annule n'est jamais reutilise


def test_facture_achat_et_tva_recuperable(db, ctx):
    fournisseur = make_supplier(db, ctx)
    invoice = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="achat",
        partner=fournisseur,
        invoice_date=date(2026, 4, 5),
        lines=[{"designation": "Marchandises", "quantity": 10, "unit_price": 100, "vat_rate": 20}],
    )
    validate_invoice(db, invoice, user_id=ctx["user"].id)
    assert invoice.number == "FA202600001"
    soldes = account_map(db.get(Entry, invoice.entry_id))
    assert soldes["6111"] == Decimal("1000.00")  # achat de marchandises (debit)
    assert soldes["34552"] == Decimal("200.00")  # TVA recuperable sur charges
    assert soldes[fournisseur.account_number] == Decimal("-1200.00")  # 4411 fournisseurs


def test_reglement_partiel_puis_total(db, ctx):
    client = make_client(db, ctx)
    invoice = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 4, 10),
        lines=[{"designation": "Vente", "quantity": 1, "unit_price": 1750, "vat_rate": 0}],
    )
    validate_invoice(db, invoice, user_id=ctx["user"].id)
    assert invoice.total_ttc == Decimal("1750.00")

    paiement = register_payment(
        db, invoice, amount=1000, payment_date=date(2026, 4, 20), method="virement"
    )
    assert invoice.status == "partially_paid"
    assert invoice.paid_amount == Decimal("1000.00")
    soldes = account_map(db.get(Entry, paiement.entry_id))
    assert soldes["5141"] == Decimal("1000.00")  # banque debitee
    assert soldes[client.account_number] == Decimal("-1000.00")

    register_payment(db, invoice, amount=750, payment_date=date(2026, 4, 25), method="espece")
    assert invoice.status == "paid"
    assert invoice.paid_amount == Decimal("1750.00")
    assert invoice.remaining_amount == Decimal("0.00")
    with pytest.raises(AccountingError):
        register_payment(db, invoice, amount=10)


def test_avoir_inverse_le_sens_de_l_ecriture(db, ctx):
    client = make_client(db, ctx)
    avoir = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 4, 30),
        is_credit_note=True,
        lines=[
            {
                "designation": "Retour de marchandise",
                "quantity": 1,
                "unit_price": 1000,
                "vat_rate": 20,
            }
        ],
    )
    validate_invoice(db, avoir, user_id=ctx["user"].id)
    assert avoir.number == "AV202600001"
    soldes = account_map(db.get(Entry, avoir.entry_id))
    assert soldes["7111"] == Decimal("1000.00")  # produit debite
    assert soldes["4455"] == Decimal("200.00")  # TVA facturee debitee
    assert soldes[client.account_number] == Decimal("-1200.00")  # client credite


def test_facture_validee_non_modifiable(db, ctx):
    client = make_client(db, ctx)
    invoice = create_invoice(
        db,
        company=ctx["company"],
        invoice_type="vente",
        partner=client,
        invoice_date=date(2026, 4, 10),
        lines=[{"designation": "Vente", "quantity": 1, "unit_price": 100, "vat_rate": 20}],
    )
    validate_invoice(db, invoice, user_id=ctx["user"].id)
    with pytest.raises(AccountingError):
        add_line(db, invoice, designation="Ligne ajoutee apres validation", unit_price=50)