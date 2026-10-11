"""Compteur de numerotation des documents (factures, avoirs, ecritures).

Une ligne par (societe, type de document, exercice). Voir app/core/numbering.py
pour l'attribution des numeros et la garantie d'absence de trou.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NumberingSequence(Base):
    __tablename__ = "numbering_sequences"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "doc_type", "year", name="uq_numbering_sequences_scope"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    doc_type: Mapped[str] = mapped_column(String(30))  # FACTURE_VENTE, AVOIR_VENTE...
    year: Mapped[int] = mapped_column(Integer)
    last_number: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NumberingSequence {self.doc_type}-{self.year} last={self.last_number}>"