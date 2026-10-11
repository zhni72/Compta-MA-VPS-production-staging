"""Acces au plan comptable : recherche et creation de comptes a la volee.

Utilise notamment pour creer les sous-comptes de tiers (34210001, 44110001...)
et tout compte de charge ou de produit specifique a l'entreprise, sans casser la
codification du PCGE.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account


class InvalidAccountNumber(ValueError):
    """Numero de compte non conforme a la codification du PCGE."""


def find_account(db: Session, number: str) -> Account | None:
    return db.execute(
        select(Account).where(Account.number == str(number).strip())
    ).scalar_one_or_none()


def validate_account_number(number: str) -> str:
    """Le PCGE impose une codification decimale d'au moins 4 chiffres."""
    number = str(number).strip()
    if not number.isdigit() or len(number) < 4:
        raise InvalidAccountNumber(
            f"Numero de compte invalide : {number!r} "
            "(au moins 4 chiffres, codification decimale du CGNC)"
        )
    return number


def ensure_account(
    db: Session, number: str, label: str | None = None, is_collectif: bool = False
) -> Account:
    """Retourne le compte, en le creant s'il n'existe pas encore."""
    number = validate_account_number(number)
    account = find_account(db, number)
    if account is not None:
        return account
    account = Account(
        number=number,
        label=(label or f"Compte {number}")[:180],
        account_class=int(number[0]),
        is_collectif=is_collectif,
    )
    db.add(account)
    db.flush()
    return account


def count_accounts(db: Session, prefix: str | None = None) -> int:
    stmt = select(func.count()).select_from(Account)
    if prefix:
        stmt = stmt.where(Account.number.like(f"{prefix}%"))
    return db.execute(stmt).scalar_one()