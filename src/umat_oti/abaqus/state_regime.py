"""What kind of point a derivative was asked for at, decided per state.

A centred difference cannot tell whether its two evaluations sat on the same
constitutive branch. At a yield point the forward step is on one branch and
the backward step on the other, and their average is the slope of a chord
across a corner -- a number that is not a derivative of anything, and that no
step size makes converge.

Two things this module refuses to do, because both would turn a failure into
a label:

* It never decides a state is inelastic from a Boolean about the whole
  loading history. An early elastic increment in a run that yields later is
  an elastic state, and calling it inelastic because activation happened
  afterwards would credit the elastic branch with covering the activated one.
  Every classification here reads the history UP TO that increment only.

* It never concludes "smooth" from a single step size. For a smooth response
  the two one-sided slopes differ by O(h) and that gap SHRINKS as h shrinks;
  at a kink they converge to two different limits and the gap does not. One
  relative difference at one step cannot tell those apart, so the decision is
  made on how the gap behaves across the sweep.

A ``transition_nearby`` state is not a verified state, and not a failed one.
It is a state at which a centred difference was the wrong reference, and it
may never stand in for verification inside the activated regime.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: Regimes a state can be in. Only the two smooth ones may carry a verified
#: derivative.
SMOOTH_ELASTIC = "smooth_elastic"
SMOOTH_INELASTIC = "smooth_inelastic"
SMOOTH_UNLOADING = "smooth_unloading"
TRANSITION_NEARBY = "transition_nearby"
NONSMOOTH_OR_UNRESOLVED = "nonsmooth_or_unresolved"

#: The regimes at which a derivative comparison means something.
VERIFIABLE = (SMOOTH_ELASTIC, SMOOTH_INELASTIC, SMOOTH_UNLOADING)

#: A relative movement below this is floating-point noise, not a material
#: doing something.
NOISE = 1e-9

#: The one-sided gap must fall by at least this factor when the step falls by
#: ten, before the response is called smooth. A smooth response gives O(h), so
#: a decade of step buys a decade of gap; anything that stays put across a
#: decade is a kink whose two one-sided limits differ.
#:
#: Three, not ten: the gap also carries cancellation noise that GROWS as h
#: shrinks, so demanding the full order would reject smooth responses at the
#: small-step end of a real sweep.
SHRINK_PER_DECADE = 3.0

#: Above this the two one-sided slopes are so far apart that no convergence
#: argument is needed: they are not slopes of the same function.
OUTRIGHT_KINK = 0.5

#: Below this the two one-sided slopes agree to six figures, which no kink
#: does -- a kink's gap is the JUMP in the derivative, of order one. A gap
#: this small is round-off, and round-off GROWS as the step shrinks, so
#: demanding that it fall with the step would reject exactly the smoothest
#: response there is: a linear one, whose one-sided slopes are identical.
DEFINITELY_SMOOTH = 1e-6


@dataclass
class Regime:
    """One state, its regime, and the evidence for it."""

    increment: int
    regime: str
    reason: str
    activated_here: bool = False
    unloading: bool = False
    smoothness: dict = field(default_factory=dict)
    selected_step: Optional[float] = None
    rejected_steps: tuple = ()

    @property
    def verifiable(self) -> bool:
        return self.regime in VERIFIABLE

    def as_dict(self) -> dict:
        return {"increment": self.increment, "regime": self.regime,
                "reason": self.reason, "activated_here": self.activated_here,
                "unloading": self.unloading, "verifiable": self.verifiable,
                "selected_step": self.selected_step,
                "rejected_steps": list(self.rejected_steps),
                "smoothness": {str(k): v for k, v in self.smoothness.items()}}


def _finite(values) -> list[float]:
    return [float(v) for v in (values or ()) if math.isfinite(float(v))]


def activated_by(records: Sequence[dict], position: int) -> bool:
    """Has the material done anything by this increment, and only by it?

    The history up to ``position`` inclusive. A run that yields at increment
    eight has seven elastic states before it, and they are elastic states.
    """
    if position <= 0 or not records:
        return False
    first = _finite((records[0] or {}).get("STATEV"))
    if first:
        for record in records[1:position + 1]:
            current = _finite(record.get("STATEV"))
            for a, b in zip(first, current):
                if abs(b - a) / max(abs(a), abs(b), 1.0) > NOISE:
                    return True
    # No state variables, or none that moved: fall back to the tangent, which
    # is the other thing a constitutive event always changes.
    reference = _finite((records[0] or {}).get("DDSDDE"))
    if not reference:
        return False
    scale = max((abs(v) for v in reference), default=0.0) or 1.0
    for record in records[1:position + 1]:
        current = _finite(record.get("DDSDDE"))
        for a, b in zip(reference, current):
            if abs(b - a) / scale > 1e-3:
                return True
    return False


def unloading_at(records: Sequence[dict], position: int) -> bool:
    """Is the strain increment pointing against the way the path set out?

    Against the FIRST increment, not against the one immediately before.
    Every state after a reversal is an unloading state, not just the increment
    at which the path turned -- and it is the states after the turn, where the
    material is being asked to remember what it did on the way out, that a
    derivative is worth checking at.
    """
    if position <= 0 or position >= len(records):
        return False
    now = _finite((records[position] or {}).get("DSTRAN"))
    first = _finite((records[0] or {}).get("DSTRAN"))
    if not now or not first:
        return False
    dot = sum(a * b for a, b in zip(first, now))
    size = (math.sqrt(sum(a * a for a in first))
            * math.sqrt(sum(b * b for b in now)))
    return bool(size) and dot / size < -0.1


def smoothness_verdict(smoothness: dict) -> tuple[bool, Optional[float], tuple, str]:
    """Does the one-sided gap SHRINK as the step shrinks?

    ``smoothness`` maps a relative step to the largest disagreement between
    the forward and backward one-sided differences, measured against the
    centred difference they average to.

    For a smooth response that gap is O(h): a decade of step buys most of a
    decade of gap. At a kink the two one-sided differences converge to two
    different limits, so the gap tends to a constant and shrinking the step
    does not move it. That difference in BEHAVIOUR is the test; a single
    relative difference at a single step cannot distinguish them.

    Returns whether it is smooth, the step whose gap was smallest, the steps
    rejected on the way, and the sentence that justifies it.
    """
    usable = {float(step): float(gap) for step, gap in (smoothness or {}).items()
              if math.isfinite(float(gap))}
    if len(usable) < 2:
        return False, None, (), (
            f"only {len(usable)} step size produced a one-sided comparison, "
            f"and one step cannot show whether the gap shrinks")

    ordered = sorted(usable.items(), key=lambda item: -item[0])   # large first
    largest_step, largest_gap = ordered[0]
    smallest = min(usable.items(), key=lambda item: item[1])
    best_step, best_gap = smallest

    if best_gap <= DEFINITELY_SMOOTH:
        rejected = tuple(step for step, gap in ordered if gap > best_gap * 10)
        return True, best_step, rejected, (
            f"the forward and backward one-sided differences agree to "
            f"{best_gap:.3g} at a step of {best_step:g}, which is round-off "
            f"rather than a jump: a kink's gap is the difference between two "
            f"limiting derivatives and is of order one")

    if best_gap > OUTRIGHT_KINK:
        return False, best_step, tuple(s for s, _ in ordered), (
            f"the forward and backward one-sided differences disagree by "
            f"{best_gap:.2f} at every step, so they are not slopes of the "
            f"same function and the two perturbations did not sit on the "
            f"same constitutive branch")

    # How much did the gap fall over the decades the sweep spans?
    decades = math.log10(largest_step / best_step) if best_step > 0 and largest_step > best_step else 0.0
    if decades <= 0:
        return False, best_step, tuple(s for s, _ in ordered), (
            f"the smallest gap is at the largest step, so the disagreement is "
            f"not falling with the step and does not behave like O(h)")
    fell_by = largest_gap / best_gap if best_gap > 0 else math.inf
    wanted = SHRINK_PER_DECADE ** decades
    if fell_by + 1e-12 < wanted:
        return False, best_step, tuple(s for s, _ in ordered), (
            f"the one-sided gap fell only {fell_by:.2f}x over {decades:.1f} "
            f"decades of step size, where a smooth response gives at least "
            f"{wanted:.2f}x: the two one-sided differences are converging to "
            f"different limits, which is a kink")

    rejected = tuple(step for step, gap in ordered if gap > best_gap * 10)
    return True, best_step, rejected, (
        f"the one-sided gap fell {fell_by:.2f}x over {decades:.1f} decades of "
        f"step size to {best_gap:.3g}, which is the O(h) a smooth response "
        f"gives; the two perturbations sat on the same branch")


def classify(records: Sequence[dict], position: int,
             smoothness: dict) -> Regime:
    """The regime of ONE evaluation state, from the history up to it."""
    increment = int((records[position] or {}).get("increment") or position + 1) \
        if 0 <= position < len(records) else position + 1
    activated = activated_by(records, position)
    reversing = unloading_at(records, position)

    smooth, step, rejected, why = smoothness_verdict(smoothness)
    if not smooth:
        regime = (TRANSITION_NEARBY if smoothness else NONSMOOTH_OR_UNRESOLVED)
        return Regime(increment=increment, regime=regime, reason=why,
                      activated_here=activated, unloading=reversing,
                      smoothness=dict(smoothness or {}), selected_step=step,
                      rejected_steps=rejected)

    if reversing:
        regime, note = SMOOTH_UNLOADING, "the strain increment has reversed"
    elif activated:
        regime, note = SMOOTH_INELASTIC, "the material has activated by here"
    else:
        regime, note = SMOOTH_ELASTIC, "nothing has activated by here"
    return Regime(increment=increment, regime=regime,
                  reason=f"{note}, and {why}", activated_here=activated,
                  unloading=reversing, smoothness=dict(smoothness or {}),
                  selected_step=step, rejected_steps=rejected)


#: What the evidence says a material's response IS, rather than what a state
#: variable happened to do. Ordered from least to most committed.
LINEAR_REVERSIBLE = "linear_reversible"
NONLINEAR_REVERSIBLE = "nonlinear_reversible"
IRREVERSIBLE = "irreversible"
UNKNOWN_STATE_SEMANTICS = "unknown_state_semantics"


def _at(records, position, field):
    return _finite((records[position] or {}).get(field)) if 0 <= position < len(records) else []


def _relative_gap(a, b) -> float:
    worst = 0.0
    for x, y in zip(a, b):
        worst = max(worst, abs(x - y) / max(abs(x), abs(y), 1.0))
    return worst


def response_character(records: Sequence[dict]) -> tuple[str, str]:
    """What this material's response is, from what it DID -- not from STATEV.

    A state variable can hold time, temperature, a total strain, a stretch, an
    orientation, a copied input or iteration bookkeeping. Measured on
    From-2D-to-2D-Axe.for: STATEV(9) rises to 1.0589 under load and falls back
    to 1.0058 the moment the strain is removed. It is a deformation measure,
    and a rule that read its movement as "the material has yielded" would have
    called a reversible response irreversible.

    So the question asked here is reversibility, which is observable: when the
    strain comes back toward where it started, does the STRESS come back too?
    An elastic material returns; anything that keeps something does not.

    Returns the character and the sentence that justifies it. Where the
    evidence does not settle it the answer is UNKNOWN_STATE_SEMANTICS, and the
    caller must not treat that as either reversible or irreversible.
    """
    usable = [r for r in (records or ()) if _finite(r.get("STRESS"))]
    if len(usable) < 4:
        return UNKNOWN_STATE_SEMANTICS, (
            f"only {len(usable)} increment(s) carry a stress, which is too "
            f"few to see whether the response returns")

    start_strain = _at(usable, 0, "STRAN")
    if not start_strain:
        return UNKNOWN_STATE_SEMANTICS, "no strain was recorded to compare against"

    # How far the path went, so "came back" can be measured against its own
    # excursion. Measured against a fixed scale instead, a path that never
    # left -- a monotonic ramp to 4e-4 -- reads as having returned, because
    # every strain on it is small in absolute terms.
    peak_excursion = 0.0
    for position in range(len(usable)):
        strain = _at(usable, position, "STRAN")
        if strain:
            peak_excursion = max(
                peak_excursion,
                max((abs(a - b) for a, b in zip(start_strain, strain)),
                    default=0.0))
    if peak_excursion <= 0.0:
        return UNKNOWN_STATE_SEMANTICS, (
            "the strain never moved from where it started, so nothing was "
            "asked of the material")

    # The increment that came back closest to where the path started, as a
    # fraction of how far it went.
    returned, distance = None, math.inf
    for position in range(1, len(usable)):
        strain = _at(usable, position, "STRAN")
        if not strain:
            continue
        gap = max((abs(a - b) for a, b in zip(start_strain, strain)),
                  default=math.inf) / peak_excursion
        if gap < distance:
            returned, distance = position, gap

    peak_stress = max((max((abs(v) for v in _finite(r.get("STRESS"))), default=0.0)
                       for r in usable), default=0.0)
    if returned is None or distance > 0.2 or not peak_stress:
        # The path never came back, so reversibility was never tested. Say so
        # rather than guessing from whether a number moved.
        return UNKNOWN_STATE_SEMANTICS, (
            "this loading never returns near the strain it started from, so "
            "nothing here shows whether the response is reversible; a state "
            "variable that moved may be a plastic strain or may be a stretch, "
            "and this evidence cannot tell them apart")

    residual = max((abs(v) for v in _at(usable, returned, "STRESS")), default=0.0)
    kept = residual / peak_stress
    if kept > 1e-2:
        return IRREVERSIBLE, (
            f"the strain returned to within {distance:.1%} of where it started "
            f"and {kept:.1%} of the peak stress remained, so the material kept "
            f"something")

    # Reversible. Linear or not?
    # The reference is the first increment that actually applied a strain.
    # Taking record zero blindly makes the reference zero on any path that
    # starts from rest, and the proportionality check then never runs -- so a
    # nonlinear response came out labelled linear.
    reference, first_stress, first_strain = 0.0, [], []
    for record in usable:
        strain = _finite(record.get("STRAN"))
        size = max((abs(v) for v in strain), default=0.0)
        if size > 0:
            reference, first_strain = size, strain
            first_stress = _finite(record.get("STRESS"))
            break
    worst = 0.0
    if reference:
        for record in usable[1:]:
            strain = _finite(record.get("STRAN"))
            stress = _finite(record.get("STRESS"))
            ratio = max((abs(v) for v in strain), default=0.0) / reference
            if ratio <= 0:
                continue
            predicted = [v * ratio for v in first_stress]
            scale = max(max((abs(v) for v in predicted), default=0.0),
                        max((abs(v) for v in stress), default=0.0), 1.0)
            for a, b in zip(predicted, stress):
                worst = max(worst, abs(a - b) / scale)
    character = NONLINEAR_REVERSIBLE if worst > 1e-3 else LINEAR_REVERSIBLE
    return character, (
        f"the strain returned to within {distance:.1%} of its start and only "
        f"{kept:.2%} of the peak stress remained, so the response is "
        f"reversible; it departs from proportionality by {worst:.3g}")


def coverage(regimes: Sequence[Regime], nonlinear: bool,
             path_dependent: bool = False,
             character: str = UNKNOWN_STATE_SEMANTICS) -> tuple[bool, str]:
    """Is this enough smooth evidence to call a material's tangent verified?

    For a linear model the elastic branch is the whole material and smooth
    elastic states are the whole story. For a NONLINEAR one they are not: a
    converted routine wrong about yielding agrees perfectly everywhere the
    model is still elastic, so verification has to reach inside the activated
    regime and stay there for more than one state.

    A transitional state counts for nothing here. It is not a failure, and it
    is not evidence either.
    """
    verifiable = [r for r in regimes if r.verifiable]
    elastic = [r for r in verifiable if r.regime == SMOOTH_ELASTIC]
    inelastic = [r for r in verifiable if r.regime == SMOOTH_INELASTIC]
    unloading = [r for r in verifiable if r.regime == SMOOTH_UNLOADING]
    transitional = [r for r in regimes if not r.verifiable]

    if not nonlinear:
        if len(verifiable) >= 2:
            return True, (f"{len(verifiable)} smooth states on a material that "
                          f"never activates, which is the whole of it")
        return False, (f"only {len(verifiable)} smooth state(s), and two are "
                       f"needed: one state cannot separate a regime from a "
                       f"coincidence")

    # A material that keeps something has an elastic branch to leave, so the
    # evidence has to span both. One whose reversibility could not be
    # established gets the SAME requirement, not a reduced one: not knowing
    # is not a reason to ask for less.
    needs_both_sides = character != NONLINEAR_REVERSIBLE
    if needs_both_sides and len(elastic) < 2:
        return False, (f"{len(elastic)} smooth state(s) before activation, and "
                       f"two are needed")
    if not needs_both_sides and len(inelastic) < 2:
        return False, (
            f"{len(inelastic)} smooth state(s), and two are needed. This "
            f"material has activated by its second increment and never stops "
            f"-- there is no elastic branch to verify on, so all the evidence "
            f"has to come from inside the activated regime"
            + (f"; {len(transitional)} state(s) sat on a transition and "
               f"establish nothing either way" if transitional else ""))
    if len(inelastic) < 2:
        return False, (
            f"{len(inelastic)} smooth state(s) inside the activated regime, "
            f"and two are needed. This material activates, so the elastic "
            f"branch is not the whole of it -- a converted routine wrong "
            f"about what happens after activation agrees perfectly on every "
            f"elastic state"
            + (f"; {len(transitional)} state(s) sat on a transition and "
               f"establish nothing either way" if transitional else ""))
    if path_dependent and not unloading:
        return False, ("no smooth unloading state, and this material's "
                       "response depends on the path it took")
    if not needs_both_sides:
        return True, (
            f"{len(inelastic)} smooth state(s) inside the activated regime, "
            f"which is the whole of this material: its response is nonlinear "
            f"but REVERSIBLE, so there is no irreversible branch to cross and "
            f"no elastic-versus-plastic split to span"
            + (f"; {len(transitional)} transitional state(s) carried no weight "
               f"either way" if transitional else ""))
    return True, (f"{len(elastic)} smooth elastic, {len(inelastic)} smooth "
                  f"activated"
                  + (f" and {len(unloading)} smooth unloading" if unloading else "")
                  + f" state(s) verified"
                  + (f"; {len(transitional)} transitional state(s) carried no "
                     f"weight either way" if transitional else ""))
