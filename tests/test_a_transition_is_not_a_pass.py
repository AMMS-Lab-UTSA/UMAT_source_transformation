"""Classifying a state as transitional must never turn a failure into a pass.

A centred difference cannot tell whether its two evaluations sat on the same
constitutive branch. Knowing that is useful -- it stops a chord across a
corner being reported as "the transform's tangent is wrong". It is also
dangerous, because the same label could quietly excuse every state at which
the derivative did not agree.

So the rule these tests fix: a transitional state is not a verified state and
not a failed one. It carries no weight in either direction, and a nonlinear
material still has to produce smooth verified states INSIDE its activated
regime before its tangent is verified.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.state_regime import (  # noqa: E402
    NONSMOOTH_OR_UNRESOLVED, SMOOTH_ELASTIC, SMOOTH_INELASTIC,
    SMOOTH_UNLOADING, TRANSITION_NEARBY, VERIFIABLE, activated_by, classify,
    coverage, smoothness_verdict, unloading_at)

STEPS = (1e-3, 1e-4, 1e-5, 1e-6)


def gaps(*values):
    return dict(zip(STEPS, values))


# ---- the smoothness verdict, on the shapes it has to tell apart ----------
def test_a_smooth_linear_response_is_smooth():
    """Forward and backward slopes are identical; the gap is round-off."""
    assert smoothness_verdict(gaps(1e-12, 1e-12, 1e-11, 1e-10))[0]


def test_a_smooth_nonlinear_response_is_smooth():
    """The gap is O(h): a decade of step buys a decade of gap."""
    assert smoothness_verdict(gaps(1e-2, 1e-3, 1e-4, 1e-5))[0]


def test_a_yield_kink_is_not_smooth():
    """The one-sided slopes converge to two DIFFERENT limits, so the gap
    stops falling however small the step gets."""
    smooth, _step, _rejected, why = smoothness_verdict(
        gaps(0.82, 0.80, 0.80, 0.79))
    assert not smooth and "same constitutive branch" in why


def test_damage_onset_with_a_smaller_jump_is_still_not_smooth():
    """A gap that is small in absolute terms but does not FALL is still a
    kink. This is the case a single threshold gets wrong."""
    smooth, _s, _r, why = smoothness_verdict(gaps(0.09, 0.088, 0.087, 0.086))
    assert not smooth and "different limits" in why


def test_one_step_size_cannot_decide_it():
    """A single relative difference cannot distinguish O(h) from a jump."""
    assert not smoothness_verdict({1e-3: 1e-6})[0]


def test_cancellation_noise_at_small_steps_is_still_smooth():
    """A gap that GROWS as the step shrinks, from a value that is already
    round-off, is cancellation on a smooth function -- not a kink. The
    smallest gap being at the largest step is what a linear response looks
    like, and rejecting it would make a linear elastic UMAT unverifiable."""
    assert smoothness_verdict(gaps(1e-8, 1e-7, 1e-6, 1e-5))[0]


def test_a_gap_that_grows_from_an_already_large_value_is_not_smooth():
    """Here the one-sided slopes never agreed to begin with, and shrinking
    the step made it worse. Nothing in the sweep shows convergence."""
    assert not smoothness_verdict(gaps(0.02, 0.05, 0.2, 0.6))[0]


def test_the_selected_and_rejected_steps_are_recorded():
    _smooth, step, rejected, _why = smoothness_verdict(
        gaps(1e-2, 1e-3, 1e-4, 1e-5))
    assert step == 1e-6
    assert 1e-3 in rejected


# ---- the regime is decided per state, from the history up to it ----------
def history(yield_at_increment, count=10, reverse_at=None):
    records = []
    for index in range(count):
        plastic = max(0, index - yield_at_increment + 1) * 1e-4
        direction = -1.0 if (reverse_at is not None and index >= reverse_at) else 1.0
        records.append({
            "increment": index + 1,
            "STATEV": [plastic],
            "DSTRAN": [direction * 1e-4] + [0.0] * 5,
            "DDSDDE": [2e5 if plastic == 0 else 2e3] + [0.0] * 35})
    return records


def test_an_early_state_in_a_run_that_yields_later_is_elastic():
    """The defect this replaces: a global "did it activate?" Boolean labelled
    every increment inelastic because activation happened somewhere."""
    records = history(yield_at_increment=8)
    assert not activated_by(records, 2)
    assert activated_by(records, 9)


def test_the_regime_of_an_early_state_is_smooth_elastic():
    records = history(yield_at_increment=8)
    assert classify(records, 2, gaps(1e-2, 1e-3, 1e-4, 1e-5)).regime == SMOOTH_ELASTIC


def test_the_regime_of_a_late_state_is_smooth_inelastic():
    records = history(yield_at_increment=3)
    assert classify(records, 8, gaps(1e-2, 1e-3, 1e-4, 1e-5)).regime == SMOOTH_INELASTIC


def test_a_reversed_increment_is_unloading():
    records = history(yield_at_increment=3, reverse_at=6)
    assert unloading_at(records, 7)
    assert classify(records, 7, gaps(1e-2, 1e-3, 1e-4, 1e-5)).regime == SMOOTH_UNLOADING


def test_a_kink_beats_every_other_label():
    """However the state would otherwise be classified, a chord across a
    corner is not a derivative."""
    records = history(yield_at_increment=3)
    found = classify(records, 8, gaps(0.8, 0.8, 0.8, 0.79))
    assert found.regime == TRANSITION_NEARBY and not found.verifiable


def test_no_sweep_at_all_is_unresolved_not_smooth():
    assert classify(history(3), 5, {}).regime == NONSMOOTH_OR_UNRESOLVED


def test_only_smooth_regimes_are_verifiable():
    assert set(VERIFIABLE) == {SMOOTH_ELASTIC, SMOOTH_INELASTIC, SMOOTH_UNLOADING}
    assert TRANSITION_NEARBY not in VERIFIABLE
    assert NONSMOOTH_OR_UNRESOLVED not in VERIFIABLE


# ---- coverage: what a transitional label may NOT buy ---------------------
def _regime(kind, increment=1):
    from umat_oti.abaqus.state_regime import Regime
    return Regime(increment=increment, regime=kind, reason="")


def test_a_nonlinear_material_needs_smooth_states_inside_the_activated_regime():
    """Elastic states alone are not evidence about a material that yields:
    a converted routine wrong about yielding agrees perfectly on all of them."""
    ok, why = coverage([_regime(SMOOTH_ELASTIC, 1), _regime(SMOOTH_ELASTIC, 2),
                        _regime(SMOOTH_ELASTIC, 3)], nonlinear=True)
    assert not ok and "not the whole of it" in why


def test_transitional_states_cannot_stand_in_for_activated_ones():
    """THE test. Three elastic states plus two transitional ones must not
    add up to a verified nonlinear tangent."""
    ok, why = coverage([_regime(SMOOTH_ELASTIC, 1), _regime(SMOOTH_ELASTIC, 2),
                        _regime(TRANSITION_NEARBY, 5),
                        _regime(TRANSITION_NEARBY, 6)], nonlinear=True)
    assert not ok
    assert "establish nothing either way" in why


def test_every_inelastic_state_being_transitional_is_not_a_pass():
    ok, _why = coverage([_regime(SMOOTH_ELASTIC, 1), _regime(SMOOTH_ELASTIC, 2),
                         _regime(NONSMOOTH_OR_UNRESOLVED, 7),
                         _regime(NONSMOOTH_OR_UNRESOLVED, 8)], nonlinear=True)
    assert not ok


def test_two_smooth_states_each_side_is_enough():
    ok, why = coverage([_regime(SMOOTH_ELASTIC, 1), _regime(SMOOTH_ELASTIC, 2),
                        _regime(SMOOTH_INELASTIC, 7),
                        _regime(SMOOTH_INELASTIC, 9)], nonlinear=True)
    assert ok and "2 smooth elastic" in why


def test_one_state_each_side_is_not_enough():
    ok, _why = coverage([_regime(SMOOTH_ELASTIC, 1),
                         _regime(SMOOTH_INELASTIC, 7)], nonlinear=True)
    assert not ok


def test_a_path_dependent_material_needs_an_unloading_state():
    states = [_regime(SMOOTH_ELASTIC, 1), _regime(SMOOTH_ELASTIC, 2),
              _regime(SMOOTH_INELASTIC, 7), _regime(SMOOTH_INELASTIC, 9)]
    assert not coverage(states, nonlinear=True, path_dependent=True)[0]
    assert coverage(states + [_regime(SMOOTH_UNLOADING, 12)],
                    nonlinear=True, path_dependent=True)[0]


def test_a_linear_material_is_whole_on_its_elastic_branch():
    """For a model that never activates there is no other regime to reach,
    and demanding one would make a linear elastic UMAT unverifiable."""
    ok, why = coverage([_regime(SMOOTH_ELASTIC, 1), _regime(SMOOTH_ELASTIC, 5)],
                       nonlinear=False)
    assert ok and "which is the whole of it" in why


def test_a_linear_material_still_needs_more_than_one_state():
    assert not coverage([_regime(SMOOTH_ELASTIC, 1)], nonlinear=False)[0]


# ---- states are chosen either side of the transition, never on it -------
def _replayable(count, activates_at=None):
    entry = {"STRESS0": [0.0] * 6}
    return [{"DDSDDE": [1.0] * 36, "entry": entry, "increment": i + 1,
             "STATEV": [0.0 if activates_at is None or i < activates_at
                        else (i - activates_at + 1) * 1e-4],
             "DSTRAN": [1e-4] + [0.0] * 5}
            for i in range(count)]


def test_states_are_taken_from_both_sides_of_the_transition():
    """Bracketing where a material activates is not verifying across it.
    Measured on From-2D-to-2D-Axe.for: discovery found activation at 2.5e-05
    and the verification then evaluated at that amplitude, so all three
    states sat on the transition and every centred difference was a chord
    across a corner."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from verify_store_in_abaqus import (choose_states_around_activation,
                                        first_activated)

    records = _replayable(14, activates_at=6)
    turn = first_activated(records)
    assert turn == 6
    chosen = [position for position, _ in
              choose_states_around_activation(records, each_side=2)]
    assert any(p < turn for p in chosen), "no state before the transition"
    assert any(p > turn for p in chosen), "no state after the transition"


