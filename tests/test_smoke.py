"""Scaffold smoke test: the package imports and exposes a version."""

from __future__ import annotations

import tigrinho


def test_package_importable() -> None:
    assert tigrinho.__version__ == "0.1.0"
