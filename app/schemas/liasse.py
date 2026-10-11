"""Schemas Pydantic de la liasse fiscale EDI (P2.1)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.models.declaration import DEPOT_EFI, DEPOT_MODES


class LiasseEnregistrementRequest(BaseModel):
    """Enregistrement de la liasse d'un exercice (brouillon, EFI ou EDI)."""

    modele: str | None = Field(
        default=None,
        description=(
            "Modèle du schéma XSD (défaut : comptable simplifié). Alias acceptés : "
            "`normal`, `assurances`, `établissements de crédit`."
        ),
    )
    mode_depot: str = Field(
        default=DEPOT_EFI,
        description=f"Mode de dépôt ({', '.join(DEPOT_MODES)}) : EFI = saisie assistée.",
    )
    avec_xml: bool = Field(
        default=False,
        description=(
            "Produire et joindre le fichier XML validé par le schéma (obligatoire "
            "pour un dépôt EDI)."
        ),
    )


class LiasseSoumissionRequest(BaseModel):
    """Dépôt de la liasse et **accusé de réception** de la DGI."""

    jour: date | None = Field(default=None, description="Date de dépôt (défaut : aujourd'hui)")
    accuse_le: date | None = Field(
        default=None, description="Date de l'accusé de réception : la déclaration est acceptée"
    )
    motif_rejet: str | None = Field(
        default=None, max_length=500, description="Motif du rejet : la déclaration est rejetée"
    )