def test_no_state_is_adjacent_to_the_transition():
    """The increment either side is where a perturbation is most likely to
    step across, so the selection keeps clear of it."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from verify_store_in_abaqus import (choose_states_around_activation,
                                        first_activated)

    records = _replayable(14, activates_at=6)
    turn = first_activated(records)
    for position, _ in choose_states_around_activation(records, each_side=2):
        assert abs(position - turn) > 1, f"state at {position} touches {turn}"


def test_a_material_that_never_activates_still_gets_states():
    """Demanding a transition would make a linear elastic UMAT unverifiable."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from verify_store_in_abaqus import choose_states_around_activation

    chosen = choose_states_around_activation(_replayable(10), each_side=2)
    assert len(chosen) >= 2


def test_verification_is_driven_past_the_transition_not_up_to_it():
    """Discovery stops at the amplitude where activation first appears.
    Verifying there puts the transition at the END of the path, so every
    increment is before it or on it and there is no smooth state inside the
    activated regime. Measured on From-2D-to-2D-Axe.for: activation at
    2.5e-05, both chosen states after it, none before.

    The verification amplitude is a multiple of the bracket, so the path
    crosses the transition partway along and carries smooth states on both
    sides. The multiple is confirmed by an actual run before it is adopted.
    """
    tool = (Path(__file__).resolve().parents[1] / "tools"
            / "verify_store_in_abaqus.py").read_text(encoding="utf-8")
    assert "BEYOND_TRANSITION" in tool
    assert "amplitude * factor" in tool, (
        "the verification amplitude is a multiple of what the search found")
    assert "ladder = RESOLUTION_FACTORS if at_the_floor else (BEYOND_TRANSITION,)" in tool, (
        "a material with a transition is driven past it; one that was already\n"
        "         active at the search's floor has no transition to cross and is\n"
        "         driven up for resolution instead")
    assert "ran, _records, why = run_at(wanted)" in tool, (
        "the extended amplitude must be confirmed by a run, not assumed")
    assert "could not be driven further than the" in tool, (
        "a material that cannot be driven further must keep the amplitude "
        "that worked, and say so")


