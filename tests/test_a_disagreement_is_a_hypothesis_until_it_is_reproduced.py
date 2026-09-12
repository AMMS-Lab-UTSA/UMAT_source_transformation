""""primal_disagreed" is a stage; a signature is a hypothesis, not a verdict.

The previous version of ``primal_signature`` returned one name per entry --
``iterative_solver_different_iterate`` for the crystal-plasticity trio, on the
strength of a sign flip in the worst pair and the word "converg" appearing in
the file. This suite pins the two properties that were missing:

* a name can be REFUTED by a measurement, and the measurement is attached;
* a name cannot be CONFIRMED except by a reproduction that says what was held
  fixed -- no classification path can reach ``confirmed``.

The numbers used here were measured from the pass9 probe records and are quoted
in each docstring, so a reader can check the claim without the 4 MB of trace.
"""
import math

import pytest

from umat_oti.abaqus import call_isolation as ci
from umat_oti.abaqus.primal_signature import (
    BRANCH_DIVERGENCE, CONFIRMED, DIFFERENT_FUNCTION, Evidence,
    FROM_ISOLATION, FROM_SOURCE_TEXT, Hypothesis, ITERATIVE_SOLVER,
    NEEDS_ABAQUS, NEEDS_MORE_EVIDENCE, NON_FINITE,
    REDUCED_PRECISION_INPUT, REFUTED, Reproduction,
    ROUND_OFF_GROWTH, SINGLE_OUTPUT_SLOT, SIGN_FLIP_CLOSENESS, classify)

pytestmark = pytest.mark.unit

NEWTON = ("      SUBROUTINE UMAT(STRESS,STATEV)\n"
          "C     Newton-Raphson iteration to solve stresses\n"
          "      DO WHILE (RESID .GT. TOLER)\n      END DO\n      END\n")
PLAIN = "      SUBROUTINE UMAT(STRESS,STATEV)\n      RETURN\n      END\n"

#: The worst pair the pass9 run recorded for huang_umat_97.for.
HUANG_PRIMAL = {
    "worst_stress_relative": 1.9863, "worst_state_relative": 1.9863,
    "worst_stress_at": [137, 3, 17.588282267417753, -20.078642697924124],
    "worst_state_at": [50, 23, -3.381688335674887e-05, 3.429471489578103e-05],
    "resolved_components": 16812, "unresolved_components": 868,
}


def _isolation(*, beyond, total=154, differing=22, call_index=4,
               worst_input=1.07e-47, verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS):
    """An Isolation built from measured numbers, without reading 4 MB of probe."""
    result = ci.Isolation(verdict=verdict, paired_calls=280,
                          call_index=call_index, element=1, point=1, step=1,
                          increment=1, time=0.0,
                          worst_input_relative=worst_input,
                          worst_input_block="DSTRAN",
                          output_slots_total=total,
                          output_slots_differing=differing,
                          output_slots_beyond_rounding=list(beyond),
                          stress_slots_differing=4,
                          stress_worst_relative=4.99e-17)
    result.scales = {"STATEV": 295.26, "STRESS": 2277.0, "DSTRAN": 0.003011}
    return result


#: The one output component that moved, measured at call 4 of all three
#: crystal-plasticity entries.
HUANG_SLOT = ci.SlotDifference("STATEV", 24, -73.46290748654624,
                               -1.6982275886200392e-30)


# ---------------------------------------------------------------------------
# what the old module did, and why it was not a diagnosis
# ---------------------------------------------------------------------------
def test_a_sign_flip_beside_a_newton_loop_raises_three_rivals_not_one_answer():
    """huang_umat_97.for: stress 17.5883 against -20.0786, state -3.38e-05
    against 3.43e-05, and the word "converg" in the file. Those facts are
    consistent with a different iterate, with a branch taken the other way, and
    with one output slot written wrongly. Returning the first of the three as
    the answer is what this replaces."""
    signature = classify(HUANG_PRIMAL, NEWTON, 140)
    names = {h.name for h in signature.hypotheses}
    assert {ITERATIVE_SOLVER, BRANCH_DIVERGENCE, SINGLE_OUTPUT_SLOT} <= names
    assert not signature.confirmed


