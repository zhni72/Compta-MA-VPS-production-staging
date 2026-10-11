"""Journaux comptables, ecritures et lignes d'ecriture.

Regles structurelles :
- une ecriture est la seule source de verite comptable (les factures et
  reglements la generent automatiquement) ;
- une ecriture VALIDEE est immuable : on la corrige par contre-ecriture ;
- debit et credit doivent etre egaux avant validation ;
- `row_version` sert au verrouillage optimiste (phase 2, multi-utilisateurs).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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

# Journaux standards marocains
DEFAULT_JOURNALS = (
    ("AC", "Journal des achats", "achat"),
    ("VE", "Journal des ventes", "vente"),
    ("BQ", "Journal de banque", "tresorerie"),
    ("CA", "Journal de caisse", "tresorerie"),
    ("OD", "Operations diverses", "general"),
)

ENTRY_STATUS_DRAFT = "draft"
ENTRY_STATUS_VALIDATED = "validated"


class Journal(Base):
    __tablename__ = "journals"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_journals_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(6))
    label: Mapped[str] = mapped_column(String(120))
    journal_type: Mapped[str] = mapped_column(String(20), default="general")
    is_active: Mapped[bool] = mapped_column(default=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Journal {self.code}>"


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="RESTRICT"), index=True
    )
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id"), index=True)

    entry_number: Mapped[str | None] = mapped_column(String(30), default=None)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    label: Mapped[str] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(60), default=None)

    status: Mapped[str] = mapped_column(String(12), default=ENTRY_STATUS_DRAFT)
    # manual | invoice | payment | reversal
    source: Mapped[str] = mapped_column(String(20), default="manual")
    source_id: Mapped[int | None] = mapped_column(Integer, default=None)
    reversed_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id"), default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    validated_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # Piste d'audit fiable (P1.6) : empreinte SHA-256 de l'ecriture validee et
    # empreinte de l'ecriture precedente (chainage) — toute alteration devient
    # detectable hors application.
    entry_hash: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lines: Mapped[list[EntryLine]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    @property
    def total_debit(self) -> Decimal:
        return sum((line.debit for line in self.lines), Decimal("0"))

    @property
    def total_credit(self) -> Decimal:
        return sum((line.credit for line in self.lines), Decimal("0"))

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def is_validated(self) -> bool:
        return self.status == ENTRY_STATUS_VALIDATED

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Entry {self.id} {self.label!r} {self.status}>"


class EntryLine(Base):
    __tablename__ = "entry_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), index=True
    )
    account_number: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number"), index=True
    )
    third_party_id: Mapped[int | None] = mapped_column(
        ForeignKey("third_parties.id", ondelete="SET NULL"), default=None, index=True
    )
    label: Mapped[str | None] = mapped_column(String(255), default=None)
    debit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    vat_rate: Mapped[Decimal | None] = mapped_column(Rate, default=None)
    position: Mapped[int] = mapped_column(Integer, default=0)

    entry: Mapped[Entry] = relationship(back_populates="lines")

    @property
    def signed_amount(self) -> Decimal:
        """Solde signe : positif au debit, negatif au credit."""
        return self.debit - self.credit

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EntryLine {self.account_number} D={self.debit} C={self.credit}>"