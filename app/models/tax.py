"""Taux de TVA historises.

Le bareme TVA marocain est passe a DEUX taux au 01/01/2026 (20 % et 10 %), les
taux de 7 % et 14 % etant supprimes. Les taux sont stockes en base avec une date
de validite pour qu'une facture de 2025 reste calculable apres un changement de
bareme : aucun taux ne doit etre code en dur dans la logique metier.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.types import Rate


class VatRate(Base):
    __tablename__ = "vat_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    rate: Mapped[Decimal] = mapped_column(Rate)
    label: Mapped[str] = mapped_column(String(180))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, default=None)
    is_deductible: Mapped[bool] = mapped_column(Boolean, default=True)

    def is_valid_on(self, day: date) -> bool:
        if day < self.valid_from:
            return False
        return self.valid_to is None or day <= self.valid_to

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VatRate {self.code} {self.rate}%>"