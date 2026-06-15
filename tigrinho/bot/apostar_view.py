"""The /apostar component flow + its pure helpers (COMPLETION.md §8.1, §8.2).

Pure helpers (knockout DRAW-hiding, labels) are unit-tested; the View/Select/Modal glue is thin
over ``parse_payload`` + ``bets_logic.place_bet``. Bets close at kickoff (place_bet re-checks with
a fresh clock).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo

import discord
from discord import ui
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.models import Game
from tigrinho.db.repositories import BetRepository, GameRepository
from tigrinho.domain.bets import (
    BetCategory,
    BetPayload,
    BttsSelection,
    InvalidBetPayload,
    OverUnderSelection,
    WinnerSelection,
    is_bet_open,
    parse_payload,
)
from tigrinho.domain.text_pt import (
    CATEGORY_LABELS_PT,
    OVER_UNDER_LABELS_PT,
    btts_label,
    render_payload,
    winner_label,
)
from tigrinho.providers.base import Stage

from .bets_logic import BetError, delete_bet, place_bet
from .sync_planning import format_kickoff_pt

# A Discord Select may show at most 25 options.
DISCORD_SELECT_LIMIT = 25
VIEW_TIMEOUT = 300

# Categories offered by /apostar, in §8.1 points order.
APOSTAR_CATEGORIES: tuple[BetCategory, ...] = (
    BetCategory.EXACT_SCORE,
    BetCategory.BTTS,
    BetCategory.WINNER,
    BetCategory.OVER_UNDER,
)


def winner_selection_options(stage: Stage) -> list[WinnerSelection]:
    """Winner choices to offer; knockout hides DRAW (a knockout is never a draw — §8.1)."""
    if stage is Stage.KNOCKOUT:
        return [WinnerSelection.HOME, WinnerSelection.AWAY]
    return [WinnerSelection.HOME, WinnerSelection.DRAW, WinnerSelection.AWAY]


def game_choice_label(home_name: str, away_name: str, kickoff_local: datetime) -> str:
    """Label for an open-game Select option, e.g. ``Brasil x Argentina — Sáb 16/06 16:00``."""
    return f"{home_name} x {away_name} — {format_kickoff_pt(kickoff_local)}"


# Discord caps modal input labels at 45 chars; team names are short but truncate to be safe.
MODAL_LABEL_LIMIT = 45


def score_field_label(team_name: str) -> str:
    """Placar-exato modal field label for a team's goals, e.g. ``Gols: Brasil`` (capped at 45)."""
    return f"Gols: {team_name}"[:MODAL_LABEL_LIMIT]


@dataclass(frozen=True, slots=True)
class Matchup:
    """The two teams of a game, carried through the /apostar flow.

    Bundles the names that always travel together so option/field labels can show *who* a bet is
    on (e.g. ``Brasil``, ``Só França``) instead of the generic ``mandante``/``visitante``. Renders
    as ``Home x Away`` for display, so existing f-string usages keep working unchanged.
    """

    home_name: str
    away_name: str

    def __str__(self) -> str:
        return f"{self.home_name} x {self.away_name}"


@dataclass(frozen=True, slots=True)
class FlowContext:
    """Everything the /apostar components need; carried through the flow's steps."""

    settings: Settings
    session_factory: Callable[[], Session]
    clock: Callable[[], datetime]
    user_id: int
    user_name: str


@dataclass(frozen=True, slots=True)
class GameChoice:
    """An open game offered in the first /apostar Select."""

    fixture_id: int
    label: str
    stage: Stage
    matchup: Matchup


def games_to_choices(games: Sequence[Game], tz: tzinfo) -> list[GameChoice]:
    """Map open games to Select choices (localized labels)."""
    choices: list[GameChoice] = []
    for game in games:
        matchup = Matchup(game.home_team_name, game.away_team_name)
        label = game_choice_label(
            game.home_team_name, game.away_team_name, game.kickoff_utc.astimezone(tz)
        )
        choices.append(
            GameChoice(
                fixture_id=game.fixture_id, label=label, stage=Stage(game.stage), matchup=matchup
            )
        )
    return choices


