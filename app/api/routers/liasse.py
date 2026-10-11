"""Liasse fiscale EDI Simpl-IS (P2.1) : assembleur, XML validé, EFI, dépôt."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User
from app.schemas import (
    LiasseEnregistrementRequest,
    LiasseSoumissionRequest,
    TaxDeclarationRead,
)
from app.services.accounting import NotFoundError
from app.services.liasse_edi import (
    MODELE_PAR_DEFAUT,
    LiasseError,
    declaration_liasse,
    dossier_liasse,
    enregistrer_liasse,
    efi_liasse_csv,
    list_declarations,
    produire_liasse_xml,
    soumettre_declaration,
)

router = APIRouter(prefix="/liasse", tags=["liasse"])

MUTATION_ROLES = ("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")
# Le dépôt et l'accusé de réception engagent la société : ADMIN / EXPERT_COMPTABLE.
DEPOT_ROLES = ("ADMIN", "EXPERT_COMPTABLE")


def _reponse_fichier(contenu: bytes, nom: str, media_type: str) -> Response:
    """Réponse de téléchargement (fichier EDI ou état EFI)."""
    return Response(
        content=contenu,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get(
    "/declarations",
    response_model=list[TaxDeclarationRead],
    summary="Registre des liasses déposées",
)
def list_declarations_route(
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    return list_declarations(db, company.id)


@router.get("/{annee}", summary="Dossier de liasse d'un exercice (IS / liasse / contrôles)")
def dossier_liasse_route(
    annee: int,
    modele: str = Query(default=MODELE_PAR_DEFAUT, description="Modèle du schéma XSD"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        dossier = dossier_liasse(db, company, annee, modele=modele)
    except LiasseError as exc:
        raise http_error(exc) from exc
    dossier["liasse"].pop("contrat", None)  # structure du schéma (objet technique)
    return dossier


@router.get("/{annee}/efi", summary="EFI assisté par tableau (saisie SIMPL)")
def efi_route(
    annee: int,
    modele: str = Query(default=MODELE_PAR_DEFAUT),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    try:
        dossier = dossier_liasse(db, company, annee, modele=modele)
    except LiasseError as exc:
        raise http_error(exc) from exc
    feuilles = dossier["efi"]
    return {
        "annee": annee,
        "modele": dossier["modele"],
        "feuilles": feuilles,
        "nb_tableaux": len(feuilles),
        "nb_lignes": sum(feuille["nb_lignes"] for feuille in feuilles),
        "nb_a_completer": sum(feuille["nb_a_completer"] for feuille in feuilles),
    }


@router.get("/{annee}/efi.csv", summary="Export CSV de l'état de saisie EFI")
def efi_csv_route(
    annee: int,
    modele: str = Query(default=MODELE_PAR_DEFAUT),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    try:
        liasse = dossier_liasse(db, company, annee, modele=modele)["liasse"]
    except LiasseError as exc:
        raise http_error(exc) from exc
    return _reponse_fichier(
        efi_liasse_csv(liasse),
        f"LIASSE_EFI_{annee}_{company.fiscal_id or 'IF'}.csv",
        "text/csv",
    )


@router.get("/{annee}/validation-xsd", summary="Validation du fichier contre le schéma XSD")
def validation_xsd_route(
    annee: int,
    modele: str = Query(default=MODELE_PAR_DEFAUT),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Valide le fichier produit : **conforme**, **refusé** ou validation **impossible**.

    Les contrôles bloquants sont renvoyés à part : la réponse ne déclare jamais un
    fichier conforme sans le résultat du schéma XSD.
    """
    try:
        production = produire_liasse_xml(db, company, annee, modele=modele, forcer=True)
    except LiasseError as exc:
        raise http_error(exc) from exc
    return {
        "annee": annee,
        "modele": production["modele"],
        "nom_fichier": production["nom_fichier"],
        "taille": production["taille"],
        "validation": production["validation"],
        "bloquants": production["bloquants"],
    }


@router.get("/{annee}/xml", summary="Fichier XML EDI de la liasse (validé par XSD)")
def xml_route(
    annee: int,
    modele: str = Query(default=MODELE_PAR_DEFAUT),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    """Fichier EDI : **refusé** si un contrôle bloquant subsiste ou si le XSD le rejette."""
    try:
        production = produire_liasse_xml(db, company, annee, modele=modele)
    except LiasseError as exc:
        raise http_error(exc) from exc
    return _reponse_fichier(
        production["xml"].encode("utf-8"), production["nom_fichier"], "application/xml"
    )


@router.post(
    "/{annee}/enregistrer",
    response_model=TaxDeclarationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer la liasse (tableaux, cellules, déclaration)",
)
def enregistrer_route(
    annee: int,
    payload: LiasseEnregistrementRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MUTATION_ROLES)),
) -> object:
    modele = payload.modele or MODELE_PAR_DEFAUT
    try:
        liasse = dossier_liasse(db, company, annee, modele=modele)["liasse"]
        xml = None
        validation = None
        if payload.avec_xml:
            production = produire_liasse_xml(db, company, annee, modele=modele)
            xml = production["xml"]
            validation = production["validation"]
        declaration = enregistrer_liasse(
            db,
            company,
            liasse,
            mode_depot=payload.mode_depot,
            xml=xml,
            validation=validation,
            user_id=user.id,
        )
        db.commit()
    except LiasseError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(declaration)
    return declaration


@router.post(
    "/{annee}/depot",
    response_model=TaxDeclarationRead,
    summary="Déposer la liasse et enregistrer l'accusé de réception",
)
def depot_route(
    annee: int,
    payload: LiasseSoumissionRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*DEPOT_ROLES)),
) -> object:
    declaration = declaration_liasse(db, company.id, annee)
    if declaration is None:
        raise http_error(
            NotFoundError(
                f"Aucune liasse enregistrée pour {annee} : enregistrez-la avant le dépôt."
            )
        )
    try:
        declaration = soumettre_declaration(
            db,
            declaration,
            jour=payload.jour,
            accuse_le=payload.accuse_le,
            motif_rejet=payload.motif_rejet,
            user_id=user.id,
        )
        db.commit()
    except LiasseError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(declaration)
    return declaration