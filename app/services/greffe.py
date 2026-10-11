"""Depot au greffe du tribunal des etats de synthese (P1.5).

Rend **operationnelle et tracable** l'obligation legale de depot annuel des
etats de synthese au greffe du tribunal via le portail du Ministere de la
Justice : checklist des pieces, controles prealables, cycle de vie des **7 etats**
du portail, alertes de delais, archive ZIP du dossier et **archivage du
certificat** de depot.

References normatives
---------------------
- **Loi 5-96** (SNC, SCS, SCA, SARL) : art. 10 — approbation des etats par
  l'assemblee **dans les six mois** de la cloture ; art. 93 — publicite par
  depot de pieces au **greffe du tribunal du lieu du siege social**.
- **Loi 17-95** (SA) : art. 14 — depot au greffe du tribunal du registre du
  commerce.
- **Guide officiel « Depot electronique des etats de synthese »** (Ministere de
  la Justice, **novembre 2025**) : portail `https://depotbilan.justice.gov.ma`,
  pieces **PDF <= 10 Mo**, paiement des taxes **sous 3 jours** apres approbation
  (au-dela : **rejet automatique**), certificat signe electroniquement.

Controles bloquants (CDC § 3.5)
-------------------------------
1. exercice **clos** (on ne depose pas des comptes provisoires) ;
2. **bilan equilibre** (etats de synthese generes sans anomalie) ;
3. chaque piece **PDF <= 10 Mo** et **checklist complete** pour la forme
   juridique ;
4. **date d'AG <= 6 mois** de la cloture (loi 5-96 art. 10) : sinon le depot
   sera « Amender » (amende) — avertissement, bloquant a la soumission ;
5. **RC / IF / ICE** renseignes et conformes (le portail exige le n° de
   registre de commerce) ;
6. **unicite par exercice** : aucune re-soumission d'une ligne « Depose ».

Aucun solde n'est duplique : le montant paye d'un dossier est **calcule** par
somme de ses paiements (`solde_taxes`), et un dossier « Depose » verrouille
l'exercice (P1.6) pour figer les etats deposes.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.config import settings
from app.core.rates_ma import money
from app.models import (
    Company,
    Entry,
    GreffeDeposit,
    GreffeDocument,
    GreffeEvent,
    GreffePayment,
)
from app.models.greffe import (
    CATALOGUE_PIECES,
    DELAI_AG_MOIS,
    DELAI_PAIEMENT_JOURS,
    ETAT_AMENDER,
    ETAT_ANNULE,
    ETAT_APPROUVE,
    ETAT_DEPOSE,
    ETAT_EN_COURS,
    ETAT_NOUVEAU,
    ETAT_REJETE,
    GREFFE_ETATS,
    GREFFE_ETAT_LABELS,
    GREFFE_MOYENS,
    GREFFE_MOYEN_LABELS,
    GREFFE_TRANSITIONS,
    PIECE_ETAT_COMPLEMENTAIRE,
    PIECE_ETATS_SYNTHESE,
    PIECE_JUSTIFICATIF_PAIEMENT,
    PIECE_PV_AG,
    PIECE_RAPPORT_CAC,
    PIECE_RAPPORT_GESTION,
    PIECE_TABLEAU_FINANCEMENT,
    PIECES_PAR_CODE,
    SOURCE_GENERE,
    SOURCE_PAIEMENT,
    SOURCE_TELEVERSE,
    PieceGreffe,
    pieces_obligatoires,
)
from app.services.accounting import create_entry, get_fiscal_year, get_journal
from app.services.etats_synthese import exercice_clos
from app.services.identifiers import (
    ComplianceError,
    validate_fiscal_id,
    validate_ice,
)
from app.services.pdf import (
    TAILLE_MAX_GREFFE,
    Colonne,
    Document,
    PdfError,
    Tableau,
    controle_taille_pdf,
    rendre_pdf,
)
from app.services.period_locks import PeriodLockError, verrouiller_periode
from app.services.reporting import balance_sheet, year_bounds

# Provision de l'amende pour depot hors delai (CGNC) : dotation 6195 /
# provision 1515 « Provisions pour amendes, double droits, penalites ».
COMPTE_DOTATION_AMENDE = "6195"
COMPTE_PROVISION_AMENDE = "1515"
JOURNAL_GREFFE = "OD"
SOURCE_ECRITURE = "greffe"
# Pieces exigees seulement au **depot final** : le justificatif de paiement des
# taxes n'existe qu'apres approbation du dossier (guide de novembre 2025).
PIECES_DIFFEREES: tuple[str, ...] = (PIECE_JUSTIFICATIF_PAIEMENT,)
URL_PORTAIL = "https://depotbilan.justice.gov.ma"
FORMES_SUPPORTEES = ("SNC", "SARL", "SA", "SCS", "SCA")


class GreffeError(ValueError):
    """Erreur de gestion du depot au greffe (controle bloquant ou saisie invalide)."""


# ---------------------------------------------------------------------------
# Helpers : dates, fichiers, empreintes
# ---------------------------------------------------------------------------
def ajouter_mois(jour: date, mois: int) -> date:
    """Ajoute des mois a une date (jour ramene a la fin du mois si besoin)."""
    from calendar import monthrange

    total = jour.month - 1 + mois
    annee = jour.year + total // 12
    mois_cible = total % 12 + 1
    dernier = monthrange(annee, mois_cible)[1]
    return date(annee, mois_cible, min(jour.day, dernier))


def date_limite_ag(cloture: date) -> date:
    """Date limite de l'assemblee d'approbation : cloture + 6 mois (loi 5-96)."""
    return ajouter_mois(cloture, DELAI_AG_MOIS)


def date_limite_paiement(date_approbation: date) -> date:
    """Date limite de paiement des taxes : approbation + 3 jours (guide 2025)."""
    return date_approbation + timedelta(days=DELAI_PAIEMENT_JOURS)


def nom_fichier_securise(nom: str | None, *, defaut: str = "piece.pdf") -> str:
    """Nom de fichier sur (pas de chemin, extension `.pdf`).

    Protege l'archivage contre toute traversee de repertoire : seul le nom de
    base est conserve et les caracteres non surs sont remplaces.
    """
    base = Path(str(nom or "")).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    if not base:
        base = defaut
    tige, point, _extension = base.rpartition(".")
    base = f"{tige if point else base}.pdf"
    return base[:120]


def empreinte_sha256(contenu: bytes) -> str:
    """Empreinte SHA-256 d'un contenu binaire (integrite des pieces et certificats)."""
    return hashlib.sha256(contenu).hexdigest()


def racine_stockage() -> Path:
    """Racine des pieces du greffe (`settings.greffe_dir`, sinon `media/greffe`)."""
    return Path(settings.greffe_racine)


def verifier_piece_pdf(nom_fichier: str | None, contenu: bytes) -> int:
    """Controle qu'une piece est un **PDF de 10 Mo maximum** ; retourne sa taille.

    Le portail n'accepte que des PDF : un fichier d'un autre type ou trop lourd
    est refuse **avant** tout envoi (controle bloquant n° 3 du CDC).
    """
    if not contenu:
        raise GreffeError(f"La piece « {nom_fichier or 'sans nom'} » est vide.")
    if not contenu.startswith(b"%PDF"):
        raise GreffeError(
            f"La piece « {nom_fichier or 'sans nom'} » n'est pas un fichier PDF : "
            "le portail du greffe n'accepte que des PDF."
        )
    try:
        return controle_taille_pdf(contenu, TAILLE_MAX_GREFFE)
    except PdfError as exc:
        raise GreffeError(
            f"La piece « {nom_fichier or 'sans nom'} » depasse la limite de 10 Mo "
            f"du portail du greffe : {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Contenu des pieces (P1 greffe) : un PDF « valide » peut etre **vide**, une
# **page blanche** ou sans contenu metier (constat de recette : deux pieces de
# 193 octets acceptees). Le controle de contenu est desormais **bloquant**.
# ---------------------------------------------------------------------------
CARACTERES_MIN_PAGE = 30          # en dessous : page consideree blanche
CARACTERES_MIN_PIECE = 120        # contenu global insuffisant
CARACTERES_MIN_METIER = 400       # pieces substantielles (PV d'AG, rapport de gestion)
PIECES_SUBSTANTIELLES = (PIECE_PV_AG, PIECE_RAPPORT_GESTION)
# Mots-cles **metier** attendus (au moins `minimum` presents) : un document
# administratif ne peut pas se reduire a un titre ou a une page blanche.
MOTS_CLES_PIECES: dict[str, tuple[tuple[str, ...], int]] = {
    PIECE_PV_AG: (
        (
            "assemblee generale",
            "associé unique",
            "associe unique",
            "resolutions",
            "approbation des comptes",
            "affectation du resultat",
        ),
        3,
    ),
    PIECE_RAPPORT_GESTION: (
        (
            "rapport de gestion",
            "exercice",
            "resultat",
            "activite",
            "perspectives",
            "affectation",
        ),
        4,
    ),
}

# Toutes les mentions metier surveillees, **toutes pieces confondues** : l'analyse
# seule (`analyser_piece_pdf`) ne connait pas le code de la piece et n'annoncait donc
# aucune mention (« 0 mention(s) metier ») meme pour un document valide. La liste
# specifique a la piece reste appliquee par `verifier_contenu_piece` (bloquant).
MOTS_CLES_TOUS: tuple[str, ...] = tuple(
    sorted({mot for mots, _ in MOTS_CLES_PIECES.values() for mot in mots})
)


@dataclass
class AnalysePiece:
    """Analyse **de contenu** d'une piece PDF (pages, texte, mots-cles metier)."""

    nb_pages: int
    caracteres: int
    pages_blanches: list[int]
    texte_normalise: str
    mots_cles_trouves: list[str]
    lisible: bool
    message_erreur: str | None = None

    @property
    def vide(self) -> bool:
        """Fichier illisible, sans page, ou **toutes** les pages blanches."""
        return (
            not self.lisible
            or self.nb_pages == 0
            or self.caracteres < CARACTERES_MIN_PAGE
            or len(self.pages_blanches) == self.nb_pages
        )

    @property
    def contenu_insuffisant(self) -> bool:
        return self.lisible and self.caracteres < CARACTERES_MIN_PIECE

    @property
    def valide(self) -> bool:
        return self.lisible and not self.vide and not self.contenu_insuffisant

    def resume(self) -> str:
        if not self.lisible:
            return f"PDF illisible ({self.message_erreur or 'erreur de lecture'})"
        return (
            f"{self.nb_pages} page(s), {self.caracteres} caractere(s) de texte, "
            f"{len(self.pages_blanches)} page(s) blanche(s), "
            f"{len(self.mots_cles_trouves)} mention(s) metier"
        )


def analyser_piece_pdf(contenu: bytes) -> AnalysePiece:
    """Analyse le **contenu** d'une piece PDF : pages, texte et normalisation.

    Ne leve pas d'exception : retourne une analyse exploitable pour les controles
    et pour l'affichage (l'utilisateur voit **pourquoi** une piece est refusee).
    """
    try:
        from io import BytesIO

        from pypdf import PdfReader

        lecteur = PdfReader(BytesIO(contenu))
        pages = list(lecteur.pages)
        textes = [(page.extract_text() or "") for page in pages]
    except Exception as exc:  # PDF corrompu, chiffre, illisible
        return AnalysePiece(
            nb_pages=0,
            caracteres=0,
            pages_blanches=[],
            texte_normalise="",
            mots_cles_trouves=[],
            lisible=False,
            message_erreur=f"{type(exc).__name__}: {exc}",
        )
    blanche = [
        index + 1
        for index, texte in enumerate(textes)
        if len(texte.strip()) < CARACTERES_MIN_PAGE
    ]
    complet = "\n".join(textes)
    normalise = _normaliser_texte(complet)
    return AnalysePiece(
        nb_pages=len(pages),
        caracteres=len(complet.strip()),
        pages_blanches=blanche,
        texte_normalise=normalise,
        mots_cles_trouves=[mot for mot in MOTS_CLES_TOUS if mot in normalise],
        lisible=True,
    )


def _normaliser_texte(texte: str) -> str:
    """Minuscules + suppression des accents (comparaison de mots-cles robuste)."""
    import unicodedata

    sans_accents = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texte)
        if not unicodedata.combining(caractere)
    )
    return " ".join(sans_accents.lower().split())


