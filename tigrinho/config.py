"""Application configuration — secrets from ``.env``, settings from ``config.yaml``.

Secrets (Discord / API-Football tokens) come **only** from environment variables or a
``.env`` file. Every other setting comes from a YAML file whose path is given by the
``CONFIG_PATH`` environment variable (default ``./config.yaml``), loaded via
pydantic-settings' :class:`YamlConfigSettingsSource`. If a key appears in both sources the
environment wins. The :class:`Settings` object is validated eagerly and fails fast (raising
:class:`ConfigError`) on any missing or malformed value. See COMPLETION.md §4.

Grounded against pydantic-settings 2.14.1:
https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/
"""

from __future__ import annotations

import os
from datetime import time
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH_ENV = "CONFIG_PATH"
DEFAULT_CONFIG_PATH = "./config.yaml"
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ProviderMode(StrEnum):
    """Which football data provider the bot talks to."""

    API_FOOTBALL = "api_football"
    FAKE = "fake"


class LogFormat(StrEnum):
    """Structured-log rendering style."""

    JSON = "json"
    CONSOLE = "console"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed (startup fail-fast)."""


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse a ``HH:MM`` 24h string, raising ``ValueError`` if malformed."""
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"invalid time {value!r}, expected HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time {value!r}, expected HH:MM within 00:00..23:59")
    return hour, minute


class Settings(BaseSettings):
    """Validated, strongly-typed runtime configuration (see COMPLETION.md §4)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    # --- Secrets: environment / .env only (§4.1) ---
    discord_token: str = Field(min_length=1)
    api_football_key: str = Field(min_length=1)

    # --- Settings: config.yaml (§4.2) ---
    guild_id: int = Field(gt=0)
    announce_channel_id: int = Field(gt=0)
    tigrinhos_role_id: int = Field(gt=0)
    admin_user_id: int = Field(gt=0)

    provider_mode: ProviderMode = ProviderMode.API_FOOTBALL
    api_football_base_url: str = "https://v3.football.api-sports.io"
    wc_league_id: int = Field(default=1, gt=0)
    wc_season: int = Field(default=2026, ge=2000, le=2100)
    timezone: str = "America/Sao_Paulo"
    sync_time: str = "06:00"
    poll_interval_minutes: int = Field(default=10, gt=0)
    match_window_hours: int = Field(default=3, gt=0)
    api_daily_cap: int = Field(default=100, ge=0)
    api_budget_reset_tz: str = "UTC"
    db_path: str = "/data/tigrinho.db"
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    @field_validator("timezone", "api_budget_reset_tz")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"invalid IANA timezone: {value!r}") from exc
        return value

    @field_validator("sync_time")
    @classmethod
    def _validate_sync_time(cls, value: str) -> str:
        _parse_hhmm(value)
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"invalid log_level {value!r}; expected one of {sorted(_VALID_LOG_LEVELS)}"
            )
        return upper

    @property
    def tzinfo(self) -> ZoneInfo:
        """Display/scheduling timezone (validated)."""
        return ZoneInfo(self.timezone)

    @property
    def budget_reset_tzinfo(self) -> ZoneInfo:
        """Timezone whose midnight resets the API request budget (validated)."""
        return ZoneInfo(self.api_budget_reset_tz)

    @property
    def sync_time_of_day(self) -> time:
        """Daily sync wall-clock time in :attr:`timezone`."""
        hour, minute = _parse_hhmm(self.sync_time)
        return time(hour=hour, minute=minute)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        config_path = Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))
        yaml_source = YamlConfigSettingsSource(settings_cls, yaml_file=config_path)
        # Priority, highest first: init kwargs > env vars > .env > config.yaml > file secrets.
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)


def load_settings() -> Settings:
    """Build and validate :class:`Settings`, failing fast with :class:`ConfigError`."""
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration:\n{exc}") from exc
