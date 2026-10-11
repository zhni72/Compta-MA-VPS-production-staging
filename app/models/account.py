"""Plan comptable (PCGE / CGNC).

Codification decimale :
  1 chiffre  : masse (classe)
  2 chiffres : rubrique
  3 chiffres : poste
  4 chiffres : compte principal  -> OBLIGATOIRE
  5 chiffres : compte divisionnaire -> recommande
  6 et plus  : sous-compte libre cree par l'entreprise

Classes 1 a 5 -> etats de synthese (bilan) ; 6 a 8 -> CPC et resultats.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CGNC_CLASSES: dict[int, str] = {
    1: "Comptes de financement permanent",
    2: "Comptes d'actif immobilise",
    3: "Comptes d'actif circulant (hors tresorerie)",
    4: "Comptes de passif circulant (hors tresorerie)",
    5: "Comptes de tresorerie",
    6: "Comptes de charges",
    7: "Comptes de produits",
    8: "Comptes de resultats",
}


class Account(Base):
    """Compte du plan comptable marocain (commun a toutes les societes)."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(180))
    account_class: Mapped[int] = mapped_column(Integer, index=True)
    # Compte collectif (3421, 4411...) : ne recoit pas d'ecriture directe,
    # ce sont ses divisionnaires qui sont mouvementes.
    is_collectif: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def statement(self) -> str:
        """'bilan' pour les classes 1 a 5, 'cpc' pour les classes 6 a 8."""
        return "bilan" if self.account_class <= 5 else "cpc"

    @property
    def is_vat_deductible(self) -> bool:
        return self.number.startswith("3455")

    @property
    def is_vat_collected(self) -> bool:
        return self.number.startswith("4455")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Account {self.number} {self.label!r}>"