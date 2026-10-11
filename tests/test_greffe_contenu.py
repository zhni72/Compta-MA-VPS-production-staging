"""P1 greffe — controle **de contenu** des pieces (anomalie bloquante de recette).

Constat de recette : deux pieces du dossier J9 — `rapport_gestion_j9.pdf` et
`pv_ag_j9.pdf` — de **193 octets** (page vide, contenu identique) etaient
acceptees comme **valides**, car seul le type MIME et la taille < 10 Mo etaient
verifies.

Ce module reproduit **exactement** ces fichiers et verifie que :
- un PDF de 193 octets sans contenu (page blanche) est **refuse** ;
- un fichier vide, un non-PDF, un PDF illisible sont refuses ;
- un contenu insuffisant et un document **sans contenu metier obligatoire**
  (mentions du PV d'AG / du rapport de gestion) sont refuses ;
- le **meme contenu** ne peut pas servir deux pieces differentes (SHA-256) ;
- le **rapport de gestion** et le **PV d'AG generes** par l'application sont
  **reels** (donnees de l'exercice, date d'AG, resolutions) et recoivent un
  **SHA-256 recalcule** apres generation ;
- l'**approbation** exige une date d'assemblee generale ;
- l'application ne simule **ni depot ni certificat** de greffe.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import get_or_create_fiscal_year
from app.models.greffe import GreffeDocument
from app.services import greffe
from app.services.pdf import Colonne, Document, Tableau, rendre_pdf
from app.services.pdf_documents import (
    DocumentIncoherentError,
    pdf_pv_ag,
    pdf_rapport_gestion,
)

pytestmark = pytest.mark.usefixtures("ctx")

# --- Fichier **exact** de la recette J9 (193 octets, page vide) -------------
PDF_193_OCTETS = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)


@pytest.fixture(autouse=True)
def stockage_greffe(tmp_path, monkeypatch):
    """Archive les pieces du greffe dans un dossier temporaire (jamais le depot)."""
    monkeypatch.setattr(settings, "greffe_dir", tmp_path)
    return tmp_path


def _cloturer(db, company, year: int) -> None:
    exercice = get_or_create_fiscal_year(db, company, year)
    exercice.status = "closed"
    db.commit()


def _dossier(db, ctx, *, date_ag: date | None = date(2026, 6, 10)) -> greffe.GreffeDeposit:
    """Dossier SARL de l'exercice de test, clos, avec date d'AG enregistrable."""
    year = ctx["year"]
    _cloturer(db, ctx["company"], year)
    return greffe.creer_depot(
        db,
        company=ctx["company"],
        exercice=year,
        user_id=ctx["user"].id,
        forme_juridique="SARL",
        date_ag=date_ag,
        montant_taxes=Decimal("350"),
    )


def _piece(db, depot, code: str) -> GreffeDocument | None:
    """Piece archivee du dossier, relue **en base** (la relation peut etre cachee)."""
    return db.scalars(
        select(GreffeDocument).where(
            GreffeDocument.deposit_id == depot.id, GreffeDocument.piece_code == code
        )
    ).first()


def _pdf_texte(texte: str) -> bytes:
    """PDF reel (1 page) portant `texte` : contenu controlable a volonte."""
    return rendre_pdf(
        Document(
            titre="Document de test",
            tableaux=[Tableau(colonnes=[Colonne("Contenu", largeur=160)], lignes=[[texte]])],
        )
    )


def _pdf_page_blanche() -> bytes:
    """PDF reel dont la seule page est **blanche** (aucun texte)."""
    return rendre_pdf(Document(titre=""))


# ---------------------------------------------------------------------------
# 1. Les PDF de 193 octets de la recette sont refuses
# ---------------------------------------------------------------------------
def test_pdf_193_octets_de_la_recette_est_refuse(db, ctx):
    """Le fichier exact de la recette (193 o, page vide) ne peut plus passer."""
    assert len(PDF_193_OCTETS) == 193  # reproduction **exacte** du constat
    analyse = greffe.analyser_piece_pdf(PDF_193_OCTETS)
    assert analyse.lisible is False  # aucune page exploitable
    assert analyse.vide is True

    depot = _dossier(db, ctx)
    for code, nom in (
        (greffe.PIECE_PV_AG, "pv_ag_j9.pdf"),
        (greffe.PIECE_RAPPORT_GESTION, "rapport_gestion_j9.pdf"),
    ):
        with pytest.raises(greffe.GreffeError) as erreur:
            greffe.ajouter_piece(
                db, depot, piece_code=code, nom_fichier=nom, contenu=PDF_193_OCTETS
            )
        assert "illisible" in str(erreur.value)
    # Aucune piece n'a ete archivee : ni en base, ni sur le disque.
    assert _piece(db, depot, greffe.PIECE_PV_AG) is None
    assert _piece(db, depot, greffe.PIECE_RAPPORT_GESTION) is None
    assert not list(settings.greffe_racine.rglob("*.pdf"))


def test_fichier_vide_et_non_pdf_refuses(db, ctx):
    """Fichier vide ou non-PDF : refus avant tout archivage."""
    depot = _dossier(db, ctx)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.ajouter_piece(
            db, depot, piece_code=greffe.PIECE_PV_AG, nom_fichier="vide.pdf", contenu=b""
        )
    assert "vide" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.ajouter_piece(
            db,
            depot,
            piece_code=greffe.PIECE_PV_AG,
            nom_fichier="pv.docx",
            contenu=b"contenu word",
        )
    assert "PDF" in str(erreur.value)


def test_page_blanche_et_contenu_insuffisant_refuses(db, ctx):
    """Page blanche et texte trop court : deux refus distincts et explicites."""
    depot = _dossier(db, ctx)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.ajouter_piece(
            db,
            depot,
            piece_code=greffe.PIECE_ETAT_COMPLEMENTAIRE,
            nom_fichier="blanche.pdf",
            contenu=_pdf_page_blanche(),
        )
    assert "blanche" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.ajouter_piece(
            db,
            depot,
            piece_code=greffe.PIECE_ETAT_COMPLEMENTAIRE,
            nom_fichier="court.pdf",
            contenu=_pdf_texte("Texte trop court."),
        )
    assert "contenu insuffisant" in str(erreur.value)


def test_pieces_substantielles_sans_contenu_metier_refusees(db, ctx):
    """PV d'AG et rapport de gestion : mentions metier obligatoires exigees."""
    depot = _dossier(db, ctx)
    sans_mention = _pdf_texte(
        "Ligne de test sans aucune mention administrative requise. " * 20
    )
    analyse = greffe.analyser_piece_pdf(sans_mention)
    assert analyse.caracteres >= 400  # contenu long, mais sans mention metier
    for code in (greffe.PIECE_PV_AG, greffe.PIECE_RAPPORT_GESTION):
        with pytest.raises(greffe.GreffeError) as erreur:
            greffe.ajouter_piece(
                db,
                depot,
                piece_code=code,
                nom_fichier=f"{code}.pdf",
                contenu=sans_mention,
            )
        assert "contenu metier obligatoire absent" in str(erreur.value)