def test_no_hypothesis_is_confirmed_without_a_controlled_call():
    """Given only the summary numbers, every hypothesis comes back open and
    asks for the controlled comparison. That is the honest state of an entry
    nobody has isolated."""
    signature = classify(HUANG_PRIMAL, NEWTON, 140)
    assert signature.status == NEEDS_ABAQUS
    assert all(h.confirmation_status in (NEEDS_ABAQUS, NEEDS_MORE_EVIDENCE)
               for h in signature.hypotheses)
    assert all(h.what_would_confirm for h in signature.hypotheses)


def test_evidence_read_off_source_text_is_marked_as_not_a_measurement():
    """"the source contains a DO WHILE" is a fact about a file. It says the
    mechanism is available, never that it ran."""
    signature = classify(HUANG_PRIMAL, NEWTON, 140)
    iterative = next(h for h in signature.hypotheses if h.name == ITERATIVE_SOLVER)
    from_text = [e for e in iterative.supporting_evidence
                 if e.origin == FROM_SOURCE_TEXT]
    assert from_text and not any(e.is_measurement for e in from_text)


# ---------------------------------------------------------------------------
# refutation by a controlled call
# ---------------------------------------------------------------------------
def test_one_moved_slot_out_of_154_refutes_the_different_iterate_hypothesis():
    """Measured at call 4 of huang_umat_97.for: the two builds were handed
    arguments agreeing to 1.07e-47 of their own scale, took two solver passes
    each in all 140 increments, returned all four stresses agreeing to 5.0e-17
    of the stress field, and 149 of 150 state variables bit-identically. One
    moved. A solve that stopped at a different iterate moves everything it
    writes, by about its own convergence tolerance."""
    signature = classify(HUANG_PRIMAL, NEWTON, 140,
                         isolation=_isolation(beyond=[HUANG_SLOT]),
                         iteration_counts_differ=0)
    iterative = next(h for h in signature.hypotheses if h.name == ITERATIVE_SOLVER)
    assert iterative.confirmation_status == REFUTED
    assert iterative.contradicting_evidence
    assert all(e.origin in (FROM_ISOLATION, "probe_history")
               for e in iterative.contradicting_evidence)


def test_equal_solver_pass_counts_refute_it_on_their_own():
    """The hypothesis names a count that must differ. In pass9 that count is
    equal in every one of the 140 increments of all three entries."""
    signature = classify(HUANG_PRIMAL, NEWTON, 140,
                         isolation=_isolation(beyond=[HUANG_SLOT]),
                         iteration_counts_differ=0)
    iterative = next(h for h in signature.hypotheses if h.name == ITERATIVE_SOLVER)
    assert any("same number of passes" in e.statement
               for e in iterative.contradicting_evidence)


def test_a_first_call_that_already_moved_refutes_round_off_growth():
    """Round-off grown along a path predicts the two builds part at the last
    representable bit. Measured at call 4: STATEV(25) differs by 24.9% of the
    state field -- 1.1e15 times a double's last place. Whatever that is, it did
    not start as rounding, and it is not grounds for widening a tolerance."""
    signature = classify(HUANG_PRIMAL, NEWTON, 140,
                         isolation=_isolation(beyond=[HUANG_SLOT]),
                         iteration_counts_differ=0)
    growth = next(h for h in signature.hypotheses if h.name == ROUND_OFF_GROWTH)
    assert growth.confirmation_status == REFUTED


def test_round_off_growth_survives_only_as_a_question_never_as_a_pass():
    """When nothing moved beyond rounding at the first controlled call, the
    hypothesis is still not granted: it asks for the ORIGINAL build's own
    sensitivity to be measured by reassociating its arithmetic. Until that
    number exists, "this is round-off" is an assumption."""
    signature = classify(
        {"worst_stress_relative": 2.336e-10,
         "worst_stress_at": [105, 1, -1.7746179282e12, -1.7746179287e12]},
        PLAIN, 280, isolation=_isolation(beyond=[], total=15, differing=3,
                                         call_index=0),
        iteration_counts_differ=16)
    growth = next(h for h in signature.hypotheses if h.name == ROUND_OFF_GROWTH)
    assert growth.confirmation_status == NEEDS_ABAQUS
    assert growth.confirmed_root_cause is None
    assert "sensitivity" in growth.what_would_confirm


