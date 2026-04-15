"""app settings and cardmarket metadata

Revision ID: 20260415_0005
Revises: 20260414_0004
Create Date: 2026-04-15 09:55:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_0005"
down_revision = "20260414_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("preferred_currency", sa.String(length=8), nullable=True),
        sa.Column("preferred_card_language", sa.String(length=16), nullable=True),
        sa.Column("preferred_search_language", sa.String(length=16), nullable=True),
        sa.Column("preferred_price_language", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.add_column("card_prints", sa.Column("cardmarket_product_url", sa.String(length=600), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_product_slug", sa.String(length=255), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_set_slug", sa.String(length=255), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_set_name", sa.String(length=255), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_product_name", sa.String(length=255), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_variant_name", sa.String(length=255), nullable=True))
    op.add_column("card_prints", sa.Column("cardmarket_category", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("card_prints", "cardmarket_category")
    op.drop_column("card_prints", "cardmarket_variant_name")
    op.drop_column("card_prints", "cardmarket_product_name")
    op.drop_column("card_prints", "cardmarket_set_name")
    op.drop_column("card_prints", "cardmarket_set_slug")
    op.drop_column("card_prints", "cardmarket_product_slug")
    op.drop_column("card_prints", "cardmarket_product_url")

    op.drop_table("app_settings")
