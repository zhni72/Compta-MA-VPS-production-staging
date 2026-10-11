"""Stocks et inventaire permanent (P1.3).

Modele (§ 2.3 du CDC) :
- `stock_items` : fiche article (compte de stock 3xxx, seuil d'alerte, **mode de
  valorisation** CMUP ou FIFO) ;
- `stock_movements` : mouvements **entree / sortie / inventaire** valorises ;
- `stock_counts` / `stock_count_lines` : inventaire physique et ecarts ;
- `stock_provisions` : depreciation des stocks (prudence) — **391x / 61961**.

References : **CGNC titre II chapitre II** (actif circulant : stocks — cout de
revient, CMUP ou FIFO, LIFO proscrit, permanence des methodes) et **CGNC titre V
chapitre I** (tenue des comptes d'inventaire permanent en comptabilite generale).

Regle de verite : la quantite et la valeur d'un article se **calculent** en
rejouant ses mouvements ; les colonnes `quantity_on_hand`, `cmup` et
`value_on_hand` de la fiche sont un **cache** de consultation, verifie par le
controle `stock.cache_divergent` (aucun solde n'est duplique en silence).
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
from app.models.types import Money, Quantity

# --- Modes de valorisation (CGNC : CMUP ou FIFO ; le LIFO est proscrit) ------
VALUATION_METHOD_CMUP = "cmup"
VALUATION_METHOD_FIFO = "fifo"
VALUATION_METHODS = (VALUATION_METHOD_CMUP, VALUATION_METHOD_FIFO)
VALUATION_METHOD_LABELS = {
    VALUATION_METHOD_CMUP: "Coût moyen unitaire pondéré (CMUP)",
    VALUATION_METHOD_FIFO: "Premier entré, premier sorti (FIFO)",
}

# --- Regimes de tenue des comptes de stock (CDC § 3.3) ----------------------
STOCK_REGIME_INTERMITTENT = "intermittent"
STOCK_REGIME_PERMANENT = "permanent"
STOCK_REGIMES = (STOCK_REGIME_INTERMITTENT, STOCK_REGIME_PERMANENT)
STOCK_REGIME_LABELS = {
    STOCK_REGIME_INTERMITTENT: "Intermittent (variation constatée à la clôture)",
    STOCK_REGIME_PERMANENT: "Inventaire permanent (comptes de stock mouvementés)",
}

# --- Types et motifs de mouvement ------------------------------------------
MOVEMENT_ENTRY = "entree"
MOVEMENT_EXIT = "sortie"
MOVEMENT_COUNT = "inventaire"
MOVEMENT_TYPES = (MOVEMENT_ENTRY, MOVEMENT_EXIT, MOVEMENT_COUNT)
MOVEMENT_TYPE_LABELS = {
    MOVEMENT_ENTRY: "Entrée",
    MOVEMENT_EXIT: "Sortie",
    MOVEMENT_COUNT: "Écart d'inventaire",
}
MOVEMENT_REASONS = (
    "ouverture",
    "achat",
    "retour_client",
    "production",
    "transfert",
    "vente",
    "consommation",
    "perte",
    "retour_fournisseur",
    "inventaire",
)
MOVEMENT_REASON_LABELS = {
    "ouverture": "Stock d'ouverture",
    "achat": "Achat (facture)",
    "retour_client": "Retour client",
    "production": "Entrée pour production",
    "transfert": "Transfert",
    "vente": "Vente",
    "consommation": "Consommation interne",
    "perte": "Perte / casse",
    "retour_fournisseur": "Retour fournisseur",
    "inventaire": "Inventaire physique",
}
COUNT_STATUS_DRAFT = "brouillon"
COUNT_STATUS_VALIDATED = "valide"


class StockItem(Base):
    """Fiche article (reference unique par dossier)."""

    __tablename__ = "stock_items"
    __table_args__ = (
        UniqueConstraint("company_id", "reference", name="uq_stock_items_company_reference"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    reference: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(180))
    unit: Mapped[str] = mapped_column(String(20), default="U")
    family: Mapped[str | None] = mapped_column(String(60), default=None)
    stock_account: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number"), index=True
    )
    purchase_account: Mapped[str | None] = mapped_column(String(12), default=None)
    sale_account: Mapped[str | None] = mapped_column(String(12), default=None)
    alert_threshold: Mapped[Decimal] = mapped_column(Quantity, default=Decimal("0"))
    valuation_method: Mapped[str] = mapped_column(
        String(10), default=VALUATION_METHOD_CMUP
    )
    # Cache de consultation, recalcule par le service (controle de coherence).
    quantity_on_hand: Mapped[Decimal] = mapped_column(Quantity, default=Decimal("0"))
    cmup: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    value_on_hand: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    movements: Mapped[list[StockMovement]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    @property
    def sous_seuil(self) -> bool:
        """Vrai si l'article **en stock** atteint son seuil d'alerte.

        Un article jamais approvisionne (stock nul) ne declenche pas d'alerte : le
        seuil sert au **reapprovisionnement** des articles suivis.
        """
        return self.alert_threshold > 0 and Decimal("0") < self.quantity_on_hand <= self.alert_threshold

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StockItem {self.reference} {self.stock_account}>"


class StockMovement(Base):
    """Mouvement de stock valorise (entree, sortie ou ecart d'inventaire)."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("stock_items.id", ondelete="CASCADE"), index=True
    )
    movement_date: Mapped[date] = mapped_column(Date, index=True)
    movement_type: Mapped[str] = mapped_column(String(12), index=True)
    reason: Mapped[str] = mapped_column(String(30), default="achat")
    quantity: Mapped[Decimal] = mapped_column(Quantity)  # + entree, - sortie
    unit_cost: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    label: Mapped[str | None] = mapped_column(String(255), default=None)
    reference: Mapped[str | None] = mapped_column(String(60), default=None)
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), default=None
    )
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    count_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    item: Mapped[StockItem] = relationship(back_populates="movements")

    @property
    def is_entry(self) -> bool:
        return self.quantity > 0

    @property
    def cout_unitaire_calcule(self) -> Decimal:
        """Cout unitaire deduit de la valeur et de la quantite (controle)."""
        if self.quantity == 0:
            return Decimal("0")
        return (abs(self.value) / abs(self.quantity)).quantize(Decimal("0.0001"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StockMovement {self.movement_type} {self.quantity} {self.value}>"



class StockCount(Base):
    """Inventaire physique (session de comptage)."""

    __tablename__ = "stock_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    count_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12), default=COUNT_STATUS_DRAFT)
    label: Mapped[str | None] = mapped_column(String(120), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    lines: Mapped[list[StockCountLine]] = relationship(
        back_populates="count", cascade="all, delete-orphan"
    )

    @property
    def total_ecart_valeur(self) -> Decimal:
        """Valeur totale des ecarts d'inventaire (positive si excedent constate)."""
        return sum((ligne.gap_value for ligne in self.lines), Decimal("0"))

    @property
    def ecarts(self) -> list[StockCountLine]:
        """Lignes presentant un ecart entre theorique et physique."""
        return [ligne for ligne in self.lines if ligne.gap_quantity != 0]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StockCount {self.count_date} {self.status}>"


class StockCountLine(Base):
    """Ligne d'inventaire physique : theorique, physique et ecart valorise."""

    __tablename__ = "stock_count_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("stock_items.id", ondelete="CASCADE"), index=True
    )
    theoretical_quantity: Mapped[Decimal] = mapped_column(Quantity, default=Decimal("0"))
    physical_quantity: Mapped[Decimal] = mapped_column(Quantity, default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    gap_quantity: Mapped[Decimal] = mapped_column(Quantity, default=Decimal("0"))
    gap_value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="SET NULL"), default=None
    )

    count: Mapped[StockCount] = relationship(back_populates="lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StockCountLine item={self.item_id} ecart={self.gap_quantity}>"


class StockProvision(Base):
    """Depreciation d'un stock (prudence) : valeur d'inventaire < valeur comptable."""

    __tablename__ = "stock_provisions"
    __table_args__ = (
        UniqueConstraint("item_id", "exercice", name="uq_stock_provisions_item_exercice"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("stock_items.id", ondelete="CASCADE"), index=True
    )
    exercice: Mapped[int] = mapped_column(Integer, index=True)
    book_value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    inventory_value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    provision: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    previous_provision: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    motif: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    @property
    def dotation(self) -> Decimal:
        """Dotation de l'exercice (positive) ou reprise (negative)."""
        return self.provision - self.previous_provision

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StockProvision item={self.item_id} {self.exercice} {self.provision}>"

