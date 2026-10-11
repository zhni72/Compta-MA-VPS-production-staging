"""Moteur et sessions de base de donnees.

Phase 1 : SQLite (mono-utilisateur, mono-poste).
Phase 2 : PostgreSQL (multi-utilisateurs) - seul `DATABASE_URL` change.
"""

from __future__ import annotations

import sqlite3

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """Active l'integrite referentielle uniquement sur les connexions SQLite."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """Dependance FastAPI : fournit une session par requete."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """Session autonome (scripts, seed, tests sans HTTP)."""
    return SessionLocal()