"""add Slack reservation owners

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.drop_constraint('ck_reservations_type_owner', type_='check')
        batch_op.add_column(sa.Column('slack_user_id', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('slack_display_name', sa.String(length=80), nullable=True))
        batch_op.create_index('ix_reservations_slack_user_id', ['slack_user_id'], unique=False)
        batch_op.create_check_constraint(
            'ck_reservations_type_owner',
            "(reservation_type = 'member' AND "
            "((user_id IS NOT NULL AND slack_user_id IS NULL AND slack_display_name IS NULL) "
            "OR (user_id IS NULL AND slack_user_id IS NOT NULL AND slack_display_name IS NOT NULL))) "
            "OR (reservation_type = 'admin_hold' AND user_id IS NULL "
            "AND slack_user_id IS NULL AND slack_display_name IS NULL)",
        )


def downgrade():
    bind = op.get_bind()
    slack_reservations = bind.execute(
        sa.text("SELECT COUNT(*) FROM reservations WHERE slack_user_id IS NOT NULL")
    ).scalar_one()
    if slack_reservations:
        raise RuntimeError('Cannot downgrade while Slack-owned reservations exist.')

    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.drop_constraint('ck_reservations_type_owner', type_='check')
        batch_op.drop_index('ix_reservations_slack_user_id')
        batch_op.drop_column('slack_display_name')
        batch_op.drop_column('slack_user_id')
        batch_op.create_check_constraint(
            'ck_reservations_type_owner',
            "(reservation_type = 'member' AND user_id IS NOT NULL) "
            "OR (reservation_type = 'admin_hold' AND user_id IS NULL)",
        )
