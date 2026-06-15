"""pt-BR message templates (COMPLETION.md §11).

The ``/ajuda`` text is built from the domain enums and the :data:`POINTS` table, so it stays in
sync with scoring automatically. **Maintenance rule:** any change to commands, categories, scoring,
or grading rules MUST update this module and COMPLETION.md together (enforced via CLAUDE.md).
"""

from __future__ import annotations

from .bets import BetCategory
from .scoring import POINTS

CATEGORY_LABELS_PT: dict[BetCategory, str] = {
    BetCategory.EXACT_SCORE: "Placar exato",
    BetCategory.FIRST_SCORER: "Primeiro a marcar",
    BetCategory.BTTS: "Ambos marcam",
    BetCategory.WINNER: "Vencedor",
    BetCategory.OVER_UNDER: "Mais/Menos 2.5 gols",
}

_CATEGORY_EXAMPLES_PT: dict[BetCategory, str] = {
    BetCategory.EXACT_SCORE: "ex.: Brasil 2x1",
    BetCategory.FIRST_SCORER: "quem faz o 1º gol até os 90' (gol contra não conta)",
    BetCategory.BTTS: "ambos marcam? (ambos / só mandante / só visitante / nenhum)",
    BetCategory.OVER_UNDER: "total de gols: mais de 2.5 (3+) ou menos de 2.5 (até 2)",
    BetCategory.WINNER: "quem vence (mandante / empate / visitante)",
}

# Display order: highest points first (matches the COMPLETION.md §8.1 table).
_CATEGORY_ORDER: tuple[BetCategory, ...] = (
    BetCategory.EXACT_SCORE,
    BetCategory.FIRST_SCORER,
    BetCategory.BTTS,
    BetCategory.WINNER,
    BetCategory.OVER_UNDER,
)

_COMMANDS_PT: tuple[tuple[str, str], ...] = (
    ("/apostar", "fazer ou editar um palpite (escolhe o jogo, a categoria e o valor)"),
    ("/minhas_apostas", "ver seus palpites e apagar os que ainda estão abertos"),
    ("/jogos", "ver os jogos abertos para apostar e o que ainda falta palpitar"),
    ("/placar", "ver o ranking — `/placar geral` (todo o torneio) ou `/placar semana`"),
    ("/inscrever", "passar a receber os avisos de novos jogos (entra no cargo @Tigrinhos)"),
    ("/sair", "parar de receber os avisos (sai do cargo @Tigrinhos)"),
    ("/ajuda", "ver esta mensagem de ajuda"),
)


def _pluralize_points(points: int) -> str:
    return f"{points} ponto" if points == 1 else f"{points} pontos"


def help_text() -> str:
    """Build the full pt-BR ``/ajuda`` text (covers every item required by §11)."""
    lines: list[str] = [
        "🐯 **TigrinhoDaCopa** — bolão da Copa do Mundo 2026, valendo só a diversão "
        "(nada de dinheiro de verdade!).",
        "",
        "Qualquer pessoa do servidor pode apostar. Quando um jogo é anunciado, use **/apostar** "
        "para dar seu palpite. As apostas **fecham no apito inicial** de cada jogo. Quando o jogo "
        "acaba, o bot apura tudo sozinho e atualiza o placar.",
        "",
        "**📋 Comandos**",
    ]
    lines += [f"• `{name}` — {desc}" for name, desc in _COMMANDS_PT]

    lines += ["", "**🎯 Categorias de palpite e pontos**"]
    for category in _CATEGORY_ORDER:
        label = CATEGORY_LABELS_PT[category]
        example = _CATEGORY_EXAMPLES_PT[category]
        lines.append(f"• **{label}** — {_pluralize_points(POINTS[category])} ({example})")

    lines += [
        "",
        "**⚖️ Regras**",
        "• Os palpites de placar (placar exato, ambos marcam, mais/menos, primeiro a marcar) "
        "valem pelo resultado dos **90 minutos** (sem prorrogação nem pênaltis).",
        "• **Mata-mata:** o Vencedor é quem **avança** — não existe empate, e o palpite de empate "
        "sempre perde. (Na fase de grupos, o empate vale normalmente.)",
        "• Gol contra **não** conta como “primeiro a marcar”. Se o jogo termina 0x0 (ou só com gol "
        "contra) nos 90', todos os palpites de primeiro a marcar perdem.",
        "• Um palpite por categoria em cada jogo; dá para editar até o apito inicial.",
        "",
        "**🔔 Avisos (cargo @Tigrinhos)**",
        "O cargo **@Tigrinhos** serve só para receber as menções nos anúncios — **qualquer pessoa "
        "pode apostar**, com ou sem o cargo. Use **/inscrever** para receber os avisos e **/sair** "
        "para parar.",
    ]
    return "\n".join(lines)
