"""Service comptable : creation, validation et contre-ecriture des ecritures.

Regles appliquees (conformite CGNC) :
- une ecriture doit etre equilibree (debit = credit) ;
- une ecriture validee est IMMUABLE : la correction se fait par contre-ecriture ;
- aucune ecriture n'est acceptee sur un exercice clos ou verrouille ;
- chaque operation est tracee dans le journal d'audit.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_action
from app.core.numbering import next_document_number
from app.core.rates_ma import money
from app.models import (
    ENTRY_STATUS_DRAFT,
    ENTRY_STATUS_VALIDATED,
    Account,
    Entry,
    EntryLine,
    FiscalYear,
    Journal,
)


class AccountingError(Exception):
    """Erreur metier comptable (message destine a l'utilisateur)."""


class NotFoundError(AccountingError):
    pass


class EntryNotBalancedError(AccountingError):
    pass


class EntryImmutableError(AccountingError):
    pass


class FiscalYearClosedError(AccountingError):
    pass


class PeriodLockedError(FiscalYearClosedError):
    """Periode (mois ou exercice) verrouillee : saisie et modification interdites (P1.6)."""


class ChainIntegrityError(AccountingError):
    """Rupture de chainage de la piste d'audit : dossier altere hors application (P1.6)."""


class ComplianceError(AccountingError):
    """Non-respect d'une obligation legale (ex. ICE manquant sur une facture)."""


def get_fiscal_year(db: Session, company_id: int, year: int) -> FiscalYear:
    fiscal_year = db.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company_id, FiscalYear.year == year
        )
    ).scalar_one_or_none()
    if fiscal_year is None:
        raise NotFoundError(f"Aucun exercice {year} pour la societe {company_id}")
    return fiscal_year


def get_journal(db: Session, company_id: int, code: str) -> Journal:
    journal = db.execute(
        select(Journal).where(Journal.company_id == company_id, Journal.code == code)
    ).scalar_one_or_none()
    if journal is None:
        raise NotFoundError(f"Journal {code} introuvable pour la societe {company_id}")
    return journal


def ensure_period_open(fiscal_year: FiscalYear) -> None:
    """Refuse toute ecriture sur un exercice clos ou verrouille."""
    if fiscal_year.status != "open":
        raise FiscalYearClosedError(
            f"Exercice {fiscal_year.year} en statut '{fiscal_year.status}' : "
            "saisie interdite (reouverture par l'expert-comptable requise)"
        )


def assert_editable(entry: Entry) -> None:
    if entry.status != ENTRY_STATUS_DRAFT:
        raise EntryImmutableError(
            f"Ecriture {entry.id} validee le {entry.validated_at} : "
            "immuable. Utilisez une contre-ecriture."
        )


def create_entry(
    db: Session,
    *,
    company_id: int,
    fiscal_year: FiscalYear,
    journal: Journal,
    entry_date: date,
    label: str,
    lines: list[dict],
    reference: str | None = None,
    notes: str | None = None,
    source: str = "manual",
    source_id: int | None = None,
    created_by: int | None = None,
    validate: bool = False,
) -> Entry:
    """Cree une ecriture comptable a partir d'une liste de lignes.

    Chaque ligne : {"account_number", "debit", "credit", "label",
                    "third_party_id", "vat_rate"}.
    """
    ensure_period_open(fiscal_year)
    # P1.6 — refus dur si la periode (mois ou exercice) est verrouillee, avec trace
    # de la tentative dans le journal d'audit (import differe : anti-cycle).
    from app.services.period_locks import controler_periode

    controler_periode(
        db,
        company_id,
        entry_date,
        user_id=created_by,
        operation=f"ecriture ({source})",
    )
    if not lines:
        raise AccountingError("Une ecriture doit contenir au moins une ligne")

    entry = Entry(
        company_id=company_id,
        fiscal_year_id=fiscal_year.id,
        journal_id=journal.id,
        entry_date=entry_date,
        label=label,
        reference=reference,
        notes=notes,
        source=source,
        source_id=source_id,
        created_by=created_by,
        status=ENTRY_STATUS_DRAFT,
    )
    db.add(entry)
    db.flush()

    for position, raw in enumerate(lines):
        debit = money(raw.get("debit") or 0)
        credit = money(raw.get("credit") or 0)
        if debit < 0 or credit < 0:
            raise AccountingError("Les montants au debit et au credit doivent etre positifs")
        if debit and credit:
            raise AccountingError(
                f"Ligne {position + 1} : une ligne ne peut etre a la fois au debit et au credit"
            )
        account_number = str(raw["account_number"]).strip()
        account = db.execute(
            select(Account).where(Account.number == account_number)
        ).scalar_one_or_none()
        if account is None:
            raise NotFoundError(
                f"Compte {account_number} inexistant dans le plan comptable"
            )
        entry.lines.append(
            EntryLine(
                account_number=account_number,
                third_party_id=raw.get("third_party_id"),
                label=raw.get("label") or label,
                debit=debit,
                credit=credit,
                vat_rate=raw.get("vat_rate"),
                position=position,
            )
        )
    db.flush()

    if validate:
        validate_entry(db, entry, user_id=created_by)
    return entry