def verifier_contenu_piece(
    piece_code: str,
    nom_fichier: str | None,
    contenu: bytes,
    analyse: AnalysePiece | None = None,
) -> AnalysePiece:
    """Refuse une piece **vide, quasi vide ou sans contenu metier obligatoire**.

    Controles bloquants (constat de recette : deux PDF de 193 octets acceptes) :
    1. PDF illisible (corrompu, chiffre) ;
    2. aucune page, ou **toutes les pages blanches** ;
    3. texte extrait insuffisant (`CARACTERES_MIN_PIECE`) ;
    4. pieces **substantielles** (PV d'AG, rapport de gestion) : texte minimal
       `CARACTERES_MIN_METIER` **et** presence des **mots-cles metier** attendus.
    """
    analyse = analyse or analyser_piece_pdf(contenu)
    nom = nom_fichier or f"{piece_code}.pdf"
    if not analyse.lisible:
        raise GreffeError(
            f"La piece « {nom} » est refusee : le PDF est illisible "
            f"({analyse.message_erreur})."
        )
    if analyse.nb_pages == 0:
        raise GreffeError(f"La piece « {nom} » est refusee : le PDF ne contient aucune page.")
    if len(analyse.pages_blanches) == analyse.nb_pages:
        raise GreffeError(
            f"La piece « {nom} » est refusee : **page(s) blanche(s)** ({analyse.nb_pages} "
            f"page(s), {analyse.caracteres} caractere(s) de texte extraits). Le portail du "
            "greffe exige un document renseigne."
        )
    if analyse.contenu_insuffisant:
        raise GreffeError(
            f"La piece « {nom} » est refusee : contenu insuffisant "
            f"({analyse.caracteres} caracteres de texte, minimum {CARACTERES_MIN_PIECE})."
        )
    if piece_code in PIECES_SUBSTANTIELLES:
        if analyse.caracteres < CARACTERES_MIN_METIER:
            raise GreffeError(
                f"La piece « {nom} » est refusee : document quasi vide "
                f"({analyse.caracteres} caracteres, minimum {CARACTERES_MIN_METIER} pour une "
                "piece substantielle). Generez le document depuis l'application."
            )
        mots_cles, minimum = MOTS_CLES_PIECES[piece_code]
        trouves = [mot for mot in mots_cles if mot in analyse.texte_normalise]
        if len(trouves) < minimum:
            raise GreffeError(
                f"La piece « {nom} » est refusee : contenu metier obligatoire absent "
                f"({len(trouves)}/{minimum} mentions attendues). Generez le document depuis "
                "l'application (rapport de gestion / PV d'AG alimentes par l'exercice)."
            )
        analyse.mots_cles_trouves = trouves
    return analyse


def taille_lisible(taille: int | None) -> str:
    """Taille en octets formatee (Ko / Mo) pour l'ecran et le bordereau."""
    octets = int(taille or 0)
    if octets >= 1024 * 1024:
        return f"{octets / (1024 * 1024):.2f} Mo"
    if octets >= 1024:
        return f"{octets / 1024:.1f} Ko"
    return f"{octets} octets"


# ---------------------------------------------------------------------------
# Dossier de depot
# ---------------------------------------------------------------------------
def controle_identite(company: Company) -> list[str]:
    """Identifiants exiges par le portail (controle bloquant n° 5 du CDC).

    Le portail selectionne le dossier par le **n° de registre de commerce** ;
    l'ICE et l'IF doivent etre valides pour que les etats deposes soient
    rattaches sans ambiguite.
    """
    problemes: list[str] = []
    if not (company.rc or "").strip():
        problemes.append("n° de registre de commerce (RC) manquant")
    try:
        validate_fiscal_id(company.fiscal_id, required=True)
    except ComplianceError as exc:
        problemes.append(f"identifiant fiscal (IF) : {exc}")
    try:
        validate_ice(company.ice, required=True)
    except ComplianceError as exc:
        problemes.append(f"ICE : {exc}")
    return problemes


def creer_depot(
    db: Session,
    *,
    company: Company,
    exercice: int,
    user_id: int | None = None,
    forme_juridique: str | None = None,
    date_ag: date | None = None,
    montant_taxes: Decimal | str | None = None,
    notes: str | None = None,
) -> GreffeDeposit:
    """Cree le dossier de depot d'un exercice (une ligne par exercice).

    La **date limite de depot** (assemblee dans les 6 mois de la cloture,
    loi 5-96 art. 10) est calculee depuis la cloture de l'exercice. L'unicite
    par exercice est verifiee ici **et** par la base : apres un rejet ou une
    annulation, on reprend la meme ligne (le journal des etats conserve tout).
    """
    forme = (forme_juridique or company.legal_form or "").upper().strip()
    # L'unicite par exercice est verifiee **avant** la forme : le conflit de
    # dossier (message le plus utile) prime sur un parametrage incomplet.
    exercice_row = get_fiscal_year(db, company.id, exercice)
    existant = depot_par_exercice(db, company.id, exercice)
    if existant is not None:
        raise GreffeError(
            f"Un dossier de depot existe deja pour l'exercice {exercice} "
            f"(statut « {existant.etat_libelle} », cree le "
            f"{existant.created_at.strftime('%d/%m/%Y') if existant.created_at else '—'}) : "
            "utilisez le suivi du dossier (le portail n'accepte qu'un depot par exercice)."
        )
    if forme not in FORMES_SUPPORTEES:
        raise GreffeError(
            f"Forme juridique « {forme or 'non renseignee'} » non supportee : "
            f"formes prises en charge {', '.join(FORMES_SUPPORTEES)} "
            "(loi 5-96 : SNC, SARL, SCS, SCA ; loi 17-95 : SA)."
        )
    fin_exercice = exercice_row.end_date or year_bounds(exercice)[1]
    depot = GreffeDeposit(
        company_id=company.id,
        fiscal_year_id=exercice_row.id,
        exercice=exercice,
        forme_juridique=forme,
        statut=ETAT_NOUVEAU,
        date_ag=date_ag,
        date_limite_depot=date_limite_ag(fin_exercice),
        montant_taxes=money(Decimal(str(montant_taxes or "0"))),
        notes=notes,
        created_by=user_id,
    )
    db.add(depot)
    db.flush()
    log_action(
        db,
        action="GREFFE_DEPOT_CREATED",
        entity="GreffeDeposit",
        entity_id=depot.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "exercice": exercice,
            "forme_juridique": forme,
            "date_limite_depot": depot.date_limite_depot.isoformat(),
            "ag_hors_delai": bool(date_ag and date_ag > depot.date_limite_depot),
        },
    )
    return depot


def get_depot(db: Session, company_id: int, deposit_id: int) -> GreffeDeposit:
    """Dossier de depot d'un dossier (leve si absent : cloisonnement par societe)."""
    depot = db.execute(
        select(GreffeDeposit).where(
            GreffeDeposit.id == deposit_id, GreffeDeposit.company_id == company_id
        )
    ).scalar_one_or_none()
    if depot is None:
        raise GreffeError(f"Dossier de depot {deposit_id} introuvable.")
    return depot


def depot_par_exercice(
    db: Session, company_id: int, exercice: int
) -> GreffeDeposit | None:
    """Dossier de depot de l'exercice (None si aucun)."""
    return db.execute(
        select(GreffeDeposit).where(
            GreffeDeposit.company_id == company_id,
            GreffeDeposit.exercice == exercice,
        )
    ).scalar_one_or_none()