async def _finalize_bet(
    ctx: FlowContext,
    interaction: discord.Interaction,
    *,
    fixture_id: int,
    matchup: Matchup,
    category: BetCategory,
    payload: BetPayload,
    edit: bool,
) -> None:
    """Upsert the bet (re-checking closing) and reply; ``edit`` distinguishes select vs modal."""
    try:
        with ctx.session_factory() as session:
            place_bet(
                session,
                fixture_id=fixture_id,
                player_discord_id=ctx.user_id,
                display_name=ctx.user_name,
                category=category,
                payload=payload,
                now=ctx.clock(),
            )
            session.commit()
        rendered = render_payload(payload, home_name=matchup.home_name, away_name=matchup.away_name)
        message = (
            f"✅ Palpite registrado — **{matchup}**\n{CATEGORY_LABELS_PT[category]}: {rendered}"
        )
    except BetError as exc:
        message = f"❌ {exc}"
    if edit:
        await interaction.response.edit_message(content=message, view=None)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class GameSelect(ui.Select[ui.View]):
    def __init__(self, ctx: FlowContext, choices: Sequence[GameChoice]) -> None:
        super().__init__(
            placeholder="Escolha um jogo",
            options=[
                discord.SelectOption(label=c.label[:100], value=str(c.fixture_id)) for c in choices
            ],
        )
        self._ctx = ctx
        self._by_id = {c.fixture_id: c for c in choices}

    async def callback(self, interaction: discord.Interaction) -> None:
        choice = self._by_id[int(self.values[0])]
        view = build_category_view(
            self._ctx, fixture_id=choice.fixture_id, stage=choice.stage, matchup=choice.matchup
        )
        await interaction.response.edit_message(
            content=f"**{choice.matchup}** — escolha a categoria:", view=view
        )


class CategorySelect(ui.Select[ui.View]):
    def __init__(
        self, ctx: FlowContext, *, fixture_id: int, stage: Stage, matchup: Matchup
    ) -> None:
        super().__init__(
            placeholder="Escolha a categoria",
            options=[
                discord.SelectOption(label=CATEGORY_LABELS_PT[c], value=c.value)
                for c in APOSTAR_CATEGORIES
            ],
        )
        self._ctx = ctx
        self._fixture_id = fixture_id
        self._stage = stage
        self._matchup = matchup

    async def callback(self, interaction: discord.Interaction) -> None:
        category = BetCategory(self.values[0])
        if category is BetCategory.EXACT_SCORE:
            await interaction.response.send_modal(
                ScoreModal(self._ctx, fixture_id=self._fixture_id, matchup=self._matchup)
            )
            return
        view = build_value_view(
            self._ctx,
            fixture_id=self._fixture_id,
            matchup=self._matchup,
            category=category,
            stage=self._stage,
        )
        await interaction.response.edit_message(
            content=f"**{self._matchup}** — {CATEGORY_LABELS_PT[category]}:", view=view
        )


class ValueSelect(ui.Select[ui.View]):
    def __init__(
        self,
        ctx: FlowContext,
        *,
        fixture_id: int,
        matchup: Matchup,
        category: BetCategory,
        options: Sequence[tuple[str, str]],
    ) -> None:
        super().__init__(
            placeholder="Escolha sua resposta",
            options=[discord.SelectOption(label=label, value=value) for label, value in options],
        )
        self._ctx = ctx
        self._fixture_id = fixture_id
        self._matchup = matchup
        self._category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            payload = parse_payload(self._category, {"sel": self.values[0]})
        except InvalidBetPayload:
            await interaction.response.edit_message(content="❌ Opção inválida.", view=None)
            return
        await _finalize_bet(
            self._ctx,
            interaction,
            fixture_id=self._fixture_id,
            matchup=self._matchup,
            category=self._category,
            payload=payload,
            edit=True,
        )


