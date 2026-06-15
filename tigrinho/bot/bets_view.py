"""Pure pt-BR rendering for /minhas_apostas and /jogos (COMPLETION.md §8.2).

These take already-resolved view lines (the cog does the DB work + payload rendering) and
produce the message text, so they are testable without a gateway or DB.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo

from tigrinho.domain.bets import BetCategory
from tigrinho.domain.text_pt import CATEGORY_LABELS_PT
from tigrinho.providers.base import Stage

from .sync_planning import format_kickoff_pt

STAGE_LABELS_PT: dict[Stage, str] = {
    Stage.GROUP: "Fase de grupos",
    Stage.KNOCKOUT: "Mata-mata",
}


@dataclass(frozen=True, slots=True)
class MyBetLine:
    """One of a player's bets, with its game and (if apurado) result."""

    matchup: str
    category: BetCategory
    value: str  # already rendered (e.g. "Brasil", "2x1")
    settled: bool
    is_correct: bool | None
    points: int | None


@dataclass(frozen=True, slots=True)
class OpenGameLine:
    """An open game and which categories the caller has already bet."""

    matchup: str
    kickoff_utc: datetime
    stage: Stage
    bet_categories: frozenset[BetCategory]


def _group_by_matchup(lines: Sequence[MyBetLine], *, settled: bool) -> list[str]:
    grouped: dict[str, list[MyBetLine]] = {}
    for line in lines:
        grouped.setdefault(line.matchup, []).append(line)
    out: list[str] = []
    for matchup, items in grouped.items():
        out.append(f"__{matchup}__")
        for item in items:
            text = f"• {CATEGORY_LABELS_PT[item.category]}: {item.value}"
            if settled:
                mark = "✅" if item.is_correct else "❌"
                text += f" {mark} (+{item.points or 0})"
            out.append(text)
    return out


def render_my_bets(lines: Sequence[MyBetLine]) -> str:
    """Render the caller's bets, grouped by game, split into open vs apurados."""
    if not lines:
        return "Você ainda não fez nenhum palpite. Use /apostar para começar! 🐯"
    open_lines = [line for line in lines if not line.settled]
    settled_lines = [line for line in lines if line.settled]
    out = ["🎯 **Suas apostas**"]
    if open_lines:
        out.append("\n**Abertas:**")
        out += _group_by_matchup(open_lines, settled=False)
    if settled_lines:
        out.append("\n**Apuradas:**")
        out += _group_by_matchup(settled_lines, settled=True)
    return "\n".join(out)


def render_open_games(games: Sequence[OpenGameLine], *, tz: tzinfo) -> str:
    """Render open games with kickoff (local), stage, and what the caller still has to predict."""
    if not games:
        return "Nenhum jogo aberto para apostar agora. ⏳"
    out = ["📅 **Jogos abertos**"]
    for game in games:
        when = format_kickoff_pt(game.kickoff_utc.astimezone(tz))
        out.append(f"• **{game.matchup}** — {when} ({STAGE_LABELS_PT[game.stage]})")
        missing = [
            CATEGORY_LABELS_PT[category]
            for category in BetCategory
            if category not in game.bet_categories
        ]
        if missing:
            out.append(f"   falta palpitar: {', '.join(missing)}")
        else:
            out.append("   ✅ tudo palpitado!")
    return "\n".join(out)
