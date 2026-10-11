"""tweestapsverificatie met authenticator-app of e-mail

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('totp_secret', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('totp_last_step', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('email_2fa', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('email_code_hash', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('email_code_sent_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('recovery_codes', sa.Text(), server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('recovery_codes')
        batch_op.drop_column('email_code_sent_at')
        batch_op.drop_column('email_code_hash')
        batch_op.drop_column('email_2fa')
        batch_op.drop_column('totp_last_step')
        batch_op.drop_column('totp_secret')
