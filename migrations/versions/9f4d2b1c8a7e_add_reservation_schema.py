"""Add reservation schema

Revision ID: 9f4d2b1c8a7e
Revises: b2aa842a2c53
Create Date: 2026-06-15 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f4d2b1c8a7e'
down_revision = 'b2aa842a2c53'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'equipment_reservation_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('equipment_id', sa.Integer(), nullable=False),
        sa.Column('reservation_slug', sa.String(length=200), nullable=False),
        sa.Column('reservations_enabled', sa.Boolean(), nullable=False),
        sa.Column('advance_booking_window_minutes', sa.Integer(), nullable=False),
        sa.Column('min_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('max_duration_minutes', sa.Integer(), nullable=False),
        sa.Column('slot_granularity_minutes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('equipment_reservation_settings', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_equipment_reservation_settings_equipment_id'),
            ['equipment_id'],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f('ix_equipment_reservation_settings_reservation_slug'),
            ['reservation_slug'],
            unique=True,
        )

    op.create_table(
        'reservations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('equipment_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_via', sa.String(length=20), nullable=False),
        sa.Column('canceled_at', sa.DateTime(), nullable=True),
        sa.Column('canceled_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['canceled_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['equipment_id'], ['equipment.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reservations_canceled_by_user_id'), ['canceled_by_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_ends_at'), ['ends_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_equipment_id'), ['equipment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_starts_at'), ['starts_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_reservations_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('reservations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reservations_user_id'))
        batch_op.drop_index(batch_op.f('ix_reservations_status'))
        batch_op.drop_index(batch_op.f('ix_reservations_starts_at'))
        batch_op.drop_index(batch_op.f('ix_reservations_equipment_id'))
        batch_op.drop_index(batch_op.f('ix_reservations_ends_at'))
        batch_op.drop_index(batch_op.f('ix_reservations_canceled_by_user_id'))
    op.drop_table('reservations')

    with op.batch_alter_table('equipment_reservation_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_equipment_reservation_settings_reservation_slug'))
        batch_op.drop_index(batch_op.f('ix_equipment_reservation_settings_equipment_id'))
    op.drop_table('equipment_reservation_settings')
