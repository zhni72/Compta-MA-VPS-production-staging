"""liasse fiscale P2.1 (liasse_tables, liasse_cells)

Jalon **J7 — P2.1 IS & liasse EDI** (etape 2 : assembleur de liasse).

- `liasse_tables` : un **tableau** de la liasse (`tableau/id` du schema DGI) rattache
  a une declaration du registre `tax_declarations` (type `LIASSE`) ;
- `liasse_cells` : une **cellule** (`cellule/codeEdi`, `valeur`, `numeroLigne`,
  `extraField`) avec la rubrique de l'application qui l'a alimentee et l'origine de
  la valeur (piste d'audit).

Migration purement **additive** : aucune table existante n'est modifiee.

Revision ID: a7f3c51d8b42
Revises: 56d9985cc7ff (paie P1.4 / DTS)
Create Date: 2026-09-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a7f3c51d8b42'
down_revision = '56d9985cc7ff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('liasse_tables',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('declaration_id', sa.Integer(), nullable=False),
    sa.Column('modele', sa.String(length=80), nullable=False),
    sa.Column('tableau_id', sa.Integer(), nullable=False),
    sa.Column('libelle', sa.String(length=200), nullable=True),
    sa.Column('extra_field', sa.String(length=20), nullable=True),
    sa.Column('ordre', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['declaration_id'], ['tax_declarations.id'], name=op.f('fk_liasse_tables_declaration_id_tax_declarations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_liasse_tables'))
    )
    with op.batch_alter_table('liasse_tables', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_liasse_tables_declaration_id'), ['declaration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_liasse_tables_tableau_id'), ['tableau_id'], unique=False)

    op.create_table('liasse_cells',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('liasse_table_id', sa.Integer(), nullable=False),
    sa.Column('declaration_id', sa.Integer(), nullable=False),
    sa.Column('tableau_id', sa.Integer(), nullable=False),
    sa.Column('code_edi', sa.String(length=10), nullable=False),
    sa.Column('rubrique', sa.String(length=80), nullable=True),
    sa.Column('libelle', sa.String(length=200), nullable=True),
    sa.Column('valeur', sa.String(length=120), nullable=False),
    sa.Column('valeur_numerique', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('numero_ligne', sa.Integer(), nullable=True),
    sa.Column('extra_field', sa.String(length=20), nullable=True),
    sa.Column('source', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['declaration_id'], ['tax_declarations.id'], name=op.f('fk_liasse_cells_declaration_id_tax_declarations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['liasse_table_id'], ['liasse_tables.id'], name=op.f('fk_liasse_cells_liasse_table_id_liasse_tables'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_liasse_cells'))
    )
    with op.batch_alter_table('liasse_cells', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_liasse_cells_declaration_id'), ['declaration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_liasse_cells_liasse_table_id'), ['liasse_table_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_liasse_cells_code_edi'), ['code_edi'], unique=False)
        batch_op.create_index(batch_op.f('ix_liasse_cells_tableau_id'), ['tableau_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('liasse_cells', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_liasse_cells_tableau_id'))
        batch_op.drop_index(batch_op.f('ix_liasse_cells_code_edi'))
        batch_op.drop_index(batch_op.f('ix_liasse_cells_liasse_table_id'))
        batch_op.drop_index(batch_op.f('ix_liasse_cells_declaration_id'))
    op.drop_table('liasse_cells')
    with op.batch_alter_table('liasse_tables', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_liasse_tables_tableau_id'))
        batch_op.drop_index(batch_op.f('ix_liasse_tables_declaration_id'))
    op.drop_table('liasse_tables')