def test_meme_fichier_pour_deux_pieces_refuse(db, ctx):
    """Le meme contenu (SHA-256) ne peut pas servir deux pieces differentes."""
    depot = _dossier(db, ctx)
    contenu = _pdf_texte("Bordereau et pieces justificatives de l'exercice. " * 4)
    greffe.ajouter_piece(
        db,
        depot,
        piece_code=greffe.PIECE_ETAT_COMPLEMENTAIRE,
        nom_fichier="bordereau.pdf",
        contenu=contenu,
    )
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.ajouter_piece(
            db,
            depot,
            piece_code=greffe.PIECE_TABLEAU_FINANCEMENT,
            nom_fichier="tableau.pdf",
            contenu=contenu,
        )
    assert "Contenu identique" in str(erreur.value)


# ---------------------------------------------------------------------------
# 2. Les pieces invalides deja archivees ne comptent plus comme fournies
# ---------------------------------------------------------------------------
def _piece_archivee_sans_controle(
    db,
    ctx,
    depot,
    contenu: bytes,
    *,
    code: str = greffe.PIECE_PV_AG,
    nom: str = "pv_ag_j9.pdf",
) -> GreffeDocument:
    """Insere une piece **sans controle** (reproduction du dossier de recette)."""
    chemin_relatif = f"{depot.company_id}/{depot.id}/{code}_{nom}"
    chemin = settings.greffe_racine / chemin_relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    document = GreffeDocument(
        deposit_id=depot.id,
        piece_code=code,
        libelle=nom,
        nom_fichier=nom,
        chemin=chemin_relatif,
        taille_octets=len(contenu),
        hash_sha256=greffe.empreinte_sha256(contenu),
        source=greffe.SOURCE_TELEVERSE,
        created_by=ctx["user"].id,
    )
    db.add(document)
    db.commit()
    return document


