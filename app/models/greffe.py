"""Depot au greffe du tribunal des etats de synthese (P1.5).

Modele (§ 2.3 du CDC) :

- `greffe_deposits` : dossier de depot par exercice — forme juridique, **statut**
  (les 7 etats du portail), dates (AG, soumission, approbation, limite de
  paiement, depot), taxes, reference et chemin du **certificat** ;
- `greffe_documents` : pieces PDF du dossier (nom, taille, **empreinte SHA-256**) ;
- `greffe_payments` : paiement des taxes du depot (CMI) ;
- `greffe_events` : **journal des transitions** d'etat (avec motif de rejet).

References normatives
---------------------
- **Loi 5-96** (SNC, SCS, SCA, SARL) : art. 10 — l'assemblee approuve les etats
  de synthese **dans les six mois** de la cloture ; art. 93 (titre VII
  « De la publicite ») — publicite par **depot d'actes ou de pieces au greffe du
  tribunal du lieu du siege social**.
- **Loi 17-95** (SA, modifiee par la loi 19-20) : art. 14 — publicite par depot
  **au greffe du tribunal** aupres duquel le registre du commerce est tenu.
- **Guide officiel « Depot electronique des etats de synthese »** (Ministere de
  la Justice, novembre 2025) : portail `https://depotbilan.justice.gov.ma`,
  pieces **PDF <= 10 Mo**, paiement des taxes **sous 3 jours** apres approbation
  (au-dela : **rejet automatique**), certificat de depot signe electroniquement.

Aucun solde n'est duplique : le montant deja paye d'un dossier est **calcule**
par somme des lignes de `greffe_payments` (voir `services.greffe.solde_taxes`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
from app.models.types import Money

# ---------------------------------------------------------------------------
# Les 7 etats d'une demande de depot (guide de novembre 2025).
# ---------------------------------------------------------------------------
ETAT_NOUVEAU = "nouveau"
ETAT_EN_COURS = "en_cours"
ETAT_ANNULE = "annule"
ETAT_REJETE = "rejete"
ETAT_AMENDER = "amender"
ETAT_APPROUVE = "approuve"
ETAT_DEPOSE = "depose"

GREFFE_ETATS = (
    ETAT_NOUVEAU,
    ETAT_EN_COURS,
    ETAT_ANNULE,
    ETAT_REJETE,
    ETAT_AMENDER,
    ETAT_APPROUVE,
    ETAT_DEPOSE,
)
GREFFE_ETAT_LABELS = {
    ETAT_NOUVEAU: "Nouveau (créé, non soumis)",
    ETAT_EN_COURS: "En cours (en traitement par le greffe)",
    ETAT_ANNULE: "Annulé",
    ETAT_REJETE: "Rejeté (dossier incomplet)",
    ETAT_AMENDER: "Amender (dépôt hors délai : amende)",
    ETAT_APPROUVE: "Approuvé (en attente de paiement)",
    ETAT_DEPOSE: "Déposé (certificat disponible)",
}

# Transitions autorisees entre etats : une ligne « Depose » ou « Annule » est
# terminale (controle bloquant n° 6 du CDC).
GREFFE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ETAT_NOUVEAU: (ETAT_EN_COURS, ETAT_AMENDER, ETAT_ANNULE),
    ETAT_EN_COURS: (ETAT_APPROUVE, ETAT_REJETE, ETAT_AMENDER, ETAT_ANNULE),
    ETAT_REJETE: (ETAT_EN_COURS, ETAT_AMENDER, ETAT_ANNULE),
    ETAT_AMENDER: (ETAT_APPROUVE, ETAT_REJETE, ETAT_DEPOSE, ETAT_ANNULE),
    ETAT_APPROUVE: (ETAT_DEPOSE, ETAT_ANNULE),
    ETAT_ANNULE: (ETAT_NOUVEAU,),
    ETAT_DEPOSE: (),
}
GREFFE_ETATS_TERMINAUX = (ETAT_DEPOSE,)
# Dossier clos mais **rouvrable** : l'annulation conserve la ligne et son motif,
# une reouverture motivee est possible (unicite par exercice conservee).
GREFFE_ETATS_REOUVRABLES = (ETAT_ANNULE,)
# Un seul dossier « vivant » par exercice (pas de doublon de depot).
GREFFE_ETATS_ACTIFS = (ETAT_EN_COURS, ETAT_APPROUVE, ETAT_DEPOSE)
GREFFE_ETATS_ALERTE = (ETAT_REJETE, ETAT_AMENDER)

# ---------------------------------------------------------------------------
# Paiement des taxes (paiement en ligne CMI apres approbation).
# ---------------------------------------------------------------------------
GREFFE_MOYENS = ("cmi", "virement", "cheque", "especes")
GREFFE_MOYEN_LABELS = {
    "cmi": "Paiement en ligne (CMI)",
    "virement": "Virement bancaire",
    "cheque": "Chèque",
    "especes": "Espèces",
}

DELAI_AG_MOIS = 6  # loi 5-96 art. 10 : assemblee dans les 6 mois de la cloture
DELAI_PAIEMENT_JOURS = 3  # guide nov. 2025 : 3 jours apres approbation

# ---------------------------------------------------------------------------
# Catalogue des pieces du dossier de depot (parametrable ; liste officielle a
# confirmer a la premiere adhesion — voir `pdf_documents.PIECES_GREFFE_*`).
# `formes_obligatoires` : formes juridiques pour lesquelles la piece est
# exigee ; `formes_conditionnelles` : exigee seulement si un commissaire aux
# comptes est nomme, donc **non bloquante** pour l'application.
# ---------------------------------------------------------------------------
SOURCE_GENERE = "genere"  # produite par Compta MA (P1.1 / module greffe)
SOURCE_TELEVERSE = "televerse"  # piece externe televersee par l'utilisateur
SOURCE_PAIEMENT = "paiement"  # justifiee par un paiement enregistre

PIECE_ETATS_SYNTHESE = "etats_synthese"
PIECE_TABLEAU_FINANCEMENT = "tableau_financement"
PIECE_RAPPORT_GESTION = "rapport_gestion"
PIECE_RAPPORT_CAC = "rapport_cac"
PIECE_PV_AG = "pv_ag"
PIECE_ETAT_COMPLEMENTAIRE = "etat_complementaire"
PIECE_JUSTIFICATIF_PAIEMENT = "justificatif_paiement"

TOUTES_FORMES = frozenset({"SNC", "SARL", "SA", "SCS", "SCA"})
FORMES_RAPPORT_CAC = frozenset({"SCA"})


@dataclass(frozen=True)
class PieceGreffe:
    """Piece du dossier de depot (catalogue officiel, § 3.5 du CDC)."""

    code: str
    libelle: str
    source: str
    formes_obligatoires: frozenset[str] = field(default_factory=frozenset)
    formes_conditionnelles: frozenset[str] = field(default_factory=frozenset)
    commentaire: str = ""

    def obligatoire_pour(self, forme: str) -> bool:
        """Vrai si la piece est exigee pour cette forme juridique."""
        return forme.upper() in self.formes_obligatoires

    def conditionnelle_pour(self, forme: str) -> bool:
        """Vrai si la piece n'est exigee que si un CAC est nomme (non bloquant)."""
        return forme.upper() in self.formes_conditionnelles