def list_depots(
    db: Session, company_id: int, *, exercice: int | None = None
) -> list[GreffeDeposit]:
    """Dossiers de depot d'une societe (filtre par exercice si fourni)."""
    requete = select(GreffeDeposit).where(GreffeDeposit.company_id == company_id)
    if exercice is not None:
        requete = requete.where(GreffeDeposit.exercice == exercice)
    return list(
        db.execute(requete.order_by(GreffeDeposit.exercice.desc())).scalars().all()
    )


def total_paye(db: Session, deposit: GreffeDeposit) -> Decimal:
    """Somme des paiements enregistres (aucun solde n'est stocke en double)."""
    lignes = db.execute(
        select(GreffePayment.montant).where(GreffePayment.deposit_id == deposit.id)
    ).scalars()
    return money(sum((Decimal(str(m)) for m in lignes), Decimal("0")))


def solde_taxes(db: Session, deposit: GreffeDeposit) -> Decimal:
    """Reste a payer du dossier (0,00 si les taxes sont reglees ou inconnues)."""
    if deposit.montant_taxes is None or deposit.montant_taxes <= 0:
        return money(Decimal("0"))
    reste = money(deposit.montant_taxes - total_paye(db, deposit))
    return reste if reste > 0 else money(Decimal("0"))


# ---------------------------------------------------------------------------
# Pieces du dossier (checklist, televersement, generation)
# ---------------------------------------------------------------------------
def _documents_par_piece(
    db: Session, deposit: GreffeDeposit
) -> dict[str, GreffeDocument]:
    """Pieces deja archivees, indexees par code de piece (lecture fraiche en base).

    La lecture passe par la base et non par la collection `deposit.documents` :
    une piece ajoutee dans la meme transaction (generation automatique, import)
    doit etre vue par la checklist, les controles et l'assembleur d'archive.
    """
    lignes = db.execute(
        select(GreffeDocument).where(GreffeDocument.deposit_id == deposit.id)
    ).scalars()
    return {document.piece_code: document for document in lignes}


def _paiement_enregistre(db: Session, deposit: GreffeDeposit) -> bool:
    """Vrai si au moins un paiement (ou un scan du justificatif) existe."""
    if total_paye(db, deposit) > 0:
        return True
    return any(
        doc.piece_code == PIECE_JUSTIFICATIF_PAIEMENT for doc in deposit.documents
    )


def checklist(db: Session, deposit: GreffeDeposit) -> list[dict]:
    """Checklist des pieces du dossier pour la forme juridique (CDC § 3.5).

    Chaque ligne indique si la piece est **obligatoire**, **conditionnelle**
    (commissaire aux comptes nomme) ou facultative, si elle est **fournie**,
    son nom de fichier, sa **taille** et son **empreinte SHA-256**.
    """
    forme = (deposit.forme_juridique or "").upper()
    documents = _documents_par_piece(db, deposit)
    paiement = _paiement_enregistre(db, deposit)
    lignes: list[dict] = []
    for piece in CATALOGUE_PIECES:
        document = documents.get(piece.code)
        obligatoire = piece.obligatoire_pour(forme)
        conditionnelle = piece.conditionnelle_pour(forme)
        if piece.source == SOURCE_PAIEMENT and paiement and document is None:
            lignes.append(
                {
                    "code": piece.code,
                    "libelle": piece.libelle,
                    "source": piece.source,
                    "obligatoire": obligatoire,
                    "conditionnelle": conditionnelle,
                    "fournie": True,
                    "par_paiement": True,
                    "document_id": None,
                    "nom_fichier": None,
                    "taille_octets": 0,
                    "taille_lisible": None,
                    "hash_sha256": None,
                    "statut": "fournie",
                    "commentaire": piece.commentaire,
                }
            )
            continue
        fournie = document is not None
        analyse: AnalysePiece | None = None
        anomalie: str | None = None
        if fournie:
            # Le statut « fournie » est **recalcule depuis le contenu archive**
            # (P1 greffe) : une piece vide, blanche ou sans contenu metier ne peut
            # pas etre presentee comme fournie, meme si elle a ete acceptee avant
            # le durcissement des controles.
            try:
                analyse = analyser_piece_pdf(lire_document(document))  # type: ignore[arg-type]
            except GreffeError as exc:
                anomalie = str(exc)
            if anomalie is None and analyse is not None:
                try:
                    verifier_contenu_piece(piece.code, document.nom_fichier, b"", analyse)
                except GreffeError as exc:
                    anomalie = str(exc)
            if anomalie is not None:
                fournie = False
                statut = "invalide"
            else:
                statut = "fournie"
        elif obligatoire:
            statut = "manquante"
        elif conditionnelle:
            statut = "conditionnelle"
        else:
            statut = "facultative"
        lignes.append(
            {
                "code": piece.code,
                "libelle": piece.libelle,
                "source": piece.source,
                "obligatoire": obligatoire,
                "conditionnelle": conditionnelle,
                "fournie": fournie,
                "par_paiement": False,
                "document_id": None if document is None else document.id,
                "nom_fichier": None if document is None else document.nom_fichier,
                "taille_octets": 0 if document is None else document.taille_octets,
                "taille_lisible": (
                    None if document is None else taille_lisible(document.taille_octets)
                ),
                "hash_sha256": None if document is None else document.hash_sha256,
                "statut": statut,
                "anomalie": anomalie,
                "analyse": None if analyse is None else analyse.resume(),
                "commentaire": piece.commentaire,
            }
        )
    return lignes


def pieces_manquantes(
    db: Session, deposit: GreffeDeposit, *, pour_depot_final: bool = False
) -> list[dict]:
    """Pieces obligatoires non fournies (source des controles bloquants).

    Le **justificatif de paiement des taxes** (`PIECES_DIFFEREES`) n'existe
    qu'apres approbation : il est donc exige pour le depot final, pas pour la
    soumission du dossier (le portail ouvre le paiement apres approbation).
    """
    return [
        ligne
        for ligne in checklist(db, deposit)
        if ligne["obligatoire"]
        and not ligne["fournie"]
        and (pour_depot_final or ligne["code"] not in PIECES_DIFFEREES)
    ]


def lire_document(document: GreffeDocument) -> bytes:
    """Relit le contenu archive d'une piece (leve si le fichier a disparu)."""
    chemin = racine_stockage() / document.chemin
    if not chemin.exists():
        raise GreffeError(
            f"Le fichier archive de la piece « {document.nom_fichier} » est introuvable "
            f"({chemin}). Re-televersez la piece avant de l'envoyer au greffe."
        )
    return chemin.read_bytes()


def ajouter_piece(
    db: Session,
    deposit: GreffeDeposit,
    *,
    piece_code: str,
    nom_fichier: str | None,
    contenu: bytes,
    user_id: int | None = None,
    source: str = SOURCE_TELEVERSE,
    remplacer: bool = True,
) -> GreffeDocument:
    """Archive une piece du dossier : controle **PDF / 10 Mo**, empreinte, disque.

    Les fichiers sont stockes **hors base** (un PDF peut atteindre 10 Mo), sous
    `settings.greffe_racine`, avec le **SHA-256** conserve en base : l'integrite
    d'une piece deja deposee peut donc etre re-verifiee.
    """
    if deposit.statut == ETAT_DEPOSE:
        raise GreffeError(
            "Le dossier est « Déposé » : les pièces transmises au greffe ne peuvent "
            "plus être modifiées (unicité du dépôt par exercice)."
        )
    piece: PieceGreffe | None = PIECES_PAR_CODE.get(piece_code)
    if piece is None:
        raise GreffeError(
            f"Code de pièce inconnu : « {piece_code} » "
            f"(codes valides : {', '.join(PIECES_PAR_CODE)})."
        )
    nom = nom_fichier_securise(nom_fichier, defaut=f"{piece_code}.pdf")
    taille = verifier_piece_pdf(nom, contenu)
    # Contenu **obligatoire** (P1 greffe) : refus d'un PDF vide, d'une page
    # blanche ou d'un document sans contenu metier (constat de recette : deux
    # pieces de 193 octets acceptees comme valides).
    analyse = verifier_contenu_piece(piece_code, nom, contenu)
    hash_sha256 = empreinte_sha256(contenu)
    # Doublons : le **meme contenu** ne peut pas servir deux pieces differentes.
    for autre_code, autre in _documents_par_piece(db, deposit).items():
        if autre_code != piece_code and autre.hash_sha256 == hash_sha256:
            raise GreffeError(
                f"Contenu identique a la piece « {autre.libelle} » ({autre_code}) : le meme "
                "fichier ne peut pas servir deux pieces differentes du dossier."
            )
    existant = _documents_par_piece(db, deposit).get(piece_code)
    if existant is not None and not remplacer:
        raise GreffeError(
            f"La pièce « {piece.libelle} » est déjà fournie "
            f"({existant.nom_fichier}). Supprimez-la avant de la remplacer."
        )
    chemin_relatif = f"{deposit.company_id}/{deposit.id}/{piece_code}_{nom}"
    chemin = racine_stockage() / chemin_relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    if existant is not None:
        if existant.chemin != chemin_relatif:
            ancien = racine_stockage() / existant.chemin
            if ancien.exists():  # pragma: no cover - nettoyage de la version remplacee
                ancien.unlink()
        document = existant
        document.nom_fichier = nom
        document.chemin = chemin_relatif
        document.taille_octets = taille
        document.hash_sha256 = hash_sha256
        document.source = source
        document.libelle = piece.libelle
        document.created_by = user_id
    else:
        document = GreffeDocument(
            deposit_id=deposit.id,
            piece_code=piece_code,
            libelle=piece.libelle,
            nom_fichier=nom,
            chemin=chemin_relatif,
            taille_octets=taille,
            hash_sha256=hash_sha256,
            source=source,
            created_by=user_id,
        )
        db.add(document)
    db.flush()
    log_action(
        db,
        action="GREFFE_PIECE_ADDED",
        entity="GreffeDocument",
        entity_id=document.id,
        user_id=user_id,
        company_id=deposit.company_id,
        payload={
            "depot": deposit.id,
            "piece": piece_code,
            "nom_fichier": nom,
            "taille_octets": taille,
            "hash_sha256": hash_sha256,
            "source": source,
        },
    )
    return document


