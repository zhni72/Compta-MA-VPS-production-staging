"""Tiers : clients, fournisseurs, salaries."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, ThirdParty, User
from app.schemas import ThirdPartyCreate, ThirdPartyRead
from app.services.accounting import AccountingError
from app.services.parties import auxiliary_balance, create_third_party

router = APIRouter(prefix="/parties", tags=["tiers"])


@router.get("", response_model=list[ThirdPartyRead], summary="Lister les tiers")
def list_parties(
    kind: str | None = Query(default=None, description="client, fournisseur ou salarie"),
    search: str | None = Query(default=None),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ThirdParty]:
    stmt = select(ThirdParty).where(ThirdParty.company_id == company.id)
    if kind:
        stmt = stmt.where(ThirdParty.kind == kind)
    if search:
        stmt = stmt.where(ThirdParty.name.ilike(f"%{search}%"))
    return list(db.execute(stmt.order_by(ThirdParty.code)).scalars())


@router.post(
    "",
    response_model=ThirdPartyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer un tiers (avec son sous-compte PCGE)",
)
def add_party(
    payload: ThirdPartyCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE", "COMMERCIAL")),
) -> ThirdParty:
    if payload.kind not in ("client", "fournisseur", "salarie"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type de tiers invalide (client, fournisseur ou salarie)",
        )
    try:
        party = create_third_party(
            db, company=company, **payload.model_dump(exclude={"company"})
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(party)
    return party


@router.get("/balance", summary="Balance auxiliaire par tiers (clients / fournisseurs)")
def get_auxiliary_balance(
    kind: str | None = Query(default=None, description="client ou fournisseur"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return auxiliary_balance(db, company.id, kind=kind)


@router.get("/{code}", response_model=ThirdPartyRead, summary="Detail d'un tiers")
def get_party(
    code: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ThirdParty:
    party = db.execute(
        select(ThirdParty).where(
            ThirdParty.company_id == company.id, ThirdParty.code == code
        )
    ).scalar_one_or_none()
    if party is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tiers introuvable")
    return party