"""indiener kiest zelf of hij mail krijgt bij tussenstappen

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('submitters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status_updates', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('submitters', schema=None) as batch_op:
        batch_op.drop_column('status_updates')
