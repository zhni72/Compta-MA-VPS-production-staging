"""Ecritures comptables : saisie, validation, contre-ecriture."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import ENTRY_STATUS_VALIDATED, Company, Entry, Journal, User
from app.schemas import EntryCreate, EntryRead, ReversalRequest
from app.services.accounting import (
    AccountingError,
    create_entry,
    delete_draft_entry,
    get_fiscal_year,
    get_journal,
    reverse_entry,
    validate_entry,
)

router = APIRouter(prefix="/entries", tags=["ecritures"])


def _get_entry(db: Session, entry_id: int, company: Company) -> Entry:
    entry = db.get(Entry, entry_id)
    if entry is None or entry.company_id != company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ecriture introuvable"
        )
    return entry


@router.get("", response_model=list[EntryRead], summary="Lister les ecritures")
def list_entries(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    journal_code: str | None = Query(default=None),
    only_validated: bool = Query(default=True),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Entry]:
    stmt = select(Entry).where(Entry.company_id == company.id)
    if date_from:
        stmt = stmt.where(Entry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(Entry.entry_date <= date_to)
    if only_validated:
        stmt = stmt.where(Entry.status == ENTRY_STATUS_VALIDATED)
    if journal_code:
        journal = db.execute(
            select(Journal).where(
                Journal.company_id == company.id, Journal.code == journal_code
            )
        ).scalar_one_or_none()
        if journal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Journal introuvable"
            )
        stmt = stmt.where(Entry.journal_id == journal.id)
    return list(db.execute(stmt.order_by(Entry.entry_date, Entry.id)).scalars())


@router.post(
    "",
    response_model=EntryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Saisir une ecriture (brouillon ou validee)",
)
def add_entry(
    payload: EntryCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> Entry:
    try:
        fiscal_year = get_fiscal_year(db, company.id, payload.entry_date.year)
        journal = get_journal(db, company.id, payload.journal_code)
        entry = create_entry(
            db,
            company_id=company.id,
            fiscal_year=fiscal_year,
            journal=journal,
            entry_date=payload.entry_date,
            label=payload.label,
            reference=payload.reference,
            created_by=user.id,
            notes=payload.notes,
            lines=[line.model_dump() for line in payload.lines],
            validate=payload.auto_validate,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(entry)
    return entry


@router.get("/{entry_id}", response_model=EntryRead, summary="Detail d'une ecriture")
def get_entry(
    entry_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Entry:
    return _get_entry(db, entry_id, company)


@router.post(
    "/{entry_id}/validate",
    response_model=EntryRead,
    summary="Valider une ecriture (controle d'equilibre)",
)
def validate(
    entry_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> Entry:
    entry = _get_entry(db, entry_id, company)
    try:
        validate_entry(db, entry, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(entry)
    return entry


@router.post(
    "/{entry_id}/reverse",
    response_model=EntryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Contre-passer une ecriture validee",
)
def reverse(
    entry_id: int,
    payload: ReversalRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> Entry:
    entry = _get_entry(db, entry_id, company)
    try:
        reversal = reverse_entry(
            db,
            entry,
            reason=payload.reason,
            reversal_date=payload.reversal_date,
            user_id=user.id,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(reversal)
    return reversal


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un brouillon (une ecriture validee est immuable)",
)
def delete_entry(
    entry_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE")),
) -> None:
    entry = _get_entry(db, entry_id, company)
    try:
        delete_draft_entry(db, entry)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc