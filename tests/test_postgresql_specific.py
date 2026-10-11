"""PG5D - preuves specifiques PostgreSQL.

Ces tests ne s'executent que sur la base dediee `compta_ma_test`.

Ils verifient :
1. SELECT ... FOR UPDATE reel ;
2. contrainte UNIQUE PostgreSQL / IntegrityError ;
3. numerotation concurrente sur sequence existante ;
4. numerotation concurrente au premier usage ;
5. verrou mensuel concurrent ;
6. verrou annuel concurrent.

Aucune execution sur staging n'est autorisee.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.numbering import next_document_number
from app.db import seed as seed_module
from app.models import FiscalYear, NumberingSequence, PeriodLock
from app.services.period_locks import PeriodLockError, verrouiller_periode


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
EXPECTED_DATABASE = "compta_ma_test"
EXPECTED_ALEMBIC_HEAD = "a50e63267636"
YEAR = 2099


if not TEST_DATABASE_URL:
    pytest.skip(
        "PG5D requiert TEST_DATABASE_URL vers compta_ma_test",
        allow_module_level=True,
    )

_url = make_url(TEST_DATABASE_URL)

if _url.get_backend_name() != "postgresql":
    raise RuntimeError("PG5D requiert PostgreSQL.")

if _url.database != EXPECTED_DATABASE:
    raise RuntimeError(
        f"PG5D refuse la base {_url.database!r}; "
        f"seule {EXPECTED_DATABASE!r} est autorisee."
    )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
        future=True,
    )

    with engine.connect() as conn:
        assert conn.dialect.name == "postgresql"
        assert conn.execute(text("SELECT current_database()")).scalar_one() == EXPECTED_DATABASE
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == EXPECTED_ALEMBIC_HEAD
        )

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def pg_company(pg_engine):
    """Societe temporaire committee, visible depuis plusieurs connexions."""
    suffix = str(uuid4().int % 100_000_000).zfill(8)
    ice = "0099999" + suffix

    SessionLocal = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    session = SessionLocal()

    company = seed_module.create_company(
        session,
        f"PG5D Test {suffix}",
        year=YEAR,
        ice=ice,
        fiscal_id=suffix[:7],
        rc=suffix,
        address="PG5D",
        city="Casablanca",
    )
    session.commit()

    company_id = company.id
    fiscal_year_id = session.execute(
        select(FiscalYear.id).where(
            FiscalYear.company_id == company_id,
            FiscalYear.year == YEAR,
        )
    ).scalar_one()

    session.close()

    try:
        yield {
            "company_id": company_id,
            "fiscal_year_id": fiscal_year_id,
            "year": YEAR,
        }
    finally:
        # Nettoyage volontairement explicite et limite a la societe PG5D.
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM audit_log WHERE company_id = :company_id"),
                {"company_id": company_id},
            )
            conn.execute(
                text("DELETE FROM period_locks WHERE company_id = :company_id"),
                {"company_id": company_id},
            )
            conn.execute(
                text("DELETE FROM numbering_sequences WHERE company_id = :company_id"),
                {"company_id": company_id},
            )
            conn.execute(
                text("DELETE FROM fiscal_years WHERE company_id = :company_id"),
                {"company_id": company_id},
            )
            conn.execute(
                text("DELETE FROM companies WHERE id = :company_id"),
                {"company_id": company_id},
            )


def _session(pg_engine, *, isolation_level: str | None = None) -> Session:
    if isolation_level is None:
        bind = pg_engine.connect()
    else:
        bind = pg_engine.connect().execution_options(
            isolation_level=isolation_level
        )

    return Session(
        bind=bind,
        autoflush=False,
        expire_on_commit=False,
    )


def _close_session(session: Session) -> None:
    bind = session.get_bind()
    try:
        session.close()
    finally:
        bind.close()


def test_postgresql_for_update_bloque_une_seconde_transaction(
    pg_engine,
    pg_company,
):
    """Un vrai FOR UPDATE PostgreSQL doit bloquer une transaction concurrente."""
    company_id = pg_company["company_id"]

    SessionLocal = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    seed = SessionLocal()
    seed.add(
        NumberingSequence(
            company_id=company_id,
            doc_type="PG5D_LOCK",
            year=YEAR,
            last_number=0,
        )
    )
    seed.commit()
    seed.close()

    s1 = SessionLocal()
    s2 = SessionLocal()

    stmt = (
        select(NumberingSequence)
        .where(
            NumberingSequence.company_id == company_id,
            NumberingSequence.doc_type == "PG5D_LOCK",
            NumberingSequence.year == YEAR,
        )
        .with_for_update()
    )

    try:
        s1.execute(stmt).scalar_one()

        s2.execute(text("SET LOCAL lock_timeout = '500ms'"))

        with pytest.raises(DBAPIError) as excinfo:
            s2.execute(stmt).scalar_one()

        assert getattr(excinfo.value.orig, "sqlstate", None) == "55P03"
        s2.rollback()

    finally:
        s1.rollback()
        s2.rollback()
        s1.close()
        s2.close()


def test_postgresql_unique_numbering_scope_declenche_integrity_error(
    pg_engine,
    pg_company,
):
    """La contrainte uq_numbering_sequences_scope est imposee par PostgreSQL."""
    company_id = pg_company["company_id"]

    SessionLocal = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    s1 = SessionLocal()
    s1.add(
        NumberingSequence(
            company_id=company_id,
            doc_type="PG5D_UNIQUE",
            year=YEAR,
            last_number=1,
        )
    )
    s1.commit()
    s1.close()

    s2 = SessionLocal()

    try:
        s2.add(
            NumberingSequence(
                company_id=company_id,
                doc_type="PG5D_UNIQUE",
                year=YEAR,
                last_number=2,
            )
        )

        with pytest.raises(IntegrityError) as excinfo:
            s2.flush()

        assert getattr(excinfo.value.orig, "sqlstate", None) == "23505"

    finally:
        s2.rollback()
        s2.close()


def test_numbering_concurrent_sequence_existante_est_serialisee(
    pg_engine,
    pg_company,
):
    """Deux consommateurs d'une sequence existante obtiennent 1 puis 2."""
    company_id = pg_company["company_id"]
    doc_type = "PG5D_EXISTING"

    SessionLocal = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    setup = SessionLocal()
    setup.add(
        NumberingSequence(
            company_id=company_id,
            doc_type=doc_type,
            year=YEAR,
            last_number=0,
        )
    )
    setup.commit()
    setup.close()

    barrier = threading.Barrier(2)

    def worker():
        session = SessionLocal()
        try:
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            barrier.wait(timeout=3)

            numero = next_document_number(
                session,
                company_id,
                doc_type,
                YEAR,
            )
            session.commit()
            return ("ok", numero)

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return ("error", exc)

        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in (
                executor.submit(worker),
                executor.submit(worker),
            )
        ]

    errors = [value for status, value in results if status == "error"]
    numeros = sorted(value for status, value in results if status == "ok")

    assert errors == []
    assert numeros == [
        f"PG{YEAR}00001",
        f"PG{YEAR}00002",
    ]

    verify = SessionLocal()
    try:
        sequence = verify.execute(
            select(NumberingSequence).where(
                NumberingSequence.company_id == company_id,
                NumberingSequence.doc_type == doc_type,
                NumberingSequence.year == YEAR,
            )
        ).scalar_one()

        assert sequence.last_number == 2
    finally:
        verify.close()


