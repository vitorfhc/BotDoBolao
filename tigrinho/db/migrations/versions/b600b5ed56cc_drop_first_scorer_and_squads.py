"""drop first_scorer and squads

Removes the FIRST_SCORER bet category's storage: deletes any existing FIRST_SCORER bets, drops
games.first_scorer_player_id, and drops the squad_players table. SQLite needs batch mode for the
column drop (render_as_batch is enabled in env.py). The leaderboard rebuilds from settled bets, so
purging FIRST_SCORER bets is enough — no scoreboard fixup needed.

Revision ID: b600b5ed56cc
Revises: ed421d04f4c4
Create Date: 2026-06-15 15:19:43.399266

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b600b5ed56cc"
down_revision: str | Sequence[str] | None = "ed421d04f4c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: purge FIRST_SCORER bets, drop the column and the squad table."""
    op.execute("DELETE FROM bets WHERE category = 'FIRST_SCORER'")
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_column("first_scorer_player_id")
    op.drop_table("squad_players")


def downgrade() -> None:
    """Downgrade schema: recreate the column and the squad table (no data restore)."""
    op.create_table(
        "squad_players",
        sa.Column("player_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("player_id"),
    )
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("first_scorer_player_id", sa.Integer(), nullable=True))