def test_piece_vide_deja_archivee_est_signalee_et_bloque(db, ctx):
    """Une piece vide archivee avant ce correctif est refusee et bloquante."""
    depot = _dossier(db, ctx)
    _piece_archivee_sans_controle(db, ctx, depot, PDF_193_OCTETS)
    lignes = {ligne["code"]: ligne for ligne in greffe.checklist(db, depot)}
    pv = lignes[greffe.PIECE_PV_AG]
    assert pv["fournie"] is False
    assert pv["statut"] == "invalide"
    assert "illisible" in (pv["anomalie"] or "")
    assert pv["taille_octets"] == 193  # taille reelle conservee (tracabilite)
    assert greffe.PIECE_PV_AG in [
        ligne["code"] for ligne in greffe.pieces_manquantes(db, depot)
    ]
    codes = {controle["code"] for controle in greffe.controles_depot(db, depot)}
    assert "greffe.piece_contenu_invalide" in codes
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    assert "contrôles bloquants" in str(erreur.value)


def test_doublon_de_contenu_bloque_le_dossier(db, ctx):
    """Deux pieces au contenu identique : controle bloquant dedie."""
    depot = _dossier(db, ctx)
    _piece_archivee_sans_controle(db, ctx, depot, PDF_193_OCTETS)
    _piece_archivee_sans_controle(
        db,
        ctx,
        depot,
        PDF_193_OCTETS,
        code=greffe.PIECE_RAPPORT_GESTION,
        nom="rapport_gestion_j9.pdf",
    )
    doublons = [
        controle
        for controle in greffe.controles_depot(db, depot)
        if controle["code"] == "greffe.pieces_dupliquees"
    ]
    assert doublons and doublons[0]["niveau"] == "bloquant"
    assert "SHA-256" in doublons[0]["message"]


# ---------------------------------------------------------------------------
# 3. Rapport de gestion et PV d'AG **generes** : documents reels
# ---------------------------------------------------------------------------
def test_generer_pieces_produit_rapport_et_pv_reels(db, ctx):
    """Le rapport de gestion et le PV d'AG generes sont alimentes par l'exercice."""
    depot = _dossier(db, ctx)
    resultat = greffe.generer_pieces(
        db, depot, company=ctx["company"], user_id=ctx["user"].id
    )
    db.commit()
    codes = {document.piece_code for document in resultat["documents"]}
    assert {
        greffe.PIECE_ETATS_SYNTHESE,
        greffe.PIECE_ETAT_COMPLEMENTAIRE,
        greffe.PIECE_RAPPORT_GESTION,
        greffe.PIECE_PV_AG,
    } <= codes

    lignes = {ligne["code"]: ligne for ligne in greffe.checklist(db, depot)}
    for code in (greffe.PIECE_RAPPORT_GESTION, greffe.PIECE_PV_AG):
        ligne = lignes[code]
        assert ligne["fournie"] is True, ligne["anomalie"]
        assert ligne["anomalie"] is None
        assert ligne["taille_octets"] > 1000  # bien plus que les 193 octets
        assert "page(s)" in (ligne["analyse"] or "")
        assert ligne["hash_sha256"] and len(ligne["hash_sha256"]) == 64

    def _contenu(code: str) -> bytes:
        document = _piece(db, depot, code)
        assert document is not None
        contenu = greffe.lire_document(document)
        # SHA-256 recalcule apres generation : identique a l'empreinte archivee.
        assert greffe.empreinte_sha256(contenu) == document.hash_sha256
        return contenu

    rapport = _contenu(greffe.PIECE_RAPPORT_GESTION)
    pv = _contenu(greffe.PIECE_PV_AG)
    assert rapport != pv  # contenus distincts (aucun doublon)

    texte_rapport = greffe.analyser_piece_pdf(rapport)
    texte_pv = greffe.analyser_piece_pdf(pv)
    assert texte_rapport.caracteres > greffe.CARACTERES_MIN_METIER
    assert texte_pv.caracteres > greffe.CARACTERES_MIN_METIER
    for mention in ("rapport de gestion", "affectation", "perspectives", "resultat"):
        assert mention in texte_rapport.texte_normalise
    for mention in (
        "assemblee generale",
        "resolution",
        "approbation des comptes",
        "affectation du resultat",
    ):
        assert mention in texte_pv.texte_normalise
    # Societe sans mention d'associe unique : assemblee des associes.
    assert "assemblee generale des associes" in texte_pv.texte_normalise
    pv_unique = greffe.analyser_piece_pdf(
        pdf_pv_ag(db, ctx["company"], depot.exercice, date_ag=date(2026, 6, 10),
                  associe_unique=True)
    )
    assert "associe unique" in pv_unique.texte_normalise
    assert "10/06/2026" in texte_pv.texte_normalise  # date d'AG reelle
    # Les deux documents passent les controles de contenu metier.
    for code, contenu in (
        (greffe.PIECE_RAPPORT_GESTION, rapport),
        (greffe.PIECE_PV_AG, pv),
    ):
        analyse = greffe.verifier_contenu_piece(code, "piece.pdf", contenu)
        assert analyse.mots_cles_trouves


