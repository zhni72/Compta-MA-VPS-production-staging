"""Gestion des tiers (clients, fournisseurs, salaries).

Chaque tiers recoit automatiquement un sous-compte du PCGE :
34210001, 34210002... pour les clients ; 44110001... pour les fournisseurs.
C'est ce sous-compte qui est mouvemente dans les ecritures, ce qui permet
d'editer une balance auxiliaire par tiers.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DEFAULT_PARTY_ACCOUNTS, PARTY_KINDS, Company, ThirdParty
from app.services.accounts import ensure_account
from app.services.identifiers import validate_party_identifiers

CODE_PREFIXES = {"client": "CL", "fournisseur": "FR", "salarie": "SA"}
ACCOUNT_LABELS = {"client": "Client", "fournisseur": "Fournisseur", "salarie": "Salarie"}


def next_party_code(db: Session, company_id: int, kind: str) -> str:
    """Code tiers sequentiel unique par societe et par type (CL0001...)."""
    prefix = CODE_PREFIXES.get(kind, "TI")
    index = (
        db.execute(
            select(func.count())
            .select_from(ThirdParty)
            .where(ThirdParty.company_id == company_id, ThirdParty.kind == kind)
        ).scalar_one()
        + 1
    )
    while True:
        code = f"{prefix}{index:04d}"
        exists = db.execute(
            select(ThirdParty.id).where(
                ThirdParty.company_id == company_id, ThirdParty.code == code
            )
        ).first()
        if exists is None:
            return code
        index += 1


def create_third_party(
    db: Session,
    *,
    company: Company,
    kind: str,
    name: str,
    code: str | None = None,
    is_individual: bool = False,
    ice: str | None = None,
    fiscal_id: str | None = None,
    rc: str | None = None,
    address: str | None = None,
    city: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    payment_terms_days: int = 0,
    account_number: str | None = None,
) -> ThirdParty:
    """Cree un tiers et son compte de rattachement dans le plan comptable."""
    if kind not in PARTY_KINDS:
        raise ValueError(f"Type de tiers invalide : {kind!r} (attendu : {PARTY_KINDS})")
    # Controle de format des identifiants legaux (ICE 15 chiffres, IF numerique).
    ice, fiscal_id = validate_party_identifiers(
        kind=kind, is_individual=is_individual, ice=ice, fiscal_id=fiscal_id
    )
    code = code or next_party_code(db, company.id, kind)
    if account_number is None:
        base = DEFAULT_PARTY_ACCOUNTS[kind]
        sequence = (
            db.execute(
                select(func.count())
                .select_from(ThirdParty)
                .where(ThirdParty.company_id == company.id, ThirdParty.kind == kind)
            ).scalar_one()
            + 1
        )
        account_number = f"{base}{sequence:04d}"
    ensure_account(
        db,
        account_number,
        label=f"{ACCOUNT_LABELS.get(kind, 'Tiers')} {code} - {name}",
    )
    party = ThirdParty(
        company_id=company.id,
        code=code,
        kind=kind,
        name=name,
        is_individual=is_individual,
        ice=ice,
        fiscal_id=fiscal_id,
        rc=rc,
        address=address,
        city=city,
        phone=phone,
        email=email,
        payment_terms_days=payment_terms_days,
        account_number=account_number,
    )
    db.add(party)
    db.flush()
    return party


def find_third_party(db: Session, company_id: int, code: str) -> ThirdParty | None:
    return db.execute(
        select(ThirdParty).where(
            ThirdParty.company_id == company_id, ThirdParty.code == code
        )
    ).scalar_one_or_none()


def auxiliary_balance(db: Session, company_id: int, kind: str | None = None) -> list[dict]:
    """Balance auxiliaire par tiers (solde du compte de rattachement)."""
    from app.models import ENTRY_STATUS_VALIDATED, Entry, EntryLine

    stmt = (
        select(
            ThirdParty.code,
            ThirdParty.name,
            ThirdParty.account_number,
            func.sum(EntryLine.debit),
            func.sum(EntryLine.credit),
        )
        .join(EntryLine, EntryLine.third_party_id == ThirdParty.id)
        .join(Entry, Entry.id == EntryLine.entry_id)
        .where(
            ThirdParty.company_id == company_id,
            Entry.status == ENTRY_STATUS_VALIDATED,
        )
        .group_by(ThirdParty.code, ThirdParty.name, ThirdParty.account_number)
        .order_by(ThirdParty.code)
    )
    if kind:
        stmt = stmt.where(ThirdParty.kind == kind)
    return [
        {
            "code": code,
            "name": name,
            "account_number": account_number,
            "debit": debit or 0,
            "credit": credit or 0,
            "solde": (debit or 0) - (credit or 0),
        }
        for code, name, account_number, debit, credit in db.execute(stmt).all()
    ]