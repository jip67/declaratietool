"""goedkeuren via link in de mail

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approve_by_link', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table('approval_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('claim_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_ip', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('approval_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_links_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_approval_links_claim_id'), ['claim_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_links_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('approval_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_links_user_id'))
        batch_op.drop_index(batch_op.f('ix_approval_links_claim_id'))
        batch_op.drop_index(batch_op.f('ix_approval_links_token_hash'))
    op.drop_table('approval_links')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('approve_by_link')
