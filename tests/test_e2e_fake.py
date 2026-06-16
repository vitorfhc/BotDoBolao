"""End-to-end smoke test with provider_mode: fake — sync → bet → settle → scoreboard.

No network and no secrets (FakeProvider + a temp SQLite). Exercises the real seams the cogs use,
through separate sessions (one per phase), like the running bot. (COMPLETION.md §18 M11.)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.bets_logic import place_bet
from tigrinho.bot.board_cog import Period, build_standing_inputs, compute_standings
from tigrinho.bot.poll_cog import collect_poll_outcome
from tigrinho.bot.sync_cog import collect_sync_messages
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import GameRepository
from tigrinho.domain.bets import (
    BetCategory,
    ExactScorePayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
)
from tigrinho.providers.base import Fixture, GameStatus, MatchResult, Stage
from tigrinho.providers.fake import FakeProvider

T0 = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)  # sync + place bets (before kickoff)
KICKOFF = datetime(2026, 6, 15, 13, 0, tzinfo=UTC)
T_SETTLE = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)  # 1h after kickoff (inside the window)


async def test_end_to_end_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # hermetic: no stray .env / config.yaml
    settings = Settings(
        discord_token="x",
        api_football_key="y",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
        provider_mode="fake",
    )
    engine = create_db_engine(str(tmp_path / "e2e.db"))
    Base.metadata.create_all(engine)
    factory: Callable[[], Session] = create_session_factory(engine)

    fixture = Fixture(
        fixture_id=1,
        stage=Stage.GROUP,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=KICKOFF,
        status=GameStatus.SCHEDULED,
    )
    provider = FakeProvider(fixtures=[fixture])

    # 1) SYNC — the daily sync inserts the game and the morning digest lists it (kicks off <24h).
    with factory() as session:
        messages = await collect_sync_messages(session, provider, settings, now=T0)
        session.commit()
    assert any("/apostar" in m for m in messages)
    with factory() as session:
        assert GameRepository(session).get(1) is not None

    # 2) PLACE BETS — game is open (now < kickoff).
    with factory() as session:
        place_bet(
            session,
            fixture_id=1,
            player_discord_id=100,
            display_name="Vitor",
            category=BetCategory.WINNER,
            payload=WinnerPayload(WinnerSelection.HOME),
            now=T0,
        )
        place_bet(
            session,
            fixture_id=1,
            player_discord_id=100,
            display_name="Vitor",
            category=BetCategory.EXACT_SCORE,
            payload=ExactScorePayload(2, 1),
            now=T0,
        )
        place_bet(
            session,
            fixture_id=1,
            player_discord_id=200,
            display_name="Ana",
            category=BetCategory.OVER_UNDER,
            payload=OverUnderPayload(OverUnderSelection.UNDER),
            now=T0,
        )
        session.commit()

    # 3) SETTLE — game finished 2x1 (Brasil); poll settles it within the window.
    provider.set_recent_results([MatchResult(1, GameStatus.FINISHED, Stage.GROUP, 2, 1, None)])
    provider.set_match_result(MatchResult(1, GameStatus.FINISHED, Stage.GROUP, 2, 1, None))
    with factory() as session:
        outcome = await collect_poll_outcome(session, provider, settings, now=T_SETTLE)
        session.commit()
    assert len(outcome.settled) == 1

    # 4) SCOREBOARD — derived purely from settled bets.
    with factory() as session:
        standings = compute_standings(
            build_standing_inputs(session), period=Period.GERAL, tz=settings.tzinfo, now=T_SETTLE
        )
    points = {row.player_discord_id: row.total_points for row in standings}
    assert points == {100: 7, 200: 0}  # WINNER(2)+EXACT(5)=7 ; OVER_UNDER UNDER loses on total 3
    assert standings[0].player_discord_id == 100  # leader