def test_numbering_concurrent_premier_usage_est_sur(
    pg_engine,
    pg_company,
):
    """Le premier usage concurrent doit lui aussi produire deux numeros uniques."""
    company_id = pg_company["company_id"]
    doc_type = "PG5D_FIRST"

    barrier = threading.Barrier(2)

    def worker():
        session = _session(pg_engine)

        try:
            session.execute(text("SET LOCAL statement_timeout = '5s'"))

            # Etablit le snapshot avant que l'un des workers n'insere la sequence.
            assert (
                session.execute(
                    select(func.count())
                    .select_from(NumberingSequence)
                    .where(
                        NumberingSequence.company_id == company_id,
                        NumberingSequence.doc_type == doc_type,
                        NumberingSequence.year == YEAR,
                    )
                ).scalar_one()
                == 0
            )

            barrier.wait(timeout=3)

            numero = next_document_number(
                session,
                company_id,
                doc_type,
                YEAR,
            )
            session.commit()
            return ("ok", numero)

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return ("error", exc)

        finally:
            _close_session(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in (
                executor.submit(worker),
                executor.submit(worker),
            )
        ]

    errors = [value for status, value in results if status == "error"]
    numeros = sorted(value for status, value in results if status == "ok")

    assert errors == []
    assert numeros == [
        f"PG{YEAR}00001",
        f"PG{YEAR}00002",
    ]


