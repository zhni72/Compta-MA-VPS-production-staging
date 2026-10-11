"""Tiers : clients, fournisseurs, salaries.

Chaque tiers est rattache a un compte de tiers du PCGE (3421 pour les clients,
4411 pour les fournisseurs) via un sous-compte divisionnaire, par exemple
34210013 pour le client n° 13.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PARTY_KINDS = ("client", "fournisseur", "salarie")
DEFAULT_PARTY_ACCOUNTS = {"client": "3421", "fournisseur": "4411", "salarie": "3431"}


class ThirdParty(Base):
    __tablename__ = "third_parties"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_third_parties_company_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20), index=True)  # code tiers (CL0001...)
    kind: Mapped[str] = mapped_column(String(15), index=True)  # client|fournisseur|salarie
    name: Mapped[str] = mapped_column(String(180), index=True)

    # Personne physique : dispensee d'ICE (le particulier n'en a pas).
    is_individual: Mapped[bool] = mapped_column(Boolean, default=False)
    ice: Mapped[str | None] = mapped_column(String(15))
    fiscal_id: Mapped[str | None] = mapped_column(String(20))
    rc: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))

    # Compte de rattachement (sous-compte du PCGE) et conditions de reglement.
    account_number: Mapped[str] = mapped_column(
        String(12), ForeignKey("accounts.number"), index=True
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def requires_ice(self) -> bool:
        """Un tiers professionnel doit porter un ICE (obligation CGI)."""
        return not self.is_individual

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ThirdParty {self.code} {self.name!r} ({self.kind})>"