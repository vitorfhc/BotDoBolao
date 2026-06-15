"""Tests for config loading: .env secrets + config.yaml settings, fail-fast validation."""

from __future__ import annotations

import textwrap
from datetime import time
from pathlib import Path

import pytest

from tigrinho.config import ConfigError, LogFormat, ProviderMode, load_settings

# Every env var that maps to a Settings field — cleared so the host environment
# cannot leak into tests (env vars override YAML by design).
_FIELD_ENV_VARS = [
    "CONFIG_PATH",
    "DISCORD_TOKEN",
    "API_FOOTBALL_KEY",
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
    "SETTLE_GRACE_HOURS",
    "STUCK_RECHECK_MINUTES",
    "API_DAILY_CAP",
    "API_BUDGET_RESET_TZ",
    "DB_PATH",
    "LOG_LEVEL",
    "LOG_FORMAT",
]


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


_FULL_YAML = """
    guild_id: 111
    announce_channel_id: 222
    tigrinhos_role_id: 333
    admin_user_id: 444
    provider_mode: fake
    timezone: America/Sao_Paulo
    sync_time: "06:30"
    poll_interval_minutes: 5
    match_window_hours: 2
    settle_grace_hours: 12
    stuck_recheck_minutes: 5
    api_daily_cap: 50
    api_budget_reset_tz: UTC
    db_path: /data/x.db
    log_level: DEBUG
    log_format: console
"""

_MINIMAL_YAML = """
    guild_id: 1
    announce_channel_id: 2
    tigrinhos_role_id: 3
    admin_user_id: 4
"""


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Clean cwd (no stray .env), no leaking field env vars, valid secrets set."""
    monkeypatch.chdir(tmp_path)
    for name in _FIELD_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "discord-tok")
    monkeypatch.setenv("API_FOOTBALL_KEY", "api-key")
    return tmp_path


def test_loads_secrets_from_env_and_settings_from_yaml(base_env: Path) -> None:
    _write_yaml(base_env / "config.yaml", _FULL_YAML)
    s = load_settings()
    assert s.discord_token == "discord-tok"
    assert s.api_football_key == "api-key"
    assert s.guild_id == 111
    assert s.announce_channel_id == 222
    assert s.tigrinhos_role_id == 333
    assert s.admin_user_id == 444
    assert s.provider_mode is ProviderMode.FAKE
    assert s.log_format is LogFormat.CONSOLE
    assert s.poll_interval_minutes == 5
    assert s.match_window_hours == 2
    assert s.settle_grace_hours == 12
    assert s.stuck_recheck_minutes == 5


def test_optional_settings_use_defaults(base_env: Path) -> None:
    _write_yaml(base_env / "config.yaml", _MINIMAL_YAML)
    s = load_settings()
    assert s.provider_mode is ProviderMode.API_FOOTBALL
    assert s.api_football_base_url == "https://v3.football.api-sports.io"
    assert s.wc_league_id == 1
    assert s.wc_season == 2026
    assert s.timezone == "America/Sao_Paulo"
    assert s.sync_time == "06:00"
    assert s.poll_interval_minutes == 1
    assert s.match_window_hours == 3
    assert s.settle_grace_hours == 24
    assert s.stuck_recheck_minutes == 15
    assert s.api_daily_cap == 3000
    assert s.api_budget_reset_tz == "UTC"
    assert s.db_path == "/data/tigrinho.db"
    assert s.log_level == "INFO"
    assert s.log_format is LogFormat.JSON


def test_missing_required_secret_fails_fast(
    base_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    _write_yaml(base_env / "config.yaml", _FULL_YAML)
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "discord_token" in str(exc.value).lower()


def test_missing_required_yaml_field_fails_fast(base_env: Path) -> None:
    _write_yaml(
        base_env / "config.yaml",
        """
        announce_channel_id: 2
        tigrinhos_role_id: 3
        admin_user_id: 4
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "guild_id" in str(exc.value)


def test_env_overrides_yaml(base_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_yaml(base_env / "config.yaml", _FULL_YAML)  # provider_mode: fake
    monkeypatch.setenv("PROVIDER_MODE", "api_football")
    s = load_settings()
    assert s.provider_mode is ProviderMode.API_FOOTBALL


def test_config_path_env_selects_file(base_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = base_env / "nested" / "myconf.yaml"
    custom.parent.mkdir()
    _write_yaml(custom, _FULL_YAML)
    monkeypatch.setenv("CONFIG_PATH", str(custom))
    s = load_settings()
    assert s.guild_id == 111


def test_invalid_timezone_fails_fast(base_env: Path) -> None:
    _write_yaml(
        base_env / "config.yaml",
        _MINIMAL_YAML + "    timezone: Not/AZone\n",
    )
    with pytest.raises(ConfigError):
        load_settings()


def test_invalid_sync_time_fails_fast(base_env: Path) -> None:
    _write_yaml(
        base_env / "config.yaml",
        _MINIMAL_YAML + '    sync_time: "6am"\n',
    )
    with pytest.raises(ConfigError):
        load_settings()


def test_invalid_provider_mode_fails_fast(base_env: Path) -> None:
    _write_yaml(
        base_env / "config.yaml",
        _MINIMAL_YAML + "    provider_mode: carrier_pigeon\n",
    )
    with pytest.raises(ConfigError):
        load_settings()


def test_unknown_yaml_key_fails_fast(base_env: Path) -> None:
    _write_yaml(
        base_env / "config.yaml",
        _MINIMAL_YAML + "    bogus_key: 9\n",
    )
    with pytest.raises(ConfigError):
        load_settings()


def test_non_positive_id_fails_fast(base_env: Path) -> None:
    _write_yaml(
        base_env / "config.yaml",
        """
        guild_id: 0
        announce_channel_id: 2
        tigrinhos_role_id: 3
        admin_user_id: 4
        """,
    )
    with pytest.raises(ConfigError):
        load_settings()


def test_settle_grace_below_match_window_fails_fast(base_env: Path) -> None:
    # Grace must be >= the fast-poll window; otherwise a game is "overdue" before it stops
    # being actively polled, which is nonsensical (COMPLETION.md §9.2).
    _write_yaml(
        base_env / "config.yaml",
        _MINIMAL_YAML + "    match_window_hours: 5\n    settle_grace_hours: 3\n",
    )
    with pytest.raises(ConfigError):
        load_settings()


def test_helpers_timezone_and_sync_time(base_env: Path) -> None:
    _write_yaml(base_env / "config.yaml", _FULL_YAML)  # sync_time 06:30, tz America/Sao_Paulo
    s = load_settings()
    assert s.sync_time_of_day == time(6, 30)
    assert s.tzinfo.key == "America/Sao_Paulo"
    assert s.budget_reset_tzinfo.key == "UTC"
