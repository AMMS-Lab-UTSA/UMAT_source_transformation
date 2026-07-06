"""Shared pytest fixtures for the UMAT-OTI test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def examples_dir(repo_root: Path) -> Path:
    """Directory holding the bundled known-good example JSON contracts."""
    return repo_root / "examples"
