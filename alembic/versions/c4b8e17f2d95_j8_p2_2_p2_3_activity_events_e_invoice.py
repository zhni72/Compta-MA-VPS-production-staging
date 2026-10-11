"""J8 — P2.2 activity_events (cessation/cession) et P2.3 e_invoice_documents

- `activity_events` : **événement de vie** de l'entreprise (cessation temporaire,
  cession, cessation) avec sa **date d'effet**, le **régime TVA** de la déclaration
  (3 ou 4) et la **période** (1 pour ces régimes, annexe 1 RD V4.0), le motif, le
  repreneur (cession) et le lien vers la déclaration du registre `tax_declarations` ;
- `e_invoice_documents` : **facture électronique** (statut, format, XML, empreinte
  SHA-256, identifiant DGI, accusé de réception, canal de transmission).

Migration purement **additive** : aucune table existante n'est modifiée.

Revision ID: c4b8e17f2d95
Revises: a7f3c51d8b42 (liasse P2.1)
Create Date: 2026-09-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c4b8e17f2d95'
down_revision = 'a7f3c51d8b42'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('activity_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('date_effet', sa.Date(), nullable=False),
    sa.Column('regime_tva', sa.Integer(), nullable=False),
    sa.Column('periode', sa.Integer(), nullable=False),
    sa.Column('motif', sa.Text(), nullable=True),
    sa.Column('repreneur_nom', sa.String(length=180), nullable=True),
    sa.Column('repreneur_fiscal_id', sa.String(length=20), nullable=True),
    sa.Column('repreneur_ice', sa.String(length=15), nullable=True),
    sa.Column('declaration_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_activity_events_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['declaration_id'], ['tax_declarations.id'], name=op.f('fk_activity_events_declaration_id_tax_declarations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_activity_events_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_activity_events'))
    )
    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_events_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_events_type'), ['type'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_events_date_effet'), ['date_effet'], unique=False)

    op.create_table('e_invoice_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('invoice_id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('statut', sa.String(length=20), nullable=False),
    sa.Column('format', sa.String(length=20), nullable=False),
    sa.Column('canal', sa.String(length=20), nullable=True),
    sa.Column('xml', sa.Text(), nullable=True),
    sa.Column('hash_sha256', sa.String(length=64), nullable=True),
    sa.Column('identifiant_dgi', sa.String(length=60), nullable=True),
    sa.Column('accuse', sa.Text(), nullable=True),
    sa.Column('envoye_le', sa.Date(), nullable=True),
    sa.Column('accuse_le', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_e_invoice_documents_company_id_companies'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_e_invoice_documents_invoice_id_invoices'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_e_invoice_documents_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_e_invoice_documents'))
    )
    with op.batch_alter_table('e_invoice_documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_e_invoice_documents_invoice_id'), ['invoice_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_e_invoice_documents_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_e_invoice_documents_statut'), ['statut'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('e_invoice_documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_e_invoice_documents_statut'))
        batch_op.drop_index(batch_op.f('ix_e_invoice_documents_company_id'))
        batch_op.drop_index(batch_op.f('ix_e_invoice_documents_invoice_id'))
    op.drop_table('e_invoice_documents')
    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_activity_events_date_effet'))
        batch_op.drop_index(batch_op.f('ix_activity_events_type'))
        batch_op.drop_index(batch_op.f('ix_activity_events_company_id'))
    op.drop_table('activity_events')
