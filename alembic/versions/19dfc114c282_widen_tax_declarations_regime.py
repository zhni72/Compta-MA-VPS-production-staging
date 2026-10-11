"""widen tax_declarations regime

Revision ID: 19dfc114c282
Revises: p1c1a2b3d4e5
Create Date: 2026-10-10 23:53:25.000451

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '19dfc114c282'
down_revision = 'p1c1a2b3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tax_declarations") as batch_op:
        batch_op.alter_column(
            "regime",
            existing_type=sa.String(length=20),
            type_=sa.String(length=64),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("tax_declarations") as batch_op:
        batch_op.alter_column(
            "regime",
            existing_type=sa.String(length=64),
            type_=sa.String(length=20),
            existing_nullable=True,
        )