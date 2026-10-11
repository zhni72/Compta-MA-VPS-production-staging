"""Rapprochement bancaire (P1.6) : releves importes et appariements.

Modele (§ 2.3 du CDC) :
- `bank_statements` : en-tete du releve importe (compte, periode, solde final) ;
- `bank_statement_lines` : lignes du releve (date, libelle, montant) ;
- `bank_reconciliations` : appariement ligne de releve <-> ligne d'ecriture
  (rapprochement direct ou ajustement).

Aucun solde n'est duplique : l'etat de rapprochement se calcule depuis les
mouvements comptables (`entry_lines`) et les lignes de releve.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.types import Money

RECONCILIATION_TYPES = ("rapproche", "ajustement")
RECONCILIATION_LABELS = {
    "rapproche": "Rapproché",
    "ajustement": "Ajustement",
}


class BankStatement(Base):
    """Releve bancaire importe (CSV normalise)."""

    __tablename__ = "bank_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    account_number: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number"), index=True
    )
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date, index=True)
    opening_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    closing_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    file_name: Mapped[str | None] = mapped_column(String(180), default=None)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    imported_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    lines: Mapped[list[BankStatementLine]] = relationship(
        back_populates="statement", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BankStatement {self.account_number} {self.date_from}..{self.date_to}>"


class BankStatementLine(Base):
    """Ligne d'un releve bancaire."""

    __tablename__ = "bank_statement_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statements.id", ondelete="CASCADE"), index=True
    )
    line_date: Mapped[date] = mapped_column(Date, index=True)
    label: Mapped[str] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(60), default=None)
    debit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    entry_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("entry_lines.id", ondelete="SET NULL"), default=None
    )
    match_type: Mapped[str | None] = mapped_column(String(20), default=None)
    note: Mapped[str | None] = mapped_column(String(255), default=None)

    statement: Mapped[BankStatement] = relationship(back_populates="lines")

    @property
    def montant(self) -> Decimal:
        """Montant signe de la ligne (positif au debit)."""
        return self.debit - self.credit

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BankStatementLine {self.line_date} {self.montant}>"


class BankReconciliation(Base):
    """Appariement d'une ligne de releve avec une ligne d'ecriture."""

    __tablename__ = "bank_reconciliations"
    __table_args__ = (
        UniqueConstraint("statement_line_id", name="uq_bank_reconciliations_statement_line"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_line_id: Mapped[int] = mapped_column(
        ForeignKey("bank_statement_lines.id", ondelete="CASCADE"), index=True
    )
    entry_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("entry_lines.id", ondelete="CASCADE"), default=None, index=True
    )
    reconciliation_type: Mapped[str] = mapped_column(String(20), default="rapproche")
    montant: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    motif: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BankReconciliation line={self.statement_line_id} entry_line={self.entry_line_id}>"
