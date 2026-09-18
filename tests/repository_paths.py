"""Configured companion checkout paths for cross-project tests."""

import os
from pathlib import Path


def resasm_repo_root() -> Path | None:
    override = os.environ.get("RESASM_REPO")
    root = Path(override).expanduser() if override else Path(__file__).resolve().parents[2] / "Residual_Assembler"
    if (root / "residual_core").is_dir():
        return root.resolve()
    if override:
        raise FileNotFoundError(f"Configured RESASM_REPO is not a checkout: {root}")
    return None


def verified_fixtures() -> list[Path]:
    root = resasm_repo_root()
    return sorted((root / "tests/fixtures/verified").glob("*.json")) if root else []