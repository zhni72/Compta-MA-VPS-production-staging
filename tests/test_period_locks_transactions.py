"""PG1A — correction H1 : la trace de refus de periode suit la transaction appelante.

`period_locks._tracer_refus` n'ouvre plus de seconde session et ne fait plus de
`commit()` cache : la trace `PERIOD_LOCK_REJECTED` est ecrite dans la session
metier de l'appelant, qui decide seul de valider ou d'annuler la transaction.

Couvre : creation de verrou, verrou existant, refus trace, transaction appelante,
rollback, absence de double commit implicite.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session as OrmSession

from app.models import AuditLog
from app.services import period_locks as verrous
from app.services.accounting import (
    PeriodLockedError,
    create_entry,
    get_fiscal_year,
    get_journal,
)

pytestmark = pytest.mark.usefixtures("ctx")

ACTION = "PERIOD_LOCK_REJECTED"


def _tentative_interdite(db, ctx, jour: date):
    """Tentative de saisie sur une periode verrouillee (doit lever PeriodLockedError)."""
    return create_entry(
        db,
        company_id=ctx["company"].id,
        fiscal_year=get_fiscal_year(db, ctx["company"].id, jour.year),
        journal=get_journal(db, ctx["company"].id, "OD"),
        entry_date=jour,
        label="Ecriture interdite",
        lines=[
            {"account_number": "6131", "label": "Charge", "debit": Decimal("10.00")},
            {"account_number": "5141", "label": "Banque", "credit": Decimal("10.00")},
        ],
        created_by=ctx["user"].id,
    )


def _traces(db) -> list[AuditLog]:
    """Traces de refus visibles dans la session courante (validees ou non)."""
    return list(
        db.execute(select(AuditLog).where(AuditLog.action == ACTION)).scalars()
    )


def _verrouiller_juin(db, ctx):
    """Cree puis valide (commit appelant) le verrou mensuel de juin 2026."""
    verrou = verrous.verrouiller_periode(
        db, company_id=ctx["company"].id, year=2026, periode=6, motif="TVA de juin"
    )
    db.commit()
    return verrou


def test_creation_de_verrou_et_refus_trace(db, ctx):
    """Verrou cree (persiste par l'appelant) puis refus trace dans la meme session."""
    verrou = _verrouiller_juin(db, ctx)
    assert verrou.id is not None
    assert verrous.est_verrouillee(db, ctx["company"].id, date(2026, 6, 15)) is True

    with pytest.raises(PeriodLockedError, match="verrouillee"):
        _tentative_interdite(db, ctx, date(2026, 6, 15))

    # La trace est visible immediatement dans la session de l'appelant.
    assert len(_traces(db)) == 1


def test_verrou_existant_refuse_le_doublon(db, ctx):
    """Un verrou deja pose refuse tout nouveau verrou sur la meme periode."""
    _verrouiller_juin(db, ctx)
    with pytest.raises(verrous.PeriodLockError, match="deja pose"):
        verrous.verrouiller_periode(
            db, company_id=ctx["company"].id, year=2026, periode=6
        )


def test_trace_de_refus_suit_la_transaction_appelante(db, ctx):
    """L'appelant peut valider la trace : elle est alors persistee."""
    _verrouiller_juin(db, ctx)
    with pytest.raises(PeriodLockedError):
        _tentative_interdite(db, ctx, date(2026, 6, 15))
    db.commit()  # l'appelant decide de conserver la trace d'audit
    assert len(_traces(db)) == 1


def test_rollback_appelant_annule_la_trace_de_refus(db, ctx):
    """Si l'appelant annule sa transaction, la trace de refus disparait avec elle."""
    _verrouiller_juin(db, ctx)
    with pytest.raises(PeriodLockedError):
        _tentative_interdite(db, ctx, date(2026, 6, 15))
    assert len(_traces(db)) == 1  # presente avant annulation
    db.rollback()  # l'appelant annule
    assert _traces(db) == []


def test_aucun_commit_implicite_dans_la_trace_de_refus(db, ctx):
    """Aucun `commit()` cache : la decision (valider/annuler) reste a l'appelant."""
    _verrouiller_juin(db, ctx)
    commits: list[OrmSession] = []

    def _on_commit(session: OrmSession) -> None:
        commits.append(session)

    event.listen(OrmSession, "after_commit", _on_commit)
    try:
        with pytest.raises(PeriodLockedError):
            _tentative_interdite(db, ctx, date(2026, 6, 15))
        # La transaction de l'appelant est toujours ouverte (aucun commit interne).
        assert db.in_transaction() is True
    finally:
        event.remove(OrmSession, "after_commit", _on_commit)

    assert commits == []  # aucun commit declenche par la trace de refus
    db.rollback()