def test_documents_generes_portent_les_montants_de_l_exercice(db, ctx):
    """Les montants imprimes viennent des comptes de l'exercice (rien d'invente)."""
    from app.services.reporting import balance_sheet, year_bounds

    depot = _dossier(db, ctx)
    annee = depot.exercice
    rapport = pdf_rapport_gestion(db, ctx["company"], annee)
    pv = pdf_pv_ag(
        db,
        ctx["company"],
        annee,
        date_ag=date(annee, 6, 10),
        date_limite=depot.date_limite_depot,
    )
    bilan = balance_sheet(db, ctx["company"].id, *year_bounds(annee))
    # Le total du bilan apparait dans les deux documents (format des PDF).
    total = f"{bilan['total_actif']:,.2f}".replace(",", " ").replace(".", ",")
    for contenu in (rapport, pv):
        texte = greffe.analyser_piece_pdf(contenu).texte_normalise
        assert total in texte
    assert str(bilan["date_to"].strftime("%d/%m/%Y")) in greffe.analyser_piece_pdf(
        rapport
    ).texte_normalise


# ---------------------------------------------------------------------------
# 4. Date d'assemblee obligatoire et absence de simulation
# ---------------------------------------------------------------------------
def test_pv_ag_exige_une_date_d_assemblee(db, ctx):
    """Sans date d'AG, ni PV ni generation de pieces : refus explicite."""
    depot = _dossier(db, ctx, date_ag=None)
    with pytest.raises(DocumentIncoherentError) as erreur:
        pdf_pv_ag(db, ctx["company"], depot.exercice)
    assert "assemblee generale" in str(erreur.value)
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.generer_pieces(db, depot, company=ctx["company"])
    assert "date de l'assemblée générale est obligatoire" in str(erreur.value)
    # Rien n'a ete genere : le dossier reste vide.
    assert _piece(db, depot, greffe.PIECE_RAPPORT_GESTION) is None
    assert _piece(db, depot, greffe.PIECE_PV_AG) is None


def test_approbation_refusee_sans_date_ag(db, ctx):
    """L'etat « Approuve » exige une date d'assemblee generale (loi 5-96)."""
    depot = _dossier(db, ctx)
    greffe.generer_pieces(db, depot, company=ctx["company"], user_id=ctx["user"].id)
    greffe.changer_etat(db, depot, "en_cours", user_id=ctx["user"].id)
    db.commit()
    depot.date_ag = None  # date effacee : le PV ne peut plus etre justifie
    db.commit()
    with pytest.raises(greffe.GreffeError) as erreur:
        greffe.changer_etat(db, depot, "approuve", motif="Notification")
    assert "date de l'assemblée générale" in str(erreur.value).lower()
    depot.date_ag = date(depot.exercice, 6, 10)
    db.commit()
    greffe.changer_etat(db, depot, "approuve", motif="Notification du greffe")
    db.commit()
    assert depot.statut == "approuve"


def test_aucun_depot_ni_certificat_simule(db, ctx):
    """L'application ne simule ni depot au greffe ni certificat officiel."""
    depot = _dossier(db, ctx)
    greffe.generer_pieces(db, depot, company=ctx["company"], user_id=ctx["user"].id)
    db.commit()
    assert depot.statut == "nouveau"  # jamais depose automatiquement
    assert depot.date_depot is None
    assert depot.date_soumission is None
    assert depot.certificat_path is None
    assert depot.reference_certificat is None
    assert depot.certificat_hash is None
    assert depot.certificat_nom is None