# `libelle` : libelles officiels, alignes sur le bordereau PDF existant
# (`pdf_documents.PIECES_GREFFE_COMMUNES` / `PIECES_GREFFE_PAR_FORME`) ; le test
# `test_catalogue_pieces_coherent_avec_le_bordereau` verifie cette coherence,
# afin qu'aucun des deux referentiels ne derive en silence.
CATALOGUE_PIECES: tuple[PieceGreffe, ...] = (
    PieceGreffe(
        code=PIECE_ETATS_SYNTHESE,
        libelle="Etats de synthese (bilan, CPC, ESG, ETIC) certifies conformes",
        source=SOURCE_GENERE,
        formes_obligatoires=TOUTES_FORMES,
        commentaire="Genere par le module etats de synthese (P1.1), PDF <= 10 Mo.",
    ),
    PieceGreffe(
        code=PIECE_TABLEAU_FINANCEMENT,
        libelle="Tableau de financement",
        source=SOURCE_GENERE,
        commentaire="Selon les seuils du CGNC (societes depassant les seuils).",
    ),
    PieceGreffe(
        code=PIECE_RAPPORT_GESTION,
        libelle="Rapport de gestion",
        source=SOURCE_TELEVERSE,
        formes_obligatoires=TOUTES_FORMES,
        commentaire="Document etabli par les dirigeants, puis televerse.",
    ),
    PieceGreffe(
        code=PIECE_RAPPORT_CAC,
        libelle="Rapport du ou des commissaires aux comptes",
        source=SOURCE_TELEVERSE,
        formes_obligatoires=FORMES_RAPPORT_CAC,
        formes_conditionnelles=frozenset({"SA", "SARL", "SCS"}),
        commentaire="Piece externe : obligatoire si un CAC est nomme (SA/SCA).",
    ),
    PieceGreffe(
        code=PIECE_PV_AG,
        libelle=(
            "Proces-verbal de l'assemblee generale d'approbation et texte "
            "des resolutions"
        ),
        source=SOURCE_TELEVERSE,
        formes_obligatoires=TOUTES_FORMES,
        commentaire="A televerser apres l'assemblee (loi 5-96, art. 10).",
    ),
    PieceGreffe(
        code=PIECE_ETAT_COMPLEMENTAIRE,
        libelle="Etat de synthese / declaration complementaire du portail",
        source=SOURCE_GENERE,
        formes_obligatoires=TOUTES_FORMES,
        commentaire="Bordereau recapitulatif du dossier, genere par le module greffe.",
    ),
    PieceGreffe(
        code=PIECE_JUSTIFICATIF_PAIEMENT,
        libelle="Justificatif de paiement des taxes",
        source=SOURCE_PAIEMENT,
        formes_obligatoires=TOUTES_FORMES,
        commentaire="Justifie des qu'un paiement est enregistre (ou scan televerse).",
    ),
)
PIECES_PAR_CODE = {piece.code: piece for piece in CATALOGUE_PIECES}


