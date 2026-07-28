"""repair invalid zero price snapshots

Revision ID: 20260727_0011
Revises: 20260417_0010
Create Date: 2026-07-27 17:00:00
"""

from alembic import op


revision = "20260727_0011"
down_revision = "20260417_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE price_monitor_states AS state
        SET
            last_price_check_at = NULL,
            next_price_check_at = CURRENT_TIMESTAMP,
            price_check_interval_hours = 6,
            price_volatility_score = 0,
            price_check_priority = 100,
            price_stability_state = 'new',
            failure_count = 0,
            consecutive_stable_checks = 0,
            last_error_message = 'Ungueltiger Nullpreis wurde verworfen.',
            updated_at = CURRENT_TIMESTAMP
        FROM inventory_items AS item
        WHERE
            state.inventory_item_id = item.id
            AND item.current_market_price <= 0
        """
    )
    op.execute(
        """
        UPDATE inventory_items
        SET
            current_market_price = NULL,
            current_price_currency = 'EUR',
            last_price_source = NULL,
            last_priced_at = NULL,
            last_price_match_quality = NULL,
            last_price_note = 'Ungueltiger Nullpreis wurde verworfen; Preisupdate ist eingeplant.',
            price_change_7d = 0,
            price_change_30d = 0,
            trend_score = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE current_market_price <= 0
        """
    )


def downgrade() -> None:
    # Invalid zero prices cannot be reconstructed into meaningful market data.
    pass
