"""Schemas tiers et compte du plan comptable."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ThirdPartyCreate(BaseModel):
    kind: str = Field(..., description="client, fournisseur ou salarie")
    name: str = Field(..., max_length=180)
    code: str | None = Field(default=None, description="Code tiers (CL0001 par defaut)")
    is_individual: bool = Field(default=False, description="Personne physique (pas d'ICE)")
    ice: str | None = None
    fiscal_id: str | None = None
    rc: str | None = None
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None
    payment_terms_days: int = Field(default=0, ge=0, le=365)
    account_number: str | None = Field(
        default=None, description="Sous-compte PCGE (cree automatiquement si absent)"
    )


class ThirdPartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    code: str
    kind: str
    name: str
    is_individual: bool
    ice: str | None = None
    fiscal_id: str | None = None
    rc: str | None = None
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None
    account_number: str
    payment_terms_days: int
    is_active: bool