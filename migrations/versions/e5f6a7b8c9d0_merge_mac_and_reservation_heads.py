"""Merge MAC and reservation migration heads.

Revision ID: e5f6a7b8c9d0
Revises: a1b2c3d4e5f6, d4e5f6a7b8c9
Create Date: 2026-07-11 13:00:00.000000

"""


revision = 'e5f6a7b8c9d0'
down_revision = ('a1b2c3d4e5f6', 'd4e5f6a7b8c9')
branch_labels = None
depends_on = None


def upgrade():
    """Merge revisions without changing the schema."""


def downgrade():
    """Split the migration graph without changing the schema."""
