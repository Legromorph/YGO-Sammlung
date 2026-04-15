"""initial schema

Revision ID: 20260414_0001
Revises:
Create Date: 2026-04-14 18:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("card_type", sa.String(length=120), nullable=True),
        sa.Column("subtype", sa.String(length=120), nullable=True),
        sa.Column("frame_type", sa.String(length=80), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attribute", sa.String(length=50), nullable=True),
        sa.Column("monster_type", sa.String(length=80), nullable=True),
        sa.Column("archetype", sa.String(length=120), nullable=True),
        sa.Column("atk", sa.Integer(), nullable=True),
        sa.Column("defense", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("link_rating", sa.Integer(), nullable=True),
        sa.Column("link_arrows", sa.JSON(), nullable=True),
        sa.Column("pendulum_scale", sa.Integer(), nullable=True),
        sa.Column("pendulum_effect", sa.Text(), nullable=True),
        sa.Column("spell_trap_type", sa.String(length=80), nullable=True),
        sa.Column("limitations", sa.JSON(), nullable=True),
        sa.Column("source_payload", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cards_name", "cards", ["name"])
    op.create_index("ix_cards_normalized_name", "cards", ["normalized_name"])

    op.create_table(
        "storage_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=True),
        sa.Column("location_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position_label", sa.String(length=80), nullable=True),
        sa.Column("path_cache", sa.String(length=500), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("storage_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_storage_locations_name"),
    )
    op.create_index("ix_storage_locations_location_type", "storage_locations", ["location_type"])

    op.create_table(
        "card_prints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("set_name", sa.String(length=255), nullable=True),
        sa.Column("set_code", sa.String(length=80), nullable=True),
        sa.Column("card_number", sa.String(length=80), nullable=True),
        sa.Column("rarity", sa.String(length=120), nullable=True),
        sa.Column("rarity_code", sa.String(length=80), nullable=True),
        sa.Column("edition", sa.String(length=80), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("remote_image_url", sa.String(length=600), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_card_prints_set_code", "card_prints", ["set_code"])
    op.create_index("ix_card_prints_language", "card_prints", ["language"])

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_location_id", sa.Integer(), sa.ForeignKey("storage_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("condition", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("purchase_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("current_market_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("current_price_currency", sa.String(length=8), nullable=False),
        sa.Column("last_price_source", sa.String(length=80), nullable=True),
        sa.Column("last_priced_at", sa.DateTime(), nullable=True),
        sa.Column("price_change_7d", sa.Float(), nullable=True),
        sa.Column("price_change_30d", sa.Float(), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("cardmarket_reference", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_inventory_items_condition", "inventory_items", ["condition"])
    op.create_index("ix_inventory_items_last_priced_at", "inventory_items", ["last_priced_at"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_price_history_captured_at", "price_history", ["captured_at"])
    op.create_index("ix_price_history_inventory_item_id", "price_history", ["inventory_item_id"])

    op.create_table(
        "decks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("format", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_decks_name", "decks", ["name"])

    op.create_table(
        "deck_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deck_id", sa.Integer(), sa.ForeignKey("decks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=20), nullable=False),
        sa.Column("is_missing", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_collections_name", "collections", ["name"])

    op.create_table(
        "collection_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), sa.ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("lock_key", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sync_jobs_job_type", "sync_jobs", ["job_type"])
    op.create_index("ix_sync_jobs_status", "sync_jobs", ["status"])

    op.create_table(
        "image_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("remote_url", sa.String(length=600), nullable=True),
        sa.Column("local_path", sa.String(length=600), nullable=True),
        sa.Column("thumbnail_path", sa.String(length=600), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("is_placeholder", sa.Boolean(), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("card_print_id", "provider_key", name="uq_image_assets_card_print_provider"),
    )

    op.create_table(
        "source_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_url", sa.String(length=600), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("target_type", "target_id", "provider_key", name="uq_source_mappings_target_provider"),
    )
    op.create_index("ix_source_mappings_external_id", "source_mappings", ["external_id"])
    op.create_index("ix_source_mappings_target", "source_mappings", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_source_mappings_target", table_name="source_mappings")
    op.drop_index("ix_source_mappings_external_id", table_name="source_mappings")
    op.drop_table("source_mappings")
    op.drop_table("image_assets")
    op.drop_index("ix_sync_jobs_status", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_job_type", table_name="sync_jobs")
    op.drop_table("sync_jobs")
    op.drop_table("collection_cards")
    op.drop_index("ix_collections_name", table_name="collections")
    op.drop_table("collections")
    op.drop_table("deck_cards")
    op.drop_index("ix_decks_name", table_name="decks")
    op.drop_table("decks")
    op.drop_index("ix_price_history_inventory_item_id", table_name="price_history")
    op.drop_index("ix_price_history_captured_at", table_name="price_history")
    op.drop_table("price_history")
    op.drop_index("ix_inventory_items_last_priced_at", table_name="inventory_items")
    op.drop_index("ix_inventory_items_condition", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_index("ix_card_prints_language", table_name="card_prints")
    op.drop_index("ix_card_prints_set_code", table_name="card_prints")
    op.drop_table("card_prints")
    op.drop_index("ix_storage_locations_location_type", table_name="storage_locations")
    op.drop_table("storage_locations")
    op.drop_index("ix_cards_normalized_name", table_name="cards")
    op.drop_index("ix_cards_name", table_name="cards")
    op.drop_table("cards")
