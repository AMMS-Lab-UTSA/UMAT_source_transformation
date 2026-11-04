"""A verification row is current only for the harness that produced it.

The transform fingerprint deliberately excludes the verification harness
(``abaqus/``, ``corpus_features/``) so that a better comparison does not force
every stored transform to be rebuilt. That left a hole: a change to HOW a
source is run -- the NTENS inference moved ten rows to a different element, one
of them recorded fully verified on a layout that put a shear in the sigma_33
slot -- left every earlier verdict looking current. The harness now has its
own fingerprint, rows record it, and the registry can require it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.store.transform_store import (
    HARNESS_CODE, NOT_TRANSFORM_CODE, harness_fingerprint, transform_fingerprint,
)

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "umat_oti"


def _copy_package(tmp_path: Path) -> Path:
    root = tmp_path / "umat_oti"
    for sub in ("abaqus", "corpus_features", "transform"):
        (root / sub).mkdir(parents=True)
        (root / sub / "m.py").write_text(f"# {sub}\n")
    return root


@pytest.mark.unit
def test_the_harness_is_exactly_the_part_the_transform_fingerprint_leaves_out():
    assert set(HARNESS_CODE) <= set(NOT_TRANSFORM_CODE)


@pytest.mark.unit
def test_a_harness_change_moves_the_harness_fingerprint_and_not_the_transform_one(tmp_path):
    root = _copy_package(tmp_path)
    before = (transform_fingerprint(root), harness_fingerprint(root))
    (root / "abaqus" / "m.py").write_text("# abaqus, now deciding NTENS differently\n")
    after = (transform_fingerprint(root), harness_fingerprint(root))
    assert after[0] == before[0]
    assert after[1] != before[1]


@pytest.mark.unit
def test_a_transform_change_leaves_the_harness_fingerprint_alone(tmp_path):
    root = _copy_package(tmp_path)
    before = harness_fingerprint(root)
    (root / "transform" / "m.py").write_text("# transform changed\n")
    assert harness_fingerprint(root) == before


@pytest.mark.unit
def test_the_real_package_has_a_harness_fingerprint():
    assert len(harness_fingerprint(PACKAGE)) == 16


def test_the_harness_fingerprint_covers_the_abaqus_gate_tool(tmp_path):
    """review G10 review: the D-4 gate's decision code lives in
    tools/verify_store_in_abaqus.py, so the harness identity covers it."""
    import shutil
    from pathlib import Path
    from umat_oti.store.transform_store import harness_fingerprint
    repo = Path(__file__).resolve().parents[1]
    copy = tmp_path / "repo"
    shutil.copytree(repo / "src" / "umat_oti", copy / "src" / "umat_oti",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (copy / "tools").mkdir()
    shutil.copy(repo / "tools" / "verify_store_in_abaqus.py", copy / "tools")
    before = harness_fingerprint(copy / "src" / "umat_oti")
    with open(copy / "tools" / "verify_store_in_abaqus.py", "a") as handle:
        handle.write("\n# changed\n")
    assert harness_fingerprint(copy / "src" / "umat_oti") != before


def test_the_fingerprint_says_which_digest_it_is(tmp_path):
    import shutil
    from pathlib import Path
    from umat_oti.store.transform_store import harness_fingerprint_basis
    repo = Path(__file__).resolve().parents[1]
    assert harness_fingerprint_basis(repo / "src" / "umat_oti") == "package+tools"
    copy = tmp_path / "repo"
    shutil.copytree(repo / "src" / "umat_oti", copy / "src" / "umat_oti",
                    ignore=shutil.ignore_patterns("__pycache__"))
    assert harness_fingerprint_basis(copy / "src" / "umat_oti") == "package-only"
