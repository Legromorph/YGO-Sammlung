"""add sync job detail logs

Revision ID: 20260417_0010
Revises: 20260416_0009
Create Date: 2026-04-17 15:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260417_0010"
down_revision = "20260416_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_jobs", sa.Column("log_details", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_jobs", "log_details")
