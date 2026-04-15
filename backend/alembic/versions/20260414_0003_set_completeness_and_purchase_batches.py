"""set completeness state and purchase batches

Revision ID: 20260414_0003
Revises: 20260414_0002
Create Date: 2026-04-14 22:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_0003"
down_revision = "20260414_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("card_sets", sa.Column("loaded_card_count", sa.Integer(), nullable=True))
    op.add_column("card_sets", sa.Column("loaded_print_count", sa.Integer(), nullable=True))
    op.add_column("card_sets", sa.Column("sync_warning", sa.Text(), nullable=True))
    op.add_column("card_sets", sa.Column("catalog_synced_at", sa.DateTime(), nullable=True))
    op.add_column("card_sets", sa.Column("cards_synced_at", sa.DateTime(), nullable=True))

    op.create_table(
        "purchase_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("set_id", sa.Integer(), sa.ForeignKey("card_sets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_location_id", sa.Integer(), sa.ForeignKey("storage_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("condition", sa.String(length=40), nullable=True),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("total_units", sa.Integer(), nullable=False),
        sa.Column("allocated_unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("rounding_remainder_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_purchase_batches_source_type", "purchase_batches", ["source_type"])
    op.create_index("ix_purchase_batches_set_id", "purchase_batches", ["set_id"])
    op.create_index("ix_purchase_batches_storage_location_id", "purchase_batches", ["storage_location_id"])

    op.add_column("inventory_items", sa.Column("purchase_batch_id", sa.Integer(), nullable=True))
    op.add_column("inventory_items", sa.Column("allocated_purchase_total", sa.Numeric(10, 2), nullable=True))
    op.create_foreign_key(
        "fk_inventory_items_purchase_batch_id",
        "inventory_items",
        "purchase_batches",
        ["purchase_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_inventory_items_purchase_batch_id", "inventory_items", ["purchase_batch_id"])
    op.alter_column(
        "inventory_items",
        "purchase_price",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Numeric(12, 4),
        existing_nullable=True,
    )

    op.create_table(
        "purchase_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_batch_id", sa.Integer(), sa.ForeignKey("purchase_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("allocated_purchase_price_per_unit", sa.Numeric(12, 4), nullable=True),
        sa.Column("allocated_purchase_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_purchase_batch_items_purchase_batch_id", "purchase_batch_items", ["purchase_batch_id"])
    op.create_index("ix_purchase_batch_items_inventory_item_id", "purchase_batch_items", ["inventory_item_id"])
    op.create_index("ix_purchase_batch_items_card_print_id", "purchase_batch_items", ["card_print_id"])

    op.execute(
        """
        UPDATE card_sets
        SET
            catalog_synced_at = last_synced_at,
            cards_synced_at = last_synced_at
        """
    )

    op.execute(
        """
        WITH print_stats AS (
            SELECT
                cp.set_id AS set_id,
                COUNT(*) AS loaded_print_count,
                COUNT(DISTINCT cp.card_id) AS loaded_card_count
            FROM card_prints cp
            WHERE cp.set_id IS NOT NULL
            GROUP BY cp.set_id
        )
        UPDATE card_sets cs
        SET
            loaded_print_count = ps.loaded_print_count,
            loaded_card_count = ps.loaded_card_count
        FROM print_stats ps
        WHERE cs.id = ps.set_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_batch_items_card_print_id", table_name="purchase_batch_items")
    op.drop_index("ix_purchase_batch_items_inventory_item_id", table_name="purchase_batch_items")
    op.drop_index("ix_purchase_batch_items_purchase_batch_id", table_name="purchase_batch_items")
    op.drop_table("purchase_batch_items")

    op.alter_column(
        "inventory_items",
        "purchase_price",
        existing_type=sa.Numeric(12, 4),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
    )
    op.drop_index("ix_inventory_items_purchase_batch_id", table_name="inventory_items")
    op.drop_constraint("fk_inventory_items_purchase_batch_id", "inventory_items", type_="foreignkey")
    op.drop_column("inventory_items", "allocated_purchase_total")
    op.drop_column("inventory_items", "purchase_batch_id")

    op.drop_index("ix_purchase_batches_storage_location_id", table_name="purchase_batches")
    op.drop_index("ix_purchase_batches_set_id", table_name="purchase_batches")
    op.drop_index("ix_purchase_batches_source_type", table_name="purchase_batches")
    op.drop_table("purchase_batches")

    op.drop_column("card_sets", "cards_synced_at")
    op.drop_column("card_sets", "catalog_synced_at")
    op.drop_column("card_sets", "sync_warning")
    op.drop_column("card_sets", "loaded_print_count")
    op.drop_column("card_sets", "loaded_card_count")
