"""Utilisateurs, roles et habilitations par societe (RBAC).

Des la phase 1 on cree les tables et l'utilisateur administrateur : passer au
multi-utilisateurs ne demande alors que d'ajouter des comptes et des roles.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.company import Company

ROLE_CODES = (
    "ADMIN",          # administrateur : tout, y compris utilisateurs et societes
    "EXPERT_COMPTABLE",  # validation, cloture, verrouillage, tous les etats
    "COMPTABLE",      # saisie, factures, reglements, etats
    "CAISSIER",       # reglements et journal de caisse
    "COMMERCIAL",     # devis, commandes, factures clients (pas d'ecriture)
    "LECTEUR",        # lecture seule et exports
)

ROLE_LABELS = {
    "ADMIN": "Administrateur",
    "EXPERT_COMPTABLE": "Expert-comptable",
    "COMPTABLE": "Comptable",
    "CAISSIER": "Caissier",
    "COMMERCIAL": "Commercial",
    "LECTEUR": "Lecteur / Auditeur",
}

# Roles portes par un utilisateur (RBAC).
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

# Dossiers (societes) accessibles a un utilisateur : plusieurs dossiers par
# utilisateur en phase 2, un seul en phase 1.
user_companies = Table(
    "user_companies",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "company_id", ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    ),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Role {self.code}>"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    companies: Mapped[list[Company]] = relationship(
        secondary=user_companies, lazy="selectin"
    )

    @property
    def role_codes(self) -> set[str]:
        return {role.code for role in self.roles}

    @property
    def company_ids(self) -> set[int]:
        return {company.id for company in self.companies}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email}>"