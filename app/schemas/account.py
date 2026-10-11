"""Schemas du plan comptable (PCGE / CGNC)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    number: str = Field(
        ..., min_length=4, max_length=12, description="Compte principal ou divisionnaire"
    )
    label: str = Field(..., max_length=180)
    is_collectif: bool = False


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    label: str
    account_class: int
    is_collectif: bool
    is_active: bool