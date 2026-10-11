"""Fixtures pytest : base SQLite en memoire (defaut) ou PostgreSQL reel (option).

Mode par defaut (``TEST_DATABASE_URL`` absent) : **SQLite en memoire** - aucun
fichier n'est cree, chaque test part d'une base vierge.

Mode PostgreSQL (``TEST_DATABASE_URL`` renseigne) : le schema est **pre-cree par
Alembic** (``alembic upgrade head`` vers la revision courante) ; aucun
``create_all`` n'est jamais utilise. Chaque test s'execute dans une transaction
externe annulee au teardown : les ``commit()`` internes des tests deviennent des
``SAVEPOINT`` (via ``join_transaction_mode="create_savepoint"``) et sont donc
defaits, ce qui isole totalement les tests malgre ces commits.

Garde-fou : l'URL PostgreSQL doit cibler **exactement** la base ``compta_ma_test``
(jamais ``compta_ma_staging``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import seed as seed_module
from app.db.base import Base

TEST_YEAR = 2026
TEST_ICE = "001234567000012"

# Base PostgreSQL autorisee pour les tests (garde-fou dur, cf. PG5B).
EXPECTED_PG_DATABASE = "compta_ma_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _postgres_engine():
    """Moteur PostgreSQL de test, apres validation stricte de l'URL cible."""
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError(
            "TEST_DATABASE_URL doit cibler PostgreSQL, recu : " + url.drivername
        )
    if url.database != EXPECTED_PG_DATABASE:
        raise RuntimeError(
            "Garde-fou PG5B : la base de test doit etre exactement "
            f"'{EXPECTED_PG_DATABASE}', refus d'utiliser '{url.database}'."
        )
    return create_engine(TEST_DATABASE_URL, pool_pre_ping=True, future=True)


@pytest.fixture()
def db() -> Iterator[Session]:
    """Session SQLAlchemy isolee par test (SQLite memoire ou PostgreSQL reel).

    - SQLite (defaut) : moteur memoire + ``create_all`` + ``StaticPool``.
    - PostgreSQL (``TEST_DATABASE_URL``) : schema Alembic reassocie, chaque test
      dans une transaction externe (SAVEPOINT pour les ``commit()`` internes)
      annulee au teardown.
    """
    if TEST_DATABASE_URL:
        engine = _postgres_engine()
        connection = engine.connect()
        # Transaction externe : jamais validee -> tout est annule au teardown.
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()
            connection.close()
            engine.dispose()
        return

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def ctx(db: Session) -> dict:
    """Plan comptable CGNC, taux de TVA, roles, une societe et un administrateur."""
    seed_module.load_plan_comptable(db)
    seed_module.seed_vat_rates(db)
    seed_module.seed_roles(db)
    company = seed_module.create_company(
        db,
        "Atlas Test SARL",
        year=TEST_YEAR,
        ice=TEST_ICE,
        fiscal_id="1234567",
        rc="12345",
        address="12 rue des Tests",
        city="Casablanca",
    )
    user = seed_module.create_user(
        db,
        "admin@test.ma",
        "MotDePasse123",
        full_name="Admin Test",
        roles=("ADMIN", "EXPERT_COMPTABLE"),
        company=company,
        is_superadmin=True,
    )
    db.commit()
    return {"company": company, "user": user, "year": TEST_YEAR}


@pytest.fixture()
def client(db: Session, ctx: dict):
    """Client HTTP de test partageant la base en memoire du test."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client) -> dict:
    """En-tetes d'authentification de l'administrateur de test (API sous /api)."""
    response = client.post(
        "/api/auth/token", data={"username": "admin@test.ma", "password": "MotDePasse123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}