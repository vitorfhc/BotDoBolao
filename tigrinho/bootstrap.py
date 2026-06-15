"""Composition-root helpers shared by the CLI and the bot.

:func:`build_provider` turns config into a :class:`FootballProvider`: a scripted ``FakeProvider``
when ``provider_mode: fake`` (offline dev/tests), else an ``ApiFootballProvider`` whose calls are
gated by a per-session :class:`RequestBudget`. Pass a shared ``client`` for the long-running bot;
omit it for one-shot CLI use.
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from tigrinho.bot.client import TigrinhoBot
from tigrinho.config import ProviderMode, Settings, load_settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.repositories import ApiUsageRepository
from tigrinho.logging import configure_logging
from tigrinho.providers.api_football import ApiFootballProvider
from tigrinho.providers.base import FootballProvider
from tigrinho.providers.budget import RequestBudget
from tigrinho.providers.fake import FakeProvider


def build_provider(
    settings: Settings, session: Session, *, client: httpx.AsyncClient | None = None
) -> FootballProvider:
    """Build the configured provider (budget bound to ``session`` for API-Football)."""
    if settings.provider_mode is ProviderMode.FAKE:
        return FakeProvider()
    budget = RequestBudget(
        ApiUsageRepository(session),
        cap=settings.api_daily_cap,
        reset_tz=settings.budget_reset_tzinfo,
    )
    return ApiFootballProvider(
        league_id=settings.wc_league_id,
        season=settings.wc_season,
        budget=budget,
        base_url=settings.api_football_base_url,
        api_key=settings.api_football_key,
        client=client,
    )


def create_bot(settings: Settings) -> TigrinhoBot:
    """Wire the bot: engine + session factory + (shared) HTTP client + provider factory + cogs."""
    engine = create_db_engine(settings.db_path)
    session_factory = create_session_factory(engine)
    client: httpx.AsyncClient | None = None
    if settings.provider_mode is not ProviderMode.FAKE:
        client = httpx.AsyncClient(
            base_url=settings.api_football_base_url,
            headers={"x-apisports-key": settings.api_football_key},
            timeout=httpx.Timeout(15.0),
        )

    def provider_factory(session: Session) -> FootballProvider:
        return build_provider(settings, session, client=client)

    return TigrinhoBot(settings, session_factory=session_factory, provider_factory=provider_factory)


def run() -> None:  # pragma: no cover - real entrypoint (connects to Discord)
    """Load config, set up logging, build the bot, and run it (the container entrypoint)."""
    settings = load_settings()
    configure_logging(settings.log_level, settings.log_format)
    bot = create_bot(settings)
    bot.run(settings.discord_token)