# ---------------------------------------------------------------------------
# and a branch that does not exist cannot be evidence
# ---------------------------------------------------------------------------
def test_a_material_with_no_elastic_branch_is_not_asked_for_two_elastic_states():
    """The Jeff97 growth family: activated from the first increment and never
    stopping. Every state agreed, every one was inside the activated regime,
    and the coverage rule failed them for the absence of a branch they do not
    have. Demanding evidence a material cannot produce is not a strict test;
    it is an unmeetable one."""
    from umat_oti.abaqus.state_regime import (Regime, SMOOTH_INELASTIC,
                                              coverage)

    inside = [Regime(increment=n, regime=SMOOTH_INELASTIC,
                     reason="activated", activated_here=True)
              for n in (2, 5)]
    enough, why = coverage(inside, nonlinear=True, character="irreversible")
    assert enough, why
    assert "no elastic branch" in why


def test_a_material_that_does_have_an_elastic_branch_still_needs_it():
    """The rule only relaxes where the branch is absent. A material with one
    pre-activation state has an elastic branch and one state on it, and one
    state cannot separate a regime from a coincidence."""
    from umat_oti.abaqus.state_regime import (Regime, SMOOTH_ELASTIC,
                                              SMOOTH_INELASTIC, coverage)

    mixed = [Regime(increment=1, regime=SMOOTH_ELASTIC, reason="quiet"),
             Regime(increment=5, regime=SMOOTH_INELASTIC, reason="activated",
                    activated_here=True),
             Regime(increment=7, regime=SMOOTH_INELASTIC, reason="activated",
                    activated_here=True)]
    enough, why = coverage(mixed, nonlinear=True, character="irreversible")
    assert not enough
    assert "before activation" in why


