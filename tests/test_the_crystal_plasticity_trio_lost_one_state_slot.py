"""The three crystal-plasticity entries did not converge to different iterates.

``RitioL/PolyFatigueCrackSim`` supplied three files -- ``huang_umat_97.for``,
``CPFEM-val/subroutines_revised.for`` and ``workplace/subroutines3_revised.for``
-- and all three reached ``primal_disagreed`` at a worst relative difference of
about 1.99, with the worst stress pair carrying opposite signs (17.5883 against
-20.0786) and the worst state pair likewise (-3.38e-05 against 3.43e-05). The
previous classifier named that ``iterative_solver_different_iterate``, because
the pair flips sign and because ``converg`` appears in the file.

Read call by call from the pass9 probe records, the runs say something else.
At call 4 -- element 1, point 1, the second equilibrium pass of increment 1 --
the two builds were handed arguments agreeing to 1.07e-47 of their own scale,
had taken the same number of passes (two) in every one of the 140 increments,
and returned:

    STRESS       all four components, agreeing to 5.0e-17 of the stress field
    STATEV       149 of 150 bit-identical
    STATEV(25)   -73.46290748654624  against  -1.6982275886200392e-30

STATEV(25) is ``STATEV(2*NSLPTL+1)``, the resolved shear stress on the first of
twelve slip systems. The other eleven -- 53.5529, 19.91, 3.52411, 11.3347,
-7.81063, -16.3859, -32.3583, -15.9725, 64.8877, 41.1046, 23.7831 -- are
bit-identical in both builds.

One slot out of 154 outputs. That is not two solves stopping at different
iterates; a different iterate moves everything the solve writes, by about its
own convergence tolerance. The +/-1.99 at record 137 is what that one lost slot
becomes after it is carried forward as STATEV0 into every later increment.
"""
import json
from pathlib import Path

def _cache():
    """The discovery cache, configurable and skipped when absent."""
    import os
    import pathlib as _pathlib

    import pytest as _pytest

    where = _pathlib.Path(
        os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
        or _pathlib.Path.home() / "softwarex_work" / "discovery_cache")
    if not where.is_dir():
        _pytest.skip(f"no discovery cache at {where}")
    return where


def _corpus_run(name: str = "pass9"):
    """Where a completed corpus run's evidence lives on this machine.

    Configurable, and skipped when absent: these are integration tests over
    evidence a real Abaqus batch produced, and the batch does not run on
    every machine that runs the suite.
    """
    import os
    import pathlib as _pathlib

    import pytest as _pytest

    root = _pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or _pathlib.Path.home() / "softwarex_work" / "corpus_run")
    where = root / name
    if not where.is_dir():
        _pytest.skip(f"no corpus run at {where}; set UMAT_OTI_CORPUS_RUN")
    return where


import pytest

from umat_oti.abaqus import call_isolation as ci
from umat_oti.abaqus.primal_signature import (CONFIRMED, ITERATIVE_SOLVER,
                                              REFUTED, SINGLE_OUTPUT_SLOT,
                                              review_entry)

pytestmark = pytest.mark.integration

PASS9 = _corpus_run("pass9")
TRIO = {
    "0d97f9db648d23a064062989":
        "RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for",
    "73bdb227267602e659445b72":
        "RitioL__PolyFatigueCrackSim/CPFEM-val/subroutines_revised.for",
    "71a0523bc387a9b773773a24":
        "RitioL__PolyFatigueCrackSim/workplace/subroutines3_revised.for",
}
CACHE = Path(str(_cache()))


def _primal(key):
    results = PASS9 / "results" / "store_verification.jsonl"
    if not results.exists():
        pytest.skip("the pass9 corpus results are not on this machine")
    for line in results.read_text().splitlines():
        record = json.loads(line)
        if record.get("key") == key:
            return record
    pytest.skip(f"{key} is not in the pass9 results")


@pytest.mark.parametrize("key", sorted(TRIO))
def test_the_two_builds_took_the_same_number_of_solver_passes(key):
    """140 increments, two passes each, in both builds, in all three entries.
    That count is the one the different-iterate hypothesis says must differ."""
    work = PASS9 / "work" / key
    if not (work / "original" / "original_probe.txt").exists():
        pytest.skip("the pass9 probe records are not on this machine")
    original, transformed = ci.read_pair(work)
    left = ci.iteration_counts(ci.pair_calls(original))
    right = ci.iteration_counts(ci.pair_calls(transformed))
    assert left == right
    assert set(left.values()) == {2}
    assert len(left) == 140


