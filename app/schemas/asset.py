"""Schemas immobilisations (P1.2) : fiches, dotations, cessions et rebuts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AssetCreate(BaseModel):
    """Fiche d'immobilisation (acquisition)."""

    label: str = Field(..., max_length=180)
    account_number: str = Field(..., description="Compte 2xxx du PCGE (ex. 2332)")
    acquisition_date: date
    valeur_origine: Decimal = Field(..., gt=0)
    duree_annees: int = Field(default=0, ge=0, le=99)
    service_date: date | None = Field(default=None, description="Date de mise en service")
    mode: str = Field(default="lineaire", description="lineaire ou degressif")
    coefficient: Decimal | None = Field(
        default=None, description="Coefficient du degressif (defaut : selon la duree)"
    )
    valeur_residuelle: Decimal = Field(default=Decimal("0"), ge=0)
    prorata_temporis: bool | None = Field(
        default=None, description="None = parametre global (prorata fiscal par defaut)"
    )
    tva_montant: Decimal = Field(default=Decimal("0"), ge=0)
    tva_compte: str | None = Field(
        default=None, description="Compte de TVA recuperable (34551 par defaut)"
    )
    third_party_id: int | None = None
    invoice_id: int | None = None
    notes: str | None = None
    comptabiliser: bool = Field(
        default=False, description="Generer l'ecriture d'acquisition (2xxx + 34551)"
    )
    compte_contrepartie: str | None = Field(
        default=None, description="Fournisseur 4411 ou banque 5141 si comptabiliser"
    )
    journal_code: str = "OD"


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    code: str
    label: str
    account_number: str
    acquisition_date: date
    service_date: date | None = None
    valeur_origine: Decimal
    valeur_residuelle: Decimal
    duree_annees: int
    mode: str
    coefficient: Decimal | None = None
    prorata_temporis: bool
    tva_montant: Decimal
    tva_compte: str
    statut: str
    disposal_date: date | None = None
    disposal_price: Decimal | None = None
    disposal_reason: str | None = None


class AssetDotationRequest(BaseModel):
    """Dotation aux amortissements d'un exercice."""

    exercice: int = Field(..., ge=2000, le=2100)
    date_ecriture: date | None = None
    journal_code: str = "OD"


class AssetCessionRequest(BaseModel):
    """Cession d'une immobilisation."""

    date_cession: date
    prix: Decimal = Field(..., ge=0)
    tva_taux: Decimal = Field(default=Decimal("0"), ge=0, le=20)
    compte_encaissement: str | None = Field(
        default=None, description="5141 si encaissement immediat, sinon 3481"
    )
    regulariser_tva: bool = True
    motif: str | None = None
    journal_code: str = "OD"


class AssetRebutRequest(BaseModel):
    """Mise au rebut d'une immobilisation."""

    date_rebut: date
    motif: str = Field(..., min_length=3, max_length=255)
    regulariser_tva: bool = True
    journal_code: str = "OD"
