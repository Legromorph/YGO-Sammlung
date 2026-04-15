"""price monitor state and sync job scheduling

Revision ID: 20260415_0007
Revises: 20260415_0006
Create Date: 2026-04-15 17:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0007"
down_revision = "20260415_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_monitor_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_item_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("last_price_check_at", sa.DateTime(), nullable=True),
        sa.Column("next_price_check_at", sa.DateTime(), nullable=True),
        sa.Column("price_check_interval_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("price_volatility_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_check_priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_stability_state", sa.String(length=50), nullable=False, server_default="new"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_stable_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_enqueued_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_price_monitor_states_next_price_check_at", "price_monitor_states", ["next_price_check_at"], unique=False)
    op.create_index("ix_price_monitor_states_price_check_priority", "price_monitor_states", ["price_check_priority"], unique=False)
    op.create_index("ix_price_monitor_states_price_stability_state", "price_monitor_states", ["price_stability_state"], unique=False)

    op.add_column("sync_jobs", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.add_column(
        "sync_jobs",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_sync_jobs_available_at", "sync_jobs", ["available_at"], unique=False)
    op.create_index("ix_sync_jobs_priority", "sync_jobs", ["priority"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sync_jobs_priority", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_available_at", table_name="sync_jobs")
    op.drop_column("sync_jobs", "priority")
    op.drop_column("sync_jobs", "available_at")

    op.drop_index("ix_price_monitor_states_price_stability_state", table_name="price_monitor_states")
    op.drop_index("ix_price_monitor_states_price_check_priority", table_name="price_monitor_states")
    op.drop_index("ix_price_monitor_states_next_price_check_at", table_name="price_monitor_states")
    op.drop_table("price_monitor_states")
