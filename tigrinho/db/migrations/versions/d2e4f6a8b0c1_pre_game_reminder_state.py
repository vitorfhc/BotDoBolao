"""pre-game reminder state

Revision ID: d2e4f6a8b0c1
Revises: b7c3f1a9d2e4
Create Date: 2026-06-15 18:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e4f6a8b0c1"
down_revision: str | Sequence[str] | None = "b7c3f1a9d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("games", sa.Column("reminder_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("games", "reminder_sent_at")
