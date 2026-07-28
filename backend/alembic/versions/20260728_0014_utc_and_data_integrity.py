"""use timezone-aware UTC and add data integrity constraints

Revision ID: 20260728_0014
Revises: 20260728_0013
Create Date: 2026-07-28 02:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_0014"
down_revision = "20260728_0013"
branch_labels = None
depends_on = None


TIMESTAMP_COLUMNS = {
    "cards": ("created_at", "updated_at", "last_synced_at"),
    "card_sets": (
        "created_at",
        "updated_at",
        "cardmarket_slug_verified_at",
        "catalog_synced_at",
        "cards_synced_at",
        "last_synced_at",
    ),
    "storage_locations": ("created_at", "updated_at"),
    "app_settings": ("created_at", "updated_at"),
    "card_prints": ("created_at", "updated_at", "cardmarket_verified_at"),
    "inventory_items": ("created_at", "updated_at", "last_priced_at"),
    "purchase_batches": ("created_at", "updated_at"),
    "purchase_batch_items": ("created_at", "updated_at"),
    "price_history": ("created_at", "updated_at", "captured_at"),
    "decks": ("created_at", "updated_at"),
    "deck_cards": ("created_at", "updated_at"),
    "collections": ("created_at", "updated_at"),
    "collection_cards": ("created_at", "updated_at"),
    "price_monitor_states": (
        "created_at",
        "updated_at",
        "last_price_check_at",
        "next_price_check_at",
        "last_enqueued_at",
    ),
    "sync_jobs": (
        "created_at",
        "updated_at",
        "available_at",
        "started_at",
        "completed_at",
        "next_scheduled_item_at",
    ),
    "image_assets": ("created_at", "updated_at", "downloaded_at"),
    "source_mappings": ("created_at", "updated_at", "last_synced_at"),
}


def _upgrade_timestamps() -> None:
    for table_name, column_names in TIMESTAMP_COLUMNS.items():
        for column_name in column_names:
            op.alter_column(
                table_name,
                column_name,
                existing_type=sa.DateTime(),
                type_=sa.DateTime(timezone=True),
                postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
            )


def _downgrade_timestamps() -> None:
    for table_name, column_names in TIMESTAMP_COLUMNS.items():
        for column_name in column_names:
            op.alter_column(
                table_name,
                column_name,
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(),
                postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
            )


def upgrade() -> None:
    _upgrade_timestamps()

    op.execute("UPDATE inventory_items SET quantity = 1 WHERE quantity <= 0")
    op.execute("UPDATE inventory_items SET purchase_price = NULL WHERE purchase_price < 0")
    op.execute("UPDATE inventory_items SET allocated_purchase_total = NULL WHERE allocated_purchase_total < 0")
    op.execute("UPDATE inventory_items SET current_market_price = NULL WHERE current_market_price <= 0")
    op.execute("DELETE FROM price_history WHERE price <= 0")
    op.execute("UPDATE purchase_batches SET total_price = 0 WHERE total_price < 0")
    op.execute("UPDATE purchase_batches SET total_units = 0 WHERE total_units < 0")
    op.execute("UPDATE purchase_batches SET allocated_unit_price = NULL WHERE allocated_unit_price < 0")
    op.execute("UPDATE purchase_batch_items SET quantity = 1 WHERE quantity <= 0")
    op.execute(
        "UPDATE purchase_batch_items SET allocated_purchase_price_per_unit = NULL "
        "WHERE allocated_purchase_price_per_unit < 0"
    )
    op.execute("UPDATE purchase_batch_items SET allocated_purchase_total = 0 WHERE allocated_purchase_total < 0")
    op.execute("UPDATE deck_cards SET quantity = 1 WHERE quantity <= 0")
    op.execute("UPDATE collection_cards SET quantity = 1 WHERE quantity <= 0")
    op.execute("UPDATE price_monitor_states SET price_check_interval_hours = 24 WHERE price_check_interval_hours <= 0")
    op.execute("UPDATE price_monitor_states SET failure_count = 0 WHERE failure_count < 0")
    op.execute("UPDATE price_monitor_states SET consecutive_stable_checks = 0 WHERE consecutive_stable_checks < 0")
    op.execute(
        """
        WITH duplicate_running_jobs AS (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY lock_key
                        ORDER BY started_at ASC NULLS LAST, id ASC
                    ) AS row_number
                FROM sync_jobs
                WHERE status = 'running'
            ) ranked
            WHERE row_number > 1
        )
        UPDATE sync_jobs
        SET
            status = 'failed',
            completed_at = CURRENT_TIMESTAMP,
            error_message = 'Parallel laufender Job wurde bei der Datenmigration beendet.'
        WHERE id IN (SELECT id FROM duplicate_running_jobs)
        """
    )

    op.create_check_constraint("ck_inventory_items_quantity_positive", "inventory_items", "quantity > 0")
    op.create_check_constraint(
        "ck_inventory_items_purchase_price_nonnegative",
        "inventory_items",
        "purchase_price IS NULL OR purchase_price >= 0",
    )
    op.create_check_constraint(
        "ck_inventory_items_allocated_total_nonnegative",
        "inventory_items",
        "allocated_purchase_total IS NULL OR allocated_purchase_total >= 0",
    )
    op.create_check_constraint(
        "ck_inventory_items_market_price_positive",
        "inventory_items",
        "current_market_price IS NULL OR current_market_price > 0",
    )
    op.create_check_constraint("ck_price_history_price_positive", "price_history", "price > 0")
    op.create_check_constraint(
        "ck_purchase_batches_total_price_nonnegative",
        "purchase_batches",
        "total_price >= 0",
    )
    op.create_check_constraint(
        "ck_purchase_batches_total_units_nonnegative",
        "purchase_batches",
        "total_units >= 0",
    )
    op.create_check_constraint(
        "ck_purchase_batches_allocated_unit_price_nonnegative",
        "purchase_batches",
        "allocated_unit_price IS NULL OR allocated_unit_price >= 0",
    )
    op.create_check_constraint(
        "ck_purchase_batch_items_quantity_positive",
        "purchase_batch_items",
        "quantity > 0",
    )
    op.create_check_constraint(
        "ck_purchase_batch_items_unit_price_nonnegative",
        "purchase_batch_items",
        "allocated_purchase_price_per_unit IS NULL OR allocated_purchase_price_per_unit >= 0",
    )
    op.create_check_constraint(
        "ck_purchase_batch_items_total_nonnegative",
        "purchase_batch_items",
        "allocated_purchase_total >= 0",
    )
    op.create_check_constraint("ck_deck_cards_quantity_positive", "deck_cards", "quantity > 0")
    op.create_check_constraint("ck_collection_cards_quantity_positive", "collection_cards", "quantity > 0")
    op.create_check_constraint(
        "ck_price_monitor_interval_positive",
        "price_monitor_states",
        "price_check_interval_hours > 0",
    )
    op.create_check_constraint(
        "ck_price_monitor_failure_count_nonnegative",
        "price_monitor_states",
        "failure_count >= 0",
    )
    op.create_check_constraint(
        "ck_price_monitor_stable_checks_nonnegative",
        "price_monitor_states",
        "consecutive_stable_checks >= 0",
    )

    op.create_index(
        "ix_inventory_items_print_condition_location",
        "inventory_items",
        ["card_print_id", "condition", "storage_location_id"],
        unique=False,
    )
    op.create_index(
        "ix_price_history_inventory_captured",
        "price_history",
        ["inventory_item_id", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_price_monitor_due_priority",
        "price_monitor_states",
        ["next_price_check_at", "price_check_priority"],
        unique=False,
    )
    op.create_index(
        "ix_sync_jobs_claim",
        "sync_jobs",
        ["status", "available_at", "priority", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_sync_jobs_running_lock_key",
        "sync_jobs",
        ["lock_key"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_sync_jobs_running_lock_key", table_name="sync_jobs")
    op.drop_index("ix_sync_jobs_claim", table_name="sync_jobs")
    op.drop_index("ix_price_monitor_due_priority", table_name="price_monitor_states")
    op.drop_index("ix_price_history_inventory_captured", table_name="price_history")
    op.drop_index("ix_inventory_items_print_condition_location", table_name="inventory_items")

    op.drop_constraint("ck_price_monitor_stable_checks_nonnegative", "price_monitor_states", type_="check")
    op.drop_constraint("ck_price_monitor_failure_count_nonnegative", "price_monitor_states", type_="check")
    op.drop_constraint("ck_price_monitor_interval_positive", "price_monitor_states", type_="check")
    op.drop_constraint("ck_collection_cards_quantity_positive", "collection_cards", type_="check")
    op.drop_constraint("ck_deck_cards_quantity_positive", "deck_cards", type_="check")
    op.drop_constraint("ck_purchase_batch_items_total_nonnegative", "purchase_batch_items", type_="check")
    op.drop_constraint("ck_purchase_batch_items_unit_price_nonnegative", "purchase_batch_items", type_="check")
    op.drop_constraint("ck_purchase_batch_items_quantity_positive", "purchase_batch_items", type_="check")
    op.drop_constraint("ck_purchase_batches_allocated_unit_price_nonnegative", "purchase_batches", type_="check")
    op.drop_constraint("ck_purchase_batches_total_units_nonnegative", "purchase_batches", type_="check")
    op.drop_constraint("ck_purchase_batches_total_price_nonnegative", "purchase_batches", type_="check")
    op.drop_constraint("ck_price_history_price_positive", "price_history", type_="check")
    op.drop_constraint("ck_inventory_items_market_price_positive", "inventory_items", type_="check")
    op.drop_constraint("ck_inventory_items_allocated_total_nonnegative", "inventory_items", type_="check")
    op.drop_constraint("ck_inventory_items_purchase_price_nonnegative", "inventory_items", type_="check")
    op.drop_constraint("ck_inventory_items_quantity_positive", "inventory_items", type_="check")

    _downgrade_timestamps()
