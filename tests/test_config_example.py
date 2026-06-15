"""The committed config.example.yaml must be valid + complete (loads via load_settings)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tigrinho.config import ProviderMode, load_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
_FIELD_ENV_VARS = [
    "GUILD_ID",
    "ANNOUNCE_CHANNEL_ID",
    "TIGRINHOS_ROLE_ID",
    "ADMIN_USER_ID",
    "PROVIDER_MODE",
    "API_FOOTBALL_BASE_URL",
    "WC_LEAGUE_ID",
    "WC_SEASON",
    "TIMEZONE",
    "SYNC_TIME",
    "POLL_INTERVAL_MINUTES",
    "MATCH_WINDOW_HOURS",
    "API_DAILY_CAP",
    "API_BUDGET_RESET_TZ",
    "DB_PATH",
    "LOG_LEVEL",
    "LOG_FORMAT",
]


def test_config_example_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no stray .env
    for name in _FIELD_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    monkeypatch.setenv("CONFIG_PATH", str(REPO_ROOT / "config.example.yaml"))

    settings = load_settings()
    assert settings.provider_mode is ProviderMode.API_FOOTBALL
    assert settings.timezone == "America/Sao_Paulo"
    assert settings.db_path == "/data/tigrinho.db"
    assert settings.guild_id > 0
    assert settings.api_daily_cap == 100
    assert settings.sync_time == "06:00"