def test_most_of_the_call_moving_names_a_different_function_not_a_path():
    """Growth-Alex.for, call 0 -- the first UMAT call of the analysis, entered
    with STRESS0 and STATEV0 all zero in both builds. The original returns
    STRESS(1)=3632006.04; the transformed build returns 7748147.17. Eleven of
    sixteen outputs move. There is no history yet for a path to have bent."""
    slots = [
        ci.SlotDifference("STRESS", 0, 3632006.0396387014, 7748147.16642186),
        ci.SlotDifference("STRESS", 1, 3631851.6414457276, 7746333.692425762),
        ci.SlotDifference("STRESS", 2, 3604020.471342695, 7700709.252172071),
        ci.SlotDifference("STRESS", 3, -99.39392539013872, 20542.983602182838),
        ci.SlotDifference("STATEV", 3, 0.2016285161787612, 1.0831647655002854),
        ci.SlotDifference("STATEV", 4, 0.0035498033562567366,
                          0.011343118641805927),
        ci.SlotDifference("STATEV", 5, 0.19812781553070552, 1.101223549612052),
        ci.SlotDifference("STATEV", 6, -0.0023554078326624315,
                          5.590316129588794),
        ci.SlotDifference("STATEV", 7, -0.003810991369661207,
                          2.023616456948967),
        ci.SlotDifference("STATEV", 8, -0.008275389145452415,
                          5.411677237896125),
        ci.SlotDifference("STATEV", 9, 1.6691000777179033, 1.6122122695052001),
    ]
    isolation = _isolation(beyond=slots, total=16, differing=11, call_index=0)
    isolation.scales = {"STRESS": 4122030997344.4517, "STATEV": 60.64962574505099}
    signature = classify(
        {"worst_stress_relative": 1.556,
         "worst_stress_at": [45, 1, 120784251.3, -217183852.4],
         "worst_state_at": [1, 8, -0.003810991, 2.023616457]},
        PLAIN, 280, isolation=isolation, iteration_counts_differ=24)
    assert DIFFERENT_FUNCTION in {h.name for h in signature.hypotheses}


def test_the_right_shape_at_the_wrong_size_is_not_a_corrupted_slot():
    """From-2D-to-2D-Scallop moves three of fifteen output components at the
    first controlled call -- the SHAPE "one output slot corrupted" predicts --
    by 1.058e-10 of the stress field: STRESS(1) is 1475386.6392696765 against
    1475386.61473371, which is 1.66e-08 of its own value. That is what a
    constant carried at the wrong precision looks like; the destroyed slot in
    huang_umat_97 moved 24.9% of its field. Raising the strong claim for the
    small number put it on the threshold the slots were binned with rather
    than on a finding."""
    small = [ci.SlotDifference("STRESS", 0, 1475386.6392696765,
                               1475386.61473371),
             ci.SlotDifference("STRESS", 1, 1475817.057395969,
                               1475817.0328115039),
             ci.SlotDifference("STRESS", 2, 1474142.8321616524,
                               1474142.8076254616)]
    isolation = _isolation(beyond=small, total=15, differing=5, call_index=0)
    isolation.scales = {"STRESS": 231989629.52393734}
    signature = classify({"worst_stress_relative": 5.855e-05,
                          "worst_stress_at": [83, 1, 1372.13, 1372.05]},
                         PLAIN, 280, isolation=isolation)
    names = {h.name for h in signature.hypotheses}
    assert SINGLE_OUTPUT_SLOT not in names
    assert REDUCED_PRECISION_INPUT in names


def test_a_slots_size_is_read_through_its_own_field_not_off_a_missing_attribute():
    """``SlotDifference`` carries ``relative_to(scale)`` as a method.
    ``getattr(slot, "relative_to_block_scale", 0.0)`` returned the default for
    every object-shaped isolation, so every refutation printed 0.000e+00 beside
    a slot it had just called "beyond rounding" -- and the single-precision
    band, which is a test on that number, could never be entered.

    SweetMelon.for, call 0, identical all-zero inputs: STRESS(1) is
    3613979.3006122583 against 3613991.595131714, which is 6.26e-08 of the
    stress field -- half of single precision's epsilon and 2.7e8 times a
    double's last place."""
    slot = ci.SlotDifference("STRESS", 0, 3613979.3006122583, 3613991.595131714)
    isolation = _isolation(beyond=[slot], total=16, differing=7, call_index=0)
    isolation.scales = {"STRESS": 196394.0 * 1000.0}
    signature = classify({"worst_stress_relative": 9.511e-03,
                          "worst_stress_at": [246, 2, 2986.86, 2958.45]},
                         PLAIN, 280, isolation=isolation)
    growth = next(h for h in signature.hypotheses if h.name == ROUND_OFF_GROWTH)
    assert growth.confirmation_status == REFUTED
    assert "0.000e+00" not in growth.contradicting_evidence[0].statement
    assert REDUCED_PRECISION_INPUT in {h.name for h in signature.hypotheses}


