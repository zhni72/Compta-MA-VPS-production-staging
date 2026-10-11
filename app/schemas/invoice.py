"""Schemas facture, ligne de facture et reglement."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class InvoiceLineCreate(BaseModel):
    designation: str = Field(..., max_length=255)
    quantity: Decimal = Field(default=Decimal("1"), ge=0)
    unit_price: Decimal = Field(default=Decimal("0"))
    vat_rate: Decimal | None = Field(
        default=None, description="20 ou 10 (bareme TVA 2026) ; 20 par defaut"
    )
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    account_number: str | None = Field(
        default=None, description="Compte de produit (vente) ou de charge (achat)"
    )


class InvoiceCreate(BaseModel):
    invoice_type: str = Field(..., description="vente ou achat")
    partner_code: str = Field(..., description="Code du tiers (CL0001...)")
    invoice_date: date
    due_date: date | None = None
    payment_mode: str | None = Field(default=None, description="espece, cheque, virement, effet")
    reference: str | None = None
    notes: str | None = None
    is_credit_note: bool = Field(default=False, description="True pour un avoir")
    auto_validate: bool = Field(
        default=False, description="Valider immediatement (numero + comptabilisation)"
    )
    lines: list[InvoiceLineCreate] = Field(default_factory=list)


class InvoiceLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    designation: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal
    vat_rate: Decimal
    account_number: str
    line_ht: Decimal
    line_vat: Decimal
    line_ttc: Decimal


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    number: str | None = None
    invoice_type: str
    is_credit_note: bool
    partner_id: int
    invoice_date: date
    due_date: date | None = None
    payment_mode: str | None = None
    reference: str | None = None
    total_ht: Decimal
    total_vat: Decimal
    total_ttc: Decimal
    paid_amount: Decimal
    status: str
    entry_id: int | None = None
    lines: list[InvoiceLineRead] = Field(default_factory=list)


class PaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0)
    payment_date: date | None = None
    method: str = Field(default="virement", description="espece, cheque, virement, effet")
    reference: str | None = None


class CancellationRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)