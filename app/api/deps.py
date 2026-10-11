"""Dependances FastAPI : session, utilisateur, societe courante, roles (RBAC)."""

from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models import Company, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Utilisateur authentifie a partir du jeton JWT."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton invalide ou expire",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur inexistant ou inactif"
        )
    return user


def get_current_company(
    x_company_id: int | None = Header(default=None, alias="X-Company-Id"),
    db: Session = Depends(get_db),
) -> Company:
    """Societe courante : en-tete X-Company-Id, sinon premiere societe active.

    En phase 1 (mono-utilisateur, une seule societe) aucun en-tete n'est requis ;
    en phase 2 le dossier est selectionne explicitement par l'utilisateur.
    """
    if x_company_id is not None:
        company = db.get(Company, x_company_id)
    else:
        company = db.execute(
            select(Company).where(Company.is_active.is_(True)).order_by(Company.id)
        ).scalars().first()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune societe disponible : executez l'amorcage (python -m app.db.seed)",
        )
    return company


def require_roles(*codes: str) -> Callable[[User], User]:
    """Controle d'acces par role (RBAC)."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.is_superadmin or user.role_codes.intersection(codes):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acces refuse : role requis parmi {sorted(codes)}",
        )

    return dependency