@pytest.mark.parametrize("key", sorted(TRIO))
def test_exactly_one_of_one_hundred_and_fifty_state_slots_moved(key):
    """And the stresses of the same call agree to 5.0e-17 of their field."""
    work = PASS9 / "work" / key
    if not (work / "original" / "original_probe.txt").exists():
        pytest.skip("the pass9 probe records are not on this machine")
    original, transformed = ci.read_pair(work)
    isolation = ci.isolate_first_divergence(original, transformed,
                                            require_beyond_rounding=True)
    assert isolation.verdict == ci.SAME_INPUTS_DIFFERENT_OUTPUTS
    assert isolation.call_index == 4
    assert isolation.worst_input_relative < 1e-40
    assert isolation.output_slots_total == 154
    assert len(isolation.output_slots_beyond_rounding) == 1
    slot = isolation.output_slots_beyond_rounding[0]
    assert (slot.block, slot.fortran_index) == ("STATEV", 25)
    assert slot.original == -73.46290748654624
    assert slot.transformed == -1.6982275886200392e-30
    assert isolation.stress_worst_relative < 1e-16


@pytest.mark.parametrize("key", sorted(TRIO))
def test_the_different_iterate_hypothesis_is_refuted_and_the_slot_confirmed(key):
    work = PASS9 / "work" / key
    if not (work / "original" / "original_probe.txt").exists():
        pytest.skip("the pass9 probe records are not on this machine")
    record = _primal(key)
    source = CACHE / TRIO[key]
    signature = review_entry(
        record["primal"], work,
        source.read_text(errors="replace") if source.exists() else "")
    by_name = {h.name: h for h in signature.hypotheses}
    assert by_name[ITERATIVE_SOLVER].confirmation_status == REFUTED
    assert by_name[SINGLE_OUTPUT_SLOT].confirmation_status == CONFIRMED
    assert by_name[SINGLE_OUTPUT_SLOT].reproduction.repeatable
    # The slot's identity is carried by block and index, which is checked
    # above. What the root cause has to name is the CONSTRUCT, because
    # "STATEV(2*NSLPTL+1) is wrong" restates the symptom. It is an 8-byte
    # REAL*8 DDCMP reaching a 40-byte TYPE(ONUMM4N1) dummy in LUDCMP_OTI.
    cause = by_name[SINGLE_OUTPUT_SLOT].confirmed_root_cause
    assert "DDCMP" in cause and "LUDCMP_OTI" in cause
    assert "TYPE(ONUMM4N1) :: DDCMP" in cause


@pytest.mark.parametrize("key", sorted(TRIO))
def test_the_lost_slot_is_carried_forward_into_the_next_increments_entry_state(key):
    """This is how one slot at increment 1 becomes +/-1.99 at record 137: the
    wrong value is written into STATEV(25), Abaqus hands it back as STATEV0 at
    increment 2, and from there the stresses part too -- 531.7907306 against
    531.7907749 at the first call of increment 2."""
    work = PASS9 / "work" / key
    if not (work / "original" / "original_probe.txt").exists():
        pytest.skip("the pass9 probe records are not on this machine")
    original, transformed = ci.read_pair(work)
    left, right = ci.pair_calls(original), ci.pair_calls(transformed)
    entry_o, result_o = left[8]
    entry_t, result_t = right[8]
    assert result_o["increment"] == 2
    assert entry_o["STATEV0"][24] == -73.46290748654624
    assert entry_t["STATEV0"][24] == -1.6982275886200392e-30
    assert result_o["STRESS"][0] != result_t["STRESS"][0]


def test_the_confirmation_stops_applying_if_the_numbers_move():
    """A confirmation has to be re-checkable, not remembered. The recorded
    reproduction is keyed to the two values it observed, so a transform that
    changes anything about this slot returns the hypothesis to open."""
    from umat_oti.abaqus.primal_signature import (CONFIRMED_FINDINGS,
                                                  apply_recorded_confirmations,
                                                  classify)
    finding = CONFIRMED_FINDINGS[0]
    matching = ci.Isolation(
        verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS,
        output_slots_beyond_rounding=[ci.SlotDifference(
            "STATEV", 24, finding.original, finding.transformed)])
    moved = ci.Isolation(
        verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS,
        output_slots_beyond_rounding=[ci.SlotDifference(
            "STATEV", 24, finding.original, -1.7e-30)])
    assert finding.matches(matching)
    assert not finding.matches(moved)
    signature = classify({"worst_stress_relative": 1.99}, "", 140)
    signature.hypotheses.append(
        __import__("umat_oti.abaqus.primal_signature", fromlist=["x"])
        .Hypothesis(SINGLE_OUTPUT_SLOT, claim="x"))
    apply_recorded_confirmations(signature, moved)
    assert not signature.confirmed
