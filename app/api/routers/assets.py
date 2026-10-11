"""Immobilisations et amortissements (P1.2) : fiches, dotations, cessions, etats."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User
from app.schemas import (
    AssetCessionRequest,
    AssetCreate,
    AssetDotationRequest,
    AssetRead,
    AssetRebutRequest,
)
from app.services.accounting import AccountingError
from app.services.assets import (
    amortissements_cumules,
    amortissements_deductibles,
    ceder_immobilisation,
    comptabiliser_dotation,
    comptabiliser_dotations,
    comptes_immobilisation,
    controles_immobilisations,
    creer_immobilisation,
    etat_immobilisations,
    get_asset,
    list_assets,
    mettre_au_rebut,
    plan_amortissement,
    tableau_cessions,
    valeur_nette_comptable,
)

router = APIRouter(prefix="/assets", tags=["immobilisations"])


@router.get("", response_model=list[AssetRead], summary="Lister les immobilisations")
def list_assets_route(
    statut: str | None = Query(default=None, description="en_service, cede ou rebut"),
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    return list_assets(db, company.id, statut=statut, exercice=exercice)


@router.get("/etat", summary="Etat des immobilisations (brut / amortissements / net)")
def etat_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return etat_immobilisations(db, company.id, exercice)


@router.get("/cessions", summary="Tableau des cessions et mises au rebut de l'exercice")
def cessions_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return tableau_cessions(db, company.id, exercice)


@router.get(
    "/amortissements",
    summary="Amortissements de l'exercice (fiscalement deductibles, CGI art. 10)",
)
def amortissements_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return amortissements_deductibles(db, company.id, exercice)


@router.get("/controles", summary="Controles de coherence du module (avertissements)")
def controles_route(
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return controles_immobilisations(db, company.id, exercice)


@router.get("/comptes/{account_number}", summary="Comptes derives d'un compte 2xxx")
def comptes_route(
    account_number: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return comptes_immobilisation(db, account_number)


@router.post(
    "",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer une fiche d'immobilisation",
)
def add_asset(
    payload: AssetCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> object:
    try:
        asset = creer_immobilisation(
            db, company=company, user_id=user.id, **payload.model_dump()
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(asset)
    return asset


@router.post(
    "/dotations",
    summary="Constater les dotations de toutes les immobilisations en service",
)
def post_dotations(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> list[dict]:
    try:
        resultats = comptabiliser_dotations(db, company, exercice, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    return [
        {
            "code": resultat["asset"].code,
            "exercice": resultat["exercice"],
            "annuite": resultat.get("annuite"),
            "entry_number": resultat.get("entry_number"),
            "erreur": resultat["erreur"],
        }
        for resultat in resultats
    ]


@router.get("/{code}", summary="Fiche d'immobilisation et plan d'amortissement")
def get_asset_route(
    code: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    asset = get_asset(db, company.id, code)
    cumul = amortissements_cumules(asset)
    return {
        "asset": AssetRead.model_validate(asset).model_dump(),
        "plan": plan_amortissement(asset),
        "comptes": comptes_immobilisation(db, asset.account_number),
        "amortissements_cumules": cumul,
        "vnc": valeur_nette_comptable(asset),
    }



@router.post("/{code}/dotation", summary="Constater la dotation d'un exercice")
def post_dotation(
    code: str,
    payload: AssetDotationRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    asset = get_asset(db, company.id, code)
    try:
        operation = comptabiliser_dotation(
            db,
            asset,
            payload.exercice,
            user_id=user.id,
            journal_code=payload.journal_code,
            date_ecriture=payload.date_ecriture,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "code": asset.code,
        "exercice": operation["exercice"],
        "annuite": operation["annuite"],
        "cumul": operation["cumul"],
        "vnc": operation["vnc"],
        "compte_dotation": operation["compte_dotation"],
        "compte_amortissement": operation["compte_amortissement"],
        "entry_number": operation["entry_number"],
    }


@router.post("/{code}/cession", summary="Ceder une immobilisation (sortie d'actif)")
def post_cession(
    code: str,
    payload: AssetCessionRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    asset = get_asset(db, company.id, code)
    try:
        resultat = ceder_immobilisation(
            db,
            asset,
            date_cession=payload.date_cession,
            prix=payload.prix,
            tva_taux=payload.tva_taux,
            compte_encaissement=payload.compte_encaissement,
            regulariser_tva=payload.regulariser_tva,
            motif=payload.motif,
            user_id=user.id,
            journal_code=payload.journal_code,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "code": asset.code,
        "cumul": resultat["cumul"],
        "vnc": resultat["vnc"],
        "prix": resultat["prix"],
        "resultat_cession": resultat["resultat_cession"],
        "regularisation_tva": resultat["regularisation"]["montant"],
        "regularisation": resultat["regularisation"],
        "entry_number": resultat["entry_number"],
    }


@router.post("/{code}/rebut", summary="Mettre une immobilisation au rebut")
def post_rebut(
    code: str,
    payload: AssetRebutRequest,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    asset = get_asset(db, company.id, code)
    try:
        resultat = mettre_au_rebut(
            db,
            asset,
            date_rebut=payload.date_rebut,
            motif=payload.motif,
            regulariser_tva=payload.regulariser_tva,
            user_id=user.id,
            journal_code=payload.journal_code,
        )
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "code": asset.code,
        "vnc": resultat["vnc"],
        "regularisation_tva": resultat["regularisation"]["montant"],
        "entry_number": resultat["entry_number"],
    }

