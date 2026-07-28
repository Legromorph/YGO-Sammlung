"""normalize spell and trap type metadata

Revision ID: 20260728_0012
Revises: 20260727_0011
Create Date: 2026-07-28 01:00:00
"""

from alembic import op


revision = "20260728_0012"
down_revision = "20260727_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE cards
        SET
            spell_trap_type = COALESCE(spell_trap_type, monster_type),
            monster_type = NULL,
            attribute = NULL,
            atk = NULL,
            defense = NULL,
            level = NULL,
            rank = NULL,
            link_rating = NULL,
            link_arrows = NULL,
            pendulum_scale = NULL,
            pendulum_effect = NULL
        WHERE card_type IN ('Spell Card', 'Trap Card')
        """
    )


def downgrade() -> None:
    # The previous invalid field assignments cannot be reconstructed reliably.
    pass