def pieces_obligatoires(forme_juridique: str | None) -> tuple[str, ...]:
    """Codes des pieces **obligatoires** pour une forme juridique.

    Forme inconnue : le socle commun a toutes les formes est exige (prudence).
    """
    forme = (forme_juridique or "").upper()
    if not forme:
        return tuple(
            p.code for p in CATALOGUE_PIECES if p.formes_obligatoires == TOUTES_FORMES
        )
    return tuple(p.code for p in CATALOGUE_PIECES if p.obligatoire_pour(forme))


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
class GreffeDeposit(Base):
    """Dossier de depot des etats de synthese d'un exercice (P1.5)."""

    __tablename__ = "greffe_deposits"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "exercice", name="uq_greffe_deposits_company_exercice"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    fiscal_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("fiscal_years.id", ondelete="SET NULL"), default=None
    )
    exercice: Mapped[int] = mapped_column(Integer, index=True)
    forme_juridique: Mapped[str] = mapped_column(String(10), default="SARL")
    statut: Mapped[str] = mapped_column(String(20), default=ETAT_NOUVEAU, index=True)

    # Delais legaux (loi 5-96 art. 10 ; guide de ministere, novembre 2025).
    date_ag: Mapped[date | None] = mapped_column(Date, default=None)
    date_limite_depot: Mapped[date] = mapped_column(Date)

    # Etapes du depot au portail.
    date_soumission: Mapped[date | None] = mapped_column(Date, default=None)
    date_approbation: Mapped[date | None] = mapped_column(Date, default=None)
    date_limite_paiement: Mapped[date | None] = mapped_column(Date, default=None)
    date_depot: Mapped[date | None] = mapped_column(Date, default=None)

    # Taxes du depot (paiement en ligne CMI) et amende hors delai.
    montant_taxes: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amende_montant: Mapped[Decimal | None] = mapped_column(Money, default=None)
    amende_motif: Mapped[str | None] = mapped_column(Text, default=None)

    # Certificat de depot (preuve legale archivee, conservation 10 ans).
    reference_certificat: Mapped[str | None] = mapped_column(String(80), default=None)
    certificat_path: Mapped[str | None] = mapped_column(String(255), default=None)
    certificat_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    certificat_nom: Mapped[str | None] = mapped_column(String(180), default=None)
    certificat_depose_le: Mapped[datetime | None] = mapped_column(
        DateTime, default=None
    )

    dernier_motif: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["GreffeDocument"]] = relationship(
        back_populates="deposit", cascade="all, delete-orphan"
    )
    paiements: Mapped[list["GreffePayment"]] = relationship(
        back_populates="deposit", cascade="all, delete-orphan"
    )
    events: Mapped[list["GreffeEvent"]] = relationship(
        back_populates="deposit", cascade="all, delete-orphan"
    )

    @property
    def etat_libelle(self) -> str:
        """Libelle francais de l'etat du portail."""
        return GREFFE_ETAT_LABELS.get(self.statut, self.statut)

    @property
    def est_terminal(self) -> bool:
        """Vrai si le dossier ne peut plus etre modifie (Annule / Depose)."""
        return self.statut in GREFFE_ETATS_TERMINAUX

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return (
            f"<GreffeDeposit exercice={self.exercice} statut={self.statut} "
            f"forme={self.forme_juridique}>"
        )


