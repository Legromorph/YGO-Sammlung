"""inventory price status metadata

Revision ID: 20260414_0004
Revises: 20260414_0003
Create Date: 2026-04-14 23:40:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_0004"
down_revision = "20260414_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_items", sa.Column("last_price_match_quality", sa.String(length=40), nullable=True))
    op.add_column("inventory_items", sa.Column("last_price_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("inventory_items", "last_price_note")
    op.drop_column("inventory_items", "last_price_match_quality")
