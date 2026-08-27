"""A reference that straddles a kink must not be allowed to adjudicate.

sweep_drucker_prager is why this exists. On the increment where it first
yields, the centred difference returned exactly half the inelastic sensitivity
-- the average of the elastic and inelastic one-sided derivatives -- and the
comparison called the model failed. Nothing was wrong with the derivative: the
OTI value was the derivative on the branch the increment actually took, and the
reference was measuring something else.
"""
from __future__ import annotations

import pytest

from umat_oti.validation.parameter_sensitivity_validation import (
    branch_history, compare,
)

PARAMETERS = [{"name": "k", "props_index": 3, "oti_direction": 1}]


def _reference(values, *, high, low, step=1e-4):
    return {3: {"step": step,
                "dsigma": [[v] for v in values],
                "dstatev": [[0.0] for _ in values],
                "high_branch": high, "low_branch": low}}


def _rows(oti_values, reference, branches):
    oti = {(i + 1, 1): {"K": v} for i, v in enumerate(oti_values)}
    return compare(oti, reference, array="DSIGMA_DP", parameters=PARAMETERS,
                   branches=branches, response_scale=1.0)


def test_branch_history_reads_the_marker():
    assert branch_history([[0.0], [0.0], [1e-6]]) == \
        ["elastic", "elastic", "inelastic"]


def test_a_stencil_that_stays_on_the_branch_is_adjudicated_normally():
    rows = _rows([1.0, 2.0],
                 _reference([1.0, 2.0], high=["elastic", "inelastic"],
                            low=["elastic", "inelastic"]),
                 ["elastic", "inelastic"])
    assert [r.branch_crossing for r in rows] == [False, False]
    assert all(r.agrees is True for r in rows)


def test_the_yield_increment_is_unresolved_not_failed():
    """The exact drucker-prager signature: reference is half the inelastic value."""
    rows = _rows([0.0, 2.0],
                 _reference([1.0, 2.0], high=["inelastic", "inelastic"],
                            low=["elastic", "inelastic"]),
                 ["elastic", "inelastic"])
    crossing = rows[0]
    assert crossing.branch_crossing is True
    assert crossing.agrees is None
    assert crossing.judged_by == "reference_unresolved_branch_crossing"
    assert rows[1].agrees is True


def test_a_crossing_row_that_happens_to_agree_is_still_unresolved():
    """Agreement across a kink is luck, not evidence, and must not count."""
    rows = _rows([1.0],
                 _reference([1.0], high=["inelastic"], low=["elastic"]),
                 ["elastic"])
    assert rows[0].agrees is None
    assert rows[0].branch_crossing is True


def test_a_reference_without_branch_records_keeps_its_old_classification():
    """Evidence produced before branches were measured must not become unresolved."""
    reference = {3: {"step": 1e-4, "dsigma": [[1.0]], "dstatev": [[0.0]]}}
    rows = _rows([1.0], reference, ["elastic"])
    assert rows[0].branch_crossing is False
    assert rows[0].agrees is True


def test_crossing_does_not_hide_a_real_disagreement_elsewhere():
    rows = _rows([0.0, 5.0],
                 _reference([1.0, 2.0], high=["inelastic", "inelastic"],
                            low=["elastic", "inelastic"]),
                 ["elastic", "inelastic"])
    assert rows[0].agrees is None
    assert rows[1].agrees is False


@pytest.mark.parametrize("high,low", [(["inelastic"], ["inelastic"]),
                                      (["elastic"], ["inelastic"]),
                                      (["inelastic"], ["elastic"])])
def test_either_side_leaving_the_branch_counts_as_crossing(high, low):
    rows = _rows([1.0], _reference([1.0], high=high, low=low), ["elastic"])
    assert rows[0].branch_crossing is True


def test_a_caller_that_labels_branches_differently_gets_no_crossing():
    """The internal-Jacobian path labels every increment "local_solve".

    There the state array holds probe slots, not an inelasticity marker, so the
    perturbed branches are meaningless. Comparing the two vocabularies made
    every row differ from its nominal branch, and one whole verification became
    "the reference cannot adjudicate" -- from a check that was passing.
    """
    rows = _rows([1.0],
                 _reference([1.0], high=["elastic"], low=["elastic"]),
                 ["local_solve"])
    assert rows[0].branch_crossing is False
    assert rows[0].agrees is True


