"""Add MAC integration schema

Adds equipment.mac_machine_name plus the machine_status cache table and the
machine_activity_events log table -- all in a single revision so there is
exactly one head (do NOT run `flask db migrate` for this; it was hand-authored,
see tech-spec F8).

Revision ID: a1b2c3d4e5f6
Revises: c2f9a8d4e6b1
Create Date: 2026-07-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'c2f9a8d4e6b1'
branch_labels = None
depends_on = None


def upgrade():
    # (a) Link column on equipment.
    with op.batch_alter_table('equipment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mac_machine_name', sa.String(length=200), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_equipment_mac_machine_name'), ['mac_machine_name'], unique=False,
        )

    # (b) Cached machine status (one row per machine, keyed by unique name).
    op.create_table('machine_status',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('machine_name', sa.String(length=200), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('relay', sa.Boolean(), nullable=False),
    sa.Column('oops', sa.Boolean(), nullable=False),
    sa.Column('locked_out', sa.Boolean(), nullable=False),
    sa.Column('current_user_account_id', sa.String(length=200), nullable=True),
    sa.Column('current_user_full_name', sa.String(length=200), nullable=True),
    sa.Column('last_checkin', sa.DateTime(), nullable=True),
    sa.Column('last_update', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('machine_status', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_machine_status_machine_name'), ['machine_name'], unique=True,
        )

    # (c) Append-only activity log with a dedup composite index (F4).
    op.create_table('machine_activity_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('machine_name', sa.String(length=200), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('user_account_id', sa.String(length=200), nullable=True),
    sa.Column('user_full_name', sa.String(length=200), nullable=True),
    sa.Column('event_timestamp', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('raw_payload', sa.JSON(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('machine_activity_events', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_machine_activity_events_machine_name'), ['machine_name'], unique=False,
        )
        batch_op.create_index(
            'ix_machine_activity_events_dedup',
            ['machine_name', 'event_type', 'event_timestamp'], unique=True,
        )


def downgrade():
    # Reverse in LIFO order. drop_table cascades each table's own indexes;
    # neither table carries a foreign key, so there is no FK-backing index to
    # preserve first.
    op.drop_table('machine_activity_events')
    op.drop_table('machine_status')
    with op.batch_alter_table('equipment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_equipment_mac_machine_name'))
        batch_op.drop_column('mac_machine_name')
