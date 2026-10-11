"""Schemas Pydantic du module greffe (P1.5) : dossiers, pieces et paiements."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GreffeDepositCreate(BaseModel):
    """Creation du dossier de depot d'un exercice."""

    exercice: int = Field(..., ge=2000, le=2100)
    forme_juridique: str | None = Field(
        default=None, description="SNC, SARL, SA, SCS ou SCA (defaut : forme de la societe)"
    )
    date_ag: date | None = Field(
        default=None, description="Date de l'assemblee generale d'approbation"
    )
    montant_taxes: Decimal = Field(
        default=Decimal("0"), ge=0, description="Taxes du depot (notifiees par le portail)"
    )
    notes: str | None = None


class GreffeEtatRequest(BaseModel):
    """Transition d'etat du portail (7 etats du guide de novembre 2025)."""

    etat: str = Field(
        ...,
        description="nouveau, en_cours, annule, rejete, amender, approuve ou depose",
    )
    motif: str | None = Field(
        default=None, description="Obligatoire pour rejet, annulation, amender et depot final"
    )
    date_effective: date | None = None
    forcer_hors_delai: bool = Field(
        default=False,
        description="Assume un depot hors delai (risque d'amende) au lieu de le bloquer",
    )


class GreffePaymentCreate(BaseModel):
    """Paiement des taxes du depot (paiement en ligne CMI)."""

    montant: Decimal = Field(..., gt=0)
    date_paiement: date | None = None
    moyen: str = Field(default="cmi", description="cmi, virement, cheque ou especes")
    reference: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class GreffeCertificatRequest(BaseModel):
    """Reference du certificat de depot (le fichier est televerse a part)."""

    reference: str | None = Field(default=None, max_length=80)


class GreffeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deposit_id: int
    piece_code: str
    libelle: str
    nom_fichier: str
    type_mime: str
    taille_octets: int
    hash_sha256: str
    source: str
    created_at: datetime


class GreffePaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deposit_id: int
    montant: Decimal
    date_paiement: date
    moyen: str
    reference: str | None = None


class GreffeEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    etat_avant: str
    etat_apres: str
    date_evenement: date
    motif: str | None = None


class GreffeDepositRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    exercice: int
    forme_juridique: str
    statut: str
    date_ag: date | None = None
    date_limite_depot: date
    date_soumission: date | None = None
    date_approbation: date | None = None
    date_limite_paiement: date | None = None
    date_depot: date | None = None
    montant_taxes: Decimal
    amende_montant: Decimal | None = None
    amende_motif: str | None = None
    reference_certificat: str | None = None
    certificat_hash: str | None = None
    certificat_nom: str | None = None
    dernier_motif: str | None = None
    notes: str | None = None