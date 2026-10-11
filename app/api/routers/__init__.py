"""Routeurs de l'API Compta MA."""

from app.api.routers import (
    accounts,
    assets,
    audit,
    auth,
    companies,
    entries,
    greffe,
    invoices,
    liasse,
    parties,
    payroll,
    reports,
    stocks,
    vat,
)

__all__ = [
    "accounts",
    "assets",
    "audit",
    "auth",
    "companies",
    "entries",
    "greffe",
    "invoices",
    "liasse",
    "parties",
    "payroll",
    "reports",
    "stocks",
    "vat",
]