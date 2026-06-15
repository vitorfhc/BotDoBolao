"""Tests for PollCog wiring + scorer-name resolution (COMPLETION.md §9.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from discord.ext import tasks
from sqlalchemy.orm import Session

from tigrinho.bot.poll_cog import PollCog, resolve_scorer_name
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game, SquadPlayer
from tigrinho.db.repositories import SquadRepository
from tigrinho.providers.fake import FakeProvider

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def test_resolve_scorer_name(session: Session) -> None:
    SquadRepository(session).replace_team(
        10, [SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")]
    )
    assert resolve_scorer_name(session, 7) == "Neymar"
    assert resolve_scorer_name(session, None) is None
    assert resolve_scorer_name(session, 999) is None


async def test_poll_cog_constructs(tmp_path: Path) -> None:
    from tigrinho.bot.client import TigrinhoBot

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = PollCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            provider_factory=lambda _session: FakeProvider(),
            clock=lambda: NOW,
        )
        assert isinstance(cog.poll, tasks.Loop)
        assert cog.poll.is_running() is False  # not started until cog_load
    finally:
        await bot.close()


async def test_post_plain_sends_without_pings(tmp_path: Path) -> None:
    import discord

    from tigrinho.bot.client import TigrinhoBot

    sent: list[tuple[str, discord.AllowedMentions]] = []

    class _StubChannel(discord.abc.Messageable):
        async def _get_channel(self) -> discord.abc.MessageableChannel:
            raise NotImplementedError

        async def send(  # type: ignore[override]
            self,
            content: str,
            *,
            allowed_mentions: discord.AllowedMentions,
        ) -> None:
            sent.append((content, allowed_mentions))

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = PollCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            provider_factory=lambda _session: FakeProvider(),
            clock=lambda: NOW,
        )
        # discord.abc.Messageable check is structural enough for get_channel's return here.
        bot.get_channel = lambda _id: _StubChannel()  # type: ignore[method-assign,assignment,return-value]
        await cog._post_plain(["🟢 oi", "⚽ gol"])
    finally:
        await bot.close()

    assert [content for content, _ in sent] == ["🟢 oi", "⚽ gol"]
    assert all(am.roles is False and am.users is False and am.everyone is False for _, am in sent)


async def test_run_poll_posts_kickoff_and_result_in_one_cycle(tmp_path: Path) -> None:
    import discord

    from tigrinho.bot.client import TigrinhoBot
    from tigrinho.providers.base import GameStatus, GoalEvent, MatchResult, Stage

    sent: list[tuple[str, discord.AllowedMentions]] = []

    class _StubChannel(discord.abc.Messageable):
        async def _get_channel(self) -> discord.abc.MessageableChannel:
            raise NotImplementedError

        async def send(  # type: ignore[override]
            self, content: str, *, allowed_mentions: discord.AllowedMentions
        ) -> None:
            sent.append((content, allowed_mentions))

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    # Game 1: just kicked off (still SCHEDULED in DB) -> kickoff notice.
    # Game 2: already announced, now finished -> result message.
    with factory() as session:
        session.add(
            Game(
                fixture_id=1,
                match_hash="h1",
                stage="GROUP",
                home_team_id=10,
                home_team_name="Brasil",
                away_team_id=20,
                away_team_name="Argentina",
                kickoff_utc=NOW - timedelta(hours=1),
                kickoff_local=NOW - timedelta(hours=1),
                status="SCHEDULED",
                home_goals_90=None,
                away_goals_90=None,
                advancing_team_id=None,
                first_scorer_player_id=None,
                announced_at=None,
                kickoff_announced_at=None,
                last_announced_home_goals=None,
                last_announced_away_goals=None,
                settled_at=None,
            )
        )
        session.add(
            Game(
                fixture_id=2,
                match_hash="h2",
                stage="GROUP",
                home_team_id=30,
                home_team_name="França",
                away_team_id=40,
                away_team_name="Alemanha",
                kickoff_utc=NOW - timedelta(hours=2),
                kickoff_local=NOW - timedelta(hours=2),
                status="LIVE",
                home_goals_90=None,
                away_goals_90=None,
                advancing_team_id=None,
                first_scorer_player_id=None,
                announced_at=None,
                kickoff_announced_at=NOW - timedelta(hours=2),
                last_announced_home_goals=None,
                last_announced_away_goals=None,
                settled_at=None,
            )
        )
        session.commit()

    provider = FakeProvider(
        recent_results=[
            MatchResult(1, GameStatus.LIVE, Stage.GROUP, None, None, (), None),
            MatchResult(2, GameStatus.FINISHED, Stage.GROUP, 2, 1, (), None),
        ],
        match_results=[
            MatchResult(
                2,
                GameStatus.FINISHED,
                Stage.GROUP,
                2,
                1,
                (GoalEvent(10, 30, 7, "Mbappé", is_own_goal=False, is_penalty=False),),
                None,
            )
        ],
    )

    bot = TigrinhoBot(_settings())
    try:
        cog = PollCog(
            bot,
            settings=_settings(),
            session_factory=factory,
            provider_factory=lambda _session: provider,
            clock=lambda: NOW,
        )
        bot.get_channel = lambda _id: _StubChannel()  # type: ignore[method-assign,assignment,return-value]
        await cog.run_poll()
    finally:
        await bot.close()

    # Exactly two posts: a kickoff (no ping) then a result (pings bettors).
    kickoff_idx = next(i for i, (c, _) in enumerate(sent) if c.startswith("🟢 **Bola rolando!**"))
    result_idx = next(i for i, (c, _) in enumerate(sent) if c.startswith("🏁"))
    assert kickoff_idx < result_idx
    kickoff_am = sent[kickoff_idx][1]
    assert kickoff_am.roles is False and kickoff_am.users is False and kickoff_am.everyone is False
    assert sent[result_idx][1].users is True