def test_an_uncontrolled_call_refutes_nothing_and_says_so():
    """If the solver had already handed the two builds different arguments by
    the time their outputs parted, the call is not an experiment. Every
    hypothesis stays open and asks for a re-run from a recorded entry state."""
    isolation = _isolation(beyond=[HUANG_SLOT], worst_input=1e-3,
                           verdict=ci.INPUTS_ALREADY_DIVERGED)
    signature = classify(HUANG_PRIMAL, NEWTON, 140, isolation=isolation)
    assert not signature.refuted
    assert signature.status == NEEDS_ABAQUS


# ---------------------------------------------------------------------------
# confirmation is a door with a lock on it
# ---------------------------------------------------------------------------
def test_confirm_refuses_a_reproduction_that_held_nothing_fixed():
    hypothesis = Hypothesis(SINGLE_OUTPUT_SLOT, claim="x")
    hypothesis.support(Evidence("measured something", FROM_ISOLATION))
    with pytest.raises(ValueError, match="held fixed"):
        hypothesis.confirm("a cause", Reproduction(
            held_fixed="  ", varied="the build", observed="they differed"))


def test_confirm_refuses_when_the_only_support_is_the_source_text():
    """A Newton loop in the file cannot be the case for a Newton loop having
    run differently."""
    hypothesis = Hypothesis(ITERATIVE_SOLVER, claim="x")
    hypothesis.support(Evidence("the source contains a DO WHILE",
                                FROM_SOURCE_TEXT))
    with pytest.raises(ValueError, match="not a measurement|no supporting"):
        hypothesis.confirm("a cause", Reproduction(
            held_fixed="the deck", varied="the build", observed="they differed"))


def test_a_refuted_hypothesis_cannot_be_confirmed_later():
    hypothesis = Hypothesis(ITERATIVE_SOLVER, claim="x")
    hypothesis.support(Evidence("measured something", FROM_ISOLATION))
    hypothesis.refute(Evidence("both builds took two passes", FROM_ISOLATION))
    with pytest.raises(ValueError, match="refuted"):
        hypothesis.confirm("a cause", Reproduction(
            held_fixed="the deck", varied="the build", observed="x"))


def test_no_classification_path_reaches_confirmed():
    """Whatever the numbers say, ``classify`` never returns a confirmation.
    Exercised over every shape the corpus produced."""
    slots = [HUANG_SLOT]
    for isolation in (_isolation(beyond=slots),
                      _isolation(beyond=[], differing=0),
                      _isolation(beyond=slots, call_index=0),
                      _isolation(beyond=slots, verdict=ci.NOT_PAIRABLE),
                      None):
        for source in (NEWTON, PLAIN, ""):
            signature = classify(HUANG_PRIMAL, source, 140,
                                 isolation=isolation)
            assert not signature.confirmed
            assert all(h.confirmed_root_cause is None
                       for h in signature.hypotheses)


# ---------------------------------------------------------------------------
# observations that are not mechanisms
# ---------------------------------------------------------------------------
def test_a_nan_is_reported_as_establishing_nothing_not_as_a_cause():
    """simplified_curing.for returned NaN in all six stress components on the
    first call, from bit-identical finite inputs. That the comparison
    established nothing is a fact; why it did is still open."""
    signature = classify({"worst_stress_relative": 0.0,
                          "non_finite_components": 2520}, PLAIN, 0)
    non_finite = next(h for h in signature.hypotheses if h.name == NON_FINITE)
    assert non_finite.confirmation_status != CONFIRMED
    assert "establishes nothing" in non_finite.supporting_evidence[0].statement


def test_an_infinite_worst_case_is_not_softened_by_a_finite_other_field():
    """HelixUp/Th001/PureGravity: the stress column went to NaN (inf) while the
    state column reported 1.29. Taking the max over the finite ones alone
    ranked it below an entry whose state moved by a percent."""
    signature = classify({"worst_stress_relative": float("inf"),
                          "worst_state_relative": 1.29,
                          "non_finite_components": 12}, PLAIN, 8)
    assert math.isinf(signature.magnitude)


