"""The consistent tangent must be checked, and the check must be able to fail.

A verification that cannot fail is not a verification, so most of this file is
about the adjudicator refusing to bless values that are wrong -- including at
the structural zeros, which are the easiest place for a check to become
vacuous.
"""
from __future__ import annotations

import pytest

from umat_oti.validation.actual_umat_higher_order import (
    TANGENT_RELATIVE_TOLERANCE, TANGENT_ZERO_FRACTION, _tangent_row,
)

SCALE = 2.3e5


def _row(oti, analytic, numeric, scale=SCALE):
    return _tangent_row(1, "elastic", 1, 1, oti, analytic, numeric, scale)


def test_matching_value_agrees():
    row = _row(1.5e5, 1.5e5, 1.5e5)
    assert row["agrees"] is True
    assert row["judged_by"] == "relative"


def test_value_outside_the_tolerance_disagrees():
    exact = 1.5e5
    row = _row(exact * (1 + 1e-6), exact, exact)
    assert row["agrees"] is False
    assert row["relative_error"] > TANGENT_RELATIVE_TOLERANCE


def test_rounding_dust_at_a_structural_zero_is_a_zero_not_a_disagreement():
    """The 80-digit reference leaves ~1e-75 where the closed form gives 0.

    Divided by itself that is a 100% relative spread, which once made 26 exact
    zeros report as entries the references could not adjudicate.
    """
    row = _row(0.0, 0.0, 2.5e-76)
    assert row["reference_classification"] == "resolved"
    assert row["judged_by"] == "structural_zero"
    assert row["agrees"] is True


def test_a_nonzero_value_at_a_structural_zero_still_fails():
    """Giving the zero test a scale must not turn it into a blanket pass."""
    row = _row(1.0, 0.0, 2.5e-76)
    assert row["judged_by"] == "structural_zero"
    assert row["agrees"] is False


def test_the_zero_floor_scales_with_the_matrix():
    """The same absolute value is dust in a stiff tangent and a defect in a soft one.

    Both references put the entry at zero either way, so it is a structural
    zero either way. What the scale decides is whether the value the build
    returned is close enough to zero to count as zero.
    """
    value = SCALE * TANGENT_ZERO_FRACTION / 10.0
    stiff = _row(value, 0.0, 0.0)
    soft = _row(value, 0.0, 0.0, scale=SCALE / 1e6)
    assert stiff["judged_by"] == soft["judged_by"] == "structural_zero"
    assert stiff["agrees"] is True
    assert soft["agrees"] is False


def test_references_that_disagree_with_each_other_adjudicate_nothing():
    row = _row(1.0e5, 1.0e5, 1.2e5)
    assert row["reference_classification"] == "reference_unresolved"
    assert row["agrees"] is None


def test_a_missing_value_is_unresolved_not_zero():
    row = _row(None, 1.5e5, 1.5e5)
    assert row["reference_classification"] == "unresolved"
    assert row["agrees"] is None
    assert row["oti"] is None


@pytest.mark.parametrize("field", ["analytic_reference",
                                   "extended_precision_reference",
                                   "reference_spread", "matrix_scale",
                                   "structural_zero_floor", "justification"])
def test_every_row_records_what_it_was_judged_against(field):
    assert field in _row(1.5e5, 1.5e5, 1.5e5)


# --------------------------------------------------------------------------- #
# The generic path, which adjudicates against a compiled reference rather than
# a closed form, and so must decide when its reference is too coarse to speak.
# --------------------------------------------------------------------------- #
from umat_oti.validation.reference_resolution import ResolutionLadder  # noqa: E402
from umat_oti.validation.tangent_validation import (  # noqa: E402
    ZERO_FRACTION, _adjudicate, _summarise,
)


def _ladder(values):
    ladder = ResolutionLadder(props_index=1, array="DDSDDE",
                              steps=tuple(range(len(values))))
    ladder.values[(1, 1)] = tuple(values)
    return ladder


def _generic(values, oti, scale=SCALE, tolerance=1e-6):
    return _adjudicate(_ladder(values), 1, 1, 1, oti, tolerance, scale)


def test_a_value_the_reference_straddles_needs_no_tolerance():
    row = _generic([1.0e5, 1.1e5, 1.05e5], 1.06e5)
    assert row["agrees"] is True
    assert row["judged_by"] == "within_reference_resolution"


def test_a_value_outside_a_tight_reference_is_judged_on_relative_error():
    tight = [1.0e5, 1.0e5 + 1.0, 1.0e5 + 2.0]
    row = _generic(tight, 1.5e5)
    assert row["judged_by"] == "relative"
    assert row["agrees"] is False


def test_an_empty_ladder_is_unresolved_not_zero():
    """A reference that could not be evaluated must not read as a zero derivative."""
    row = _generic([], 1.5e5)
    assert row["reference_classification"] == "unresolved"
    assert row["agrees"] is None
    assert row["absolute_error"] is None


def test_a_nonzero_value_where_the_reference_says_zero_disagrees():
    row = _generic([0.0, 0.0, 0.0], SCALE * ZERO_FRACTION * 10)
    assert row["judged_by"] == "structural_zero"
    assert row["agrees"] is False


def test_the_summary_keeps_every_entry_in_the_denominator():
    rows = [_generic([1.0e5] * 3, 1.0e5), _generic([], 1.0e5),
            _generic([0.0] * 3, SCALE)]
    summary = _summarise(rows)
    assert summary["entries"] == 3
    assert summary["resolved"] + summary["unresolved"] == 3
    assert summary["disagreeing"] == 1