class GreffeDocument(Base):
    """Piece PDF du dossier de depot (une piece obligatoire = une ligne)."""

    __tablename__ = "greffe_documents"
    __table_args__ = (
        UniqueConstraint(
            "deposit_id", "piece_code", name="uq_greffe_documents_deposit_piece"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    deposit_id: Mapped[int] = mapped_column(
        ForeignKey("greffe_deposits.id", ondelete="CASCADE"), index=True
    )
    piece_code: Mapped[str] = mapped_column(String(40), index=True)
    libelle: Mapped[str] = mapped_column(String(255))
    nom_fichier: Mapped[str] = mapped_column(String(180))
    chemin: Mapped[str] = mapped_column(String(255))
    type_mime: Mapped[str] = mapped_column(String(60), default="application/pdf")
    taille_octets: Mapped[int] = mapped_column(Integer, default=0)
    hash_sha256: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(20), default=SOURCE_TELEVERSE)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    deposit: Mapped[GreffeDeposit] = relationship(back_populates="documents")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<GreffeDocument piece={self.piece_code} taille={self.taille_octets}>"


class GreffePayment(Base):
    """Paiement des taxes du depot (paiement en ligne CMI apres approbation)."""

    __tablename__ = "greffe_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    deposit_id: Mapped[int] = mapped_column(
        ForeignKey("greffe_deposits.id", ondelete="CASCADE"), index=True
    )
    montant: Mapped[Decimal] = mapped_column(Money)
    date_paiement: Mapped[date] = mapped_column(Date)
    moyen: Mapped[str] = mapped_column(String(20), default="cmi")
    reference: Mapped[str | None] = mapped_column(String(80), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    deposit: Mapped[GreffeDeposit] = relationship(back_populates="paiements")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<GreffePayment montant={self.montant} moyen={self.moyen}>"


class GreffeEvent(Base):
    """Transition d'etat d'un dossier (journal des 7 etats du portail)."""

    __tablename__ = "greffe_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    deposit_id: Mapped[int] = mapped_column(
        ForeignKey("greffe_deposits.id", ondelete="CASCADE"), index=True
    )
    etat_avant: Mapped[str] = mapped_column(String(20))
    etat_apres: Mapped[str] = mapped_column(String(20))
    date_evenement: Mapped[date] = mapped_column(Date)
    motif: Mapped[str | None] = mapped_column(Text, default=None)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    deposit: Mapped[GreffeDeposit] = relationship(back_populates="events")

    def __repr__(self) -> str:  # pragma: no cover - confort de debogage
        return f"<GreffeEvent {self.etat_avant} -> {self.etat_apres}>"



