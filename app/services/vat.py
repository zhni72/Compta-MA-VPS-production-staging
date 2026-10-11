"""TVA : regime declaratif, declaration periodique, echeances.

Bareme 2026 : uniquement 20 % (normal) et 10 % (reduit). Regime mensuel si le
chiffre d'affaires est >= 1 000 000 MAD, trimestriel en dessous ; depot et
paiement le 20 du mois suivant la periode (portail SIMPL-TVA de la DGI).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rates_ma import VAT_DECLARATION_THRESHOLD, money
from app.models import (
    INVOICE_STATUS_CANCELLED,
    INVOICE_STATUS_DRAFT,
    Invoice,
    InvoiceLine,
)
from app.services.accounting import AccountingError
from app.services.reporting import movements

VAT_COLLECTED_PREFIX = "4455"
VAT_DEDUCTIBLE_PREFIX = "3455"


def suggested_vat_regime(ca_annuel: Decimal | int | float | str) -> str:
    """Regime de declaration TVA selon le chiffre d'affaires annuel."""
    return (
        "mensuel"
        if Decimal(str(ca_annuel)) >= VAT_DECLARATION_THRESHOLD
        else "trimestriel"
    )


def _end_of_month(year: int, month: int) -> date:
    return (
        date(year, 12, 31)
        if month == 12
        else date(year, month + 1, 1) - timedelta(days=1)
    )


def period_bounds(
    year: int, month: int | None = None, quarter: int | None = None
) -> tuple[date, date]:
    """Bornes de la periode declarative (mois en regime mensuel, sinon trimestre)."""
    if month:
        return date(year, month, 1), _end_of_month(year, month)
    if quarter:
        if quarter not in (1, 2, 3, 4):
            raise AccountingError("Trimestre invalide (1 a 4)")
        start_month = 3 * (quarter - 1) + 1
        return date(year, start_month, 1), _end_of_month(year, start_month + 2)
    raise AccountingError("Precisez le mois (regime mensuel) ou le trimestre")


def vat_deadline(date_to: date) -> date:
    """Echeance legale : le 20 du mois suivant la periode declairee."""
    if date_to.month == 12:
        return date(date_to.year + 1, 1, 20)
    return date(date_to.year, date_to.month + 1, 20)


def vat_return(
    db: Session, company_id: int, date_from: date, date_to: date
) -> dict:
    """Declaration de TVA d'une periode : collectee, deductible, net, credit."""
    rows = movements(db, company_id, date_from, date_to)
    collectee = money(
        sum(
            (-r["solde"] for r in rows if r["account_number"].startswith(VAT_COLLECTED_PREFIX)),
            Decimal("0"),
        )
    )
    deductible = money(
        sum(
            (r["solde"] for r in rows if r["account_number"].startswith(VAT_DEDUCTIBLE_PREFIX)),
            Decimal("0"),
        )
    )
    nette = money(collectee - deductible)
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "tva_collectee": collectee,
        "tva_deductible": deductible,
        "tva_nette": nette,
        "tva_a_payer": nette if nette > 0 else money(0),
        "credit_tva_a_reporter": money(-nette) if nette < 0 else money(0),
        "echeance": vat_deadline(date_to),
        "detail": [
            r
            for r in rows
            if r["account_number"].startswith((VAT_COLLECTED_PREFIX, VAT_DEDUCTIBLE_PREFIX))
        ],
    }


def vat_summary_by_rate(
    db: Session,
    company_id: int,
    date_from: date,
    date_to: date,
    invoice_type: str | None = None,
) -> list[dict]:
    """Recapitulatif par taux de TVA (base, TVA, TTC) sur une periode.

    `invoice_type` :
      - "vente" : TVA collectee (a declarer) ;
      - "achat" : TVA deductible (releve des deductions) ;
      - None : agrege les deux (controle interne uniquement).

    Le filtrage par type est indispensable : agreger ventes et achats fausse
    toute lecture de la declaration (defaut corrige).
    """
    stmt = (
        select(
            InvoiceLine.vat_rate,
            func.sum(InvoiceLine.line_ht),
            func.sum(InvoiceLine.line_vat),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            Invoice.company_id == company_id,
            Invoice.status.notin_(
                (INVOICE_STATUS_DRAFT, INVOICE_STATUS_CANCELLED)
            ),
            Invoice.invoice_date >= date_from,
            Invoice.invoice_date <= date_to,
        )
        .group_by(InvoiceLine.vat_rate)
        .order_by(InvoiceLine.vat_rate)
    )
    if invoice_type:
        stmt = stmt.where(Invoice.invoice_type == invoice_type)
    return [
        {
            "vat_rate": rate,
            "base_ht": money(base or 0),
            "tva": money(tva or 0),
            "ttc": money((base or 0) + (tva or 0)),
        }
        for rate, base, tva in db.execute(stmt).all()
    ]