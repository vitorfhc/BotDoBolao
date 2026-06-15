"""Tests for structlog setup: JSON vs console rendering, level filtering, bound context."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import structlog

from tigrinho.config import LogFormat
from tigrinho.logging import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def test_json_output_is_parseable_with_context(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", log_format=LogFormat.JSON)
    log = get_logger("test")
    log.info("game_synced", fixture_id=42, count=3)
    line = capfd.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["event"] == "game_synced"
    assert rec["fixture_id"] == 42
    assert rec["count"] == 3
    assert rec["level"] == "info"
    assert "timestamp" in rec


def test_console_output_is_human_readable_not_json(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", log_format=LogFormat.CONSOLE)
    log = get_logger("test")
    log.info("hello_world", fixture_id=7)
    out = capfd.readouterr().out
    assert "hello_world" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip().splitlines()[-1])


def test_level_filtering_suppresses_below_threshold(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="WARNING", log_format=LogFormat.JSON)
    log = get_logger("test")
    log.info("suppressed_event")
    log.warning("kept_event")
    out = capfd.readouterr().out
    assert "suppressed_event" not in out
    assert "kept_event" in out


def test_bound_context_appears_in_output(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", log_format=LogFormat.JSON)
    log = get_logger("test").bind(component="sync")
    log.info("tick")
    rec = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    assert rec["component"] == "sync"


def test_unknown_level_falls_back_to_info(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="NOPE", log_format=LogFormat.JSON)
    log = get_logger("test")
    log.info("still_logged")
    assert "still_logged" in capfd.readouterr().out