def supprimer_piece(
    db: Session,
    deposit: GreffeDeposit,
    piece_code: str,
    *,
    user_id: int | None = None,
) -> bool:
    """Retire une piece du dossier (fichier + ligne) ; False si elle est absente."""
    if deposit.statut == ETAT_DEPOSE:
        raise GreffeError(
            "Le dossier est « Déposé » : les pièces transmises au greffe sont figées."
        )
    document = _documents_par_piece(db, deposit).get(piece_code)
    if document is None:
        return False
    chemin = racine_stockage() / document.chemin
    document_id = document.id
    db.delete(document)
    db.flush()
    if chemin.exists():
        chemin.unlink()
    log_action(
        db,
        action="GREFFE_PIECE_REMOVED",
        entity="GreffeDocument",
        entity_id=document_id,
        user_id=user_id,
        company_id=deposit.company_id,
        payload={"depot": deposit.id, "piece": piece_code},
    )
    return True


def fusionner_pdfs(parties: list[bytes]) -> bytes:
    """Assemble plusieurs PDF en un seul (pieces du dossier de depot).

    Le fichier obtenu repasse par le controle de taille (10 Mo) : la contrainte
    du portail s'applique **a chaque fichier transmis**, y compris apres fusion.
    """
    try:
        from pypdf import PdfWriter  # noqa: PLC0415 - dependance optionnelle du poste
    except ImportError as exc:  # pragma: no cover - depend de l'environnement
        raise GreffeError(
            "La fusion des états de synthèse nécessite la bibliothèque « pypdf » "
            "(pip install pypdf)."
        ) from exc
    assembleur = PdfWriter()
    for contenu in parties:
        assembleur.append(BytesIO(contenu))
    sortie = BytesIO()
    assembleur.write(sortie)
    return sortie.getvalue()


def generer_pieces(
    db: Session,
    deposit: GreffeDeposit,
    *,
    company: Company,
    user_id: int | None = None,
    date_ag: date | None = None,
) -> dict:
    """Genere les pieces que Compta MA produit : etats de synthese, bordereau,
    **rapport de gestion** et **PV d'AG**.

    Les etats de synthese (bilan, CPC, ESG, ETIC — P1.1) sont fusionnes en un
    **seul PDF <= 10 Mo** conforme au portail ; le **bordereau recapitulatif**
    (etat complementaire de la demande) est ajoute comme seconde piece. Le
    **rapport de gestion** et le **proces-verbal d'assemblee generale** sont
    desormais **rediges par l'application** a partir des comptes de l'exercice
    (P1 greffe) : le PV exige une **date d'assemblee** (parametre `date_ag` ou
    date deja enregistree sur le dossier). Seul le **rapport du commissaire aux
    comptes**, s'il est nomme, reste a televerser.
    """
    if deposit.statut == ETAT_DEPOSE:
        raise GreffeError(
            "Le dossier est « Déposé » : les pièces générées ne peuvent plus être "
            "remplacées."
        )
    if date_ag is not None:
        # Date d'assemblee fournie : enregistree **avant** generation (traçabilite).
        deposit.date_ag = date_ag
    if deposit.date_ag is None:
        raise GreffeError(
            "La date de l'assemblée générale est obligatoire pour générer le PV d'AG "
            "(loi 5-96, art. 10) : renseignez la date d'AG du dossier avant de générer "
            "les pièces."
        )
    from app.services.pdf_documents import (  # noqa: PLC0415 - anti-cycle d'import
        pdf_bilan,
        pdf_cpc,
        pdf_esg,
        pdf_etic,
        pdf_pv_ag,
        pdf_rapport_gestion,
    )

    parties = [
        fonction(db, company, deposit.exercice)
        for fonction in (pdf_bilan, pdf_cpc, pdf_esg, pdf_etic)
    ]
    contenu_etats = fusionner_pdfs(parties)
    document_etats = ajouter_piece(
        db,
        deposit,
        piece_code=PIECE_ETATS_SYNTHESE,
        nom_fichier=f"Etats_synthese_{deposit.exercice}.pdf",
        contenu=contenu_etats,
        user_id=user_id,
        source=SOURCE_GENERE,
    )
    contenu_bordereau = pdf_recapitulatif_dossier(db, company, deposit)
    document_bordereau = ajouter_piece(
        db,
        deposit,
        piece_code=PIECE_ETAT_COMPLEMENTAIRE,
        nom_fichier=f"Bordereau_depot_greffe_{deposit.exercice}.pdf",
        contenu=contenu_bordereau,
        user_id=user_id,
        source=SOURCE_GENERE,
    )
    documents = [document_etats, document_bordereau]
    # P1 greffe : pieces **redigees par l'application** a partir de l'exercice.
    document_rapport = ajouter_piece(
        db,
        deposit,
        piece_code=PIECE_RAPPORT_GESTION,
        nom_fichier=f"Rapport_gestion_{deposit.exercice}.pdf",
        contenu=pdf_rapport_gestion(db, company, deposit.exercice),
        user_id=user_id,
        source=SOURCE_GENERE,
    )
    document_pv = ajouter_piece(
        db,
        deposit,
        piece_code=PIECE_PV_AG,
        nom_fichier=f"PV_AG_{deposit.exercice}.pdf",
        contenu=pdf_pv_ag(
            db,
            company,
            deposit.exercice,
            date_ag=deposit.date_ag,
            date_limite=deposit.date_limite_depot,
        ),
        user_id=user_id,
        source=SOURCE_GENERE,
    )
    documents.extend([document_rapport, document_pv])
    # Justificatif de paiement des taxes : attestation produite des qu'un
    # paiement existe (le scan du recu du portail peut la remplacer).
    if _paiement_enregistre(db, deposit):
        documents.append(
            ajouter_piece(
                db,
                deposit,
                piece_code=PIECE_JUSTIFICATIF_PAIEMENT,
                nom_fichier=f"Attestation_paiement_taxes_{deposit.exercice}.pdf",
                contenu=pdf_attestation_paiement(db, company, deposit),
                user_id=user_id,
                source=SOURCE_GENERE,
            )
        )
    log_action(
        db,
        action="GREFFE_PIECES_GENERATED",
        entity="GreffeDeposit",
        entity_id=deposit.id,
        user_id=user_id,
        company_id=deposit.company_id,
        payload={
            "exercice": deposit.exercice,
            "date_ag": deposit.date_ag.isoformat() if deposit.date_ag else None,
            "etats_synthese": document_etats.taille_octets,
            "bordereau": document_bordereau.taille_octets,
            "rapport_gestion": document_rapport.taille_octets,
            "pv_ag": document_pv.taille_octets,
        },
    )
    return {
        "depot": deposit,
        "documents": documents,
        "etats_synthese": document_etats,
        "bordereau": document_bordereau,
        "rapport_gestion": document_rapport,
        "pv_ag": document_pv,
        "taux_completude": taux_completude(db, deposit),
    }


def taux_completude(db: Session, deposit: GreffeDeposit) -> dict:
    """Avancement du dossier : pieces obligatoires fournies / exigees."""
    lignes = checklist(db, deposit)
    obligatoires = [ligne for ligne in lignes if ligne["obligatoire"]]
    manquantes = [ligne["libelle"] for ligne in obligatoires if not ligne["fournie"]]
    total = len(obligatoires)
    fournies = len(obligatoires) - len(manquantes)
    return {
        "nb_exigees": total,
        "nb_fournies": fournies,
        "ratio": (fournies / total) if total else 1.0,
        "complete": not manquantes,
        "manquantes": manquantes,
    }