# --------------------------------------------------------------------------- #
# A one-sided reference inside the branch, where the centred one crosses it
# --------------------------------------------------------------------------- #
def _reference_with_sides(centred, *, high, low, forward, backward, step=1e-4,
                          far_high=None, far_low=None):
    """A reference carrying both the centred and the one-sided estimates.

    ``far_high`` and ``far_low`` are the branches the outer point of each
    three-point one-sided stencil landed on; they default to the near ones,
    which is the case where a side stays on its branch throughout.
    """
    return {3: {"step": step,
                "dsigma": [[v] for v in centred],
                "dstatev": [[0.0] for _ in centred],
                "forward_dsigma": [[v] for v in forward],
                "backward_dsigma": [[v] for v in backward],
                "forward_dstatev": [[0.0] for _ in forward],
                "backward_dstatev": [[0.0] for _ in backward],
                "high_branch": high, "low_branch": low,
                "forward_far_branch": far_high if far_high is not None else high,
                "backward_far_branch": far_low if far_low is not None else low}}


def test_a_crossing_row_is_adjudicated_by_the_side_that_stayed_on_the_branch():
    """The drucker-prager signature: centred gives half, one side gives the truth.

    At the increment where the material first yields, the centred difference
    averages the elastic and inelastic one-sided derivatives. The value under
    test is the elastic one, and the backward difference still measures it.
    """
    reference = _reference_with_sides(
        [1.0], high=["inelastic"], low=["elastic"],
        forward=[2.0], backward=[0.0])
    rows = _rows([0.0], reference, ["elastic"])
    row = rows[0]
    assert row.branch_crossing is True
    assert row.judged_by.startswith("one_sided_within_branch_backward:")
    assert row.agrees is True
    assert row.reference == 0.0


def test_the_forward_side_is_used_when_that_is_the_one_inside_the_branch():
    reference = _reference_with_sides(
        [1.0], high=["elastic"], low=["inelastic"],
        forward=[0.0], backward=[2.0])
    rows = _rows([0.0], reference, ["elastic"])
    assert rows[0].judged_by.startswith("one_sided_within_branch_forward:")
    assert rows[0].agrees is True


def test_a_one_sided_reference_carries_the_rule_it_was_judged_by():
    """The label names both the reference and the test applied to it."""
    reference = _reference_with_sides(
        [1.0], high=["inelastic"], low=["elastic"],
        forward=[2.0], backward=[0.0])
    row = _rows([0.0], reference, ["elastic"])[0]
    kind, _, rule = row.judged_by.partition(":")
    assert kind == "one_sided_within_branch_backward"
    assert rule in ("relative", "within_reference_resolution",
                    "absolute_near_zero", "reference_unresolved")


def test_a_structural_zero_at_a_branch_boundary_is_not_a_disagreement():
    """Six rows were called disagreements because 0 against 6e-11 of round-off
    is a relative error of exactly 1."""
    reference = _reference_with_sides(
        [1.0], high=["inelastic"], low=["elastic"],
        forward=[2.0], backward=[6.0e-11])
    rows = _rows([0.0], reference, ["elastic"])
    assert rows[0].agrees is not False, rows[0].judged_by


def test_a_one_sided_reference_can_still_disagree():
    """It is a reference, not a way of passing."""
    reference = _reference_with_sides(
        [1.0], high=["inelastic"], low=["elastic"],
        forward=[2.0], backward=[0.0])
    rows = _rows([5.0], reference, ["elastic"])
    assert rows[0].judged_by.startswith("one_sided_within_branch_backward:")
    assert rows[0].agrees is False


def test_when_neither_side_stays_on_the_branch_the_row_stays_unresolved():
    reference = _reference_with_sides(
        [1.0], high=["inelastic"], low=["inelastic"],
        forward=[2.0], backward=[2.0])
    rows = _rows([0.0], reference, ["elastic"])
    assert rows[0].judged_by == "reference_unresolved_branch_crossing"
    assert rows[0].agrees is None


def test_a_side_whose_outer_point_crosses_the_branch_is_not_used():
    """A three-point stencil reaching across the kink is no better than the
    centred one it replaces."""
    reference = _reference_with_sides(
        [1.0], high=["inelastic"], low=["elastic"],
        forward=[2.0], backward=[0.0], far_low=["inelastic"])
    rows = _rows([0.0], reference, ["elastic"])
    assert rows[0].judged_by == "reference_unresolved_branch_crossing"
    assert rows[0].agrees is None


def test_without_recorded_one_sided_values_the_row_stays_unresolved():
    """Evidence produced before one-sided values were kept must not change."""
    reference = {3: {"step": 1e-4, "dsigma": [[1.0]], "dstatev": [[0.0]],
                     "high_branch": ["inelastic"], "low_branch": ["elastic"]}}
    rows = _rows([0.0], reference, ["elastic"])
    assert rows[0].judged_by == "reference_unresolved_branch_crossing"
    assert rows[0].agrees is None
