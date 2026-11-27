"""al getekend: de voorzitter tekende de bon al buiten de tool

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-27 23:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.add_column(sa.Column('signed_on_paper_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_claims_signed_on_paper_by_id_users', 'users', ['signed_on_paper_by_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_constraint('fk_claims_signed_on_paper_by_id_users', type_='foreignkey')
        batch_op.drop_column('signed_on_paper_by_id')
