"""Stocks et inventaire permanent (P1.3) : articles, mouvements, inventaire, etats."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user, require_roles
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User
from app.schemas import (
    StockCountCreate,
    StockItemCreate,
    StockItemRead,
    StockMovementCreate,
    StockProvisionCreate,
)
from app.services.accounting import AccountingError
from app.services.stocks import (
    StockError,
    comptabiliser_mouvement,
    comptabiliser_mouvements,
    constater_stock_final,
    controles_stocks,
    cout_fifo,
    creer_article,
    enregistrer_mouvement,
    etat_article,
    etat_provisions,
    etat_stocks,
    get_item,
    inventaire_physique,
    inventaire_valorise,
    list_items,
    provisionner_stock,
    variation_stocks,
)

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("", response_model=list[StockItemRead], summary="Lister les articles")
def list_stock_items(
    sous_seuil: bool = Query(default=False, description="Uniquement les articles sous seuil"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list:
    return list_items(db, company.id, sous_seuil=sous_seuil)


@router.post(
    "",
    response_model=StockItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer une fiche article",
)
def add_stock_item(
    payload: StockItemCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> object:
    try:
        article = creer_article(db, company=company, user_id=user.id, **payload.model_dump())
        db.commit()
    except (AccountingError, StockError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    db.refresh(article)
    return article


@router.get("/etat", summary="Etat de stock valorise (quantite, CMUP, valeur)")
def etat_stocks_route(
    au: date | None = Query(default=None),
    sous_seuil: bool = Query(default=False),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return etat_stocks(db, company.id, au=au, sous_seuil=sous_seuil)


@router.get("/inventaire", summary="Feuille d'inventaire physique (quantites theoriques)")
def inventaire_route(
    au: date | None = Query(default=None),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return inventaire_valorise(db, company.id, au=au)


@router.get("/variation", summary="Variation de stocks de l'exercice")
def variation_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return variation_stocks(db, company.id, exercice)


@router.get("/provisions", summary="Depreciations de stocks de l'exercice")
def provisions_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return etat_provisions(db, company.id, exercice)


@router.get("/controles", summary="Controles de coherence du module stocks")
def controles_route(
    exercice: int | None = Query(default=None, ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return controles_stocks(db, company.id, exercice)


@router.post(
    "/journal",
    summary="Constater le stock final et la variation (regime intermittent)",
)
def stock_final_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    try:
        resultat = constater_stock_final(db, company, exercice, user_id=user.id)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise http_error(exc) from exc
    resultat.pop("entry", None)
    return resultat


@router.post(
    "/mouvements/comptabiliser",
    summary="Comptabiliser les mouvements non ecrits (inventaire permanent)",
)
def comptabiliser_route(
    exercice: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> list[dict]:
    resultats = comptabiliser_mouvements(db, company, exercice, user_id=user.id)
    db.commit()
    return [
        {
            "movement_id": resultat["mouvement"].id,
            "entry_number": resultat.get("entry_number"),
            "erreur": resultat["erreur"],
        }
        for resultat in resultats
    ]


@router.post(
    "/inventaire",
    status_code=status.HTTP_201_CREATED,
    summary="Saisir un inventaire physique (ecarts valorises et ecritures)",
)
def inventaire_physique_route(
    payload: StockCountCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    try:
        comptage = inventaire_physique(
            db,
            company=company,
            count_date=payload.count_date,
            lignes=payload.lignes,
            label=payload.label,
            note=payload.note,
            visumotif=payload.visumotif,
            comptabiliser=payload.comptabiliser,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, StockError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "count_id": comptage.id,
        "status": comptage.status,
        "nb_lignes": len(comptage.lines),
        "nb_ecarts": len(comptage.ecarts),
        "ecart_valeur": comptage.total_ecart_valeur,
    }



@router.get("/{reference}", summary="Fiche article : etat et mouvements")
def get_stock_item(
    reference: str,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    article = get_item(db, company.id, reference)
    etat = etat_article(article)
    return {
        "article": StockItemRead.model_validate(article).model_dump(),
        "etat": {
            "quantity": etat["quantity"],
            "value": etat["value"],
            "cmup": etat["cmup"],
            "nb_mouvements": etat["nb_mouvements"],
        },
        "couches_fifo": (
            cout_fifo(article, Decimal("0.001"))["couches"]
            if article.valuation_method == "fifo"
            else []
        ),
        "mouvements": [
            {
                "id": mouvement.id,
                "date": mouvement.movement_date,
                "type": mouvement.movement_type,
                "reason": mouvement.reason,
                "quantity": mouvement.quantity,
                "unit_cost": mouvement.unit_cost,
                "value": mouvement.value,
                "entry_id": mouvement.entry_id,
            }
            for mouvement in sorted(
                article.movements,
                key=lambda mouvement: (mouvement.movement_date, mouvement.id or 0),
            )
        ],
    }


@router.post(
    "/{reference}/mouvements",
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un mouvement de stock (entree ou sortie valorisee)",
)
def add_stock_movement(
    reference: str,
    payload: StockMovementCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    try:
        article = get_item(db, company.id, reference)
        mouvement = enregistrer_mouvement(
            db,
            article=article,
            movement_date=payload.movement_date,
            movement_type=payload.movement_type,
            quantity=payload.quantity,
            reason=payload.reason,
            unit_cost=payload.unit_cost,
            label=payload.label,
            reference=payload.reference,
            invoice_id=payload.invoice_id,
            allow_negative=payload.allow_negative,
            user_id=user.id,
        )
        operation = (
            comptabiliser_mouvement(db, mouvement, user_id=user.id)
            if payload.comptabiliser
            else None
        )
        db.commit()
    except (AccountingError, StockError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "movement_id": mouvement.id,
        "quantity": mouvement.quantity,
        "unit_cost": mouvement.unit_cost,
        "value": mouvement.value,
        "etat": etat_article(article)["value"],
        "entry_number": operation["entry_number"] if operation else None,
    }


@router.post(
    "/{reference}/provisions",
    status_code=status.HTTP_201_CREATED,
    summary="Deprecier un stock (prudence) ou reprendre la depreciation",
)
def add_stock_provision(
    reference: str,
    payload: StockProvisionCreate,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "EXPERT_COMPTABLE", "COMPTABLE")),
) -> dict:
    try:
        article = get_item(db, company.id, reference)
        resultat = provisionner_stock(
            db,
            article,
            payload.exercice,
            inventory_value=payload.inventory_value,
            motif=payload.motif,
            user_id=user.id,
        )
        db.commit()
    except (AccountingError, StockError) as exc:
        db.rollback()
        raise http_error(exc) from exc
    return {
        "provision": resultat["provision"].provision,
        "dotation": resultat["dotation"],
        "compte_provision": resultat["compte_provision"],
        "entry_number": resultat["entry_number"],
    }

