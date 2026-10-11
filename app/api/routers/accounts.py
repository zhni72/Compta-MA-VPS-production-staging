"""Plan comptable (PCGE / CGNC)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Account, User
from app.schemas import AccountCreate, AccountRead
from app.services.accounts import InvalidAccountNumber, ensure_account

router = APIRouter(prefix="/accounts", tags=["plan comptable"])


@router.get("", response_model=list[AccountRead], summary="Rechercher des comptes")
def list_accounts(
    prefix: str | None = Query(default=None, description="Ex. 61 pour toutes les charges 61xx"),
    account_class: int | None = Query(default=None, ge=1, le=9),
    search: str | None = Query(default=None, description="Recherche sur le libelle"),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Account]:
    stmt = select(Account).order_by(Account.number)
    if prefix:
        stmt = stmt.where(Account.number.like(f"{prefix}%"))
    if account_class:
        stmt = stmt.where(Account.account_class == account_class)
    if search:
        stmt = stmt.where(Account.label.ilike(f"%{search}%"))
    return list(db.execute(stmt.limit(limit)).scalars())


@router.get("/{number}", response_model=AccountRead, summary="Detail d'un compte")
def get_account(
    number: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Account:
    account = db.execute(
        select(Account).where(Account.number == number)
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable")
    return account


@router.post(
    "",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer un compte (divisionnaire ou sous-compte)",
)
def add_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> Account:
    existing = db.execute(
        select(Account).where(Account.number == payload.number)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ce compte existe deja"
        )
    try:
        account = ensure_account(
            db, payload.number, label=payload.label, is_collectif=payload.is_collectif
        )
    except InvalidAccountNumber as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(account)
    return account