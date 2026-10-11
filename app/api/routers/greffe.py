"""Depot au greffe du tribunal (P1.5) : dossiers, pieces, paiements, archive."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User
from app.models.greffe import CATALOGUE_PIECES
from app.schemas import (
    GreffeCertificatRequest,
    GreffeDepositCreate,
    GreffeDepositRead,
    GreffeDocumentRead,
    GreffeEtatRequest,
    GreffePaymentCreate,
    GreffePaymentRead,
)
from app.services.greffe import (
    GreffeError,
    ajouter_piece,
    alertes_greffe,
    assembler_dossier,
    changer_etat,
    checklist,
    comptabiliser_amende,
    controles_depot,
    creer_depot,
    enregistrer_certificat,
    enregistrer_paiement,
    etat_depots,
    generer_pieces,
    get_depot,
    lire_certificat,
    lire_document,
    list_depots,
    pdf_attestation_paiement,
    pdf_recapitulatif_dossier,
    pieces_obligatoires,
    solde_taxes,
    supprimer_piece,
    taux_completude,
    total_paye,
)

router = APIRouter(prefix="/greffe", tags=["greffe"])

MUTATION_ROLES = ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")


def _reponse_pdf(pdf: bytes, nom: str) -> Response:
    """Reponse de telechargement PDF (nom de fichier explicite)."""
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get(
    "/pieces",
    summary="Catalogue des pieces du dossier de depot (checklist par forme juridique)",
)
def catalogue_route(
    forme_juridique: str | None = Query(default=None, description="SNC, SARL, SA, SCS, SCA"),
    _: User = Depends(get_current_user),
) -> dict:
    obligatoires = set(pieces_obligatoires(forme_juridique))
    return {
        "forme_juridique": forme_juridique,
        "pieces": [
            {
                "code": piece.code,
                "libelle": piece.libelle,
                "source": piece.source,
                "obligatoire": piece.code in obligatoires,
                "conditionnelle": (
                    piece.conditionnelle_pour(forme_juridique)
                    if forme_juridique
                    else False
                ),
                "commentaire": piece.commentaire,
            }
            for piece in CATALOGUE_PIECES
        ],
        "texte_limite": "PDF uniquement, 10 Mo maximum par fichier (portail du greffe).",
    }


@router.get("/depots", response_model=list[GreffeDepositRead], summary="Lister les depots")
def list_depots_route(
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    return list_depots(db, company.id, exercice=exercice)


@router.post(
    "/depots",
    response_model=GreffeDepositRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer le dossier de depot d'un exercice",
)
def creer_depot_route(
    payload: GreffeDepositCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        depot = creer_depot(
            db,
            company=company,
            exercice=payload.exercice,
            user_id=user.id,
            forme_juridique=payload.forme_juridique,
            date_ag=payload.date_ag,
            montant_taxes=payload.montant_taxes,
            notes=payload.notes,
        )
        db.commit()
    except (GreffeError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(depot)
    return depot


@router.get(
    "/depots/{deposit_id}",
    response_model=GreffeDepositRead,
    summary="Fiche d'un dossier de depot",
)
def get_depot_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> object:
    try:
        return get_depot(db, company.id, deposit_id)
    except GreffeError as exc:
        raise http_error(exc) from exc


@router.get("/depots/{deposit_id}/checklist", summary="Checklist des pieces du dossier")
def checklist_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        depot = get_depot(db, company.id, deposit_id)
        return {
            "depot_id": depot.id,
            "exercice": depot.exercice,
            "forme_juridique": depot.forme_juridique,
            "statut": depot.statut,
            "pieces": checklist(db, depot),
            "completude": taux_completude(db, depot),
        }
    except GreffeError as exc:
        raise http_error(exc) from exc


@router.get("/depots/{deposit_id}/controles", summary="Controles prealables au depot")
def controles_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    try:
        depot = get_depot(db, company.id, deposit_id)
    except GreffeError as exc:
        raise http_error(exc) from exc
    return [
        {**controle, "depot_id": depot.id, "exercice": depot.exercice}
        for controle in controles_depot(db, depot)
    ]


@router.post(
    "/depots/{deposit_id}/pieces",
    response_model=GreffeDocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Televerser une piece PDF du dossier (10 Mo maximum)",
)
def ajouter_piece_route(
    deposit_id: int,
    piece_code: str = Query(..., description="Code du catalogue (ex. pv_ag)"),
    fichier: UploadFile = File(..., description="Piece au format PDF (10 Mo max)"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        depot = get_depot(db, company.id, deposit_id)
        document = ajouter_piece(
            db,
            depot,
            piece_code=piece_code,
            nom_fichier=fichier.filename,
            contenu=fichier.file.read(),
            user_id=user.id,
        )
        db.commit()
    except GreffeError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(document)
    return document


@router.post(
    "/depots/{deposit_id}/pieces/generer",
    summary="Generer les pieces produites par Compta MA (etats de synthese, bordereau)",
)
def generer_pieces_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> dict:
    try:
        depot = get_depot(db, company.id, deposit_id)
        resultat = generer_pieces(db, depot, company=company, user_id=user.id)
        db.commit()
    except (GreffeError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "depot_id": depot.id,
        "documents": [
            {
                "piece_code": document.piece_code,
                "nom_fichier": document.nom_fichier,
                "taille_octets": document.taille_octets,
                "hash_sha256": document.hash_sha256,
                "source": document.source,
            }
            for document in resultat["documents"]
        ],
        "completude": resultat["taux_completude"],
    }


@router.get("/depots/{deposit_id}/pieces/{piece_code}", summary="Telecharger une piece")
def telecharger_piece_route(
    deposit_id: int,
    piece_code: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        depot = get_depot(db, company.id, deposit_id)
        document = next(
            (doc for doc in depot.documents if doc.piece_code == piece_code), None
        )
        if document is None:
            raise GreffeError(f"Piece « {piece_code} » absente du dossier {deposit_id}.")
        return _reponse_pdf(lire_document(document), document.nom_fichier)
    except GreffeError as exc:
        raise http_error(exc) from exc


@router.delete(
    "/depots/{deposit_id}/pieces/{piece_code}",
    summary="Retirer une piece du dossier",
)
def supprimer_piece_route(
    deposit_id: int,
    piece_code: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> dict:
    try:
        depot = get_depot(db, company.id, deposit_id)
        supprime = supprimer_piece(db, depot, piece_code, user_id=user.id)
        db.commit()
    except GreffeError as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {"piece_code": piece_code, "supprime": supprime}


@router.post(
    "/depots/{deposit_id}/etat",
    response_model=GreffeDepositRead,
    summary="Faire evoluer le dossier dans les 7 etats du portail",
)
def changer_etat_route(
    deposit_id: int,
    payload: GreffeEtatRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        depot = get_depot(db, company.id, deposit_id)
        changer_etat(
            db,
            depot,
            payload.etat,
            motif=payload.motif,
            user_id=user.id,
            jour=payload.date_effective,
            forcer_hors_delai=payload.forcer_hors_delai,
        )
        db.commit()
    except (GreffeError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(depot)
    return depot


@router.get(
    "/depots/{deposit_id}/paiements",
    summary="Paiements des taxes : lignes enregistrees, total paye et solde",
)
def paiements_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        depot = get_depot(db, company.id, deposit_id)
    except GreffeError as exc:
        raise http_error(exc) from exc
    return {
        "depot_id": depot.id,
        "exercice": depot.exercice,
        "statut": depot.statut,
        "montant_taxes": str(depot.montant_taxes),
        "total_paye": str(total_paye(db, depot)),
        "solde": str(solde_taxes(db, depot)),
        "date_limite_paiement": depot.date_limite_paiement,
        "paiements": [
            GreffePaymentRead.model_validate(ligne) for ligne in depot.paiements
        ],
    }


@router.post(
    "/depots/{deposit_id}/paiements",
    response_model=GreffePaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer le paiement des taxes (apres approbation)",
)
def enregistrer_paiement_route(
    deposit_id: int,
    payload: GreffePaymentCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        depot = get_depot(db, company.id, deposit_id)
        ligne = enregistrer_paiement(
            db,
            depot,
            montant=payload.montant,
            date_paiement=payload.date_paiement,
            moyen=payload.moyen,
            reference=payload.reference,
            notes=payload.notes,
            user_id=user.id,
        )
        db.commit()
    except (GreffeError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(ligne)
    return ligne


@router.post(
    "/depots/{deposit_id}/certificat",
    response_model=GreffeDepositRead,
    summary="Archiver le certificat de depot (PDF, empreinte SHA-256)",
)
def certificat_route(
    deposit_id: int,
    fichier: UploadFile = File(..., description="Certificat de depot (PDF)"),
    reference: str | None = Query(default=None, max_length=80),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    try:
        depot = get_depot(db, company.id, deposit_id)
        enregistrer_certificat(
            db,
            depot,
            nom_fichier=fichier.filename,
            contenu=fichier.file.read(),
            reference=reference,
            user_id=user.id,
        )
        db.commit()
    except GreffeError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(depot)
    return depot


@router.get(
    "/depots/{deposit_id}/certificat",
    summary="Telecharger le certificat de depot archive",
)
def telecharger_certificat_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        depot = get_depot(db, company.id, deposit_id)
        return _reponse_pdf(
            lire_certificat(depot), depot.certificat_nom or "certificat_depot.pdf"
        )
    except GreffeError as exc:
        raise http_error(exc) from exc


@router.get(
    "/depots/{deposit_id}/dossier",
    summary="Archive ZIP du dossier de depot (pieces PDF + bordereau + manifeste)",
)
def dossier_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        depot = get_depot(db, company.id, deposit_id)
        archive = assembler_dossier(db, company, depot)
    except (GreffeError, ValueError) as exc:
        raise http_error(exc) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="Dossier_greffe_{depot.exercice}.zip"'
            )
        },
    )


@router.get(
    "/depots/{deposit_id}/bordereau",
    summary="Bordereau recapitulatif du dossier (PDF)",
)
def bordereau_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        depot = get_depot(db, company.id, deposit_id)
        pdf = pdf_recapitulatif_dossier(db, company, depot)
    except GreffeError as exc:
        raise http_error(exc) from exc
    return _reponse_pdf(pdf, f"Bordereau_greffe_{depot.exercice}.pdf")


@router.get(
    "/depots/{deposit_id}/attestation-paiement",
    summary="Attestation de paiement des taxes (PDF)",
)
def attestation_route(
    deposit_id: int,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        depot = get_depot(db, company.id, deposit_id)
        pdf = pdf_attestation_paiement(db, company, depot)
    except GreffeError as exc:
        raise http_error(exc) from exc
    return _reponse_pdf(pdf, f"Attestation_paiement_taxes_{depot.exercice}.pdf")


@router.post(
    "/depots/{deposit_id}/amende",
    summary="Provisionner l'amende hors delai (dotation 6195 / provision 1515)",
)
def amende_route(
    deposit_id: int,
    montant: Decimal = Query(..., gt=0, description="Montant de l'amende notifiee"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> dict:
    try:
        depot = get_depot(db, company.id, deposit_id)
        resultat = comptabiliser_amende(
            db, company, depot, montant=montant, user_id=user.id
        )
        db.commit()
    except (GreffeError, ValueError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "depot_id": depot.id,
        "exercice": depot.exercice,
        "montant": str(resultat["montant"]),
        "entry_number": resultat["entry_number"],
        "comptes": resultat["comptes"],
    }


@router.get("/etat", summary="Suivi des depots (7 etats) et completude des dossiers")
def etat_route(
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return etat_depots(db, company.id, exercice=exercice)


@router.get("/alertes", summary="Alertes de delais (3 jours, AG 6 mois, rejet, amende)")
def alertes_route(
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return alertes_greffe(db, company.id, exercice=exercice)