def test_the_best_step_is_the_one_the_verdict_is_taken_on():
    """Choosing the step by the Frobenius norm and reporting that step's
    RELATIVE error let the two disagree about which step was best -- and they
    did. Measured on From-2D-to-2D-Axe.for: the Frobenius minimum sat at a
    step whose worst-component relative error was 1.20e-04, while its
    neighbour's was 7.69e-06. Fifteen times better and not reported."""
    from umat_oti.abaqus.compare import compare_tangent

    oti = [[1000.0, 0.0], [0.0, 1.0]]
    # 1e-3: a SMALL absolute error, all of it on the small entry, so its
    #       Frobenius norm is the smaller and its worst-component relative
    #       error is the larger.
    # 1e-4: a larger absolute error on the large entry: worse Frobenius,
    #       better worst component.
    differences = {
        1e-3: [[1000.0, 0.0], [0.0, 1.0 + 1e-3]],
        1e-4: [[1000.0 + 1e-2, 0.0], [0.0, 1.0]],
    }
    found = compare_tangent(oti, differences).as_dict()
    assert found["best_step"] == 1e-4
    assert found["best_relative"] < 1e-4
    # and the Frobenius plateau still spans both, because that is a statement
    # about the shape of the sweep rather than about one component
    assert tuple(found["stable_range"]) == (1e-4, 1e-3)


def test_a_smooth_unloading_state_is_evidence_about_the_activated_material():
    """It is a state INSIDE the activated material, and a stronger one than a
    state on the way up: unloading is where a model that keeps something and a
    model that does not finally differ. Counted apart from the loading states,
    a material verified at one of each was recorded as "1 smooth state, and two
    are needed" -- seventeen of them in one batch, every state agreeing."""
    from umat_oti.abaqus.state_regime import (Regime, SMOOTH_INELASTIC,
                                              SMOOTH_UNLOADING, coverage)

    both = [Regime(increment=4, regime=SMOOTH_INELASTIC, reason="activated",
                   activated_here=True),
            Regime(increment=3, regime=SMOOTH_UNLOADING, reason="reversing",
                   activated_here=True, unloading=True)]
    enough, why = coverage(both, nonlinear=True, character="irreversible")
    assert enough, why
    assert "1 loading, 1 unloading" in why


def test_one_state_of_either_kind_is_still_not_enough():
    from umat_oti.abaqus.state_regime import (Regime, SMOOTH_UNLOADING,
                                              coverage)

    one = [Regime(increment=3, regime=SMOOTH_UNLOADING, reason="reversing",
                  activated_here=True, unloading=True)]
    enough, why = coverage(one, nonlinear=True, character="irreversible")
    assert not enough
    assert "two are needed" in why
