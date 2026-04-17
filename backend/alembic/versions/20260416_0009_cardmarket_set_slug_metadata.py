"""cardmarket set slug metadata

Revision ID: 20260416_0009
Revises: 20260415_0008
Create Date: 2026-04-16 10:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260416_0009"
down_revision = "20260415_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("card_sets", sa.Column("cardmarket_set_slug", sa.String(length=255), nullable=True))
    op.add_column("card_sets", sa.Column("cardmarket_set_name", sa.String(length=255), nullable=True))
    op.add_column("card_sets", sa.Column("cardmarket_aliases", sa.JSON(), nullable=True))
    op.add_column("card_sets", sa.Column("cardmarket_slug_match_quality", sa.String(length=40), nullable=True))
    op.add_column("card_sets", sa.Column("cardmarket_slug_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("card_sets", "cardmarket_slug_verified_at")
    op.drop_column("card_sets", "cardmarket_slug_match_quality")
    op.drop_column("card_sets", "cardmarket_aliases")
    op.drop_column("card_sets", "cardmarket_set_name")
    op.drop_column("card_sets", "cardmarket_set_slug")
