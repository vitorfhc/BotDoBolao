"""kickoff & goal notification state

Revision ID: b7c3f1a9d2e4
Revises: ed421d04f4c4
Create Date: 2026-06-15 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3f1a9d2e4"
down_revision: str | Sequence[str] | None = "ed421d04f4c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("games", sa.Column("kickoff_announced_at", sa.DateTime(), nullable=True))
    op.add_column("games", sa.Column("last_announced_home_goals", sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("last_announced_away_goals", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("games", "last_announced_away_goals")
    op.drop_column("games", "last_announced_home_goals")
    op.drop_column("games", "kickoff_announced_at")
