"""Environnement Alembic : migrations SQLite (phase 1) et PostgreSQL (phase 2/3).

L'URL de connexion provient de `app.core.config` :
  - `MIGRATION_DATABASE_URL` si elle est definie (role dedie aux migrations) ;
  - sinon `DATABASE_URL` (comportement historique, y compris SQLite).

Les migrations sont identiques quel que soit le SGBD ; le runtime applicatif
n'a jamais besoin des identifiants du role de migration (cf. PG6E1).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

import app.models  # noqa: F401 - enregistre toutes les tables dans Base.metadata
from app.core.config import settings
from app.db.base import Base

config = context.config

# URL reelle des migrations : `MIGRATION_DATABASE_URL` sinon `DATABASE_URL`.
ALEMBIC_DATABASE_URL = settings.alembic_database_url
config.set_main_option("sqlalchemy.url", ALEMBIC_DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# SQLite ne sait pas modifier une table : le mode "batch" reconstruit la table.
# Le mode est derive de l'URL REELLE des migrations (et non de DATABASE_URL) :
# si MIGRATION_DATABASE_URL cible PostgreSQL, aucun batch n'est applique.
RENDER_AS_BATCH = make_url(ALEMBIC_DATABASE_URL).get_backend_name() == "sqlite"


def run_migrations_offline() -> None:
    """Generation du SQL sans connexion (alembic upgrade head --sql)."""
    context.configure(
        url=ALEMBIC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=RENDER_AS_BATCH,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Application des migrations sur la base configuree."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=RENDER_AS_BATCH,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()