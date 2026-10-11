"""Schemas utilisateur, role et jeton d'acces."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: str = Field(..., max_length=150)
    password: str = Field(..., min_length=8, description="8 caracteres minimum")
    full_name: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["COMPTABLE"])
    is_superadmin: bool = False


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    is_active: bool
    is_superadmin: bool
    role_codes: set[str] = Field(default_factory=set)