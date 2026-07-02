"""Add reservation advance notice settings

Revision ID: c2f9a8d4e6b1
Revises: 9f4d2b1c8a7e
Create Date: 2026-06-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2f9a8d4e6b1'
down_revision = '9f4d2b1c8a7e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('equipment_reservation_settings', schema=None) as batch_op:
        batch_op.alter_column(
            'advance_booking_window_minutes',
            new_column_name='max_advance_notice_minutes',
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                'min_advance_notice_minutes',
                sa.Integer(),
                nullable=False,
                server_default='120',
            )
        )
        batch_op.alter_column(
            'min_advance_notice_minutes',
            server_default=None,
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
    op.execute(
        'UPDATE equipment_reservation_settings '
        'SET max_advance_notice_minutes = 20160 '
        'WHERE max_advance_notice_minutes = 10080'
    )


def downgrade():
    op.execute(
        'UPDATE equipment_reservation_settings '
        'SET max_advance_notice_minutes = 10080 '
        'WHERE max_advance_notice_minutes = 20160'
    )
    with op.batch_alter_table('equipment_reservation_settings', schema=None) as batch_op:
        batch_op.drop_column('min_advance_notice_minutes')
        batch_op.alter_column(
            'max_advance_notice_minutes',
            new_column_name='advance_booking_window_minutes',
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