def pdf_recapitulatif_dossier(
    db: Session, company: Company, deposit: GreffeDeposit
) -> bytes:
    """Bordereau recapitulatif du dossier (piece « etat complementaire »).

    Reprend l'identite du deposant, la **checklist des pieces** avec leur taille
    et leur **empreinte SHA-256**, les delais legaux, l'etat des taxes et le
    **journal des etats** du portail.
    """
    lignes_pieces = checklist(db, deposit)
    # Identite harmonisee (fiche societe) : import tardif pour eviter un cycle
    # `greffe` <-> `pdf_documents`.
    from app.services.pdf_documents import (  # noqa: PLC0415
        associe_unique,
        forme_juridique,
        siege_social,
    )

    statuts = {
        "fournie": "Fournie",
        "manquante": "A JOINDRE",
        "conditionnelle": "Si CAC nomme",
        "facultative": "Non exigee",
    }
    tableaux = [
        Tableau(
            titre="Identite du deposant",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Societe", company.name],
                # Identite **harmonisee** avec la fiche societe (forme, siege, qualite) :
                # le bordereau ne doit pas diverger du rapport de gestion ni du PV d'AG.
                [
                    "Forme juridique",
                    forme_juridique(company)
                    + (" (associe unique)" if associe_unique(company) else ""),
                ],
                [
                    "Qualite de l'assemblee",
                    "associe unique" if associe_unique(company) else "assemblee des associes",
                ],
                ["Siege social", siege_social(company)],
                ["Registre de commerce (exige par le portail)", str(company.rc or "-")],
                ["Identifiant fiscal (IF)", str(company.fiscal_id or "-")],
                ["ICE", str(company.ice or "-")],
                ["Portail de depot", URL_PORTAIL],
            ],
        ),
        Tableau(
            titre="Suivi du depot (7 etats du portail)",
            colonnes=(
                Colonne("Element", largeur=95),
                Colonne("Valeur", largeur=65, alignement="right"),
            ),
            lignes=[
                ["Exercice concerne", str(deposit.exercice)],
                ["Etat de la demande", deposit.etat_libelle],
                ["Date de l'assemblee generale", _date_fr(deposit.date_ag)],
                [
                    "Date limite d'AG et de depot (cloture + 6 mois)",
                    _date_fr(deposit.date_limite_depot),
                ],
                ["Soumission au portail", _date_fr(deposit.date_soumission)],
                ["Approbation du greffe", _date_fr(deposit.date_approbation)],
                [
                    f"Limite de paiement des taxes ({DELAI_PAIEMENT_JOURS} jours)",
                    _date_fr(deposit.date_limite_paiement),
                ],
                ["Depot finalise", _date_fr(deposit.date_depot)],
                ["Taxes du depot", f"{deposit.montant_taxes:.2f} DH"],
                ["Taxes payees", f"{total_paye(db, deposit):.2f} DH"],
                ["Reste a payer", f"{solde_taxes(db, deposit):.2f} DH"],
            ],
        ),
        Tableau(
            titre="Pieces du dossier (checklist de la forme juridique)",
            colonnes=(
                Colonne("Piece", largeur=85),
                Colonne("Etat", largeur=25),
                Colonne("Taille", largeur=20, alignement="right"),
                Colonne("Empreinte SHA-256", largeur=45),
            ),
            lignes=[
                [
                    ligne["libelle"][:70],
                    statuts.get(ligne["statut"], "-"),
                    ligne["taille_lisible"] or "-",
                    (ligne["hash_sha256"] or "-")[:32],
                ]
                for ligne in lignes_pieces
            ],
        ),
    ]
    if deposit.events:
        tableaux.append(
            Tableau(
                titre="Journal des etats (transitions enregistrees)",
                colonnes=(
                    Colonne("Date", largeur=20),
                    Colonne("Etat avant", largeur=30),
                    Colonne("Etat apres", largeur=30),
                    Colonne("Motif", largeur=80),
                ),
                lignes=[
                    [
                        _date_fr(evenement.date_evenement),
                        evenement.etat_avant,
                        evenement.etat_apres,
                        (evenement.motif or "-")[:70],
                    ]
                    for evenement in deposit.events
                ],
            )
        )
    certificat = (
        f"Certificat de depot {deposit.reference_certificat or ''} - SHA-256 "
        f"{deposit.certificat_hash}"
        if deposit.certificat_hash
        else "Certificat de depot : non encore archive."
    )
    provisoire = (
        None
        if exercice_clos(db, company.id, deposit.exercice)
        else "ATTENTION : exercice non cloture - etats de synthese provisoires."
    )
    lignes_entete = [
        f"{company.name} - RC {company.rc or '-'} - IF {company.fiscal_id or '-'} "
        f"- ICE {company.ice or '-'}",
        f"Exercice {deposit.exercice} - forme juridique {deposit.forme_juridique} "
        f"- etat : {deposit.etat_libelle}",
        f"Portail du greffe : {URL_PORTAIL} - pieces PDF <= 10 Mo - paiement des "
        f"taxes sous {DELAI_PAIEMENT_JOURS} jours",
    ]
    if provisoire:
        lignes_entete.insert(0, provisoire)
    document = Document(
        titre=f"DOSSIER DE DEPOT AU GREFFE - exercice {deposit.exercice}",
        sous_titre="Etats de synthese (CGNC) - dossier a deposer au greffe du tribunal",
        entete=lignes_entete,
        tableaux=tableaux,
        pied=f"{certificat} - document genere par Compta MA.",
        filigrane="PROVISOIRE" if provisoire else None,
    )
    return rendre_pdf(document)


def _date_fr(jour: date | None) -> str:
    """Date au format marocain (jj/mm/aaaa) ; tiret si absente."""
    return "-" if jour is None else jour.strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Controles prealables et alertes
# ---------------------------------------------------------------------------
def controles_depot(
    db: Session,
    deposit: GreffeDeposit,
    *,
    aujourdhui: date | None = None,
    pour_soumission: bool = False,
) -> list[dict]:
    """Controles du dossier de depot (CDC § 3.5, controles bloquants 1 a 6).

    `pour_soumission` : a la soumission, la **date d'AG hors delai** devient
    bloquante (elle expose a l'etat « Amender » et a l'amende) ; la creation du
    dossier ne fait que l'avertir, pour laisser le temps de regulariser.
    """
    jour = aujourdhui or date.today()
    controles: list[dict] = []

    def ajouter(code: str, niveau: str, message: str) -> None:
        controles.append({"code": code, "niveau": niveau, "message": message})

    # 1. Exercice clos : on ne depose pas des comptes provisoires.
    if not exercice_clos(db, deposit.company_id, deposit.exercice):
        ajouter(
            "greffe.exercice_non_clos",
            "bloquant",
            f"Exercice {deposit.exercice} non clôturé : les états de synthèse sont "
            "provisoires (le greffe exige des comptes définitifs). Clôturez "
            "l'exercice (écran Exercices) avant de soumettre.",
        )

    # 2. Bilan equilibre (etats de synthese generes sans anomalie).
    _, date_to = year_bounds(deposit.exercice)
    bilan = balance_sheet(db, deposit.company_id, *year_bounds(deposit.exercice))
    if not bilan["equilibre"]:
        ajouter(
            "greffe.bilan_desequilibre",
            "bloquant",
            f"Bilan non équilibré au {_date_fr(date_to)} : actif "
            f"{bilan['total_actif']:.2f} DH contre passif "
            f"{bilan['total_passif_avec_resultat']:.2f} DH.",
        )

    # 3. Checklist complete pour la forme juridique et pieces <= 10 Mo.
    manquantes = pieces_manquantes(db, deposit)
    if manquantes:
        ajouter(
            "greffe.checklist_incomplete",
            "bloquant",
            f"Checklist incomplète pour la forme {deposit.forme_juridique} : "
            f"{len(manquantes)} pièce(s) obligatoire(s) manquante(s) — "
            + " ; ".join(ligne["libelle"] for ligne in manquantes)
            + ".",
        )
    # 3 bis. Pieces fournies **mais invalides** (vide, page blanche, sans contenu
    # metier) : elles ne comptent pas comme fournies (P1 greffe).
    invalides = [ligne for ligne in checklist(db, deposit) if ligne.get("anomalie")]
    for ligne in invalides:
        ajouter(
            "greffe.piece_contenu_invalide",
            "bloquant",
            f"Pièce « {ligne['libelle']} » ({ligne['nom_fichier']}) : {ligne['anomalie']}",
        )
    # 3 ter. Doublons : le meme contenu (SHA-256) ne peut pas servir deux pieces.
    # Lecture **fraiche** en base (une piece ajoutee dans la transaction courante
    # doit etre vue, comme pour la checklist).
    par_empreinte: dict[str, list[str]] = {}
    for document in _documents_par_piece(db, deposit).values():
        par_empreinte.setdefault(document.hash_sha256, []).append(
            f"{document.libelle} ({document.nom_fichier})"
        )
    for empreinte, documents in par_empreinte.items():
        if len(documents) > 1:
            ajouter(
                "greffe.pieces_dupliquees",
                "bloquant",
                "Contenu identique (SHA-256 "
                f"{empreinte[:12]}…) pour plusieurs pièces : " + " ; ".join(documents) + ".",
            )
    for document in deposit.documents:
        if document.taille_octets > TAILLE_MAX_GREFFE:
            ajouter(
                "greffe.piece_sur_dimension",
                "bloquant",
                f"Pièce « {document.libelle} » : "
                f"{taille_lisible(document.taille_octets)} (la limite du portail est "
                "de 10 Mo par fichier).",
            )

    # 5. RC / IF / ICE renseignes et conformes.
    company = db.get(Company, deposit.company_id)
    if company is not None:
        problemes = controle_identite(company)
        if problemes:
            ajouter(
                "greffe.identite_incomplete",
                "bloquant",
                "Identifiants exigés par le portail : " + " ; ".join(problemes) + ".",
            )

    # 4. Date d'AG <= 6 mois de la cloture (loi 5-96, art. 10).
    hors_delai = bool(deposit.date_ag and deposit.date_ag > deposit.date_limite_depot)
    ag_depassee = deposit.date_ag is None and jour > deposit.date_limite_depot
    if hors_delai or ag_depassee:
        detail = (
            f"AG du {_date_fr(deposit.date_ag)}"
            if hors_delai
            else "aucune date d'AG enregistrée"
        )
        ajouter(
            "greffe.ag_hors_delai",
            "bloquant" if pour_soumission else "avertissement",
            f"Délai d'approbation dépassé ({detail} ; limite "
            f"{_date_fr(deposit.date_limite_depot)}, loi 5-96 art. 10) : le dépôt "
            "sera « Amender » et exposé à une amende.",
        )

    # 6. Unicite du depot par exercice (aucune re-soumission d'un dossier depose).
    if deposit.statut == ETAT_DEPOSE:
        ajouter(
            "greffe.dossier_deja_depose",
            "bloquant",
            f"Exercice {deposit.exercice} déjà déposé le {_date_fr(deposit.date_depot)} "
            f"(certificat {deposit.reference_certificat or 'non référencé'}) : le "
            "portail n'accepte qu'un dépôt par exercice.",
        )

    # Taxes : paiement sous 3 jours apres approbation (rejet automatique au-dela).
    solde = solde_taxes(db, deposit)
    if solde > 0 and deposit.statut in (ETAT_APPROUVE, ETAT_AMENDER):
        echu = bool(
            deposit.date_limite_paiement and deposit.date_limite_paiement < jour
        )
        ajouter(
            "greffe.paiement_3_jours",
            "bloquant" if echu else "avertissement",
            f"Taxes du dépôt : {solde:.2f} DH restant à payer"
            + (
                f" — délai dépassé le {_date_fr(deposit.date_limite_paiement)} "
                "(rejet automatique du dossier)"
                if echu
                else f" — à payer avant le {_date_fr(deposit.date_limite_paiement)} "
                f"({DELAI_PAIEMENT_JOURS} jours après approbation)"
            )
            + ".",
        )
    if deposit.statut == ETAT_DEPOSE and not deposit.certificat_hash:
        ajouter(
            "greffe.certificat_manquant",
            "avertissement",
            "Dossier déposé : archivez le certificat de dépôt signé (preuve légale, "
            "conservation 10 ans).",
        )
    if deposit.statut == ETAT_AMENDER and not deposit.amende_montant:
        ajouter(
            "greffe.amende_a_preciser",
            "avertissement",
            "Dépôt hors délai : saisissez le montant de l'amende notifiée pour la "
            "provisionner (dotation 6195 / provision 1515).",
        )
    return controles


