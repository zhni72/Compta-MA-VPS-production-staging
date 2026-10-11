"""TVA : taux, regime declaratif, declaration periodique."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_company, get_current_user
from app.api.errors import http_error
from app.db.session import get_db
from app.models import Company, User, VatRate
from app.services.accounting import AccountingError
from app.services.edi_tva import (
    BASE_PERIODE_DEFAUT,
    EdiTvaError,
    build_rd_xml,
    collect_rd_lines,
    controle_taille,
    limite_lignes,
    regime_code,
    xml_filename,
)
from app.services.pdf_documents import nom_fichier_pdf, pdf_bordereau_tva
from app.services.vat import (
    period_bounds,
    suggested_vat_regime,
    vat_return,
    vat_summary_by_rate,
)

router = APIRouter(prefix="/vat", tags=["TVA"])


def _resolve_period(
    year: int, month: int | None, quarter: int | None
) -> tuple[date, date]:
    try:
        return period_bounds(year, month=month, quarter=quarter)
    except AccountingError as exc:
        raise http_error(exc) from exc


@router.get("/rates", summary="Taux de TVA en vigueur (bareme 2026 : 20 % et 10 %)")
def list_rates(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[dict]:
    rows = db.execute(select(VatRate).order_by(VatRate.rate.desc())).scalars()
    return [rate.as_dict() for rate in rows]


@router.get("/regime", summary="Regime declaratif suggere selon le chiffre d'affaires")
def regime(
    ca_annuel: float = Query(..., ge=0, description="Chiffre d'affaires annuel en MAD"),
    _: User = Depends(get_current_user),
) -> dict:
    suggested = suggested_vat_regime(ca_annuel)
    return {
        "ca_annuel": ca_annuel,
        "regime": suggested,
        "echeance": "le 20 du mois suivant (regime mensuel)"
        if suggested == "mensuel"
        else "le 20 du mois suivant le trimestre",
        "seuil_mensuel": 1000000,
    }


@router.get("/return", summary="Declaration de TVA d'une periode (mois ou trimestre)")
def get_return(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12, description="Regime mensuel"),
    quarter: int | None = Query(default=None, ge=1, le=4, description="Regime trimestriel"),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if month is None and quarter is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Precisez le mois (regime mensuel) ou le trimestre (regime trimestriel)",
        )
    date_from, date_to = _resolve_period(year, month, quarter)
    result = vat_return(db, company.id, date_from, date_to)
    result["regime"] = company.vat_regime
    result["periode"] = (
        f"{month:02d}/{year}" if month else f"T{quarter} {year}"
    )
    return result


@router.get(
    "/summary-by-rate",
    summary="Récapitulatif par taux de TVA (ventes = collectée, achats = déductible)",
)
def get_summary_by_rate(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    type: str | None = Query(
        default="vente",
        description="vente (TVA collectée), achat (TVA déductible) ou vide pour les deux",
    ),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    date_from, date_to = _resolve_period(year, month, quarter)
    type_facture = type if type in ("vente", "achat") else None
    return vat_summary_by_rate(
        db, company.id, date_from, date_to, invoice_type=type_facture
    )


# ---------------------------------------------------------------------------
# Export EDI : releve des deductions de TVA (SIMPL-TVA / DGI)
# ---------------------------------------------------------------------------
@router.get(
    "/edi/check",
    summary="Controles prealables du releve des deductions (anomalies a corriger)",
)
def edi_check(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    include_zero_vat: bool = Query(default=False),
    max_lignes: int | None = Query(
        default=None,
        ge=1,
        description="Limite de lignes du releve (<ord>) ; defaut : settings.max_rd_lines (127)",
    ),
    base_periode: str = Query(
        default=BASE_PERIODE_DEFAUT,
        description="paiement (regime de l'encaissement, defaut) ou facture",
    ),
    prorata: float = Query(
        default=1,
        gt=0,
        le=1,
        description="Prorata de deduction de la TVA (CGI art. 106) : 1 = 100 %",
    ),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    date_from, date_to = _resolve_period(year, month, quarter)
    regime = regime_code(company)
    try:
        collecte = collect_rd_lines(
            db,
            company,
            date_from,
            date_to,
            include_zero_vat=include_zero_vat,
            prorata=Decimal(str(prorata)),
            base_periode=base_periode,
        )
    except EdiTvaError as exc:
        raise http_error(exc) from exc
    return {
        "company_id": company.id,
        "date_from": date_from,
        "date_to": date_to,
        "regime": regime,
        "base_periode": collecte["base_periode"],
        "prorata": str(collecte["prorata"]),
        "limite_lignes": limite_lignes(max_lignes),
        "regime_libelle": "mensuel" if regime == 1 else "trimestriel",
        "identifiant_fiscal": company.fiscal_id,
        "lignes": [ligne.as_dict() for ligne in collecte["lignes"]],
        "exclues": collecte["exclues"],
        "anomalies": collecte["anomalies"],
        "totaux": collecte["totaux"],
    }


@router.get(
    "/edi/rd",
    summary="Fichier XML du releve des deductions TVA (a deposer sur Simpl-TVA)",
    response_class=Response,
)
def edi_rd(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    tx_unit: str = Query(default="percent", description="percent (20) ou ratio (0.20)"),
    include_zero_vat: bool = Query(default=False),
    max_lignes: int | None = Query(
        default=None,
        ge=1,
        description="Limite de lignes du releve (<ord>) ; defaut : settings.max_rd_lines (127)",
    ),
    inclure_prorata: bool = Query(
        default=False,
        description="Ajouter la balise <prorata> (absente du XSD officiel DGI)",
    ),
    blocage_anomalies: bool = Query(
        default=True,
        description="Refuser la generation si une anomalie bloquante est detectee",
    ),
    base_periode: str = Query(
        default=BASE_PERIODE_DEFAUT,
        description="paiement (regime de l'encaissement, defaut) ou facture",
    ),
    prorata: float = Query(
        default=1,
        gt=0,
        le=1,
        description="Prorata de deduction de la TVA (CGI art. 106) : 1 = 100 %",
    ),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    date_from, date_to = _resolve_period(year, month, quarter)
    regime = regime_code(company)
    periode = month or quarter or 0
    try:
        collecte = collect_rd_lines(
            db,
            company,
            date_from,
            date_to,
            include_zero_vat=include_zero_vat,
            prorata=Decimal(str(prorata)),
            base_periode=base_periode,
        )
        bloquantes = [a for a in collecte["anomalies"] if a["bloquant"]]
        if blocage_anomalies and bloquantes:
            raise EdiTvaError(
                "Anomalies bloquantes a corriger avant export : "
                + " | ".join(f"{a['reference']} : {a['motif']}" for a in bloquantes[:5])
            )
        xml = build_rd_xml(
            identifiant_fiscal=company.fiscal_id or "",
            annee=year,
            periode=periode,
            regime=regime,
            lignes=collecte["lignes"],
            tx_unit=tx_unit,
            declarant_nom=company.name,
            inclure_prorata=inclure_prorata,
            max_lignes=max_lignes,
        )
        controle_taille(xml)
    except EdiTvaError as exc:
        raise http_error(exc) from exc
    nom = xml_filename(year, periode, regime)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get(
    "/edi/bordereau",
    summary="Bordereau recapitulatif du releve des deductions TVA (PDF, avant depot)",
    response_class=Response,
)
def edi_bordereau(
    year: int = Query(..., ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    """PDF recapitulant exactement les totaux, exclusions et anomalies du XML."""
    try:
        pdf = pdf_bordereau_tva(db, company, year, month=month, quarter=quarter)
    except AccountingError as exc:
        raise http_error(exc) from exc
    nom = nom_fichier_pdf(
        "Bordereau_TVA", year, f"P{month or quarter or 0}", company.name
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )
