"""add canonical card metadata

Revision ID: 20260728_0013
Revises: 20260728_0012
Create Date: 2026-07-28 02:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_0013"
down_revision = "20260728_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cards",
        sa.Column("card_kind", sa.String(length=20), nullable=False, server_default="other"),
    )
    op.execute(
        """
        UPDATE cards
        SET card_kind = CASE
            WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%spell%' THEN 'spell'
            WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%trap%' THEN 'trap'
            WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%skill%' THEN 'skill'
            WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%token%' THEN 'token'
            WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%monster%' THEN 'monster'
            ELSE 'other'
        END
        """
    )
    op.execute(
        """
        UPDATE cards
        SET spell_trap_type = CASE
            WHEN spell_trap_type IS NULL OR BTRIM(spell_trap_type) = '' THEN NULL
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'quickplay' THEN 'quick_play'
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'normal' THEN 'normal'
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'continuous' THEN 'continuous'
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'equip' THEN 'equip'
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'field' THEN 'field'
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'ritual' THEN 'ritual'
            WHEN REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '', 'g') = 'counter' THEN 'counter'
            ELSE TRIM(BOTH '_' FROM REGEXP_REPLACE(LOWER(spell_trap_type), '[^a-z0-9]+', '_', 'g'))
        END
        WHERE card_kind IN ('spell', 'trap')
        """
    )
    op.execute(
        """
        UPDATE cards
        SET
            attribute = NULL,
            monster_type = NULL,
            atk = NULL,
            defense = NULL,
            level = NULL,
            rank = NULL,
            link_rating = NULL,
            link_arrows = NULL,
            pendulum_scale = NULL,
            pendulum_effect = NULL
        WHERE card_kind <> 'monster'
        """
    )
    op.execute("UPDATE cards SET spell_trap_type = NULL WHERE card_kind NOT IN ('spell', 'trap')")
    op.execute(
        """
        UPDATE cards
        SET
            defense = CASE WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%link%' THEN NULL ELSE defense END,
            level = CASE
                WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%link%'
                  OR LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%xyz%'
                THEN NULL ELSE level END,
            rank = CASE WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%xyz%' THEN rank ELSE NULL END,
            link_rating = CASE WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%link%' THEN link_rating ELSE NULL END,
            link_arrows = CASE WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%link%' THEN link_arrows ELSE NULL END,
            pendulum_scale = CASE WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%pendulum%' THEN pendulum_scale ELSE NULL END,
            pendulum_effect = CASE WHEN LOWER(COALESCE(card_type, '') || ' ' || COALESCE(frame_type, '')) LIKE '%pendulum%' THEN pendulum_effect ELSE NULL END
        WHERE card_kind = 'monster'
        """
    )
    op.create_check_constraint(
        "ck_cards_card_kind",
        "cards",
        "card_kind IN ('monster', 'spell', 'trap', 'skill', 'token', 'other')",
    )
    op.create_index("ix_cards_card_kind", "cards", ["card_kind"], unique=False)
    op.alter_column("cards", "card_kind", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_cards_card_kind", table_name="cards")
    op.drop_constraint("ck_cards_card_kind", "cards", type_="check")
    op.drop_column("cards", "card_kind")
