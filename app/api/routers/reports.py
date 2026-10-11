"""Etats comptables : balance, grand livre, journaux, CPC, bilan."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User
from app.services.accounting import AccountingError
from app.services.etats_synthese import etat_soldes_gestion, notes_etic
from app.services.pdf_documents import (
    nom_fichier_pdf,
    pdf_bilan,
    pdf_bordereau_greffe,
    pdf_cpc,
    pdf_esg,
    pdf_etic,
)
from app.services.reporting import (
    balance_generale,
    balance_sheet,
    grand_livre,
    income_statement,
    journal_entries,
    year_bounds,
)
from app.services.vat import period_bounds

router = APIRouter(prefix="/reports", tags=["etats comptables"])


def _period(
    year: int, month: int | None, quarter: int | None
) -> tuple[date, date]:
    """Periode d'edition : mois, trimestre, ou exercice complet par defaut."""
    if month is None and quarter is None:
        return year_bounds(year)
    try:
        return period_bounds(year, month=month, quarter=quarter)
    except AccountingError as exc:
        raise http_error(exc) from exc


@router.get("/balance", summary="Balance generale (mouvements et soldes par compte)")
def get_balance(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    prefix: str | None = Query(default=None, description="Ex. 61 pour la classe 61xx"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _period(year, month, quarter)
    return balance_generale(db, company.id, date_from, date_to, prefix=prefix)


@router.get("/grand-livre", summary="Grand livre d'un compte (utilisez * comme joker)")
def get_grand_livre(
    account_number: str = Query(..., description="Ex. 3421* pour tous les clients"),
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _period(year, month, quarter)
    return grand_livre(db, company.id, account_number, date_from, date_to)


@router.get("/journal", summary="Ecritures d'un journal (AC, VE, BQ, CA, OD)")
def get_journal(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    journal_code: str | None = Query(default=None),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    date_from, date_to = _period(year, month, quarter)
    return journal_entries(db, company.id, date_from, date_to, journal_code=journal_code)


@router.get("/cpc", summary="CPC simplifie : charges, produits et resultat")
def get_cpc(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _period(year, month, quarter)
    return income_statement(db, company.id, date_from, date_to)




# ---------------------------------------------------------------------------
# Etats CGNC complementaires et documents PDF (jalon J1)
# ---------------------------------------------------------------------------
@router.get("/esg", summary="Etat des Soldes de Gestion (marge brute, VA, EBE, resultats)")
def get_esg(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _period(year, month, quarter)
    resultat = etat_soldes_gestion(db, company.id, date_from, date_to)
    return {**resultat, "soldes": [{"libelle": l, "montant": m} for l, m in resultat["soldes"]]}


@router.get("/etic", summary="Etat des Informations Complementaires (notes annexes)")
def get_etic(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _period(year, month, quarter)
    notes = notes_etic(db, company.id, date_from, date_to)
    return {
        "notes": [
            {
                "numero": note["numero"],
                "titre": note["titre"],
                "lignes": note["lignes"],
                "total": note["total"],
                "commentaire": note["commentaire"],
            }
            for note in notes["notes"]
        ],
        "indisponibles": [
            {"information": information, "origine": origine}
            for information, origine in notes["indisponibles"]
        ],
    }


def _pdf(pdf: bytes, nom_fichier: str) -> Response:
    """Reponse de telechargement PDF (API)."""
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@router.get(
    "/bordereau-greffe/pdf",
    summary="Bordereau et checklist du depot des etats de synthese au greffe",
)
def get_bordereau_greffe(
    year: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    pdf = pdf_bordereau_greffe(db, company, year)
    return _pdf(pdf, nom_fichier_pdf("Bordereau_greffe", year, company.name))


@router.get("/{etat}/pdf", summary="Etat de synthese au format PDF (bilan, cpc, esg, etic)")
def get_etat_pdf(
    etat: str,
    year: int = Query(..., ge=2000, le=2100),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    generateurs = {
        "bilan": pdf_bilan,
        "cpc": pdf_cpc,
        "esg": pdf_esg,
        "etic": pdf_etic,
    }
    generateur = generateurs.get(etat.lower())
    if generateur is None:
        raise HTTPException(
            status_code=400, detail="Etat inconnu (bilan, cpc, esg, etic)"
        )
    pdf = generateur(db, company, year)
    return _pdf(pdf, nom_fichier_pdf(etat.upper(), year, company.name))


@router.get("/bilan", summary="Bilan simplifie (controle d'equilibre inclus)")
def get_bilan(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _period(year, month, quarter)
    return balance_sheet(db, company.id, date_from, date_to)