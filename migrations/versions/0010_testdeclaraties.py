"""testdeclaraties: de beheerder speelt zelf alle rollen

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.add_column(sa.Column('test_user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_claims_test_user_id'), ['test_user_id'], unique=False)
        batch_op.create_foreign_key('fk_claims_test_user_id_users', 'users', ['test_user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_constraint('fk_claims_test_user_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_claims_test_user_id'))
        batch_op.drop_column('test_user_id')
