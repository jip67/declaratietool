"""getekende paraaf van de voorzitter in plaats van een stempel

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('signature', sa.LargeBinary(), nullable=True))
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approval_signature', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_column('approval_signature')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('signature')
