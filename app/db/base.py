"""Base declarative SQLAlchemy 2.0 (convient a SQLite et PostgreSQL)."""

from __future__ import annotations

from sqlalchemy import Engine, MetaData
from sqlalchemy.orm import DeclarativeBase

# Convention de nommage des contraintes : indispensable pour des migrations
# Alembic propres (et pour pouvoir supprimer une contrainte plus tard).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def as_dict(self) -> dict:
        """Representation simple d'une entite (utile pour les schemas et l'API)."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


def creer_tables_dev(engine: Engine) -> None:
    """Cree le schema via ``create_all`` **en developpement SQLite uniquement**.

    En production/staging (PostgreSQL), le schema est gere **exclusivement** par
    Alembic (``alembic upgrade head``) : ``create_all`` y est refuse afin qu'il ne
    devienne jamais le mecanisme de creation du schema hors historique de migration.
    """
    if not str(engine.url).startswith("sqlite"):
        raise RuntimeError(
            "create_all est reserve au developpement SQLite. Sur PostgreSQL, le "
            "schema est cree par Alembic : executez « alembic upgrade head »."
        )
    Base.metadata.create_all(bind=engine)