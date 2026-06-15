"""Tests for the deployment files: Dockerfile, entrypoint, compose (COMPLETION.md §15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_compose_structure() -> None:
    data: dict[str, Any] = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    service = data["services"]["bot"]
    assert service["env_file"] == ".env"
    assert service["restart"] == "unless-stopped"
    assert service["environment"]["CONFIG_PATH"] == "/app/config.yaml"
    volumes = service["volumes"]
    assert "tigrinho-data:/data" in volumes  # named volume for the SQLite DB
    assert any("config.yaml" in v and ":ro" in v for v in volumes)  # config bind-mount, read-only
    assert "tigrinho-data" in data["volumes"]


def test_dockerfile_uses_slim_and_nonroot() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "python:3.12-slim" in dockerfile
    assert "USER appuser" in dockerfile  # runs non-root


def test_entrypoint_runs_migrations_then_bot() -> None:
    entry = (REPO_ROOT / "docker" / "entrypoint.sh").read_text()
    assert "alembic upgrade head" in entry
    assert "python -m tigrinho" in entry
    # migrations must come before launching the bot
    assert entry.index("alembic upgrade head") < entry.index("python -m tigrinho")