NIVEAUX_ALERTE = {"urgent": 0, "attention": 1, "information": 2}


def alertes_depot(
    db: Session, deposit: GreffeDeposit, *, aujourdhui: date | None = None
) -> list[dict]:
    """Alertes propres a un dossier (echeances et etats du portail).

    Les trois alertes du guide de novembre 2025 : **AG > 6 mois** (risque
    « Amender »), **3 jours** apres approbation pour payer les taxes (sinon
    rejet automatique), **rejet** du dossier (piece a corriger), et depot non
    finalise a la fin de l'exercice suivant.
    """
    jour = aujourdhui or date.today()
    alertes: list[dict] = []

    def ajouter(code: str, niveau: str, message: str, **extra: object) -> None:
        alertes.append(
            {
                "code": code,
                "niveau": niveau,
                "message": message,
                "depot_id": deposit.id,
                "exercice": deposit.exercice,
                "statut": deposit.statut,
                **extra,
            }
        )

    if deposit.statut in (ETAT_REJETE, ETAT_AMENDER):
        if deposit.statut == ETAT_REJETE:
            ajouter(
                "greffe.dossier_rejete",
                "urgent",
                f"Exercice {deposit.exercice} : dossier rejeté par le greffe — "
                f"{(deposit.dernier_motif or 'motif non consigné')}. Corrigez la pièce "
                "puis re-soumettez.",
            )
        else:
            ajouter(
                "greffe.dossier_amender",
                "urgent",
                f"Exercice {deposit.exercice} : dépôt hors délai (« Amender ») — "
                "régularisez et provisionnez l'amende"
                + (
                    f" ({deposit.amende_montant:.2f} DH enregistrés)"
                    if deposit.amende_montant
                    else " (montant de l'amende à saisir)"
                )
                + ".",
            )
    solde = solde_taxes(db, deposit)
    if deposit.statut == ETAT_APPROUVE and solde > 0:
        limite = deposit.date_limite_paiement
        jours_restants = None if limite is None else (limite - jour).days
        if jours_restants is not None and jours_restants < 0:
            ajouter(
                "greffe.paiement_en_retard",
                "urgent",
                f"Exercice {deposit.exercice} : délai de paiement dépassé de "
                f"{abs(jours_restants)} jour(s) (limite {_date_fr(limite)}) — "
                f"{solde:.2f} DH restant à payer, rejet automatique du dossier.",
                date_limite=limite,
                jours_restants=jours_restants,
                montant=solde,
            )
        else:
            ajouter(
                "greffe.paiement_3_jours",
                "urgent" if (jours_restants or 0) <= 1 else "attention",
                f"Exercice {deposit.exercice} : dossier approuvé — {solde:.2f} DH à "
                f"payer avant le {_date_fr(limite)} "
                f"({jours_restants} jour(s) restant(s)) : au-delà, rejet automatique.",
                date_limite=limite,
                jours_restants=jours_restants,
                montant=solde,
            )
    if deposit.statut != ETAT_DEPOSE:
        hors_delai = bool(
            deposit.date_ag and deposit.date_ag > deposit.date_limite_depot
        ) or (deposit.date_ag is None and jour > deposit.date_limite_depot)
        if hors_delai:
            ajouter(
                "greffe.ag_hors_delai",
                "attention",
                f"Exercice {deposit.exercice} : délai d'AG (6 mois) expiré depuis le "
                f"{_date_fr(deposit.date_limite_depot)} — dépôt exposé à l'amende.",
                date_limite=deposit.date_limite_depot,
            )
        fin_exercice_suivant = year_bounds(deposit.exercice + 1)[1]
        if jour > fin_exercice_suivant:
            ajouter(
                "greffe.depot_non_finalise",
                "attention",
                f"Exercice {deposit.exercice} : dépôt toujours non finalisé "
                f"(exercice suivant clos le {_date_fr(fin_exercice_suivant)}).",
                date_limite=fin_exercice_suivant,
            )
    if deposit.statut == ETAT_DEPOSE and not deposit.certificat_hash:
        ajouter(
            "greffe.certificat_manquant",
            "attention",
            f"Exercice {deposit.exercice} : certificat de dépôt non archivé "
            "(preuve légale à conserver 10 ans).",
        )
    return sorted(alertes, key=lambda alerte: NIVEAUX_ALERTE.get(alerte["niveau"], 9))


# ---------------------------------------------------------------------------
# Cycle de vie des 7 etats du portail
# ---------------------------------------------------------------------------
def _motif_obligatoire(etat: str, etat_avant: str) -> bool:
    """Vrai si la transition exige un motif ecrit (piste d'audit)."""
    if etat in (ETAT_REJETE, ETAT_ANNULE, ETAT_AMENDER):
        return True
    return (etat_avant, etat) in (
        (ETAT_REJETE, ETAT_EN_COURS),
        (ETAT_ANNULE, ETAT_NOUVEAU),
        (ETAT_APPROUVE, ETAT_DEPOSE),
        (ETAT_AMENDER, ETAT_DEPOSE),
    )


def changer_etat(
    db: Session,
    deposit: GreffeDeposit,
    etat: str,
    *,
    motif: str | None = None,
    user_id: int | None = None,
    jour: date | None = None,
    forcer_hors_delai: bool = False,
    verrouiller: bool = True,
) -> GreffeDeposit:
    """Fait passer le dossier a un nouvel etat du portail (transitions controlees).

    - **En cours** : soumission — les **controles bloquants** doivent etre tous
      verts (exercice clos, bilan equilibre, checklist complete, identifiants
      valides) ; un **depot hors delai** ne peut etre assume qu'avec
      `forcer_hors_delai=True` (le risque d'amende est alors trace) ;
    - **Approuve** : enregistre la date d'approbation et la **limite de paiement
      a 3 jours** ;
    - **Depose** : exige les **taxes integralement payees**, puis **verrouille
      l'exercice** (P1.6) et fige les pieces.
    """
    jour = jour or date.today()
    if etat not in GREFFE_ETATS:
        raise GreffeError(
            f"Etat « {etat} » inconnu (etats du portail : {', '.join(GREFFE_ETATS)})."
        )
    etat_avant = deposit.statut
    if etat == etat_avant:
        raise GreffeError(f"Le dossier est déjà à l'état « {deposit.etat_libelle} ».")
    autorisees = GREFFE_TRANSITIONS.get(etat_avant, ())
    if etat not in autorisees:
        libelles = ", ".join(GREFFE_ETAT_LABELS.get(e, e) for e in autorisees) or "aucune"
        raise GreffeError(
            f"Transition refusée : « {deposit.etat_libelle} » → "
            f"« {GREFFE_ETAT_LABELS.get(etat, etat)} ». Etats accessibles : {libelles}."
        )
    if _motif_obligatoire(etat, etat_avant) and not (motif or "").strip():
        raise GreffeError(
            f"Un motif est obligatoire pour passer à l'état "
            f"« {GREFFE_ETAT_LABELS.get(etat, etat)} » (piste d'audit)."
        )

    if etat == ETAT_EN_COURS:
        controles = controles_depot(
            db,
            deposit,
            aujourdhui=jour,
            pour_soumission=not forcer_hors_delai,
        )
        bloquants = controles_bloquants(controles)
        if bloquants:
            raise GreffeError(
                "Soumission au portail refusée — contrôles bloquants : "
                + " | ".join(controle["message"] for controle in bloquants)
            )
        deposit.date_soumission = jour
    elif etat == ETAT_APPROUVE:
        # P1 greffe : pas d'approbation sans **date d'assemblee generale**
        # (loi 5-96, art. 10) — le PV d'AG ne peut pas exister sans elle.
        if deposit.date_ag is None:
            raise GreffeError(
                "Transition refusée : la **date de l'assemblée générale** doit être "
                "enregistrée avant d'approuver les comptes (loi 5-96, art. 10) — elle est "
                "portée par le PV d'AG généré par l'application."
            )
        deposit.date_approbation = jour
        deposit.date_limite_paiement = date_limite_paiement(jour)
    elif etat == ETAT_DEPOSE:
        reste = solde_taxes(db, deposit)
        if reste > 0:
            raise GreffeError(
                f"Le dépôt définitif exige le paiement intégral des taxes : "
                f"{reste:.2f} DH restant(s) à régler "
                f"(limite {_date_fr(deposit.date_limite_paiement)})."
            )
        deposit.date_depot = jour

    deposit.statut = etat
    if (motif or "").strip():
        deposit.dernier_motif = motif
    if etat == ETAT_AMENDER and not deposit.amende_motif:
        deposit.amende_motif = motif or "Dépôt hors délai notifié par le greffe."
    db.add(
        GreffeEvent(
            deposit_id=deposit.id,
            etat_avant=etat_avant,
            etat_apres=etat,
            date_evenement=jour,
            motif=motif,
            user_id=user_id,
        )
    )
    db.flush()
    log_action(
        db,
        action="GREFFE_ETAT_CHANGED",
        entity="GreffeDeposit",
        entity_id=deposit.id,
        user_id=user_id,
        company_id=deposit.company_id,
        payload={
            "exercice": deposit.exercice,
            "etat_avant": etat_avant,
            "etat_apres": etat,
            "motif": motif,
            "forcer_hors_delai": forcer_hors_delai,
        },
    )
    if etat == ETAT_DEPOSE and verrouiller:
        verrouiller_apres_depot(db, deposit, user_id=user_id)
    return deposit


