"""A gap measured against zero is not a measurement of a gap.

The one-sided smoothness gap asks whether the forward and backward
perturbations landed on the same constitutive branch. It was measured
componentwise against each component's own centred slope -- so a tangent
carrying entries eight orders of magnitude below its largest had that many
denominators made of round-off, and the worst of them decided the state.

Measured on Growth-MinSur2.for, whose tangent has sixteen near-zero entries:
the gap came back as 1.7e-04, 31.6, 3.0e-05, 2.0, 0.29, 2.0 across six step
sizes. A quantity that moves six orders of magnitude non-monotonically is not
converging to two different limits; it is not being measured. Nine corpus
entries were classified as sitting on a constitutive transition on that basis
and their tangents were never verified.

The fix is the rule compare_tangent already applies to the error it reports:
a component below near_zero_fraction of the largest entry is measured against
the largest entry instead of against itself.
"""
import math

from umat_oti.abaqus.replay import one_sided_gap
from umat_oti.abaqus.state_regime import smoothness_verdict


def _gap(forward, backward, near_zero_fraction):
    """The gap the real sweep computes, over one perturbed column."""
    return one_sided_gap([(0, list(forward), list(backward))],
                         near_zero_fraction)


def test_a_near_zero_entry_no_longer_sets_the_whole_gap():
    # One stiff component carrying the response, one that is numerically
    # zero and carries only round-off.
    forward = [4.7e5, 1.01e-3]
    backward = [4.7e5 * (1 + 1e-9), -1.0e-3]
    unguarded = _gap(forward, backward, 0.0)
    guarded = _gap(forward, backward, 1e-8)
    assert unguarded > 1.0, "the artefact this is about"
    assert guarded < 1e-6, "the stiff component is smooth and now says so"


def test_a_real_kink_is_still_a_kink():
    # A branch change halves the stiffness the backward step sees. That lives
    # in the component that carries the stiffness, which no floor touches.
    forward = [4.7e5, 1.0e4]
    backward = [2.3e5, 1.0e4]
    assert _gap(forward, backward, 1e-8) > 0.5


def test_the_measured_growth_gaps_read_as_smooth_once_floored():
    # The six steps as recorded, and what they become when the sixteen
    # near-zero entries stop setting them. The point is the verdict: an O(h)
    # fall, not a pair of limits.
    floored = {1e-2: 2.0e-6, 1e-3: 1.7e-7, 1e-4: 3.1e-8,
               1e-5: 2.0e-8, 1e-6: 2.0e-8, 1e-7: 2.0e-8}
    smooth, step, _rejected, why = smoothness_verdict(floored)
    assert smooth is True, why
    assert step is not None


def test_the_recorded_gaps_are_what_the_old_rule_rejected():
    recorded = {1e-3: 1.7179545131944393e-4, 1e-4: 31.599999999999994,
                1e-5: 3.0460409083293996e-5, 1e-6: 2.0,
                1e-7: 0.28571428571428564, 1e-8: 2.0}
    smooth, _step, _rejected, why = smoothness_verdict(recorded)
    assert smooth is False
    assert "kink" in why
    # and the reason it is not a kink: the sequence is not monotone in any
    # direction, which neither a limit nor an O(h) fall can be.
    values = [recorded[k] for k in sorted(recorded, reverse=True)]
    rising = all(b >= a for a, b in zip(values, values[1:]))
    falling = all(b <= a for a, b in zip(values, values[1:]))
    assert not rising and not falling


def test_the_sweep_reaches_the_top_decade_the_method_asks_for():
    """The minimum has to be INSIDE the sweep, not at its edge.

    Measured over the thirteen entries whose tangent failed for want of a
    second agreeing step: of the twenty-six states they evaluated, the step
    with the smallest error was the LARGEST step in the sweep in twenty-four
    of them. A minimum at the boundary is not a minimum; it says the U-curve
    turns somewhere the sweep never looked.
    """
    from umat_oti.abaqus.manifest import VerificationManifest
    steps = VerificationManifest.fd_steps
    assert max(steps) == 1e-2, (
        "a stiff model's U-curve minimum can sit above 1e-3; a sweep that "
        "starts there has no minimum in it to find")
    assert min(steps) <= 1e-6
    assert steps == tuple(sorted(steps, reverse=True))
    assert len(set(steps)) == len(steps)


def test_a_step_where_nothing_was_resolvable_is_absent_not_zero():
    # Every component round-off. A gap of zero would read as perfect
    # smoothness; the honest answer is that this step measured nothing.
    assert one_sided_gap([(0, [0.0, 0.0], [0.0, 0.0])], 1e-8) is None
    assert one_sided_gap([], 1e-8) is None


def test_difference_tangent_takes_the_fraction_from_the_manifest():
    import inspect
    from umat_oti.abaqus.replay import difference_tangent
    assert "near_zero_fraction" in inspect.signature(difference_tangent).parameters
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    assert "near_zero_fraction=manifest.near_zero_fraction" in text, (
        "the sweep would otherwise floor against a default the manifest "
        "does not know about")
