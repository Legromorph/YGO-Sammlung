"""cardmarket print verification metadata

Revision ID: 20260415_0006
Revises: 20260415_0005
Create Date: 2026-04-15 14:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0006"
down_revision = "20260415_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("card_prints", sa.Column("cardmarket_match_quality", sa.String(length=40), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_verified_at", sa.DateTime(), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_expected_rarity", sa.String(length=120), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_expected_language", sa.String(length=16), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_expected_set_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("card_prints", "cardmarket_expected_set_name")
    op.drop_column("card_prints", "cardmarket_expected_language")
    op.drop_column("card_prints", "cardmarket_expected_rarity")
    op.drop_column("card_prints", "cardmarket_verified_at")
    op.drop_column("card_prints", "cardmarket_match_quality")
