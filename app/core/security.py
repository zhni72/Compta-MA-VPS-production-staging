"""Securite : hachage des mots de passe (Argon2id) et jetons JWT.

Utilise des le MVP (un utilisateur), indispensable en phase 2 (multi-utilisateurs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hache un mot de passe avec Argon2id."""
    return _hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verifie un mot de passe contre son empreinte Argon2id."""
    try:
        return _hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def create_access_token(
    subject: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    """Genere un jeton d'acces JWT pour un utilisateur (`sub` = identifiant)."""
    minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode et valide un jeton JWT. Leve jwt.PyJWTError si invalide/expire."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])