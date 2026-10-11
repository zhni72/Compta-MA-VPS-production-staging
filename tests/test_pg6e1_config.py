"""PG6E1 - tests de durcissement de la configuration de production.

Ces tests construisent `Settings` **directement** (arguments explicites) : ils ne
dependent ni d'un fichier `.env`, ni d'un serveur PostgreSQL. Les controles de
securite ne s'appliquent qu'en `environment == "production"` ; les valeurs par
defaut de developpement restent valides.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import (
    MIN_SECRET_KEY_LENGTH,
    PLACEHOLDER_SECRET_KEY,
    Settings,
)

# Configurations valides reutilisables (aucun secret reel : valeurs de test).
PG_DATABASE_URL = "postgresql+psycopg://compta_ma_app:motdepasse_test@db:5432/compta_ma"
PG_MIGRATION_URL = (
    "postgresql+psycopg://compta_ma_migrator:motdepasse_test@db:5432/compta_ma"
)
SQLITE_DATABASE_URL = "sqlite:///./compta_ma.db"
# Secret de test suffisamment long (>= 32) et different du placeholder.
VALID_SECRET_KEY = "cle-de-test-suffisamment-longue-0123456789"


def test_a_development_defaults_remain_valid():
    """A. Les valeurs par defaut de developpement restent acceptees."""
    assert Settings.model_fields["environment"].default == "development"

    settings = Settings(
        environment="development",
        debug=True,
        database_url=SQLITE_DATABASE_URL,
        secret_key=PLACEHOLDER_SECRET_KEY,
    )
    assert settings.environment == "development"
    assert settings.debug is True
    assert settings.is_sqlite is True
    assert settings.secret_key == PLACEHOLDER_SECRET_KEY


def test_a_test_environment_also_accepts_defaults():
    """A (bis). L'environnement `test` n'applique aucun controle de production."""
    settings = Settings(
        environment="test",
        debug=True,
        database_url=SQLITE_DATABASE_URL,
        secret_key=PLACEHOLDER_SECRET_KEY,
    )
    assert settings.environment == "test"


def test_b_production_rejects_debug_true():
    """B. La production refuse DEBUG=true."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            environment="production",
            debug=True,
            database_url=PG_DATABASE_URL,
            secret_key=VALID_SECRET_KEY,
        )
    assert "DEBUG" in str(excinfo.value)


def test_c_production_rejects_sqlite_database_url():
    """C. La production refuse une DATABASE_URL SQLite."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            environment="production",
            debug=False,
            database_url=SQLITE_DATABASE_URL,
            secret_key=VALID_SECRET_KEY,
        )
    assert "SQLite" in str(excinfo.value)


def test_d_production_rejects_placeholder_secret_key():
    """D. La production refuse le SECRET_KEY d'exemple."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            environment="production",
            debug=False,
            database_url=PG_DATABASE_URL,
            secret_key=PLACEHOLDER_SECRET_KEY,
        )
    assert "SECRET_KEY" in str(excinfo.value)


def test_e_production_rejects_short_secret_key():
    """E. La production refuse un SECRET_KEY de moins de 32 caracteres."""
    secret_court = "secret-trop-court"  # < MIN_SECRET_KEY_LENGTH et != placeholder
    assert len(secret_court) < MIN_SECRET_KEY_LENGTH
    assert secret_court != PLACEHOLDER_SECRET_KEY

    with pytest.raises(ValidationError) as excinfo:
        Settings(
            environment="production",
            debug=False,
            database_url=PG_DATABASE_URL,
            secret_key=secret_court,
        )
    assert "SECRET_KEY" in str(excinfo.value)


def test_f_valid_production_postgresql_runtime_config_accepted():
    """F. Une configuration runtime PostgreSQL de production valide est acceptee.

    `MIGRATION_DATABASE_URL` n'est PAS requise pour demarrer l'application.
    """
    settings = Settings(
        environment="production",
        debug=False,
        database_url=PG_DATABASE_URL,
        secret_key=VALID_SECRET_KEY,
    )
    assert settings.environment == "production"
    assert settings.debug is False
    assert settings.is_sqlite is False
    assert settings.migration_database_url is None
    # sans URL de migration, Alembic retombe sur DATABASE_URL
    assert settings.alembic_database_url == PG_DATABASE_URL


def test_g_alembic_database_url_defaults_to_database_url():
    """G. Sans MIGRATION_DATABASE_URL, Alembic utilise DATABASE_URL."""
    settings = Settings(database_url=SQLITE_DATABASE_URL)
    assert settings.migration_database_url is None
    assert settings.alembic_database_url == SQLITE_DATABASE_URL


def test_h_alembic_database_url_prefers_migration_database_url():
    """H. Avec MIGRATION_DATABASE_URL, Alembic l'utilise en priorite."""
    settings = Settings(
        database_url=PG_DATABASE_URL,
        migration_database_url=PG_MIGRATION_URL,
    )
    assert settings.alembic_database_url == PG_MIGRATION_URL
    assert settings.migration_database_url == PG_MIGRATION_URL