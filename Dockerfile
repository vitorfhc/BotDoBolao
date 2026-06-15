# TigrinhoDaCopa bot image (COMPLETION.md §15).
FROM python:3.12-slim

# uv for fast, reproducible dependency installs (matches the project's toolchain).
COPY --from=ghcr.io/astral-sh/uv:0.9.20 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Dependencies first (cached layer) — only the lockfile + manifest are needed.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Application code + migrations, then install the project itself.
COPY alembic.ini ./
COPY tigrinho ./tigrinho
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN uv sync --frozen --no-dev && chmod +x docker/entrypoint.sh

# 3) Run as a non-root user; /data is the mounted volume for the SQLite DB.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

ENV CONFIG_PATH=/app/config.yaml
ENTRYPOINT ["./docker/entrypoint.sh"]
