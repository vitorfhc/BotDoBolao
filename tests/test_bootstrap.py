"""Tests for build_provider — the config→provider composition helper (shared by CLI + bot)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from tigrinho.bootstrap import build_provider
from tigrinho.config import ProviderMode, Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.providers.api_football import ApiFootballProvider
from tigrinho.providers.fake import FakeProvider


def _settings(mode: ProviderMode) -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
        provider_mode=mode,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def test_build_provider_fake(session: Session) -> None:
    provider = build_provider(_settings(ProviderMode.FAKE), session)
    assert isinstance(provider, FakeProvider)


async def test_build_provider_api_football(session: Session) -> None:
    client = httpx.AsyncClient(base_url="http://test")
    try:
        provider = build_provider(_settings(ProviderMode.API_FOOTBALL), session, client=client)
        assert isinstance(provider, ApiFootballProvider)
    finally:
        await client.aclose()
