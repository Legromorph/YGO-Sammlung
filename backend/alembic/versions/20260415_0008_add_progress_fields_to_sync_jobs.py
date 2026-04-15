"""Add progress tracking fields to sync_jobs

Revision ID: 20260415_0008
Revises: 20260415_0007
Create Date: 2026-04-15 17:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0008"
down_revision = "20260415_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_jobs", sa.Column("total_items", sa.Integer(), nullable=True))
    op.add_column("sync_jobs", sa.Column("processed_items", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("sync_jobs", sa.Column("successful_items", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("sync_jobs", sa.Column("failed_items", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("sync_jobs", sa.Column("next_scheduled_item_at", sa.DateTime(), nullable=True))
    op.add_column("sync_jobs", sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_jobs", "rate_limit_per_minute")
    op.drop_column("sync_jobs", "next_scheduled_item_at")
    op.drop_column("sync_jobs", "failed_items")
    op.drop_column("sync_jobs", "successful_items")
    op.drop_column("sync_jobs", "processed_items")
    op.drop_column("sync_jobs", "total_items")