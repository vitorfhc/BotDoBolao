"""CLAUDE.md must encode the mandatory project rules (COMPLETION.md §2, §11)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_claude_md_encodes_required_rules() -> None:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    lowered = text.lower()
    # Grounding rule (§2): web-search official docs before using/changing an external API.
    assert "web search" in lowered or "web-search" in lowered
    # Secrets-in-.env / settings-in-config.yaml split (§4).
    assert ".env" in text and "config.yaml" in text
    # /ajuda + COMPLETION.md kept in sync on rule changes (§11 maintenance rule).
    assert "/ajuda" in text
    assert "COMPLETION.md" in text
    # Quality gates.
    assert "mypy --strict" in text
