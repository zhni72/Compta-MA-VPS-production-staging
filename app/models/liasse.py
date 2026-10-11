"""Liasse fiscale EDI : tableaux et cellules (P2.1 — Simpl-IS).

Modele (§ 2.3 du CDC) :

- `liasse_tables` : un **tableau** de la liasse (`tableau/id` du schéma DGI, avec son
  libellé, son `extraField` et son ordre) rattaché à une déclaration du registre
  `tax_declarations` ;
- `liasse_cells` : une **cellule** de tableau (`cellule/codeEdi`, sa valeur, son
  `numeroLigne` et son `extraField`), avec la **rubrique** de l'application qui l'a
  alimentée et l'origine de la valeur (`source`) pour la piste d'audit.

Le modèle suit **exactement la structure du schéma officiel** Simpl-IS (CDC EDI
v2.0.3, § 4.3.1) : `ValeursTableau` (tableau) → `groupeValeurs` → `ValeurCellule`
(`cellule/codeEdi`, `valeur`, `numeroLigne`) et `extraFieldvaleurs`.

Regle de verite : les cellules portent les **valeurs produites par l'application**
(balance définitive, immobilisations, stocks, paie/DTS, résultat fiscal) ; aucun
`codeEdi` n'est deviné — la correspondance vient du référentiel
`codification_liasse.csv`, contrôlé contre les énumérations du XSD officiel.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.types import Money


class LiasseTableau(Base):
    """Tableau de la liasse (`ValeursTableau` du schéma DGI)."""

    __tablename__ = "liasse_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    declaration_id: Mapped[int] = mapped_column(
        ForeignKey("tax_declarations.id", ondelete="CASCADE"), index=True
    )
    modele: Mapped[str] = mapped_column(String(80))
    tableau_id: Mapped[int] = mapped_column(Integer, index=True)
    libelle: Mapped[str | None] = mapped_column(String(200), default=None)
    extra_field: Mapped[str | None] = mapped_column(String(20), default=None)
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cells: Mapped[list["LiasseCell"]] = relationship(
        back_populates="tableau",
        cascade="all, delete-orphan",
        order_by="LiasseCell.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<LiasseTableau modele={self.modele} tableau={self.tableau_id}>"


class LiasseCell(Base):
    """Cellule de la liasse (`ValeurCellule` du schéma DGI).

    `declaration_id` et `tableau_id` sont **repétés** depuis le tableau parent :
    c'est la forme demandée par le CDC (§ 2.3) et cela permet à l'EFI, à la
    réconciliation et au constructeur XML de travailler **sur les seules cellules**,
    sans jointure (les deux colonnes sont écrites par le service, jamais saisies).
    """

    __tablename__ = "liasse_cells"

    id: Mapped[int] = mapped_column(primary_key=True)
    liasse_table_id: Mapped[int] = mapped_column(
        ForeignKey("liasse_tables.id", ondelete="CASCADE"), index=True
    )
    declaration_id: Mapped[int] = mapped_column(
        ForeignKey("tax_declarations.id", ondelete="CASCADE"), index=True
    )
    tableau_id: Mapped[int] = mapped_column(Integer, index=True)
    code_edi: Mapped[str] = mapped_column(String(10), index=True)
    rubrique: Mapped[str | None] = mapped_column(String(80), default=None)
    libelle: Mapped[str | None] = mapped_column(String(200), default=None)
    valeur: Mapped[str] = mapped_column(String(120))
    valeur_numerique: Mapped[Decimal | None] = mapped_column(Money, default=None)
    numero_ligne: Mapped[int | None] = mapped_column(Integer, default=None)
    extra_field: Mapped[str | None] = mapped_column(String(20), default=None)
    source: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tableau: Mapped[LiasseTableau] = relationship(back_populates="cells")

    @property
    def montant(self) -> Decimal | None:
        """Valeur numerique de la cellule (None si la valeur n'est pas un montant)."""
        if self.valeur_numerique is not None:
            return self.valeur_numerique
        try:
            return Decimal(self.valeur.replace(",", "."))
        except (InvalidOperation, AttributeError, ValueError):
            return None

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<LiasseCell tableau={self.tableau_id} codeEdi={self.code_edi}>"
