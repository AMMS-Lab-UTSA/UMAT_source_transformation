"""What can change a stored transform must make it stale; nothing else may.

The store keys every entry on a digest of the transform code, so that changing
the transform re-derives every cached output instead of serving yesterday's.
That is the property worth having and these tests hold it: every subpackage the
transform is built from contributes to the digest.

One subpackage is exempt. ``umat_oti.abaqus`` is the verification harness --
decks, jobs, probes, comparisons, the finite-difference replay -- and it cannot
reach the bytes the store holds, because nothing on the transform side imports
it. The exemption is therefore structural, and the second test below is what
keeps it structural: the day a transform module imports the harness, the
exemption is unsound and this fails.

Why it matters: with the harness fingerprinted, improving a comparison marked
all 250 stored transforms stale, so looking harder at the evidence cost a full
re-derivation of the evidence.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from umat_oti.store.transform_store import (NOT_TRANSFORM_CODE,  # noqa: E402
                                            transform_fingerprint)

PACKAGE = ROOT / "src" / "umat_oti"


def test_a_change_anywhere_in_the_transform_changes_the_fingerprint(tmp_path):
    """Every transform subpackage is covered, one file at a time."""
    before = transform_fingerprint(PACKAGE)
    touched = 0
    for module in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        relative = module.relative_to(PACKAGE)
        if relative.parts[0] in NOT_TRANSFORM_CODE:
            continue
        original = module.read_bytes()
        try:
            module.write_bytes(original + b"\n# fingerprint probe\n")
            assert transform_fingerprint(PACKAGE) != before, relative
            touched += 1
        finally:
            module.write_bytes(original)
    assert transform_fingerprint(PACKAGE) == before
    assert touched > 50, "the transform is not this small; the walk missed it"


def test_the_exempt_subpackage_is_a_leaf():
    """Nothing on the transform side may import the verification harness.

    If one did, the harness would be transform code, and excluding it from the
    fingerprint would let a change to it serve stale transforms as current.
    """
    offenders = []
    for module in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        relative = module.relative_to(PACKAGE)
        if relative.parts[0] in NOT_TRANSFORM_CODE:
            continue
        # Parsed, not grepped: a docstring that names the harness is prose
        # about the boundary, and prose is not an import.
        tree = ast.parse(module.read_text(errors="replace"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                reached = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level
                reached = [f"{prefix}{node.module or ''}"]
            else:
                continue
            for name in reached:
                bare = name.lstrip(".")
                head = bare.split(".")[0] if name.startswith(".") else ""
                package = (bare.split(".")[1] if bare.startswith("umat_oti.")
                           else head)
                if package in NOT_TRANSFORM_CODE:
                    offenders.append(f"{relative} imports {name}")
    assert not offenders, (
        "these modules make the exemption unsound: " + "; ".join(offenders))


def test_a_change_to_the_harness_leaves_the_fingerprint_alone():
    before = transform_fingerprint(PACKAGE)
    harness = PACKAGE / "abaqus" / "compare.py"
    original = harness.read_bytes()
    try:
        harness.write_bytes(original + b"\n# fingerprint probe\n")
        assert transform_fingerprint(PACKAGE) == before
    finally:
        harness.write_bytes(original)


def test_the_fortran_the_transform_copies_is_covered():
    """The OTI support units are copied verbatim into every output, so a change
    to one changes what every transformed source computes."""
    before = transform_fingerprint(PACKAGE)
    units = [p for p in PACKAGE.rglob("*.f90")
             if p.relative_to(PACKAGE).parts[0] not in NOT_TRANSFORM_CODE]
    assert units, "the bundled OTI Fortran is missing"
    original = units[0].read_bytes()
    try:
        units[0].write_bytes(original + b"\n! fingerprint probe\n")
        assert transform_fingerprint(PACKAGE) != before
    finally:
        units[0].write_bytes(original)
