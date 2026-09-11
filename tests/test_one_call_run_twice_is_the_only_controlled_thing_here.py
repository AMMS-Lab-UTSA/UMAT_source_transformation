"""A history comparison is not an experiment; a single call can be.

By the time a stress at increment 137 differs, the state it was computed from
differs too and the solver has been handing each build its own displacement
increment for a hundred increments. Every quantity on both sides has moved.

The probe already records two per call -- what the routine was given and what
it returned -- so the controlled experiment is in the data and needs no run:
find a call where both builds were handed the same arguments, and read off what
each returned. The numbers in these docstrings come from
``corpus_run/pass9/work/<key>/{original,transformed}/*_probe.txt``.
"""
import math

import pytest

from umat_oti.abaqus import call_isolation as ci

pytestmark = pytest.mark.unit


def _call(element, point, step, increment, time, entry, result):
    head = {"element": element, "point": point, "step": step,
            "increment": increment, "time": time}
    return ({"kind": "entry", **head, **entry},
            {"kind": "result", **head, **result})


def _flat(calls):
    out = []
    for entry, result in calls:
        out.append(entry)
        out.append(result)
    return out


def test_calls_are_paired_from_the_probe_in_the_order_abaqus_made_them():
    """``converged_only`` keeps the last call of each increment, which is right
    for comparing histories and wrong for this: measured on huang_umat_97.for,
    the call where the two builds first part beyond rounding is call 4 -- the
    second equilibrium pass of increment 1, which ``converged_only`` keeps, and
    calls 0 to 3, which it discards, are where they still agree."""
    records = _flat([_call(1, p, 1, 1, 0.0, {"STRESS0": [0.0]}, {"STRESS": [1.0]})
                     for p in (1, 2, 3, 4)] * 2)
    assert len(ci.pair_calls(records)) == 8


def test_the_solver_pass_count_is_read_off_the_probe_not_guessed():
    """This is the number "the two builds converged to different iterates"
    says must differ. In pass9 it is 2 for every increment of both builds of
    all three crystal-plasticity entries -- 140 increments, 280 calls each."""
    calls = ci.pair_calls(_flat(
        [_call(1, 1, 1, 1, 0.0, {}, {}), _call(1, 1, 1, 1, 0.0, {}, {}),
         _call(1, 1, 1, 2, 0.1, {}, {})]))
    assert ci.iteration_counts(calls) == {(1, 1, 1, 1): 2, (1, 1, 1, 2): 1}


def test_bit_identical_inputs_make_the_call_an_experiment():
    """Measured at call 4 of huang_umat_97.for: STRESS0 and STATEV0 are all
    zero in both builds and the largest argument difference is 3.2e-50 in
    DSTRAN(2), which is 1.07e-47 of DSTRAN's own scale over the run."""
    entry = {"STRESS0": [0.0, 0.0], "DSTRAN": [0.0009995002499, -5.711531008470997e-35]}
    shifted = {"STRESS0": [0.0, 0.0], "DSTRAN": [0.0009995002499, -5.711531008471001e-35]}
    left = _flat([_call(1, 1, 1, 1, 0.0, entry, {"STRESS": [1.0], "STATEV": [2.0]})])
    right = _flat([_call(1, 1, 1, 1, 0.0, shifted, {"STRESS": [1.0], "STATEV": [3.0]})])
    result = ci.isolate_first_divergence(left, right)
    assert result.verdict == ci.SAME_INPUTS_DIFFERENT_OUTPUTS
    assert result.worst_input_relative < ci.INPUT_SAME


def test_an_input_that_really_moved_is_not_called_the_same_input():
    left = _flat([_call(1, 1, 1, 1, 0.0, {"DSTRAN": [1.0]}, {"STRESS": [1.0]})])
    right = _flat([_call(1, 1, 1, 1, 0.0, {"DSTRAN": [1.1]}, {"STRESS": [2.0]})])
    result = ci.isolate_first_divergence(left, right)
    assert result.verdict == ci.INPUTS_ALREADY_DIVERGED


def test_first_difference_and_first_difference_that_matters_are_two_questions():
    """Both have to be asked. On all 42 entries the first difference of ANY
    kind is at call 0 at one unit in the last place; on huang_umat_97.for the
    first difference beyond rounding is at call 4, where one state slot moves
    by 24.9% of the field. Reporting only the first reads the whole corpus as
    round-off."""
    rounding = _call(1, 1, 1, 1, 0.0, {"STRESS0": [0.0]},
                     {"STRESS": [1.0], "STATEV": [100.0]})
    rounded = _call(1, 1, 1, 1, 0.0, {"STRESS0": [0.0]},
                    {"STRESS": [1.0000000000000002], "STATEV": [100.0]})
    material = _call(1, 1, 1, 2, 0.1, {"STRESS0": [1.0]},
                     {"STRESS": [1.0], "STATEV": [100.0]})
    moved = _call(1, 1, 1, 2, 0.1, {"STRESS0": [1.0]},
                  {"STRESS": [1.0], "STATEV": [25.0]})
    left, right = _flat([rounding, material]), _flat([rounded, moved])
    assert ci.isolate_first_divergence(left, right).call_index == 0
    assert ci.isolate_first_divergence(
        left, right, require_beyond_rounding=True).call_index == 1


def test_a_slot_difference_is_reported_against_its_own_field_not_against_zero():
    """The serialised relative came back 0.0 for every slot, because the scale
    defaulted to zero at serialisation time and the division was skipped. A
    0.0 printed beside a slot listed as "beyond rounding" is worse than no
    number at all."""
    left = _flat([_call(1, 1, 1, 1, 0.0, {}, {"STATEV": [295.26, -73.46290748654624]})])
    right = _flat([_call(1, 1, 1, 1, 0.0, {}, {"STATEV": [295.26, -1.6982275886e-30]})])
    result = ci.isolate_first_divergence(left, right).as_dict()
    slot = result["output_slots_beyond_rounding"][0]
    assert slot["fortran_index"] == 2
    assert 0.24 < slot["relative_to_block_scale"] < 0.25


def test_a_non_finite_output_is_located_at_the_call_that_produced_it():
    """simplified_curing.for: the transformed build returns NaN in all six
    stress components at call 0 -- the first UMAT call of the analysis -- from
    inputs bit-identical to the original's, which are finite."""
    calls = ci.pair_calls(_flat([
        _call(1, 1, 1, 1, 0.0, {"STRESS0": [0.0]},
              {"STRESS": [float("nan")] * 6})]))
    where = ci.first_non_finite(calls)
    assert where["call_index"] == 0 and where["block"] == "STRESS"
    assert where["components"] == [0, 1, 2, 3, 4, 5]


def test_a_run_with_no_divergence_says_so_rather_than_reporting_call_minus_one():
    left = _flat([_call(1, 1, 1, 1, 0.0, {}, {"STRESS": [1.0]})])
    result = ci.isolate_first_divergence(left, list(left))
    assert result.verdict == ci.NO_DIVERGENCE
    assert result.call_index == -1


def test_calls_that_stopped_lining_up_are_refused_rather_than_compared():
    """Two builds that walked different increments have no call in common from
    that point on. Comparing position for position past it compares increment
    3 of one with increment 3 of the other at different times."""
    left = _flat([_call(1, 1, 1, 1, 0.0, {}, {"STRESS": [1.0]})])
    right = _flat([_call(1, 1, 1, 9, 0.5, {}, {"STRESS": [1.0]})])
    result = ci.isolate_first_divergence(left, right)
    assert result.verdict == ci.NOT_PAIRABLE
