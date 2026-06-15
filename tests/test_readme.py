"""README must be the full deployment guide with all §15.1 sections (COMPLETION.md §15.1)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_readme_has_all_14_sections() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for number in range(1, 15):
        assert f"## {number}." in text, f"missing section {number}"


def test_readme_covers_key_steps() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "cp .env.example .env" in text
    assert "cp config.example.yaml config.yaml" in text
    assert "docker compose up -d --build" in text
    assert "python -m tigrinho.cli" in text  # admin CLI
    assert "provider_mode: fake" in text  # local dev
    # every player command is documented
    for command in (
        "/apostar",
        "/minhas_apostas",
        "/jogos",
        "/placar",
        "/inscrever",
        "/sair",
        "/ajuda",
    ):
        assert command in text
    # no-real-money note + FIFA disclaimer
    assert "no real money" in lowered
    assert "fifa" in lowered
