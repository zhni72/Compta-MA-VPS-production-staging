"""Verrouillage de periode (P1.6).

Un verrou porte sur un **exercice** (`periode = None`) ou sur un **mois**
(`periode = 1..12`). Il interdit toute nouvelle ecriture et toute modification de
brouillon dans la periode couverte — y compris via les outils d'import.

Regle CGNC (« organisation de la comptabilite ») : les livres doivent pouvoir etre
presentes a tout controle, **sans blanc ni alteration** ; le verrouillage est la
garantie technique de cet engagement.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PERIOD_LOCK_MOTIFS = (
    "libelle",
)


class PeriodLock(Base):
    """Verrou d'une periode (mois ou exercice complet) d'un dossier."""

    __tablename__ = "period_locks"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "fiscal_year_id",
            "periode",
            name="uq_period_locks_company_year_period",
        ),
        Index(
            "uq_period_locks_company_year_annual",
            "company_id",
            "fiscal_year_id",
            unique=True,
            postgresql_where=text("periode IS NULL"),
            sqlite_where=text("periode IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="CASCADE"), index=True
    )
    # None = exercice entier ; 1 a 12 = mois verrouille
    periode: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    motif: Mapped[str | None] = mapped_column(String(255), default=None)
    locked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    locked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    @property
    def libelle(self) -> str:
        """Libelle affichable du verrou."""
        return "Exercice entier" if self.periode is None else f"Mois {self.periode:02d}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PeriodLock year={self.fiscal_year_id} periode={self.periode}>"
