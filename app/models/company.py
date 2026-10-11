"""Societe (dossier comptable) et exercice comptable.

Multi-tenant : toutes les tables metier portent `company_id` et, quand la notion
s'applique, `fiscal_year_id`. C'est ce qui permet de passer du mono-utilisateur au
multi-utilisateurs (plusieurs dossiers, plusieurs utilisateurs) sans reprendre les
donnees.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

FISCAL_YEAR_STATUSES = ("open", "closed", "locked")


class Company(Base):
    """Dossier comptable d'une societe marocaine."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    legal_form: Mapped[str | None] = mapped_column(String(40))  # SARL, SAS, SA...
    ice: Mapped[str | None] = mapped_column(String(15))  # Identifiant Commun de l'Entreprise
    fiscal_id: Mapped[str | None] = mapped_column(String(20))  # IF
    rc: Mapped[str | None] = mapped_column(String(30))  # Registre de commerce
    patente: Mapped[str | None] = mapped_column(String(30))  # Taxe professionnelle
    cnss_number: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))

    currency: Mapped[str] = mapped_column(String(3), default="MAD")
    # Regime de TVA : mensuel si CA >= 1 M MAD, trimestriel en dessous.
    vat_regime: Mapped[str] = mapped_column(String(20), default="trimestriel")
    # ICE obligatoire sur les factures B2B (regle CGI).
    require_ice: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Dates **reelles** de la societe (P1) : servent a calculer la duree
    # d'activite, donc l'**exoneration de cotisation minimale** (36 premiers
    # mois, CGI art. 20) — aucun mois d'activite n'est code en dur.
    date_constitution: Mapped[date | None] = mapped_column(Date, default=None)
    date_debut_exploitation: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    fiscal_years: Mapped[list[FiscalYear]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company {self.id} {self.name!r} ICE={self.ice}>"


class FiscalYear(Base):
    """Exercice comptable (annee civile pour les societes marocaines)."""

    __tablename__ = "fiscal_years"
    __table_args__ = (
        UniqueConstraint("company_id", "year", name="uq_fiscal_years_company_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    year: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # open -> closed -> locked (voir services/accounting.py)
    status: Mapped[str] = mapped_column(String(10), default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    company: Mapped[Company] = relationship(back_populates="fiscal_years")

    @classmethod
    def for_year(cls, year: int) -> dict:
        """Bornes par defaut d'un exercice : annee civile."""
        return {
            "year": year,
            "start_date": date(year, 1, 1),
            "end_date": date(year, 12, 31),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FiscalYear {self.year} status={self.status}>"