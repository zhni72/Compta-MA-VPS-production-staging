"""Schemas societe et exercice comptable."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CompanyCreate(BaseModel):
    name: str = Field(..., max_length=180, description="Raison sociale")
    legal_form: str | None = Field(default=None, description="SARL, SAS, SA...")
    ice: str | None = Field(default=None, description="Identifiant Commun de l'Entreprise")
    fiscal_id: str | None = Field(default=None, description="Identifiant fiscal (IF)")
    rc: str | None = Field(default=None, description="Registre de commerce")
    patente: str | None = None
    cnss_number: str | None = None
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None
    vat_regime: str = Field(default="trimestriel", description="mensuel ou trimestriel")
    require_ice: bool = Field(default=True, description="Exiger l'ICE sur les factures de vente")
    fiscal_year: int | None = Field(default=None, description="Premier exercice a creer")


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_form: str | None = None
    ice: str | None = None
    fiscal_id: str | None = None
    rc: str | None = None
    patente: str | None = None
    cnss_number: str | None = None
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None
    currency: str
    vat_regime: str
    require_ice: bool
    is_active: bool


class FiscalYearCreate(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    status: str = Field(default="open", description="open, closed ou locked")


class FiscalYearRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    year: int
    start_date: date
    end_date: date
    status: str