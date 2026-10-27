"""Resolve public demo inputs without assuming a checkout surrounds the wheel."""

from importlib import resources
import os
from pathlib import Path


# The demo contract names UMATs/UMATs/ICP/elasticity/elastic.f (Dunne & Petrinic).
# That file has no redistribution licence and is no longer shipped: users who
# want the demo download it from the publisher (UMATs/UMATs/ICP/
# DUNNE_PETRINIC_REMOVED.md). It is therefore not a required demo input, so a
# checkout without it is still recognised as the repository root.
DEMO_INPUTS = (
    "examples/elastic_minimal.json",
)


def repository_root() -> Path | None:
    override = os.environ.get("UMAT_OTI_REPO") or os.environ.get("UMAT_OTI_REPO_ROOT")
    candidate = Path(override).expanduser() if override else Path(__file__).resolve().parents[3]
    if all((candidate / relative).is_file() for relative in DEMO_INPUTS):
        return candidate.resolve()
    if override:
        raise FileNotFoundError(f"UMAT demo inputs missing from configured checkout: {candidate}")
    return None


def demo_contract(workspace: Path) -> Path:
    root = repository_root()
    if root is not None:
        return root / DEMO_INPUTS[0]
    bundled = resources.files("umat_oti.app").joinpath("demo_inputs")
    destination = Path(workspace) / "demo_inputs"
    for relative in DEMO_INPUTS:
        content = bundled.joinpath(relative).read_bytes()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != content:
            target.write_bytes(content)
    return destination / DEMO_INPUTS[0]