def test_verrou_mensuel_concurrent_reste_unique_et_erreur_metier(
    pg_engine,
    pg_company,
):
    """Deux poses concurrentes du meme mois doivent donner un seul verrou."""
    company_id = pg_company["company_id"]
    fiscal_year_id = pg_company["fiscal_year_id"]

    barrier = threading.Barrier(2)

    def worker():
        session = _session(pg_engine)

        try:
            session.execute(text("SET LOCAL statement_timeout = '5s'"))

            # Snapshot commun : aucun verrou visible au depart.
            assert (
                session.execute(
                    select(func.count())
                    .select_from(PeriodLock)
                    .where(
                        PeriodLock.company_id == company_id,
                        PeriodLock.fiscal_year_id == fiscal_year_id,
                        PeriodLock.periode == 6,
                    )
                ).scalar_one()
                == 0
            )

            barrier.wait(timeout=3)

            verrouiller_periode(
                session,
                company_id=company_id,
                year=YEAR,
                periode=6,
                motif="PG5D concurrence",
                user_id=None,
            )
            session.commit()
            return ("ok", None)

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return ("error", exc)

        finally:
            _close_session(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in (
                executor.submit(worker),
                executor.submit(worker),
            )
        ]

    successes = sum(status == "ok" for status, _ in results)
    errors = [value for status, value in results if status == "error"]

    assert successes == 1, repr(errors)
    assert len(errors) == 1
    assert isinstance(errors[0], PeriodLockError)

    with pg_engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(PeriodLock)
            .where(
                PeriodLock.company_id == company_id,
                PeriodLock.fiscal_year_id == fiscal_year_id,
                PeriodLock.periode == 6,
            )
        ).scalar_one()

    assert count == 1


def test_verrou_annuel_concurrent_reste_unique(
    pg_engine,
    pg_company,
):
    """Deux poses concurrentes du verrou annuel doivent donner un seul verrou."""
    company_id = pg_company["company_id"]
    fiscal_year_id = pg_company["fiscal_year_id"]

    barrier = threading.Barrier(2)

    def worker():
        session = _session(pg_engine)

        try:
            session.execute(text("SET LOCAL statement_timeout = '5s'"))

            assert (
                session.execute(
                    select(func.count())
                    .select_from(PeriodLock)
                    .where(
                        PeriodLock.company_id == company_id,
                        PeriodLock.fiscal_year_id == fiscal_year_id,
                        PeriodLock.periode.is_(None),
                    )
                ).scalar_one()
                == 0
            )

            barrier.wait(timeout=3)

            verrouiller_periode(
                session,
                company_id=company_id,
                year=YEAR,
                periode=None,
                motif="PG5D verrou annuel",
                user_id=None,
            )
            session.commit()
            return ("ok", None)

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return ("error", exc)

        finally:
            _close_session(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=10)
            for future in (
                executor.submit(worker),
                executor.submit(worker),
            )
        ]

    successes = sum(status == "ok" for status, _ in results)
    errors = [value for status, value in results if status == "error"]

    assert successes == 1, repr(errors)
    assert len(errors) == 1
    assert isinstance(errors[0], PeriodLockError)

    with pg_engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(PeriodLock)
            .where(
                PeriodLock.company_id == company_id,
                PeriodLock.fiscal_year_id == fiscal_year_id,
                PeriodLock.periode.is_(None),
            )
        ).scalar_one()

    assert count == 1
