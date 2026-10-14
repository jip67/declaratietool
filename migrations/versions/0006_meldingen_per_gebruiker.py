"""meldingen per gebruiker

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

ADMIN_KINDS = ('login', 'lockout', 'mail')


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify', sa.String(length=255), server_default='', nullable=False))
        batch_op.add_column(sa.Column('notify_overdue_days', sa.Integer(), server_default='3', nullable=False))
    op.create_table('overdue_notices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('claim_id', sa.Integer(), nullable=False),
    sa.Column('since', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('overdue_notices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_overdue_notices_claim_id'), ['claim_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_overdue_notices_user_id'), ['user_id'], unique=False)

    # De meldingen voor de beheerder stonden tot nu toe voor alle beheerders samen aan of uit.
    # Elke beheerder krijgt de keuzes die al aan stonden als eigen instelling.
    conn = op.get_bind()
    on = [k for (k,) in conn.execute(sa.text(
        "SELECT key FROM key_values WHERE key LIKE 'notify.%' AND value = '1'"))]
    kinds = ','.join(k.removeprefix('notify.') for k in on if k.removeprefix('notify.') in ADMIN_KINDS)
    if kinds:
        for user_id, roles in conn.execute(sa.text("SELECT id, roles FROM users")).all():
            if 'admin' in (roles or '').split(','):
                conn.execute(sa.text("UPDATE users SET notify = :n WHERE id = :i"), {'n': kinds, 'i': user_id})
    conn.execute(sa.text("DELETE FROM key_values WHERE key LIKE 'notify.%'"))


def downgrade() -> None:
    with op.batch_alter_table('overdue_notices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_overdue_notices_user_id'))
        batch_op.drop_index(batch_op.f('ix_overdue_notices_claim_id'))
    op.drop_table('overdue_notices')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notify_overdue_days')
        batch_op.drop_column('notify')
