"""Factures (ventes et achats), avoirs, reglements.

Cycle de vie d'une facture :
  draft -> (validation) : numero attribue + ecriture comptable generee
        -> validated / partially_paid / paid
        -> cancelled (le numero reste consomme : numerotation sans trou)

Statuts et workflow sont volontairement explicites : la validation est le point
unique ou la numerotation, le controle de conformite (ICE) et la comptabilisation
sont effectues.
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
from app.models.types import Money, Quantity, Rate

INVOICE_TYPES = ("vente", "achat")

INVOICE_STATUS_DRAFT = "draft"
INVOICE_STATUS_VALIDATED = "validated"
INVOICE_STATUS_PARTIALLY_PAID = "partially_paid"
INVOICE_STATUS_PAID = "paid"
INVOICE_STATUS_CANCELLED = "cancelled"

# Modes de reglement : codification alignee sur la nomenclature EDI de la DGI
# (Annexe 1 « releve des deductions » : 1 espece, 2 cheque, 3 prelevement,
# 4 virement, 5 effet, 6 compensation, 7 autres).
PAYMENT_METHODS = (
    "espece",
    "cheque",
    "prelevement",
    "virement",
    "effet",
    "compensation",
    "autre",
)

# Correspondance mode de reglement -> code DGI (balise <mp><id> du fichier EDI).
PAYMENT_METHOD_CODES: dict[str, int] = {
    "espece": 1,
    "cheque": 2,
    "prelevement": 3,
    "virement": 4,
    "effet": 5,
    "compensation": 6,
    "autre": 7,
}

PAYMENT_METHOD_LABELS: dict[str, str] = {
    "espece": "Espèces",
    "cheque": "Chèque",
    "prelevement": "Prélèvement",
    "virement": "Virement bancaire",
    "effet": "Effet (traite)",
    "compensation": "Compensation",
    "autre": "Autre",
}


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("company_id", "number", name="uq_invoices_company_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="RESTRICT"), index=True
    )
    # Numero attribue a la validation (numerotation continue et sans trou).
    number: Mapped[str | None] = mapped_column(String(30), default=None)
    invoice_type: Mapped[str] = mapped_column(String(10), index=True)
    is_credit_note: Mapped[bool] = mapped_column(Boolean, default=False)

    partner_id: Mapped[int] = mapped_column(ForeignKey("third_parties.id"), index=True)
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    payment_mode: Mapped[str | None] = mapped_column(String(20), default=None)
    reference: Mapped[str | None] = mapped_column(String(60), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    total_ht: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_vat: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_ttc: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    paid_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    status: Mapped[str] = mapped_column(String(16), default=INVOICE_STATUS_DRAFT)
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    @property
    def remaining_amount(self) -> Decimal:
        return self.total_ttc - self.paid_amount

    @property
    def is_editable(self) -> bool:
        """Un document valide n'est plus modifiable : il faut un avoir."""
        return self.status == INVOICE_STATUS_DRAFT

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Invoice {self.number or 'BROUILLON'} {self.invoice_type} {self.total_ttc}>"


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    designation: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Quantity, default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    discount_percent: Mapped[Decimal] = mapped_column(Rate, default=Decimal("0"))
    vat_rate: Mapped[Decimal] = mapped_column(Rate, default=Decimal("20"))
    # Compte de produit (7111) ou de charge (6111) mouvemente par la ligne.
    account_number: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number")
    )

    line_ht: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    line_vat: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    line_ttc: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvoiceLine {self.designation!r} {self.line_ttc}>"


class Payment(Base):
    """Reglement (total ou partiel) d'une facture ou d'un compte de tiers."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="RESTRICT"), index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), default=None, index=True
    )
    partner_id: Mapped[int] = mapped_column(ForeignKey("third_parties.id"), index=True)
    payment_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    method: Mapped[str] = mapped_column(String(20), default="virement")
    reference: Mapped[str | None] = mapped_column(String(60), default=None)
    # Compte de tresorerie mouvemente (5141 banque, 5161 caisse).
    treasury_account: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number"), default="5141"
    )
    entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment {self.payment_date} {self.amount} {self.method}>"