def validate_entry(db: Session, entry: Entry, user_id: int | None = None) -> Entry:
    """Valide une ecriture : controle d'equilibre + numerotation + audit."""
    assert_editable(entry)
    fiscal_year = db.get(FiscalYear, entry.fiscal_year_id)
    if fiscal_year is not None:
        ensure_period_open(fiscal_year)
    if len(entry.lines) < 2:
        raise AccountingError("Une ecriture validee doit contenir au moins deux lignes")

    total_debit = money(sum((line.debit for line in entry.lines), Decimal("0")))
    total_credit = money(sum((line.credit for line in entry.lines), Decimal("0")))
    if total_debit != total_credit:
        raise EntryNotBalancedError(
            f"Ecriture desequilibree : debit {total_debit} <> credit {total_credit}"
        )
    if total_debit <= 0:
        raise AccountingError("Une ecriture validee doit avoir un montant non nul")

    entry.status = ENTRY_STATUS_VALIDATED
    entry.validated_at = datetime.now()
    if entry.entry_number is None:
        year = entry.entry_date.year
        entry.entry_number = next_document_number(db, entry.company_id, "ECRITURE", year)
    # P1.6 — piste d'audit fiable : empreinte SHA-256 + chainage sur l'ecriture
    # precedente (toute alteration posterieure devient detectable).
    from app.services.audit_trail import chainer_ecriture

    chainer_ecriture(db, entry)
    entry.row_version += 1
    db.flush()
    log_action(
        db,
        action="ENTRY_VALIDATED",
        entity="Entry",
        entity_id=entry.id,
        user_id=user_id,
        company_id=entry.company_id,
        payload={
            "entry_number": entry.entry_number,
            "entry_date": entry.entry_date,
            "total": total_debit,
        },
    )
    return entry


def update_draft_entry(
    db: Session,
    entry: Entry,
    *,
    label: str | None = None,
    lines: list[dict] | None = None,
    user_id: int | None = None,
) -> Entry:
    """Modifie un brouillon. Toute ecriture validee est refusee (immuabilite)."""
    assert_editable(entry)
    # P1.6 : un brouillon d'une periode verrouillee n'est pas modifiable.
    from app.services.period_locks import controler_periode

    controler_periode(
        db,
        entry.company_id,
        entry.entry_date,
        user_id=user_id,
        operation="modification d'un brouillon",
    )
    if label is not None:
        entry.label = label
    if lines is not None:
        entry.lines.clear()
        db.flush()
        for position, raw in enumerate(lines):
            entry.lines.append(
                EntryLine(
                    account_number=str(raw["account_number"]).strip(),
                    third_party_id=raw.get("third_party_id"),
                    label=raw.get("label") or entry.label,
                    debit=money(raw.get("debit") or 0),
                    credit=money(raw.get("credit") or 0),
                    vat_rate=raw.get("vat_rate"),
                    position=position,
                )
            )
    entry.row_version += 1
    db.flush()
    return entry


def delete_draft_entry(db: Session, entry: Entry, user_id: int | None = None) -> None:
    """Supprime un brouillon. Une ecriture validee n'est jamais supprimee."""
    assert_editable(entry)
    from app.services.period_locks import controler_periode

    controler_periode(
        db,
        entry.company_id,
        entry.entry_date,
        user_id=user_id,
        operation="suppression d'un brouillon",
    )
    db.delete(entry)
    db.flush()


def reverse_entry(
    db: Session,
    entry: Entry,
    reason: str,
    reversal_date: date | None = None,
    user_id: int | None = None,
) -> Entry:
    """Contre-ecriture (extourne) d'une ecriture validee, dans le meme journal."""
    if not entry.is_validated:
        raise AccountingError("Seule une ecriture validee peut etre contre-passee")
    fiscal_year = db.get(FiscalYear, entry.fiscal_year_id)
    journal = db.get(Journal, entry.journal_id)
    if journal is None:
        raise NotFoundError("Journal de l'ecriture introuvable")
    reversal = create_entry(
        db,
        company_id=entry.company_id,
        fiscal_year=fiscal_year,
        journal=journal,
        entry_date=reversal_date or date.today(),
        label=f"Extourne {entry.entry_number or entry.id} - {reason}",
        reference=entry.entry_number,
        source="reversal",
        source_id=entry.id,
        created_by=user_id,
        lines=[
            {
                "account_number": line.account_number,
                "debit": line.credit,
                "credit": line.debit,
                "label": f"Extourne - {line.label or ''}".strip(),
                "third_party_id": line.third_party_id,
            }
            for line in entry.lines
        ],
    )
    reversal.reversed_entry_id = entry.id
    validate_entry(db, reversal, user_id=user_id)
    log_action(
        db,
        action="ENTRY_REVERSED",
        entity="Entry",
        entity_id=entry.id,
        user_id=user_id,
        company_id=entry.company_id,
        payload={"reversal_entry_id": reversal.id, "reason": reason},
    )
    return reversal