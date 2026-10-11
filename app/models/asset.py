"""Immobilisations : fiches, plan d'amortissement et journal des mouvements (P1.2).

Cycle de vie : **acquisition → mise en service → dotations → cession / rebut**.

Regles structurelles :
- la fiche (`assets`) est la **source du plan d'amortissement** ; les ecritures
  (`entries` / `entry_lines`) restent la seule source de verite comptable ;
- une ligne de plan (`asset_depreciation_lines`) est liee a l'ecriture de dotation
  (`entry_id`) : **aucune dotation n'est constatee sans ecriture** ;
- tout mouvement (acquisition, dotation, cession, rebut, regularisation art. 106)
  est historise dans `asset_events` (piste d'audit fiable) ;
- aucun solde n'est duplique : l'amortissement cumule et la VNC se calculent
  depuis les lignes de plan.

References : CGNC (plan comptable, titre II chapitre I : actif immobilise) et CGI
(art. 10 : amortissements — art. 106 : regularisation de la TVA).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.types import Money, Rate

# --- Statuts de la fiche -----------------------------------------------------
ASSET_STATUS_EN_SERVICE = "en_service"
ASSET_STATUS_CELE = "cede"
ASSET_STATUS_REBUTE = "rebut"
ASSET_STATUSES = (ASSET_STATUS_EN_SERVICE, ASSET_STATUS_CELE, ASSET_STATUS_REBUTE)
ASSET_STATUS_LABELS = {
    ASSET_STATUS_EN_SERVICE: "En service",
    ASSET_STATUS_CELE: "Cédée",
    ASSET_STATUS_REBUTE: "Mise au rebut",
}

# --- Modes d'amortissement (CGI art. 10) ------------------------------------
ASSET_METHOD_LINEAIRE = "lineaire"
ASSET_METHOD_DEGRESSIF = "degressif"
ASSET_METHODS = (ASSET_METHOD_LINEAIRE, ASSET_METHOD_DEGRESSIF)
ASSET_METHOD_LABELS = {
    ASSET_METHOD_LINEAIRE: "Linéaire",
    ASSET_METHOD_DEGRESSIF: "Dégressif (coefficient paramétrable)",
}

# --- Types d'evenement (journal de la fiche) --------------------------------
ASSET_EVENT_ACQUISITION = "acquisition"
ASSET_EVENT_DOTATION = "dotation"
ASSET_EVENT_CESSION = "cession"
ASSET_EVENT_REBUT = "rebut"
ASSET_EVENT_REGULARISATION = "regularisation_tva"
ASSET_EVENT_TYPES = (
    ASSET_EVENT_ACQUISITION,
    ASSET_EVENT_DOTATION,
    ASSET_EVENT_CESSION,
    ASSET_EVENT_REBUT,
    ASSET_EVENT_REGULARISATION,
)
ASSET_EVENT_LABELS = {
    ASSET_EVENT_ACQUISITION: "Acquisition",
    ASSET_EVENT_DOTATION: "Dotation aux amortissements",
    ASSET_EVENT_CESSION: "Cession",
    ASSET_EVENT_REBUT: "Mise au rebut",
    ASSET_EVENT_REGULARISATION: "Régularisation TVA (art. 106 CGI)",
}


class Asset(Base):
    """Fiche d'immobilisation (une immobilisation = un compte 2xxx)."""

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_assets_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))  # IM202600001
    label: Mapped[str] = mapped_column(String(180))
    account_number: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number"), index=True
    )
    third_party_id: Mapped[int | None] = mapped_column(
        ForeignKey("third_parties.id", ondelete="SET NULL"), default=None, index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), default=None
    )

    acquisition_date: Mapped[date] = mapped_column(Date, index=True)
    service_date: Mapped[date | None] = mapped_column(Date, default=None)
    valeur_origine: Mapped[Decimal] = mapped_column(Money)
    valeur_residuelle: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    duree_annees: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(20), default=ASSET_METHOD_LINEAIRE)
    coefficient: Mapped[Decimal | None] = mapped_column(Rate, default=None)
    # Prorata temporis fiscal (CGI art. 10) sur la premiere annuite ; False = annuite pleine.
    prorata_temporis: Mapped[bool] = mapped_column(Boolean, default=True)

    # TVA ayant greve l'immobilisation : compte 34551 (jamais 34552) — CGI art. 106.
    tva_montant: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    tva_compte: Mapped[str] = mapped_column(String(12), default="34551")

    statut: Mapped[str] = mapped_column(String(20), default=ASSET_STATUS_EN_SERVICE)
    disposal_date: Mapped[date | None] = mapped_column(Date, default=None)
    disposal_price: Mapped[Decimal | None] = mapped_column(Money, default=None)
    disposal_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    depreciation_lines: Mapped[list[AssetDepreciationLine]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    events: Mapped[list[AssetEvent]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    @property
    def base_amortissable(self) -> Decimal:
        """Valeur amortissable (CGNC : valeur d'entree - valeur residuelle)."""
        return self.valeur_origine - self.valeur_residuelle

    @property
    def is_disposed(self) -> bool:
        """Vrai si le bien est sorti de l'actif (cede ou mis au rebut)."""
        return self.statut in (ASSET_STATUS_CELE, ASSET_STATUS_REBUTE)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Asset {self.code} {self.account_number} {self.valeur_origine}>"



class AssetDepreciationLine(Base):
    """Ligne de plan d'amortissement d'un exercice (projetee ou realisee).

    Une ligne est **realisee** lorsqu'elle porte `entry_id` : elle correspond alors
    a une ecriture de dotation validee (6193x / 283x). Elle sert de source unique au
    cumul et a la VNC (aucun solde duplique).
    """

    __tablename__ = "asset_depreciation_lines"
    __table_args__ = (
        UniqueConstraint("asset_id", "exercice", name="uq_asset_depreciation_asset_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    exercice: Mapped[int] = mapped_column(Integer, index=True)
    base: Mapped[Decimal] = mapped_column(Money)  # base amortissable
    annuite: Mapped[Decimal] = mapped_column(Money)
    cumul: Mapped[Decimal] = mapped_column(Money)  # cumul a la fin de l'exercice
    vnc: Mapped[Decimal] = mapped_column(Money)  # valeur nette d'amortissement
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    asset: Mapped[Asset] = relationship(back_populates="depreciation_lines")

    @property
    def is_constatee(self) -> bool:
        """Vrai si la dotation a ete comptabilisee (ecriture validee)."""
        return self.entry_id is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AssetDepreciationLine {self.exercice} annuite={self.annuite}>"


class AssetEvent(Base):
    """Journal des mouvements d'une immobilisation (piste d'audit fiable)."""

    __tablename__ = "asset_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    montant: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    motif: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    asset: Mapped[Asset] = relationship(back_populates="events")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AssetEvent {self.event_type} {self.event_date} {self.montant}>"

