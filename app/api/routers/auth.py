"""Authentification et gestion des utilisateurs (RBAC)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Role, User
from app.schemas import Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["authentification"])


@router.post("/token", response_model=Token, summary="Obtenir un jeton d'acces JWT")
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    """Connexion (e-mail + mot de passe). Le champ `username` recoit l'e-mail."""
    user = db.execute(
        select(User).where(User.email == form.username)
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(form.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants invalides",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user.id, extra={"email": user.email}))


@router.get("/me", response_model=UserRead, summary="Profil de l'utilisateur connecte")
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get(
    "/users",
    response_model=list[UserRead],
    summary="Lister les utilisateurs (administrateur)",
)
def list_users(
    db: Session = Depends(get_db), _: User = Depends(require_roles("ADMIN"))
) -> list[User]:
    return list(db.execute(select(User).order_by(User.id)).scalars())


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Creer un utilisateur (administrateur)",
)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN")),
) -> User:
    exists = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email deja utilise")
    user = User(
        email=payload.email,
        full_name=payload.full_name or payload.email,
        password_hash=hash_password(payload.password),
        is_superadmin=payload.is_superadmin,
    )
    for code in payload.roles:
        role = db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Role inconnu : {code}"
            )
        user.roles.append(role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user