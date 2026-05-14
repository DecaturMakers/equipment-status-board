"""Add duplicated_repair_id to repair_records

Revision ID: b2aa842a2c53
Revises: 374030acbd33
Create Date: 2026-05-13 18:34:49.672116

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2aa842a2c53'
down_revision = '374030acbd33'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('repair_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duplicated_repair_id', sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_repair_records_duplicated_repair_id'),
            ['duplicated_repair_id'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_repair_records_duplicated_repair_id',
            'repair_records',
            ['duplicated_repair_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('repair_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_repair_records_duplicated_repair_id'))
        batch_op.drop_constraint(
            'fk_repair_records_duplicated_repair_id', type_='foreignkey',
        )
        batch_op.drop_column('duplicated_repair_id')
