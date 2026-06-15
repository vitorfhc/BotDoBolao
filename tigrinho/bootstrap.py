"""Composition-root helpers shared by the CLI and the bot.

:func:`build_provider` turns config into a :class:`FootballProvider`: a scripted ``FakeProvider``
when ``provider_mode: fake`` (offline dev/tests), else an ``ApiFootballProvider`` whose calls are
gated by a per-session :class:`RequestBudget`. Pass a shared ``client`` for the long-running bot;
omit it for one-shot CLI use.
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from tigrinho.config import ProviderMode, Settings
from tigrinho.db.repositories import ApiUsageRepository
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