def verrouiller_apres_depot(
    db: Session, deposit: GreffeDeposit, *, user_id: int | None = None
) -> dict:
    """Verrouille l'exercice depose (P1.6) : les comptes deposes ne bougent plus.

    Un verrou deja pose n'est pas une erreur (depot apres verrouillage manuel) :
    le resultat indique alors que l'exercice etait deja fige.
    """
    try:
        verrou = verrouiller_periode(
            db,
            company_id=deposit.company_id,
            year=deposit.exercice,
            motif=f"Dépôt des états de synthèse au greffe (exercice {deposit.exercice})",
            user_id=user_id,
        )
    except PeriodLockError as exc:
        return {"verrouille": False, "motif": str(exc)}
    return {"verrouille": True, "verrou_id": verrou.id, "periode": None}


def alertes_greffe(
    db: Session,
    company_id: int,
    *,
    aujourdhui: date | None = None,
    exercice: int | None = None,
) -> list[dict]:
    """Alertes de tous les dossiers d'une societe (tableau de bord du greffe)."""
    alertes: list[dict] = []
    for depot in list_depots(db, company_id, exercice=exercice):
        if depot.statut == ETAT_ANNULE:
            continue
        alertes.extend(alertes_depot(db, depot, aujourdhui=aujourdhui))
    return sorted(alertes, key=lambda alerte: NIVEAUX_ALERTE.get(alerte["niveau"], 9))


def controles_bloquants(controles: list[dict]) -> list[dict]:
    """Controles de niveau bloquant (interdisent la soumission au portail)."""
    return [controle for controle in controles if controle["niveau"] == "bloquant"]


