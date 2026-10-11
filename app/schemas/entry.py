"""Schemas ecriture comptable et lignes d'ecriture."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EntryLineCreate(BaseModel):
    account_number: str = Field(..., min_length=4, max_length=12)
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)
    label: str | None = None
    third_party_id: int | None = None
    vat_rate: Decimal | None = None


class EntryCreate(BaseModel):
    entry_date: date
    label: str = Field(..., max_length=255)
    journal_code: str = Field(default="OD", description="AC, VE, BQ, CA ou OD")
    reference: str | None = None
    notes: str | None = None
    auto_validate: bool = Field(default=False, description="Valider immediatement")
    lines: list[EntryLineCreate] = Field(..., min_length=2)


class EntryLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_number: str
    third_party_id: int | None = None
    label: str | None = None
    debit: Decimal
    credit: Decimal
    vat_rate: Decimal | None = None
    position: int


class EntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    fiscal_year_id: int
    journal_id: int
    entry_number: str | None = None
    entry_date: date
    label: str
    reference: str | None = None
    status: str
    source: str
    total_debit: Decimal
    total_credit: Decimal
    lines: list[EntryLineRead] = Field(default_factory=list)


class ReversalRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)
    reversal_date: date | None = None