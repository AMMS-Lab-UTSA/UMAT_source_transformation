"""The ways a comparison can report agreement without having established it.

Every case here was found by adversarially reviewing the comparison rather than
by using it, and each one had already reached a published-looking result:

* A transformed build returning NaN scored AGREED with a worst relative
  difference of 0.0, because ``nan > worst`` is False and the running maximum
  never moved. A transform that destroyed the stress completely read as
  agreement, and dragged the headline "worst difference among agreeing rows"
  toward zero.
* Two all-zero responses compared equal, so a build that computed nothing at
  all agreed with another build that computed nothing at all.
* Histories of different length were zipped to the shorter one, so a build
  whose probe wrote one record out of twenty was compared over that one record
  and reported as agreeing over the whole history.

The rule these enforce: agreement is something a comparison has to earn on
resolvable, finite values, over the records both builds actually produced.
Anything else is a stated reason, never a pass.
"""
import math

from umat_oti.abaqus.compare import compare_primal, compare_tangent


def record(stress, state=()):
    return {"STRESS": list(stress), "STATEV": list(state)}


# ---- non-finite values ---------------------------------------------------
def test_a_nan_in_the_transformed_build_is_never_agreement():
    result = compare_primal([record([16.15, 0.0, 0.0])],
                            [record([math.nan, math.nan, math.nan])])
    assert not result.agrees
    assert result.non_finite_components > 0
    assert "not finite" in result.reason


def test_a_nan_does_not_leave_the_worst_difference_at_zero():
    """The number a reader quotes must not be flattered by the failure."""
    result = compare_primal([record([16.15])], [record([math.nan])])
    assert result.worst_stress_relative == math.inf


def test_an_infinity_is_treated_the_same_way():
    result = compare_primal([record([1.0])], [record([math.inf])])
    assert not result.agrees and result.non_finite_components == 1


def test_a_nan_in_the_original_is_caught_too():
    """A reference that is not finite cannot adjudicate anything."""
    result = compare_primal([record([math.nan])], [record([1.0])])
    assert not result.agrees and result.non_finite_components == 1


def test_a_nan_in_the_state_is_caught():
    result = compare_primal([record([1.0], [math.nan])], [record([1.0], [2.0])])
    assert not result.agrees and result.non_finite_components == 1


# ---- a response that never moved ----------------------------------------
def test_two_builds_that_computed_nothing_do_not_agree():
    """Zero against zero is not evidence that a model was reproduced."""
    result = compare_primal([record([0.0] * 6)], [record([0.0] * 6)])
    assert not result.agrees
    assert result.resolved_components == 0
    assert "nothing to compare" in result.reason or "no resolvable" in result.reason


def test_a_real_response_still_agrees():
    """The guard must not reject the case it exists to certify."""
    history = [record([1000.0, 2.0, 3.0], [0.5]),
               record([2000.0, 4.0, 6.0], [0.7])]
    result = compare_primal(history, history)
    assert result.agrees and result.resolved_components > 0
    assert result.non_finite_components == 0


def test_a_response_whose_only_movement_is_unresolvable_is_not_agreement():
    """Every component dismissed as too small leaves nothing established."""
    a = [record([100.0, 1e-30])]
    b = [record([100.0000000000001, 2e-30])]
    result = compare_primal(a, b, tolerance=1e-30)
    assert not result.agrees


# ---- histories of different length --------------------------------------
def test_a_shorter_history_is_not_compared_as_if_it_were_whole():
    long = [record([float(i), 0.0, 0.0]) for i in range(1, 21)]
    short = long[:1]
    result = compare_primal(long, short)
    assert not result.agrees
    assert result.records_original == 20 and result.records_transformed == 1
    assert "20" in result.reason and "1" in result.reason


def test_equal_length_histories_report_what_they_compared():
    history = [record([10.0]), record([20.0])]
    result = compare_primal(history, history)
    assert result.records_original == result.records_transformed == 2
    assert result.increments == 2


def test_no_records_on_either_side_is_not_agreement():
    assert not compare_primal([], []).agrees
    assert not compare_primal([record([1.0])], []).agrees


# ---- the tangent comparison -----------------------------------------------
def test_a_non_finite_tangent_entry_is_not_a_best_step():
    """A sweep point holding NaN cannot be the one a reader is pointed at."""
    exact = [[100.0, 0.0], [0.0, 50.0]]
    differences = {
        1e-3: [[100.5, 0.0], [0.0, 50.2]],
        1e-5: [[math.nan, 0.0], [0.0, math.nan]],
    }
    result = compare_tangent(exact, differences)
    assert result.best is None or result.best.step == 1e-3
    assert result.non_finite_entries == 2


def test_a_non_finite_oti_tangent_is_reported():
    exact = [[math.nan, 0.0], [0.0, 50.0]]
    result = compare_tangent(exact, {1e-5: [[100.0, 0.0], [0.0, 50.0]]})
    assert result.non_finite_entries >= 1
    assert "not finite" in result.notes
