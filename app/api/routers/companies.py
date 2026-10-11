"""Societes (dossiers comptables) et exercices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.api.errors import http_error
from app.db.seed import create_company, get_or_create_fiscal_year
from app.db.session import get_db
from app.models import Company, FiscalYear, User
from app.schemas import CompanyCreate, CompanyRead, FiscalYearCreate, FiscalYearRead
from app.services.identifiers import ComplianceError, validate_fiscal_id, validate_ice

router = APIRouter(prefix="/companies", tags=["societes"])


@router.get("", response_model=list[CompanyRead], summary="Lister les societes")
def list_companies(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[Company]:
    return list(db.execute(select(Company).order_by(Company.id)).scalars())


@router.post(
    "",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer une societe (dossier comptable)",
)
def add_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN")),
) -> Company:
    data = payload.model_dump(exclude={"fiscal_year"})
    try:
        # IF du declarant sur 8 chiffres, ICE sur 15 chiffres.
        data["fiscal_id"] = validate_fiscal_id(data.get("fiscal_id"))
        data["ice"] = validate_ice(data.get("ice"))
    except ComplianceError as exc:
        raise http_error(exc) from exc
    company = create_company(db, year=payload.fiscal_year, **data)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyRead, summary="Detail d'une societe")
def get_company(
    company_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Societe introuvable")
    return company


@router.get(
    "/{company_id}/fiscal-years",
    response_model=list[FiscalYearRead],
    summary="Exercices d'une societe",
)
def list_fiscal_years(
    company_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[FiscalYear]:
    return list(
        db.execute(
            select(FiscalYear)
            .where(FiscalYear.company_id == company_id)
            .order_by(FiscalYear.year)
        ).scalars()
    )


@router.post(
    "/{company_id}/fiscal-years",
    response_model=FiscalYearRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir un exercice",
)
def add_fiscal_year(
    company_id: int,
    payload: FiscalYearCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> FiscalYear:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Societe introuvable")
    fiscal_year = get_or_create_fiscal_year(db, company, payload.year)
    db.commit()
    db.refresh(fiscal_year)
    return fiscal_year


@router.post(
    "/{company_id}/fiscal-years/{year}/{new_status}",
    response_model=FiscalYearRead,
    summary="Cloturer (closed) ou verrouiller (locked) un exercice",
)
def change_fiscal_year_status(
    company_id: int,
    year: int,
    new_status: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> FiscalYear:
    if new_status not in ("open", "closed", "locked"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Statut invalide (open, closed ou locked)",
        )
    fiscal_year = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company_id, FiscalYear.year == year
        )
    ).scalar_one_or_none()
    if fiscal_year is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    fiscal_year.status = new_status
    if new_status != "open" and fiscal_year.closed_at is None:
        from datetime import datetime

        fiscal_year.closed_at = datetime.now()
    db.commit()
    db.refresh(fiscal_year)
    return fiscal_year