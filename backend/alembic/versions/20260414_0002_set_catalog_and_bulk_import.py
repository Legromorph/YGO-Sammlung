"""set catalog and bulk import support

Revision ID: 20260414_0002
Revises: 20260414_0001
Create Date: 2026-04-14 20:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_0002"
down_revision = "20260414_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("set_code", sa.String(length=80), nullable=True),
        sa.Column("card_count", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("source_payload", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_card_sets_provider_key", "card_sets", ["provider_key"])
    op.create_index("ix_card_sets_name", "card_sets", ["name"])
    op.create_index("ix_card_sets_normalized_name", "card_sets", ["normalized_name"])
    op.create_index("ix_card_sets_set_code", "card_sets", ["set_code"])
    op.create_index("uq_card_sets_provider_name", "card_sets", ["provider_key", "normalized_name"], unique=True)

    op.add_column("card_prints", sa.Column("set_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_card_prints_set_id", "card_prints", "card_sets", ["set_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_card_prints_set_id", "card_prints", ["set_id"])

    op.execute(
        """
        INSERT INTO card_sets (
            provider_key,
            name,
            normalized_name,
            set_code,
            card_count,
            release_date,
            source_payload,
            last_synced_at,
            created_at,
            updated_at
        )
        SELECT
            'legacy',
            cp.set_name,
            lower(trim(cp.set_name)),
            NULL,
            count(*),
            min(cp.release_date),
            NULL,
            NULL,
            now(),
            now()
        FROM card_prints cp
        WHERE cp.set_name IS NOT NULL
        GROUP BY cp.set_name
        """
    )

    op.execute(
        """
        UPDATE card_prints cp
        SET set_id = cs.id
        FROM card_sets cs
        WHERE cs.provider_key = 'legacy'
          AND cp.set_name IS NOT NULL
          AND cs.normalized_name = lower(trim(cp.set_name))
        """
    )


def downgrade() -> None:
    op.drop_index("ix_card_prints_set_id", table_name="card_prints")
    op.drop_constraint("fk_card_prints_set_id", "card_prints", type_="foreignkey")
    op.drop_column("card_prints", "set_id")

    op.drop_index("uq_card_sets_provider_name", table_name="card_sets")
    op.drop_index("ix_card_sets_set_code", table_name="card_sets")
    op.drop_index("ix_card_sets_normalized_name", table_name="card_sets")
    op.drop_index("ix_card_sets_name", table_name="card_sets")
    op.drop_index("ix_card_sets_provider_key", table_name="card_sets")
    op.drop_table("card_sets")