def test_two_magnitudes_far_apart_are_not_a_sign_flip():
    signature = classify({"worst_stress_relative": 1.0,
                          "worst_stress_at": [50, 1, 10.0, -1000.0]}, PLAIN, 100)
    assert SINGLE_OUTPUT_SLOT not in {h.name for h in signature.hypotheses}
    assert 0.0 < SIGN_FLIP_CLOSENESS < 1.0


# ---------------------------------------------------------------------------
# the contract with the caller
# ---------------------------------------------------------------------------
def test_the_signature_is_recorded_beside_the_comparison():
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    assert 'record["primal_signature"] = primal_signature.classify(' in text


def test_a_signature_never_changes_a_verdict():
    """It is a hypothesis with evidence, not a tolerance."""
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    block = text[text.index('record["primal_signature"]'):]
    block = block[:block.index('seen["primal_agrees"]')]
    assert "agrees" not in block and "tolerance" not in block


# ---------------------------------------------------------------------------
# the recorded confirmations, checked against what they were built from
# ---------------------------------------------------------------------------
def test_a_confirmation_matches_only_the_measurement_it_was_built_from():
    """A confirmation has to be re-checkable, not remembered. Each recorded
    finding names the exact component and the exact two values the controlled
    call produced, and the number of components that moved. Change any of
    them and the hypothesis goes back to open."""
    from umat_oti.abaqus.primal_signature import CONFIRMED_FINDINGS

    for finding in CONFIRMED_FINDINGS:
        matching = ci.Isolation(
            verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS,
            output_slots_beyond_rounding=[
                ci.SlotDifference(finding.block, finding.fortran_index - 1,
                                  finding.original, finding.transformed)]
            + [ci.SlotDifference("STATEV", 90 + n, 1.0, 2.0)
               for n in range(finding.slots_beyond_rounding - 1)])
        assert finding.matches(matching), finding.hypothesis
        moved = ci.Isolation(
            verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS,
            output_slots_beyond_rounding=[
                ci.SlotDifference(finding.block, finding.fortran_index - 1,
                                  finding.original, 1.25e-7)]
            + [ci.SlotDifference("STATEV", 90 + n, 1.0, 2.0)
               for n in range(finding.slots_beyond_rounding - 1)])
        assert not finding.matches(moved), finding.hypothesis
        fewer = ci.Isolation(
            verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS,
            output_slots_beyond_rounding=[
                ci.SlotDifference(finding.block, finding.fortran_index - 1,
                                  finding.original, finding.transformed)])
        assert finding.matches(fewer) == (finding.slots_beyond_rounding == 1)


def test_a_recorded_nan_finding_can_match_its_own_nan():
    """simplified_curing's confirmation IS a NaN, and ``nan == nan`` is False.
    Keyed on equality alone it could never match the measurement it was built
    from, and the entry would have read as unconfirmed for ever."""
    from umat_oti.abaqus.primal_signature import CONFIRMED_FINDINGS

    nan_findings = [f for f in CONFIRMED_FINDINGS
                    if isinstance(f.transformed, float)
                    and math.isnan(f.transformed)]
    assert nan_findings, "the NaN finding is registered"
    finding = nan_findings[0]
    isolation = ci.Isolation(
        verdict=ci.SAME_INPUTS_DIFFERENT_OUTPUTS,
        output_slots_beyond_rounding=[
            ci.SlotDifference(finding.block, finding.fortran_index - 1,
                              finding.original, float("nan"))]
        + [ci.SlotDifference("STRESS", n, 0.0, float("nan"))
           for n in range(1, finding.slots_beyond_rounding)])
    assert finding.matches(isolation)


def test_every_recorded_confirmation_names_what_it_held_fixed():
    """The field is not decorative: ``confirm`` refuses without it, and a
    reproduction that cannot say what was held fixed was not an experiment."""
    from umat_oti.abaqus.primal_signature import CONFIRMED_FINDINGS

    for finding in CONFIRMED_FINDINGS:
        assert finding.reproduction.held_fixed.strip()
        assert finding.reproduction.varied.strip()
        assert finding.reproduction.observed.strip()
        assert finding.reproduction.repeatable
        assert finding.root_cause.strip()
