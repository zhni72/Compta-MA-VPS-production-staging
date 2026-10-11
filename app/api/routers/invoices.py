"""Factures de vente et d'achat, avoirs et reglements."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, Invoice, User
from app.schemas import (
    CancellationRequest,
    InvoiceCreate,
    InvoiceLineCreate,
    InvoiceRead,
    PaymentCreate,
)
from app.services.accounting import AccountingError
from app.services.invoicing import (
    add_line,
    cancel_invoice,
    create_invoice,
    register_payment,
    validate_invoice,
)
from app.services.parties import find_third_party
from app.services.pdf_documents import nom_fichier_pdf, pdf_facture

router = APIRouter(prefix="/invoices", tags=["factures"])

SALES_ROLES = ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE", "COMMERCIAL")


def _get_invoice(db: Session, invoice_id: int, company: Company) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.company_id != company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Facture introuvable"
        )
    return invoice


@router.get("", response_model=list[InvoiceRead], summary="Lister les factures")
def list_invoices(
    invoice_type: str | None = Query(default=None, description="vente ou achat"),
    invoice_status: str | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Invoice]:
    stmt = select(Invoice).where(Invoice.company_id == company.id)
    if invoice_type:
        stmt = stmt.where(Invoice.invoice_type == invoice_type)
    if invoice_status:
        stmt = stmt.where(Invoice.status == invoice_status)
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    return list(db.execute(stmt.order_by(Invoice.invoice_date, Invoice.id)).scalars())


@router.post(
    "",
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer une facture (brouillon ou validee)",
)
def add_invoice(
    payload: InvoiceCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SALES_ROLES)),
) -> Invoice:
    partner = find_third_party(db, company.id, payload.partner_code)
    if partner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tiers {payload.partner_code} introuvable",
        )
    try:
        invoice = create_invoice(
            db,
            company=company,
            invoice_type=payload.invoice_type,
            partner=partner,
            invoice_date=payload.invoice_date,
            due_date=payload.due_date,
            payment_mode=payload.payment_mode,
            reference=payload.reference,
            notes=payload.notes,
            is_credit_note=payload.is_credit_note,
            lines=[line.model_dump() for line in payload.lines],
        )
        if payload.auto_validate:
            validate_invoice(db, invoice, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceRead, summary="Detail d'une facture")
def get_invoice(
    invoice_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Invoice:
    return _get_invoice(db, invoice_id, company)


@router.post(
    "/{invoice_id}/lines",
    response_model=InvoiceRead,
    summary="Ajouter une ligne a une facture brouillon",
)
def add_invoice_line(
    invoice_id: int,
    payload: InvoiceLineCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*SALES_ROLES)),
) -> Invoice:
    invoice = _get_invoice(db, invoice_id, company)
    try:
        add_line(db, invoice, **payload.model_dump())
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(invoice)
    return invoice


@router.post(
    "/{invoice_id}/validate",
    response_model=InvoiceRead,
    summary="Valider : numerotation + ecriture comptable",
)
def validate(
    invoice_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> Invoice:
    invoice = _get_invoice(db, invoice_id, company)
    try:
        validate_invoice(db, invoice, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(invoice)
    return invoice


@router.post(
    "/{invoice_id}/payments",
    response_model=InvoiceRead,
    summary="Enregistrer un reglement",
)
def add_payment(
    invoice_id: int,
    payload: PaymentCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE", "CAISSIER")
    ),
) -> Invoice:
    invoice = _get_invoice(db, invoice_id, company)
    try:
        register_payment(
            db,
            invoice,
            amount=payload.amount,
            payment_date=payload.payment_date,
            method=payload.method,
            reference=payload.reference,
            user_id=user.id,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(invoice)
    return invoice


@router.post(
    "/{invoice_id}/cancel",
    response_model=InvoiceRead,
    summary="Annuler une facture (contre-ecriture si comptabilisee)",
)
def cancel(
    invoice_id: int,
    payload: CancellationRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> Invoice:
    invoice = _get_invoice(db, invoice_id, company)
    try:
        cancel_invoice(db, invoice, reason=payload.reason, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(invoice)
    return invoice


@router.get(
    "/{invoice_id}/pdf",
    summary="Facture au format PDF (mentions CGI art. 145, original ou duplicata)",
    response_class=Response,
)
def get_invoice_pdf(
    invoice_id: int,
    duplicata: bool = Query(default=False),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    """Telecharge la facture en PDF (memes montants que l'ecran, au centime)."""
    facture = db.get(Invoice, invoice_id)
    if facture is None or facture.company_id != company.id:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    pdf = pdf_facture(db, facture, duplicata=duplicata)
    nom = nom_fichier_pdf(
        "Facture",
        facture.number or f"brouillon-{facture.id}",
        "duplicata" if duplicata else "originale",
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )
