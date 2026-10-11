"""Etats comptables : balance, grand livre, journaux, CPC, bilan.

Seules les ecritures VALIDEES sont prises en compte : les brouillons n'ont aucune
incidence sur les etats de synthese.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rates_ma import money
from app.models import ENTRY_STATUS_VALIDATED, Account, Entry, EntryLine, Journal


def year_bounds(year: int) -> tuple[date, date]:
    """Bornes de l'exercice (annee civile pour les societes marocaines)."""
    return date(year, 1, 1), date(year, 12, 31)


def movements(
    db: Session,
    company_id: int,
    date_from: date,
    date_to: date,
    prefix: str | None = None,
) -> list[dict]:
    """Mouvements valides agreges par compte (base de tous les etats)."""
    stmt = (
        select(
            EntryLine.account_number,
            Account.label,
            Account.account_class,
            func.sum(EntryLine.debit),
            func.sum(EntryLine.credit),
        )
        .join(Entry, Entry.id == EntryLine.entry_id)
        .join(Account, Account.number == EntryLine.account_number)
        .where(
            Entry.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            Entry.entry_date >= date_from,
            Entry.entry_date <= date_to,
        )
        .group_by(EntryLine.account_number, Account.label, Account.account_class)
        .order_by(EntryLine.account_number)
    )
    if prefix:
        stmt = stmt.where(EntryLine.account_number.like(f"{prefix}%"))
    rows: list[dict] = []
    for number, label, account_class, debit, credit in db.execute(stmt).all():
        debit_value = money(debit or 0)
        credit_value = money(credit or 0)
        rows.append(
            {
                "account_number": number,
                "label": label,
                "account_class": account_class,
                "debit": debit_value,
                "credit": credit_value,
                "solde": money(debit_value - credit_value),
                "statement": "bilan" if account_class <= 5 else "cpc",
            }
        )
    return rows


def balance_generale(
    db: Session,
    company_id: int,
    date_from: date,
    date_to: date,
    prefix: str | None = None,
) -> dict:
    """Balance generale : mouvements et soldes par compte, controle d'equilibre."""
    lines = movements(db, company_id, date_from, date_to, prefix=prefix)
    total_debit = money(sum((l["debit"] for l in lines), Decimal("0")))
    total_credit = money(sum((l["credit"] for l in lines), Decimal("0")))
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "lines": lines,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "equilibre": total_debit == total_credit,
    }


def grand_livre(
    db: Session,
    company_id: int,
    account_number: str,
    date_from: date,
    date_to: date,
) -> dict:
    """Grand livre d'un compte (ou d'une racine de compte avec %)."""
    pattern = account_number.replace("*", "%")
    stmt = (
        select(
            Entry.entry_date,
            Entry.entry_number,
            Entry.label,
            EntryLine.label,
            EntryLine.debit,
            EntryLine.credit,
        )
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .where(
            Entry.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            Entry.entry_date >= date_from,
            Entry.entry_date <= date_to,
            EntryLine.account_number.like(pattern),
        )
        .order_by(Entry.entry_date, Entry.id)
    )
    lines: list[dict] = []
    running = Decimal("0")
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for entry_date, number, entry_label, line_label, debit, credit in db.execute(stmt).all():
        debit_value = money(debit or 0)
        credit_value = money(credit or 0)
        running = money(running + debit_value - credit_value)
        total_debit = money(total_debit + debit_value)
        total_credit = money(total_credit + credit_value)
        lines.append(
            {
                "entry_date": entry_date,
                "entry_number": number,
                "entry_label": entry_label,
                "line_label": line_label,
                "debit": debit_value,
                "credit": credit_value,
                "solde_cumule": running,
            }
        )
    return {
        "account_number": account_number,
        "date_from": date_from,
        "date_to": date_to,
        "lines": lines,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "solde": money(total_debit - total_credit),
    }


def journal_entries(
    db: Session,
    company_id: int,
    date_from: date,
    date_to: date,
    journal_code: str | None = None,
) -> list[dict]:
    """Ecritures validees d'un journal (ou de tous les journaux)."""
    stmt = (
        select(
            Journal.code,
            Entry.id,
            Entry.entry_number,
            Entry.entry_date,
            Entry.label,
            Entry.reference,
            func.sum(EntryLine.debit),
            func.sum(EntryLine.credit),
        )
        .join(EntryLine, EntryLine.entry_id == Entry.id)
        .join(Journal, Journal.id == Entry.journal_id)
        .where(
            Entry.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
            Entry.entry_date >= date_from,
            Entry.entry_date <= date_to,
        )
        .group_by(
            Journal.code,
            Entry.id,
            Entry.entry_number,
            Entry.entry_date,
            Entry.label,
            Entry.reference,
        )
        .order_by(Entry.entry_date, Entry.id)
    )
    if journal_code:
        stmt = stmt.where(Journal.code == journal_code)
    return [
        {
            "journal": code,
            "entry_id": entry_id,
            "entry_number": number,
            "entry_date": entry_date,
            "label": label,
            "reference": reference,
            "debit": money(debit or 0),
            "credit": money(credit or 0),
        }
        for code, entry_id, number, entry_date, label, reference, debit, credit in db.execute(
            stmt
        ).all()
    ]


def income_statement(
    db: Session, company_id: int, date_from: date, date_to: date
) -> dict:
    """CPC simplifie : charges (classe 6), produits (classe 7) et resultat."""
    lines = movements(db, company_id, date_from, date_to)
    charges = [l for l in lines if l["account_class"] == 6]
    produits = [l for l in lines if l["account_class"] == 7]
    total_charges = money(sum((l["solde"] for l in charges), Decimal("0")))
    # Classe 7 : le solde est negatif (comptes crediteurs), d'ou l'inversion.
    total_produits = money(sum((-l["solde"] for l in produits), Decimal("0")))
    resultat = money(total_produits - total_charges)
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "charges": charges,
        "produits": produits,
        "total_charges": total_charges,
        "total_produits": total_produits,
        "resultat": resultat,
        "nature_resultat": "benefice" if resultat >= 0 else "perte",
    }


def balance_sheet(
    db: Session, company_id: int, date_from: date, date_to: date
) -> dict:
    """Bilan simplifie (modele normal : classes 1 a 5) + resultat de l'exercice.

    Le resultat de l'exercice est porte au passif, ce qui assure l'equilibre
    du bilan sans ecriture de cloture. Les etats officiels (modele normal du
    CGNC) restent a produire a partir de cette base.
    """
    lines = movements(db, company_id, date_from, date_to)
    actif: list[dict] = []
    passif: list[dict] = []
    for line in lines:
        if line["account_class"] not in (1, 2, 3, 4, 5):
            continue
        if line["account_class"] in (2, 3, 5):
            (actif if line["solde"] >= 0 else passif).append(
                {**line, "montant": abs(line["solde"])}
            )
        else:
            (passif if line["solde"] <= 0 else actif).append(
                {**line, "montant": abs(line["solde"])}
            )
    cpc = income_statement(db, company_id, date_from, date_to)
    total_actif = money(sum((l["montant"] for l in actif), Decimal("0")))
    total_passif = money(sum((l["montant"] for l in passif), Decimal("0")))
    resultat = cpc["resultat"]
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "actif": actif,
        "passif": passif,
        "resultat_exercice": resultat,
        "total_actif": total_actif,
        "total_passif": total_passif,
        "total_passif_avec_resultat": money(total_passif + resultat),
        "equilibre": total_actif == money(total_passif + resultat),
    }