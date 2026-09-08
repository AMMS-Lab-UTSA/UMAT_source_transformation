"""A model can stop producing numbers part-way along a probe path.

The verification drives every material through extension, then shear, then a
reversal. Measured on BodyForce-Growth-2Stages.for: both builds agree through
twenty-two increments -- the whole uniaxial segment, the whole shear segment
and two of the reversal -- and then BOTH return NaN from increment
twenty-three, at the same increment and in the same components. That is a
growth model declining to be driven backwards.

Comparing across it produced `inf` and the row was recorded as
primal_disagreed, which reads as a conversion defect and is not one. Refusing
the row outright would throw away twenty-two increments of real agreement.

The line that matters: this only ever applies where BOTH builds went
non-finite at the SAME increment. A transformed build that goes non-finite
where the original did not is the defect this pipeline exists to catch.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_store_in_abaqus import (MINIMUM_COMPARABLE_INCREMENTS,  # noqa: E402
                                    STAGES, common_finite_prefix)

NAN = float("nan")


def _r(*values):
    return {"STRESS": list(values), "STATEV": []}


def test_both_builds_leaving_together_truncates_to_what_they_computed():
    history = [_r(1.0), _r(2.0), _r(NAN), _r(NAN)]
    left, right, stopped = common_finite_prefix(history, list(history))
    assert len(left) == len(right) == 2
    assert stopped == 2


def test_the_transformed_build_leaving_first_is_not_truncated():
    """It is the defect the pipeline exists to catch, and it must keep
    failing rather than being trimmed away."""
    original = [_r(1.0), _r(2.0), _r(3.0), _r(4.0)]
    transformed = [_r(1.0), _r(NAN), _r(NAN), _r(NAN)]
    left, right, stopped = common_finite_prefix(original, transformed)
    assert stopped == -1
    assert len(left) == 4 and len(right) == 4


def test_the_original_leaving_first_is_not_truncated_either():
    original = [_r(1.0), _r(NAN), _r(NAN)]
    transformed = [_r(1.0), _r(2.0), _r(3.0)]
    assert common_finite_prefix(original, transformed)[2] == -1


def test_a_history_that_stays_finite_is_untouched():
    history = [_r(1.0), _r(2.0)]
    left, right, stopped = common_finite_prefix(history, list(history))
    assert stopped == -1 and len(left) == 2


def test_a_non_finite_state_variable_counts_too():
    """A model can keep returning a stress while its state goes bad."""
    history = [{"STRESS": [1.0], "STATEV": [0.0]},
               {"STRESS": [2.0], "STATEV": [NAN]}]
    assert common_finite_prefix(history, list(history))[2] == 1


def test_an_infinity_counts_as_leaving_the_domain():
    history = [_r(1.0), _r(math.inf)]
    assert common_finite_prefix(history, list(history))[2] == 1


def test_too_short_a_prefix_establishes_nothing():
    """Agreement over one or two increments is not a verification, however
    well those increments agree."""
    assert MINIMUM_COMPARABLE_INCREMENTS >= 5


def test_the_outcome_has_its_own_rung():
    """Reported as what it is rather than folded into a disagreement: a
    model leaving its own domain and a conversion computing the wrong number
    are two different findings."""
    assert "both_builds_non_finite" in STAGES
    assert STAGES.index("both_builds_non_finite") < STAGES.index("verified")
