"""What a comparison is allowed to call agreement.

The rules these lock down are the ones a comparison silently breaks when it is
written for a passing result rather than for a true one: an unresolved
component must not be scored as agreeing, a length mismatch must not be
averaged over, and a finite-difference sweep must report where it was stable
rather than the single step that happened to look best.
"""
from umat_oti.abaqus.compare import compare_primal, compare_tangent


def record(stress, state=()):
    return {"STRESS": list(stress), "STATEV": list(state)}


def test_identical_histories_agree():
    history = [record([100.0, 2.0, 3.0], [0.5]), record([200.0, 4.0, 6.0], [0.7])]
    result = compare_primal(history, history)
    assert result.agrees and result.increments == 2
    assert result.worst_stress_relative == 0.0


def test_a_difference_in_the_response_is_a_disagreement():
    a = [record([100.0, 2.0, 3.0])]
    b = [record([100.0000001, 2.0, 3.0])]
    result = compare_primal(a, b)
    assert not result.agrees
    assert result.worst_stress_at[1] == 1        # component 1, one-based
    assert "tolerance" in result.reason


def test_a_vanishing_component_is_counted_not_scored():
    """1e-30 against 2e-30 differs by 50%, and means nothing next to 100."""
    a = [record([100.0, 1e-30])]
    b = [record([100.0, 2e-30])]
    result = compare_primal(a, b)
    assert result.unresolved_components == 1
    assert result.agrees                          # the response itself agrees
    assert result.worst_stress_relative == 0.0


def test_no_records_is_not_agreement():
    result = compare_primal([], [])
    assert not result.agrees and "no records" in result.reason


def test_differing_component_counts_stop_the_comparison():
    result = compare_primal([record([1.0, 2.0])], [record([1.0, 2.0, 3.0])])
    assert not result.agrees
    assert "2 components in one build and 3 in the other" in result.reason


def test_state_is_compared_as_well_as_stress():
    a = [record([100.0], [10.0])]
    b = [record([100.0], [11.0])]
    result = compare_primal(a, b)
    assert not result.agrees
    assert result.worst_state_relative > 0.0


def test_the_sweep_reports_where_it_was_stable():
    """A step that is good alone is not converged; a plateau is."""
    exact = [[100.0, 0.0], [0.0, 50.0]]
    # Truncation error falls with the step until round-off takes over.
    differences = {
        1e-3: [[100.5, 0.0], [0.0, 50.2]],
        1e-4: [[100.05, 0.0], [0.0, 50.02]],
        1e-5: [[100.005, 0.0], [0.0, 50.002]],
        1e-6: [[100.006, 0.0], [0.0, 50.003]],
        1e-8: [[103.0, 0.0], [0.0, 48.0]],
    }
    result = compare_tangent(exact, differences)
    assert result.best.step == 1e-5
    low, high = result.stable_range
    assert low <= 1e-5 <= high
    assert low > 1e-8                        # round-off is excluded
    assert len(result.sweep) == 5


def test_a_zero_entry_is_scored_against_the_matrix_not_itself():
    """Otherwise a rounding residue divided by a rounding residue reads as 100%."""
    exact = [[100.0, 0.0], [0.0, 100.0]]
    differences = {1e-5: [[100.0, 1e-9], [1e-9, 100.0]]}
    result = compare_tangent(exact, differences)
    assert result.near_zero_entries == 2
    assert result.sweep[0].relative < 1e-6


def test_nothing_to_compare_says_so():
    assert "nothing to compare" in compare_tangent([], {}).notes
    assert "nothing to compare" in compare_tangent([[1.0]], {}).notes