class ScoreModal(ui.Modal):
    def __init__(self, ctx: FlowContext, *, fixture_id: int, matchup: Matchup) -> None:
        super().__init__(title="Placar exato")
        self._ctx = ctx
        self._fixture_id = fixture_id
        self._matchup = matchup
        self.home_input: ui.TextInput[ScoreModal] = ui.TextInput(
            label=score_field_label(matchup.home_name), placeholder="0", max_length=2, required=True
        )
        self.away_input: ui.TextInput[ScoreModal] = ui.TextInput(
            label=score_field_label(matchup.away_name), placeholder="0", max_length=2, required=True
        )
        self.add_item(self.home_input)
        self.add_item(self.away_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            home = int(self.home_input.value)
            away = int(self.away_input.value)
            payload = parse_payload(BetCategory.EXACT_SCORE, {"home": home, "away": away})
        except (ValueError, InvalidBetPayload):
            await interaction.response.send_message(
                "❌ Use números válidos (ex.: 2 e 1).", ephemeral=True
            )
            return
        await _finalize_bet(
            self._ctx,
            interaction,
            fixture_id=self._fixture_id,
            matchup=self._matchup,
            category=BetCategory.EXACT_SCORE,
            payload=payload,
            edit=False,
        )


def build_apostar_view(ctx: FlowContext, choices: Sequence[GameChoice]) -> ui.View:
    """Entry view: a Select of open games."""
    view = ui.View(timeout=VIEW_TIMEOUT)
    view.add_item(GameSelect(ctx, choices[:DISCORD_SELECT_LIMIT]))
    return view


def build_category_view(
    ctx: FlowContext, *, fixture_id: int, stage: Stage, matchup: Matchup
) -> ui.View:
    """Second step: a Select of the bet categories."""
    view = ui.View(timeout=VIEW_TIMEOUT)
    view.add_item(CategorySelect(ctx, fixture_id=fixture_id, stage=stage, matchup=matchup))
    return view


def build_value_view(
    ctx: FlowContext, *, fixture_id: int, matchup: Matchup, category: BetCategory, stage: Stage
) -> ui.View:
    """Third step (select-based categories): a Select of the answer options."""
    if category is BetCategory.WINNER:
        options = [
            (winner_label(s, home_name=matchup.home_name, away_name=matchup.away_name), s.value)
            for s in winner_selection_options(stage)
        ]
    elif category is BetCategory.BTTS:
        options = [
            (btts_label(s, home_name=matchup.home_name, away_name=matchup.away_name), s.value)
            for s in BttsSelection
        ]
    elif category is BetCategory.OVER_UNDER:
        options = [(OVER_UNDER_LABELS_PT[s], s.value) for s in OverUnderSelection]
    else:
        raise ValueError(f"{category} has no value Select")
    view = ui.View(timeout=VIEW_TIMEOUT)
    view.add_item(
        ValueSelect(ctx, fixture_id=fixture_id, matchup=matchup, category=category, options=options)
    )
    return view


@dataclass(frozen=True, slots=True)
class OpenBetChoice:
    """A caller's still-open (deletable) bet, offered in the delete Select."""

    fixture_id: int
    category: BetCategory
    matchup: str


def build_open_bet_choices(
    session: Session, player_discord_id: int, *, now: datetime
) -> list[OpenBetChoice]:
    """The caller's bets on still-open games (only these can be deleted — §8.2)."""
    games = GameRepository(session)
    choices: list[OpenBetChoice] = []
    for bet in BetRepository(session).list_for_player(player_discord_id):
        game = games.get(bet.fixture_id)
        if game is not None and is_bet_open(game.kickoff_utc, now):
            choices.append(
                OpenBetChoice(
                    fixture_id=bet.fixture_id,
                    category=BetCategory(bet.category),
                    matchup=f"{game.home_team_name} x {game.away_team_name}",
                )
            )
    return choices


class DeleteSelect(ui.Select[ui.View]):
    def __init__(self, ctx: FlowContext, choices: Sequence[OpenBetChoice]) -> None:
        super().__init__(
            placeholder="Apagar um palpite (opcional)",
            options=[
                discord.SelectOption(
                    label=f"{c.matchup} — {CATEGORY_LABELS_PT[c.category]}"[:100],
                    value=f"{c.fixture_id}:{c.category.value}",
                )
                for c in choices
            ],
        )
        self._ctx = ctx

    async def callback(self, interaction: discord.Interaction) -> None:
        fixture_str, category_str = self.values[0].split(":", 1)
        category = BetCategory(category_str)
        try:
            with self._ctx.session_factory() as session:
                deleted = delete_bet(
                    session,
                    fixture_id=int(fixture_str),
                    player_discord_id=self._ctx.user_id,
                    category=category,
                    now=self._ctx.clock(),
                )
                session.commit()
            message = "✅ Palpite apagado." if deleted else "Esse palpite não existe mais."
        except BetError as exc:
            message = f"❌ {exc}"
        await interaction.response.edit_message(content=message, view=None)


def build_delete_view(ctx: FlowContext, choices: Sequence[OpenBetChoice]) -> ui.View:
    """A Select to delete one of the caller's open bets."""
    view = ui.View(timeout=VIEW_TIMEOUT)
    view.add_item(DeleteSelect(ctx, choices[:DISCORD_SELECT_LIMIT]))
    return view
