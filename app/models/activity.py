"""Evenements de vie de l'entreprise : cessation / cession (P2.2).

Modele (§ 2.3 du CDC) : `activity_events` — **un evenement par changement de
situation** (cessation temporaire, cession, cessation), rattache a la declaration
TVA correspondante (`declaration_id`) et au **regime TVA** publie par la DGI.

Base legale (CGI 2026, edition fournie par le client)
-----------------------------------------------------
- **Article 114** — « Déclaration de cession, de cessation et de ... » : le
  redevable qui cesse son exploitation doit fournir, **dans les trente (30) jours**
  qui suivent la date de cession ou de cessation, une declaration contenant les
  indications necessaires a la **liquidation de la taxe** due jusqu'a cette date et
  a la **regularisation des deductions** (renvoi aux articles **101 a 105**) ; la
  taxe due est exigible dans ce delai. En cas de fusion, scission, apport en
  societe ou transformation, ce paiement et cette regularisation ne sont pas exiges
  si la nouvelle entite s'engage a acquitter la taxe au fur et a mesure des
  encaissements.
- **Article 150-I** : declaration de cessation, cession, fusion, scission ou
  transformation dans un delai de **quarante-cinq (45) jours** ;
- **Article 150 bis** : declaration de **cessation temporaire d'activite**
  souscrite **dans le mois qui suit la cloture du dernier exercice**, pour **deux
  exercices** renouvelable **un seul exercice**, en indiquant les **motifs** ;
- **Article 102 et 104-II-1°** : regularisation de la TVA sur les **biens
  amortissables** (le projet cite « art. 106 », qui traite en realite des
  **exclusions** du droit a deduction — incoherence **A23** du CDC).

Regime TVA des declarations (Annexe 1 « correspondance balise RD V4.0 »)
-----------------------------------------------------------------------
`<regime>` vaut **1** mensuel, **2** trimestriel, **3** *declaration TVA de
cessation temporaire d'activite*, **4** *declaration de cession ou cessation TVA* ;
la balise `<periode>` vaut alors **1**.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# --- Types d'evenement -----------------------------------------------------
TYPE_CESSATION_TEMPORAIRE = "cessation_temporaire"
TYPE_CESSION = "cession"
TYPE_CESSATION = "cessation"
ACTIVITY_TYPES = (TYPE_CESSATION_TEMPORAIRE, TYPE_CESSION, TYPE_CESSATION)
ACTIVITY_TYPE_LABELS = {
    TYPE_CESSATION_TEMPORAIRE: "Cessation temporaire d'activité (CGI art. 150 bis)",
    TYPE_CESSION: "Cession de l'entreprise (CGI art. 114 et 150)",
    TYPE_CESSATION: "Cessation définitive d'activité (CGI art. 114 et 150)",
}

# --- Regimes TVA des declarations d'activite (Annexe 1 RD V4.0) ------------
REGIME_TVA_CESSATION_TEMPORAIRE = 3
REGIME_TVA_CESSION_CESSATION = 4
REGIME_TVA_ACTIVITE = {
    TYPE_CESSATION_TEMPORAIRE: REGIME_TVA_CESSATION_TEMPORAIRE,
    TYPE_CESSION: REGIME_TVA_CESSION_CESSATION,
    TYPE_CESSATION: REGIME_TVA_CESSION_CESSATION,
}
REGIME_TVA_LABELS = {
    REGIME_TVA_CESSATION_TEMPORAIRE: (
        "Déclaration TVA de cessation temporaire d'activité (régime 3)"
    ),
    REGIME_TVA_CESSION_CESSATION: "Déclaration de cession ou cessation TVA (régime 4)",
}
PERIODE_REGIME_ACTIVITE = 1  # l'annexe RD V4.0 impose `periode` = 1 pour les régimes 3 et 4

# --- Delais legaux (CGI 2026) ----------------------------------------------
DELAI_DECLARATION_TVA_JOURS = 30  # art. 114 : TVA de cession/cessation + régularisation
DELAI_DECLARATION_ART_150_JOURS = 45  # art. 150-I : déclaration de cessation/cession
DELAI_CESSATION_TEMPORAIRE_MOIS = 1  # art. 150 bis : dans le mois suivant la clôture
DUREE_CESSATION_TEMPORAIRE_EXERCICES = 2  # art. 150 bis : deux exercices
RENOUVELLEMENT_CESSATION_TEMPORAIRE_EXERCICES = 1  # art. 150 bis : un seul exercice


def regime_tva_pour_type(type_evenement: str) -> int:
    """Regime TVA (3 ou 4) de la declaration liee a l'evenement."""
    try:
        return REGIME_TVA_ACTIVITE[type_evenement]
    except KeyError as exc:
        raise ValueError(
            f"Type d'événement inconnu « {type_evenement} » (valeurs admises : "
            f"{', '.join(ACTIVITY_TYPES)})."
        ) from exc


class ActivityEvent(Base):
    """Evenement de vie de l'entreprise (cessation temporaire, cession, cessation)."""

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(30), index=True)
    date_effet: Mapped[date] = mapped_column(Date, index=True)
    regime_tva: Mapped[int] = mapped_column(Integer)
    periode: Mapped[int] = mapped_column(Integer, default=PERIODE_REGIME_ACTIVITE)
    motif: Mapped[str | None] = mapped_column(Text, default=None)
    # Cession : identification du repreneur (art. 114 : la taxe peut être acquittée
    # au fur et à mesure des encaissements par la nouvelle entité).
    repreneur_nom: Mapped[str | None] = mapped_column(String(180), default=None)
    repreneur_fiscal_id: Mapped[str | None] = mapped_column(String(20), default=None)
    repreneur_ice: Mapped[str | None] = mapped_column(String(15), default=None)
    declaration_id: Mapped[int | None] = mapped_column(
        ForeignKey("tax_declarations.id", ondelete="SET NULL"), default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def type_libelle(self) -> str:
        """Libelle francais du type d'evenement."""
        return ACTIVITY_TYPE_LABELS.get(self.type, self.type)

    @property
    def regime_libelle(self) -> str:
        """Libelle du regime TVA de la declaration liee."""
        return REGIME_TVA_LABELS.get(self.regime_tva, f"Régime {self.regime_tva}")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<ActivityEvent {self.type} {self.date_effet}>"