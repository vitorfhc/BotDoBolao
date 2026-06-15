#!/usr/bin/env sh
# Container entrypoint: apply DB migrations, then run the bot (COMPLETION.md §15).
set -eu

alembic upgrade head
exec python -m tigrinho
