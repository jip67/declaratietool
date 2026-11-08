"""betaaldatum: de datum waarop de secretaris de betaling deed of inplande

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-08 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_date', sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_column('payment_date')
