"""Registre unique des declarations fiscales et sociales (§ 2.3 du CDC).

`tax_declarations` est la **table transverse** qui porte la tracabilite des
depots : TVA (EDI ou EFI), **DTS « 9421 »** (paie), IS/liasse, DTS/IR, et plus
tard les declarations complementaires. Chaque ligne conserve la periode, le
regime, l'etat, le **fichier produit** (nom, empreinte) et l'**accuse de
reception** de la DGI.

Le module Paie (P1.4) est le premier utilisateur : les autres modules
déclaratifs s'y raccorderont sans changer le modele.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.types import Money

# --- Types de declaration --------------------------------------------------
DECLARATION_TVA = "TVA"
DECLARATION_DTS = "DTS"
DECLARATION_IS = "IS"
DECLARATION_LIASSE = "LIASSE"
DECLARATION_TYPES = (DECLARATION_TVA, DECLARATION_DTS, DECLARATION_IS, DECLARATION_LIASSE)
DECLARATION_TYPE_LABELS = {
    DECLARATION_TVA: "Déclaration de TVA",
    DECLARATION_DTS: "Déclaration des traitements et salaires (DTS « 9421 »)",
    DECLARATION_IS: "Déclaration de l'impôt sur les sociétés",
    DECLARATION_LIASSE: "Liasse fiscale (Simpl-IS)",
}

# --- Etats d'une declaration ----------------------------------------------
DECLARATION_BROUILLON = "brouillon"
DECLARATION_SOUMISE = "soumise"
DECLARATION_ACCEPTEE = "acceptee"
DECLARATION_REJETEE = "rejetee"
DECLARATION_STATUTS = (
    DECLARATION_BROUILLON,
    DECLARATION_SOUMISE,
    DECLARATION_ACCEPTEE,
    DECLARATION_REJETEE,
)
DECLARATION_STATUT_LABELS = {
    DECLARATION_BROUILLON: "Brouillon (fichier préparé, non déposé)",
    DECLARATION_SOUMISE: "Soumise (accusé en attente)",
    DECLARATION_ACCEPTEE: "Acceptée par la DGI",
    DECLARATION_REJETEE: "Rejetée (à corriger)",
}

# --- Modes de depot --------------------------------------------------------
DEPOT_EDI = "EDI"
DEPOT_EFI = "EFI"
DEPOT_MODES = (DEPOT_EDI, DEPOT_EFI)
DEPOT_MODE_LABELS = {
    DEPOT_EDI: "EDI (fichier XML produit par le logiciel)",
    DEPOT_EFI: "EFI (saisie assistée sur le téléservice SIMPL)",
}


class TaxDeclaration(Base):
    """Declaration deposee (ou a deposer) : registre de tracabilite."""

    __tablename__ = "tax_declarations"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="SET NULL"), default=None
    )
    type: Mapped[str] = mapped_column(String(20), index=True)
    periode: Mapped[str] = mapped_column(String(10), index=True)  # AAAA-MM ou AAAA-Tn
    regime: Mapped[str | None] = mapped_column(String(64), default=None)
    mode_depot: Mapped[str] = mapped_column(String(5), default=DEPOT_EDI)
    statut: Mapped[str] = mapped_column(String(20), default=DECLARATION_BROUILLON)
    montant: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    nb_lignes: Mapped[int] = mapped_column(default=0)
    fichier_nom: Mapped[str | None] = mapped_column(String(120), default=None)
    fichier_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    fichier_taille: Mapped[int] = mapped_column(default=0)
    deposant: Mapped[str | None] = mapped_column(String(120), default=None)
    motif_rejet: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    soumise_le: Mapped[date | None] = mapped_column(Date, default=None)
    accuse_le: Mapped[date | None] = mapped_column(Date, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    @property
    def type_libelle(self) -> str:
        """Libelle francais du type de declaration."""
        return DECLARATION_TYPE_LABELS.get(self.type, self.type)

    @property
    def statut_libelle(self) -> str:
        """Libelle francais de l'etat de la declaration."""
        return DECLARATION_STATUT_LABELS.get(self.statut, self.statut)

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<TaxDeclaration {self.type} {self.periode} {self.statut}>"
