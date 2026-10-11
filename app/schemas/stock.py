"""Schemas du module Stocks & inventaire permanent (P1.3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StockItemCreate(BaseModel):
    """Fiche article."""

    reference: str = Field(..., max_length=40)
    label: str = Field(..., max_length=180)
    stock_account: str = Field(..., description="Compte de stock 3xxx (ex. 3111)")
    unit: str = Field(default="U", max_length=20)
    family: str | None = None
    purchase_account: str | None = Field(default=None, description="Compte d'achat (6111…)")
    sale_account: str | None = Field(default=None, description="Compte de vente (7111…)")
    alert_threshold: Decimal = Field(default=Decimal("0"), ge=0)
    valuation_method: str = Field(
        default="cmup", description="cmup ou fifo (le LIFO est proscrit par le CGNC)"
    )
    notes: str | None = None


class StockItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    reference: str
    label: str
    unit: str
    family: str | None = None
    stock_account: str
    purchase_account: str | None = None
    sale_account: str | None = None
    alert_threshold: Decimal
    valuation_method: str
    quantity_on_hand: Decimal
    cmup: Decimal
    value_on_hand: Decimal
    is_active: bool


class StockMovementCreate(BaseModel):
    """Mouvement de stock (entree ou sortie)."""

    movement_date: date
    movement_type: str = Field(..., description="entree ou sortie")
    quantity: Decimal = Field(..., gt=0)
    reason: str = Field(default="achat", description="achat, vente, perte, transfert…")
    unit_cost: Decimal | None = Field(
        default=None, description="Obligatoire pour une entree (cout de revient)"
    )
    label: str | None = None
    reference: str | None = None
    invoice_id: int | None = None
    allow_negative: bool = Field(
        default=False, description="Autoriser explicitement un stock negatif"
    )
    comptabiliser: bool = Field(
        default=True, description="Generer l'ecriture de variation (stock 3xxx / 6114-6124)"
    )


class StockCountCreate(BaseModel):
    """Inventaire physique."""

    count_date: date
    lignes: list[dict] = Field(..., description='[{"reference": "...", "physical_quantity": "10"}]')
    label: str | None = None
    note: str | None = None
    visumotif: str | None = Field(
        default=None, description="Visa obligatoire au-dela de 5 % d'ecart"
    )
    comptabiliser: bool = True


class StockProvisionCreate(BaseModel):
    """Depreciation de stock (prudence)."""

    exercice: int = Field(..., ge=2000, le=2100)
    inventory_value: Decimal = Field(..., ge=0, description="Valeur d'inventaire (prix du marche)")
    motif: str = Field(..., min_length=3, max_length=255)
