"""Add reservation type and audit fields.

Revision ID: d4e5f6a7b8c9
Revises: c2f9a8d4e6b1
Create Date: 2026-07-11 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c2f9a8d4e6b1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'reservation_type',
                sa.String(length=20),
                nullable=False,
                server_default='member',
            )
        )
        # The server default backfills all existing rows as member reservations.
        batch_op.add_column(
            sa.Column('created_by_user_id', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('replaces_reservation_id', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                'overridden_policy_codes',
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.alter_column(
            'user_id',
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_foreign_key(
            'fk_reservations_created_by_user_id_users',
            'users',
            ['created_by_user_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_reservations_replaces_reservation_id_reservations',
            'reservations',
            ['replaces_reservation_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index(
            'ix_reservations_equipment_status_interval',
            ['equipment_id', 'status', 'starts_at', 'ends_at'],
            unique=False,
        )
        batch_op.create_index(
            'ix_reservations_user_status_start',
            ['user_id', 'status', 'starts_at'],
            unique=False,
        )
        batch_op.create_index(
            'ix_reservations_replaces_reservation_id',
            ['replaces_reservation_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_reservations_created_by_user_id',
            ['created_by_user_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_reservations_reservation_type',
            ['reservation_type'],
            unique=False,
        )
        batch_op.create_check_constraint(
            'ck_reservations_type',
            "reservation_type IN ('member', 'admin_hold')",
        )
        batch_op.create_check_constraint(
            'ck_reservations_type_owner',
            "(reservation_type = 'member' AND user_id IS NOT NULL) "
            "OR (reservation_type = 'admin_hold' AND user_id IS NULL)",
        )
        batch_op.create_check_constraint(
            'ck_reservations_valid_interval',
            'ends_at > starts_at',
        )
        batch_op.alter_column(
            'reservation_type',
            server_default=None,
            existing_type=sa.String(length=20),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'overridden_policy_codes',
            server_default=None,
            existing_type=sa.JSON(),
            existing_nullable=False,
        )


def downgrade():
    bind = op.get_bind()
    holds = bind.execute(
        sa.text("SELECT COUNT(*) FROM reservations WHERE reservation_type = 'admin_hold'")
    ).scalar_one()
    if holds:
        raise RuntimeError(
            'Cannot downgrade reservation audit fields while admin holds exist.'
        )

    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.drop_constraint('ck_reservations_valid_interval', type_='check')
        batch_op.drop_constraint('ck_reservations_type_owner', type_='check')
        batch_op.drop_constraint('ck_reservations_type', type_='check')
        batch_op.drop_index('ix_reservations_reservation_type')
        batch_op.drop_index('ix_reservations_created_by_user_id')
        batch_op.drop_index('ix_reservations_replaces_reservation_id')
        batch_op.drop_index('ix_reservations_user_status_start')
        batch_op.drop_index('ix_reservations_equipment_status_interval')
        batch_op.drop_constraint(
            'fk_reservations_replaces_reservation_id_reservations',
            type_='foreignkey',
        )
        batch_op.drop_constraint(
            'fk_reservations_created_by_user_id_users',
            type_='foreignkey',
        )
        batch_op.drop_column('overridden_policy_codes')
        batch_op.drop_column('replaces_reservation_id')
        batch_op.drop_column('created_by_user_id')
        batch_op.drop_column('reservation_type')
        batch_op.alter_column(
            'user_id',
            existing_type=sa.Integer(),
            nullable=False,
        )
