"""The routine-level primal gate, on calls recorded from real corpus runs.

Every fixture is a pass16 row replayed offline (corpus_campaign/batches/B2/
curie_g): each converged call of the original's Abaqus history, re-run in both
builds from the recorded arguments.
"""
import gzip
import json
from pathlib import Path

import pytest

from umat_oti.abaqus.compare import (STIFFNESS_ULPS, compare_calls,
                                     stiffness_scale)

FIXTURES = Path(__file__).parent / "fixtures" / "primal_gate"


def case(name):
    with gzip.open(FIXTURES / f"{name}.json.gz", "rt") as handle:
        return json.load(handle)


def gate(reference, other, excluded=None):
    return compare_calls(reference, other, stiffness=stiffness_scale(other),
                         tolerance=1e-10, excluded=excluded)


def test_a_routine_that_agrees_call_by_call_passes_at_a_few_stiffness_ulps():
    # MinSur1: the FE histories differ by 5.3e-7 because the solver was
    # steered by different Jacobians; the routines agree to 4 ulpK.
    c = case("minsur1")
    result = gate(c["routine_original"], c["routine_transformed"])
    assert result.agrees, result.reason
    assert result.worst_stress_ulpk < 10
    assert result.calls == 160


def test_the_negative_control_agrees_with_almost_nothing_to_spare():
    # PureGravity: stresses of order 0.3 on a modulus of 1e10. A relative
    # metric reads its pressure rounding as 1e-8; in stiffness ulps it is 5e-5.
    c = case("puregravity")
    result = gate(c["routine_original"], c["routine_transformed"],
                  excluded={"STATEV": [7]})
    assert result.agrees, result.reason
    assert result.worst_stress_ulpk < 1e-3


def test_a_single_precision_declaration_widened_by_the_transform_fails_the_gate():
    # Growth-EX declares REAL Lambda1.. ; the transform lifts them to doubles.
    c = case("growth_ex")
    result = gate(c["routine_original"], c["routine_transformed"])
    assert not result.agrees
    assert result.worst_stress_ulpk > 1e8      # five decades above the bound
    assert "stiffness ulps" in result.reason


def test_the_declared_precision_control_explains_exactly_that_difference():
    c = case("growth_ex")
    widened = gate(c["routine_widened"], c["routine_transformed"])
    assert widened.agrees, widened.reason
    assert widened.worst_stress_ulpk < 10


def test_the_bound_sits_between_the_measured_rounding_and_the_first_real_difference():
    # Measured maxima: 9.7 ulpK with every construct reproduced; 7e5 ulpK for
    # the smallest un-reproduced single-precision construct.
    assert 6 * 9.7 <= STIFFNESS_ULPS <= 7e5 / 1e3


def test_an_excluded_undefined_output_is_never_compared():
    c = case("minsur1")
    other = [dict(r, STATEV=list(r["STATEV"])) for r in c["routine_transformed"]]
    for record in other:
        record["STATEV"][0] = record["STATEV"][0] + 1.0
    assert not gate(c["routine_original"], other).agrees
    assert gate(c["routine_original"], other, excluded={"STATEV": [1]}).agrees


def test_a_nan_in_one_build_only_never_reads_as_agreement():
    c = case("minsur1")
    other = [dict(r, STRESS=list(r["STRESS"])) for r in c["routine_transformed"]]
    other[5]["STRESS"][2] = float("nan")
    result = gate(c["routine_original"], other)
    assert not result.agrees and result.non_finite_mismatches == 1


def test_different_numbers_of_calls_are_not_the_same_calls():
    c = case("minsur1")
    result = gate(c["routine_original"], c["routine_transformed"][:-1])
    assert not result.agrees and "not the same calls" in result.reason


def test_case4_every_converged_call_of_the_original_is_replayed_not_only_the_aligned_ones():
    # The original walked 208 records, the transformed 192 (different Newton
    # paths); pairing by time left 8. The routine gate replays all 208.
    c = case("case4")
    assert len(c["routine_original"]) == 208
    assert not gate(c["routine_original"], c["routine_transformed"]).agrees
    widened = gate(c["routine_widened"], c["routine_transformed"])
    assert widened.agrees, widened.reason
