"""End-to-end budget enforcement: at the cap, the poll path makes NO HTTP call (§7.3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.poll_cog import collect_poll_outcome
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import ApiUsageRepository
from tigrinho.providers.api_football import ApiFootballProvider
from tigrinho.providers.budget import BudgetExceeded, RequestBudget

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        discord_token="x",
        api_football_key="y",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
        provider_mode="api_football",
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _add_active_game(session: Session) -> None:
    session.add(
        Game(
            fixture_id=1,
            match_hash="h",
            stage="GROUP",
            home_team_id=10,
            home_team_name="Brasil",
            away_team_id=20,
            away_team_name="Argentina",
            kickoff_utc=NOW - timedelta(hours=1),  # kicked off, within the window -> active
            kickoff_local=NOW - timedelta(hours=1),
            status="LIVE",
            home_goals_90=None,
            away_goals_90=None,
            advancing_team_id=None,
            announced_at=None,
            settled_at=None,
        )
    )
    session.flush()


async def test_budget_cap_blocks_http_in_poll(session: Session) -> None:
    _add_active_game(session)
    usage = ApiUsageRepository(session)
    for _ in range(5):
        usage.increment(NOW.date())  # reach the cap
    session.commit()

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"errors": [], "response": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    budget = RequestBudget(ApiUsageRepository(session), cap=5, reset_tz=UTC, clock=lambda: NOW)
    provider = ApiFootballProvider(league_id=1, season=2026, budget=budget, client=client)
    try:
        with pytest.raises(BudgetExceeded):
            await collect_poll_outcome(session, provider, _settings(), now=NOW)
        assert called is False  # the daily cap prevented the network call entirely
    finally:
        await client.aclose()
