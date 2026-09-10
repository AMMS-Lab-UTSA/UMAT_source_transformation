"""A centred difference is not exact, and on some models it is not close.

The tangent under test is compared with a centred difference of the original.
That difference has an error of its own, and on a model with a local Newton
solve or an ill-conditioned kinematic expression it is far above the
eps**(2/3) a smooth function would give. Several corpus entries miss the 1e-6
tolerance by a factor of two to fifty -- 2.07e-06, 7.69e-06 -- which is a
question about the reference as much as about the transform.

There is a second reference available for nothing. The ORIGINAL routine
returns its own analytic DDSDDE, and the replay records it at the same state.
It shares no code path with the converted build. So the same sweep answers
three questions rather than one: how far the conversion is from the
difference, how far the AUTHOR'S OWN tangent is from the same difference, and
how far the conversion is from the author's.

Where the conversion reproduces the author's tangent and sits no further from
the difference than the author's own does, the difference cannot tell them
apart -- and a reference that cannot tell two values apart is not evidence
that they differ. That is a pass on a narrower claim and it says so.

Where they do NOT agree there are two candidate tangents and a reference too
coarse to choose, which is exactly the situation nothing may be claimed in.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_store_in_abaqus import (SAME_TANGENT,  # noqa: E402
                                    _resolved_by_the_reference)


def outcome(mine: float, author: float, floor: float) -> dict:
    return {"comparison": {"best_relative": mine},
            "against_the_authors_tangent": {"best_relative": author},
            "the_references_own_error": {"best_relative": floor}}


def test_a_difference_that_cannot_tell_them_apart_is_not_evidence():
    verified, why = _resolved_by_the_reference(
        outcome(mine=2.07e-6, author=3e-13, floor=2.5e-6),
        tolerance=1e-6, reason="the closest step agreed only to 2.07e-06")
    assert verified
    assert "cannot separate them" in why
    assert "3.000e-13" in why


def test_a_conversion_that_differs_from_the_author_is_not_rescued():
    """Two candidate answers and a reference too coarse to choose."""
    verified, why = _resolved_by_the_reference(
        outcome(mine=2.07e-6, author=4.0e-3, floor=2.5e-6),
        tolerance=1e-6, reason="the closest step agreed only to 2.07e-06")
    assert not verified
    assert "two candidate tangents" in why


def test_a_reference_good_enough_to_have_noticed_is_believed():
    """The author's own tangent sits much closer to the difference than the
    conversion does, so the difference was sharp enough to see the gap."""
    verified, why = _resolved_by_the_reference(
        outcome(mine=2.07e-6, author=1e-13, floor=1e-11),
        tolerance=1e-6, reason="the closest step agreed only to 2.07e-06")
    assert not verified
    assert "not too coarse to have noticed" in why


def test_a_missing_measurement_rescues_nothing():
    for missing in ("comparison", "against_the_authors_tangent",
                    "the_references_own_error"):
        record = outcome(1e-6, 1e-13, 1e-5)
        record[missing] = {}
        verified, why = _resolved_by_the_reference(
            record, tolerance=1e-6, reason="unchanged")
        assert not verified
        assert why == "unchanged"


def test_the_threshold_is_not_a_tolerance_on_correctness():
    """It is the point at which two numbers are indistinguishable to the
    reference, and it is far below the tolerance the verdict uses."""
    assert SAME_TANGENT < 1e-6
