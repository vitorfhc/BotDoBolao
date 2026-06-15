"""Entrypoint: ``python -m tigrinho`` loads config, sets up logging, and runs the bot."""

from __future__ import annotations

from tigrinho.bootstrap import run

if __name__ == "__main__":  # pragma: no cover - process entrypoint
    run()