# ---------------------------------------------------------------------------
# Paiement des taxes et certificat de depot
# ---------------------------------------------------------------------------
def enregistrer_paiement(
    db: Session,
    deposit: GreffeDeposit,
    *,
    montant: Decimal | str,
    date_paiement: date | None = None,
    moyen: str = "cmi",
    reference: str | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> GreffePayment:
    """Enregistre le paiement des taxes du depot (souvent en ligne, CMI).

    Le paiement n'est admis qu'**apres approbation** du dossier (le portail
    n'ouvre le paiement qu'a ce stade) et dans la limite des taxes dues : le
    total paye est la **somme des lignes**, jamais un solde stocke a part.
    """
    if deposit.statut not in (ETAT_APPROUVE, ETAT_AMENDER):
        raise GreffeError(
            f"Le paiement des taxes intervient après approbation du dossier "
            f"(état actuel : « {deposit.etat_libelle} »)."
        )
    if moyen not in GREFFE_MOYENS:
        raise GreffeError(
            f"Moyen de paiement « {moyen} » inconnu "
            f"(valeurs admises : {', '.join(GREFFE_MOYENS)})."
        )
    montant_paye = money(Decimal(str(montant)))
    if montant_paye <= 0:
        raise GreffeError("Le montant du paiement doit être supérieur à zéro.")
    deja = total_paye(db, deposit)
    if deposit.montant_taxes and deposit.montant_taxes > 0:
        if deja + montant_paye > deposit.montant_taxes:
            raise GreffeError(
                f"Le montant des taxes est déjà réglé : {deja:.2f} DH payés sur "
                f"{deposit.montant_taxes:.2f} DH dus (paiement de {montant_paye:.2f} DH "
                "refusé)."
            )
    ligne = GreffePayment(
        deposit_id=deposit.id,
        montant=montant_paye,
        date_paiement=date_paiement or date.today(),
        moyen=moyen,
        reference=reference,
        notes=notes,
        created_by=user_id,
    )
    db.add(ligne)
    db.flush()
    log_action(
        db,
        action="GREFFE_PAYMENT_ADDED",
        entity="GreffePayment",
        entity_id=ligne.id,
        user_id=user_id,
        company_id=deposit.company_id,
        payload={
            "depot": deposit.id,
            "exercice": deposit.exercice,
            "montant": str(montant_paye),
            "moyen": moyen,
            "reference": reference,
            "total_paye": str(total_paye(db, deposit)),
            "solde": str(solde_taxes(db, deposit)),
        },
    )
    return ligne


def enregistrer_certificat(
    db: Session,
    deposit: GreffeDeposit,
    *,
    nom_fichier: str | None,
    contenu: bytes,
    reference: str | None = None,
    user_id: int | None = None,
) -> GreffeDeposit:
    """Archive le **certificat de depot** signe (preuve legale, 10 ans).

    Le certificat est stocke hors base avec son **empreinte SHA-256** ; l'alerte
    « certificat manquant » disparait des que l'archive est en place.
    """
    nom = nom_fichier_securise(nom_fichier, defaut="certificat_depot.pdf")
    taille = verifier_piece_pdf(nom, contenu)
    hash_sha256 = empreinte_sha256(contenu)
    chemin_relatif = f"{deposit.company_id}/{deposit.id}/certificat_{nom}"
    chemin = racine_stockage() / chemin_relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    deposit.certificat_nom = nom
    deposit.certificat_path = chemin_relatif
    deposit.certificat_hash = hash_sha256
    deposit.reference_certificat = reference or deposit.reference_certificat
    deposit.certificat_depose_le = datetime.now()
    db.flush()
    log_action(
        db,
        action="GREFFE_CERTIFICAT_ARCHIVED",
        entity="GreffeDeposit",
        entity_id=deposit.id,
        user_id=user_id,
        company_id=deposit.company_id,
        payload={
            "depot": deposit.id,
            "exercice": deposit.exercice,
            "reference": deposit.reference_certificat,
            "nom_fichier": nom,
            "taille_octets": taille,
            "hash_sha256": hash_sha256,
        },
    )
    return deposit


def lire_certificat(deposit: GreffeDeposit) -> bytes:
    """Contenu archive du certificat de depot (leve si absent)."""
    if not deposit.certificat_path:
        raise GreffeError(
            f"Aucun certificat de dépôt n'est archivé pour l'exercice "
            f"{deposit.exercice}."
        )
    chemin = racine_stockage() / deposit.certificat_path
    if not chemin.exists():
        raise GreffeError(
            f"Le certificat de dépôt archivé est introuvable ({chemin})."
        )
    return chemin.read_bytes()


# ---------------------------------------------------------------------------
# Archive ZIP du dossier (assembleur) et etats de suivi
# ---------------------------------------------------------------------------
def assembler_dossier(db: Session, company: Company, deposit: GreffeDeposit) -> bytes:
    """Assemble l'**archive ZIP** du dossier de depot, prete a televerser.

    L'archive contient : le **bordereau recapitulatif** (PDF, regeneré a la
    date), chaque **piece PDF** nommee `NN_piece_libelle.pdf`, et un
    **manifeste JSON** (empreintes SHA-256, tailles, delais, checklist). Une
    piece est relue **et re-verifiee par son empreinte** avant d'entrer dans
    l'archive : une piece alteree sur le disque fait echouer l'assemblage.

    Aucune archive n'est produite si un **controle bloquant** subsiste (exercice
    non clos, bilan desequilibre, checklist incomplete, identites manquantes) :
    « aucune soumission sans tout vert » (CDC § 3.5).
    """
    controles = controles_depot(db, deposit)
    bloquants = [
        controle
        for controle in controles_bloquants(controles)
        # L'archive deja produite reste re-editable apres le depot : c'est le
        # **portail** qui refuse une seconde soumission, pas l'archivage interne
        # (le dossier « Depose » est conserve 10 ans au dossier permanent).
        if controle["code"] != "greffe.dossier_deja_depose"
    ]
    if bloquants:
        raise GreffeError(
            "Archive du dossier refusée — contrôles bloquants : "
            + " | ".join(controle["message"] for controle in bloquants)
        )
    bordereau = pdf_recapitulatif_dossier(db, company, deposit)
    manifeste_pieces = []
    avec_contenu: list[tuple[str, bytes]] = []
    for index, ligne in enumerate(checklist(db, deposit), start=1):
        document = _documents_par_piece(db, deposit).get(ligne["code"])
        entree = {
            "code": ligne["code"],
            "libelle": ligne["libelle"],
            "obligatoire": ligne["obligatoire"],
            "fournie": ligne["fournie"],
            "nom_fichier": ligne["nom_fichier"],
            "taille_octets": ligne["taille_octets"],
            "hash_sha256": ligne["hash_sha256"],
        }
        manifeste_pieces.append(entree)
        if document is None:
            continue
        if not ligne["fournie"]:
            # Un fichier **present mais invalide** (vide, page blanche, sans contenu
            # metier, ancienne version de 193 octets) ne doit **jamais** entrer dans
            # l'archive : c'est exactement le defaut de recette (rapport de gestion et
            # PV d'AG de 193 octets). L'archive est refusee, motif a l'appui.
            raise GreffeError(
                f"Archive du dossier refusée — la pièce « {document.libelle} » "
                f"({document.nom_fichier}) est présente dans le dossier mais "
                f"**invalide** : {ligne.get('anomalie') or 'contenu non conforme'}. "
                "Régénérez ou re-téléversez la pièce avant l'archivage."
            )
        contenu = lire_document(document)
        if empreinte_sha256(contenu) != document.hash_sha256:
            raise GreffeError(
                f"La pièce « {document.libelle} » (fichier {document.nom_fichier}) a "
                "été modifiée depuis son archivage : empreinte SHA-256 différente. "
                "Re-téléversez la pièce avant de déposer le dossier."
            )
        avec_contenu.append((f"{index:02d}_{ligne['code']}_{document.nom_fichier}", contenu))
    manifeste = {
        "portail": URL_PORTAIL,
        "societe": company.name,
        "rc": company.rc,
        "if": company.fiscal_id,
        "ice": company.ice,
        "exercice": deposit.exercice,
        "forme_juridique": deposit.forme_juridique,
        "etat": deposit.statut,
        "date_limite_depot": deposit.date_limite_depot.isoformat(),
        "date_limite_paiement": (
            deposit.date_limite_paiement.isoformat()
            if deposit.date_limite_paiement
            else None
        ),
        "montant_taxes": str(deposit.montant_taxes),
        "taxes_payees": str(total_paye(db, deposit)),
        "reste_a_payer": str(solde_taxes(db, deposit)),
        "pieces": manifeste_pieces,
        "bordereau_sha256": empreinte_sha256(bordereau),
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "contraintes": {
            "format": "PDF",
            "taille_max_par_fichier_octets": TAILLE_MAX_GREFFE,
            "delai_paiement_jours": DELAI_PAIEMENT_JOURS,
        },
    }
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_dossier:
        zip_dossier.writestr("00_bordereau_recapitulatif.pdf", bordereau)
        for nom_archive, contenu in avec_contenu:
            zip_dossier.writestr(nom_archive, contenu)
        zip_dossier.writestr(
            "manifeste.json",
            json.dumps(manifeste, ensure_ascii=False, indent=2),
        )
    log_action(
        db,
        action="GREFFE_ARCHIVE_BUILT",
        entity="GreffeDeposit",
        entity_id=deposit.id,
        company_id=company.id,
        payload={
            "exercice": deposit.exercice,
            "nb_pieces": len(avec_contenu),
            "taille_bordereau": len(bordereau),
        },
    )
    return archive.getvalue()


def pdf_attestation_paiement(
    db: Session, company: Company, deposit: GreffeDeposit
) -> bytes:
    """Attestation de paiement des taxes du depot (piece justificative).

    Produite par Compta MA a partir des paiements enregistres
    (`greffe_payments`) : elle tient lieu de justificatif de paiement des taxes
    dans le dossier lorsque le recu du portail n'est pas encore disponible ; le
    scan du recu peut la remplacer par un televersement.
    """
    paiements = db.execute(
        select(GreffePayment)
        .where(GreffePayment.deposit_id == deposit.id)
        .order_by(GreffePayment.date_paiement)
    ).scalars()
    lignes = [
        [
            _date_fr(paiement.date_paiement),
            GREFFE_MOYEN_LABELS.get(paiement.moyen, paiement.moyen),
            paiement.reference or "-",
            f"{paiement.montant:.2f} DH",
        ]
        for paiement in paiements
    ]
    total = total_paye(db, deposit)
    document = Document(
        titre=f"ATTESTATION DE PAIEMENT DES TAXES - exercice {deposit.exercice}",
        sous_titre=(
            "Depot des etats de synthese au greffe du tribunal "
            "(paiement en ligne CMI)"
        ),
        entete=[
            f"{company.name} - RC {company.rc or '-'} - IF {company.fiscal_id or '-'} "
            f"- ICE {company.ice or '-'}",
            f"Exercice {deposit.exercice} - forme juridique {deposit.forme_juridique}",
            f"Taxes dues : {deposit.montant_taxes:.2f} DH - payees : {total:.2f} DH",
        ],
        tableaux=[
            Tableau(
                titre="Paiements enregistres",
                colonnes=(
                    Colonne("Date", largeur=25),
                    Colonne("Moyen", largeur=45),
                    Colonne("Reference", largeur=45),
                    Colonne("Montant", largeur=35, alignement="right"),
                ),
                lignes=lignes or [["-", "-", "aucun paiement enregistre", "0,00 DH"]],
                total=["Total paye", "", "", f"{total:.2f} DH"],
            )
        ],
        pied=(
            "Attestation generee par Compta MA a partir des paiements enregistres - "
            f"portail {URL_PORTAIL}."
        ),
    )
    return rendre_pdf(document)


def etat_depots(
    db: Session,
    company_id: int,
    *,
    exercice: int | None = None,
    aujourdhui: date | None = None,
) -> dict:
    """Etat de suivi des depots (tableau de bord du module greffe).

    Une ligne par exercice : etat du portail, dates cles, completude de la
    checklist, taxes (payees / restantes) et nombre d'alertes ouvertes.
    """
    jour = aujourdhui or date.today()
    dossiers: list[dict] = []
    for depot in list_depots(db, company_id, exercice=exercice):
        completude = taux_completude(db, depot)
        alertes = alertes_depot(db, depot, aujourdhui=jour)
        dossiers.append(
            {
                "id": depot.id,
                "exercice": depot.exercice,
                "forme_juridique": depot.forme_juridique,
                "statut": depot.statut,
                "etat_libelle": depot.etat_libelle,
                "date_ag": depot.date_ag,
                "date_limite_depot": depot.date_limite_depot,
                "date_soumission": depot.date_soumission,
                "date_approbation": depot.date_approbation,
                "date_limite_paiement": depot.date_limite_paiement,
                "date_depot": depot.date_depot,
                "jours_restants_ag": (depot.date_limite_depot - jour).days,
                "montant_taxes": depot.montant_taxes,
                "taxes_payees": total_paye(db, depot),
                "solde_taxes": solde_taxes(db, depot),
                "reference_certificat": depot.reference_certificat,
                "certificat_archive": bool(depot.certificat_hash),
                "certificat_le": depot.certificat_depose_le,
                "amende_montant": depot.amende_montant,
                "dernier_motif": depot.dernier_motif,
                "completude": completude,
                "alertes": alertes,
                "nb_alertes": len(alertes),
                "controles": controles_depot(db, depot, aujourdhui=jour),
            }
        )
    compteurs = {etat: 0 for etat in GREFFE_ETATS}
    for ligne in dossiers:
        compteurs[ligne["statut"]] = compteurs.get(ligne["statut"], 0) + 1
    alertes_globales = alertes_greffe(
        db, company_id, aujourdhui=jour, exercice=exercice
    )
    return {
        "company_id": company_id,
        "au": jour,
        "exercice": exercice,
        "dossiers": dossiers,
        "nb_dossiers": len(dossiers),
        "compteurs": compteurs,
        "alertes": alertes_globales,
        "nb_alertes_urgentes": sum(
            1 for alerte in alertes_globales if alerte["niveau"] == "urgent"
        ),
    }


def comptabiliser_amende(
    db: Session,
    company: Company,
    deposit: GreffeDeposit,
    *,
    montant: Decimal | str | None = None,
    jour: date | None = None,
    user_id: int | None = None,
    journal_code: str = JOURNAL_GREFFE,
) -> dict:
    """Provisionne l'**amende hors delai** (etat « Amender ») : 6195 / 1515.

    CGNC : une amende probable pour depot tardif est un **risque et charge** ;
    la dotation est enregistree en charge d'exploitation (`6195`) par le credit
    de la provision `1515` « provisions pour amendes, doubles droits,
    penalites » (amende **non deductible** : a rattacher dans la liasse fiscale).
    L'ecriture est **unique par dossier** (source `greffe`) : rappeler la
    fonction ne double pas la provision.
    """
    montant_provision = money(
        Decimal(str(montant if montant is not None else (deposit.amende_montant or 0)))
    )
    if montant_provision <= 0:
        raise GreffeError(
            "Montant de l'amende inconnu : saisissez-le (ou passez `montant`) pour "
            "provisionner l'amende."
        )
    if deposit.statut != ETAT_AMENDER:
        raise GreffeError(
            "L'amende hors délai ne se provisionne que pour un dossier à l'état "
            f"« Amender » (état actuel : « {deposit.etat_libelle} »)."
        )
    existante = db.execute(
        select(Entry.id).where(
            Entry.company_id == company.id,
            Entry.source == SOURCE_ECRITURE,
            Entry.source_id == deposit.id,
        )
    ).first()
    if existante is not None:
        raise GreffeError(
            f"L'amende du dossier {deposit.exercice} est déjà provisionnée "
            f"(écriture n° {existante[0]})."
        )
    jour_ecriture = jour or date.today()
    exercice_row = get_fiscal_year(db, company.id, jour_ecriture.year)
    journal = get_journal(db, company.id, journal_code)
    ecriture = create_entry(
        db,
        company_id=company.id,
        fiscal_year=exercice_row,
        journal=journal,
        entry_date=jour_ecriture,
        label=(
            f"Provision amende - depot des etats de synthese {deposit.exercice} "
            f"au greffe ({deposit.amende_motif or 'depot hors delai'})"
        ),
        lines=[
            {"account_number": COMPTE_DOTATION_AMENDE, "debit": montant_provision},
            {"account_number": COMPTE_PROVISION_AMENDE, "credit": montant_provision},
        ],
        reference=f"Amen.GR.{deposit.exercice}",
        notes=deposit.amende_motif,
        source=SOURCE_ECRITURE,
        source_id=deposit.id,
        created_by=user_id,
        validate=True,
    )
    deposit.amende_montant = montant_provision
    db.flush()
    log_action(
        db,
        action="GREFFE_AMENDE_PROVISIONNEE",
        entity="GreffeDeposit",
        entity_id=deposit.id,
        user_id=user_id,
        company_id=company.id,
        payload={
            "exercice": deposit.exercice,
            "montant": str(montant_provision),
            "ecriture": ecriture.entry_number,
            "comptes": f"{COMPTE_DOTATION_AMENDE}/{COMPTE_PROVISION_AMENDE}",
        },
    )
    return {
        "depot": deposit,
        "entry_number": ecriture.entry_number,
        "entry_id": ecriture.id,
        "montant": montant_provision,
        "comptes": {
            "dotation": COMPTE_DOTATION_AMENDE,
            "provision": COMPTE_PROVISION_AMENDE,
        },
    }





