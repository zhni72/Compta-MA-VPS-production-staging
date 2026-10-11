"""Tests du coeur comptable : equilibre, immuabilite, numerotation, extourne."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.numbering import peek_next_number
from app.models import AuditLog, Entry
from app.services.accounting import (
    AccountingError,
    EntryImmutableError,
    EntryNotBalancedError,
    FiscalYearClosedError,
    NotFoundError,
    create_entry,
    delete_draft_entry,
    get_fiscal_year,
    get_journal,
    reverse_entry,
    update_draft_entry,
    validate_entry,
)

pytestmark = pytest.mark.usefixtures("ctx")


def make_entry(db, ctx, *, debit=Decimal("1000"), credit=Decimal("1000"), validate=False):
    """Ecriture simple : debit banque / credit vente."""
    company = ctx["company"]
    fiscal_year = get_fiscal_year(db, company.id, ctx["year"])
    journal = get_journal(db, company.id, "OD")
    return create_entry(
        db,
        company_id=company.id,
        fiscal_year=fiscal_year,
        journal=journal,
        entry_date=date(2026, 3, 15),
        label="Ecriture de test",
        lines=[
            {"account_number": "5141", "debit": debit},
            {"account_number": "7111", "credit": credit},
        ],
        created_by=ctx["user"].id,
        validate=validate,
    )


def test_brouillon_sans_numero(db, ctx):
    entry = make_entry(db, ctx)
    assert entry.status == "draft"
    assert entry.entry_number is None
    assert entry.is_balanced


def test_validation_numerote_et_trace_l_audit(db, ctx):
    entry = validate_entry(db, make_entry(db, ctx), user_id=ctx["user"].id)
    assert entry.status == "validated"
    assert entry.entry_number == "EC202600001"
    assert entry.validated_at is not None
    logs = db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "ENTRY_VALIDATED")
    ).scalar_one()
    assert logs == 1
    assert peek_next_number(db, ctx["company"].id, "ECRITURE", 2026) == "EC202600002"


def test_ecriture_desequilibree_refusee(db, ctx):
    with pytest.raises(EntryNotBalancedError):
        make_entry(db, ctx, debit=Decimal("1000"), credit=Decimal("900"), validate=True)


def test_ecriture_validee_immuable(db, ctx):
    entry = validate_entry(db, make_entry(db, ctx), user_id=ctx["user"].id)
    with pytest.raises(EntryImmutableError):
        update_draft_entry(db, entry, label="Modification interdite")
    with pytest.raises(EntryImmutableError):
        delete_draft_entry(db, entry)


def test_brouillon_supprimable(db, ctx):
    entry = make_entry(db, ctx)
    entry_id = entry.id
    delete_draft_entry(db, entry)
    assert db.get(Entry, entry_id) is None


def test_compte_inexistant_refuse(db, ctx):
    company = ctx["company"]
    fiscal_year = get_fiscal_year(db, company.id, ctx["year"])
    journal = get_journal(db, company.id, "OD")
    with pytest.raises(NotFoundError):
        create_entry(
            db,
            company_id=company.id,
            fiscal_year=fiscal_year,
            journal=journal,
            entry_date=date(2026, 3, 15),
            label="Compte inexistant",
            lines=[
                {"account_number": "99999", "debit": Decimal("100")},
                {"account_number": "7111", "credit": Decimal("100")},
            ],
        )


def test_contre_ecriture_annule_l_ecriture(db, ctx):
    entry = validate_entry(db, make_entry(db, ctx), user_id=ctx["user"].id)
    reversal = reverse_entry(db, entry, reason="Erreur de saisie", user_id=ctx["user"].id)
    assert reversal.reversed_entry_id == entry.id
    assert reversal.status == "validated"
    # Le debit de la banque et le credit de la vente reviennent a zero.
    assert reversal.total_debit == entry.total_credit
    assert reversal.total_credit == entry.total_debit
    from app.services.reporting import balance_generale

    balance = balance_generale(db, ctx["company"].id, date(2026, 1, 1), date(2026, 12, 31))
    assert balance["equilibre"] is True
    for line in balance["lines"]:
        assert line["solde"] == Decimal("0.00")


def test_exercice_cloture_refuse_la_saisie(db, ctx):
    fiscal_year = get_fiscal_year(db, ctx["company"].id, ctx["year"])
    fiscal_year.status = "closed"
    db.flush()
    with pytest.raises(FiscalYearClosedError):
        make_entry(db, ctx)


def test_ligne_debit_et_credit_refusee(db, ctx):
    company = ctx["company"]
    fiscal_year = get_fiscal_year(db, company.id, ctx["year"])
    journal = get_journal(db, company.id, "OD")
    with pytest.raises(AccountingError):
        create_entry(
            db,
            company_id=company.id,
            fiscal_year=fiscal_year,
            journal=journal,
            entry_date=date(2026, 3, 15),
            label="Ligne invalide",
            lines=[
                {
                    "account_number": "5141",
                    "debit": Decimal("100"),
                    "credit": Decimal("100"),
                },
                {"account_number": "7111", "credit": Decimal("100")},
            ],
        )