"""Comparing what two builds computed, and a tangent against finite differences.

Two separate questions, kept separate.

The primal comparison asks whether the transformed build still computes the
model. That has to pass before a derivative comparison means anything: a
tangent that agrees with a finite difference of the *wrong* stress is not
evidence about the transform, and the finite difference is taken from the
untransformed build precisely so the two sides share no code path.

The tangent comparison asks whether the OTI derivative equals a centred
difference of that stress. It is reported as a sweep over the step size,
because one step cannot tell a truncation error from a cancellation one -- and
because the honest statement about a finite-difference check is the range over
which it was stable, not a single number chosen after the fact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence


@dataclass
class PrimalComparison:
    """Do two builds agree on the response, increment by increment?"""

    increments: int = 0
    #: How many records each build actually produced. They have to match: a
    #: build whose probe wrote one record out of twenty was being compared over
    #: that one record and reported as agreeing over the whole history.
    indistinguishable_components: int = 0
    records_original: int = 0
    records_transformed: int = 0
    worst_stress_relative: float = 0.0
    worst_stress_at: tuple = ()
    worst_state_relative: float = 0.0
    worst_state_at: tuple = ()
    #: Components too small a fraction of the response to compare, counted
    #: rather than silently averaged away.
    unresolved_components: int = 0
    #: Components that were large enough to compare. Agreement requires at
    #: least one: two builds that both computed nothing compare equal, and
    #: that is not evidence that either reproduced a model.
    resolved_components: int = 0
    #: Values that were not finite. A NaN makes every comparison against it
    #: False, so a running maximum never moves and the failure reads as a
    #: perfect match -- which is how a transform that destroyed the stress
    #: entirely scored agreement at a worst difference of 0.0.
    non_finite_components: int = 0
    agrees: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "increments": self.increments,
            "indistinguishable_components": self.indistinguishable_components,
            "records_original": self.records_original,
            "records_transformed": self.records_transformed,
            "worst_stress_relative": self.worst_stress_relative,
            "worst_stress_at": list(self.worst_stress_at),
            "worst_state_relative": self.worst_state_relative,
            "worst_state_at": list(self.worst_state_at),
            "unresolved_components": self.unresolved_components,
            "resolved_components": self.resolved_components,
            "non_finite_components": self.non_finite_components,
            "agrees": self.agrees,
            "reason": self.reason,
        }


#: The absolute floor, as a fraction of the largest value the field reaches
#: over the whole run. See the note at its use for why it is 1e-12.
ABSOLUTE_FLOOR_FRACTION = 1e-12


def compare_primal(
    original: Sequence[dict],
    transformed: Sequence[dict],
    *,
    tolerance: float = 1e-10,
    near_zero_fraction: float = 1e-8,
) -> PrimalComparison:
    """Stress and state histories, compared where a comparison means something.

    A component that is a vanishing fraction of the response holds each build's
    rounding and nothing else; two such values differ by 100% without that
    being a disagreement about the model. Those are counted as unresolved, not
    scored -- and never counted as agreement either.

    Three things this refuses to call agreement, each of which it once did:

    **A value that is not finite.** Every comparison against NaN is False, so
    the running maximum never moves and the row reads as an exact match. A
    transformed build returning NaN for all six stress components scored
    AGREED at a worst relative difference of 0.0.

    **A response that never moved.** Two all-zero histories compare equal at
    every component, which says only that neither build computed anything.
    Agreement now requires at least one component large enough to resolve.

    **Histories of different length.** These were zipped to the shorter one, so
    a build whose probe wrote one record out of twenty was compared over that
    record alone and reported as agreeing over the whole history.
    """
    result = PrimalComparison()
    result.records_original = len(original)
    result.records_transformed = len(transformed)
    if not original or not transformed:
        result.reason = "no records to compare"
        return result
    if result.records_original != result.records_transformed:
        result.reason = (
            f"the builds produced different histories: "
            f"{result.records_original} records from the original and "
            f"{result.records_transformed} from the transformed build. "
            f"Comparing them over the shorter one would report agreement "
            f"about increments one of them never reached")
        return result

    paired = list(zip(original, transformed))
    result.increments = len(paired)

    # One scale per field, over every increment of both builds: what a
    # "vanishing fraction of the response" means is a property of the run, not
    # of whichever increment a component happens to sit in.
    scales: dict[str, float] = {}
    for field_name in ("STRESS", "STATEV"):
        largest = 0.0
        for record in list(original) + list(transformed):
            for value in (record.get(field_name) or ()):
                if math.isfinite(value):
                    largest = max(largest, abs(value))
        scales[field_name] = largest

    for index, (left, right) in enumerate(paired, start=1):
        for field_name, attribute in (("STRESS", "stress"), ("STATEV", "state")):
            a, b = left.get(field_name) or [], right.get(field_name) or []
            if len(a) != len(b):
                result.reason = (
                    f"{field_name} has {len(a)} components in one build and "
                    f"{len(b)} in the other at increment {index}")
                return result
            # The scale is the largest value this field reaches over the WHOLE
            # history, not within this one increment. Per-increment scaling
            # makes the first increment -- where every component is still tiny
            # -- judge a component against its own neighbours rather than
            # against the response the model eventually produces. Measured:
            # UMAT_Tissue_2d_plane_strain was recorded as disagreeing by
            # 9.617e-09, entirely from a component of 6.35e-08 at increment 1,
            # in a run whose stresses reach 4.668. Against the history's own
            # scale the two builds agree to 3.806e-16. The component carried no
            # information and decided the verdict.
            response = scales.get(field_name, 0.0)
            for component, (x, y) in enumerate(zip(a, b), start=1):
                # Checked before anything else: a non-finite value poisons
                # every comparison it takes part in, silently.
                if not (math.isfinite(x) and math.isfinite(y)):
                    result.non_finite_components += 1
                    setattr(result, f"worst_{attribute}_relative", math.inf)
                    setattr(result, f"worst_{attribute}_at",
                            (index, component, x, y))
                    continue
                scale = max(abs(x), abs(y))
                if not scale:
                    continue
                if response and scale <= near_zero_fraction * response:
                    result.unresolved_components += 1
                    continue
                result.resolved_components += 1
                # Absolute floor beside the relative test, both stated.
                #
                # A component at a fraction f of the run's response has been
                # computed through arithmetic scaled to that response, so its
                # OWN relative precision is about eps/f -- for f = 1e-8 that is
                # 2e-8, and asking it to agree to 1e-10 asks for a hundred
                # times more precision than the number has. The floor says
                # what "the same" means in absolute terms: a difference below
                # this fraction of the response is not distinguishable as
                # physics, whichever component it lands on.
                #
                # 1e-12 of the response is roughly 4e4 times double epsilon --
                # loose enough to cover rounding accumulated through an
                # increment, and still a hundred times TIGHTER than the 1e-10
                # relative tolerance applied to a full-scale component. It
                # cannot rescue a real disagreement: From-3D-to-3D-Petal
                # differs by 1.29e-02 on stresses of 4e+06, against a floor of
                # 4e-06, and still fails.
                # Bounded by the caller's own tolerance, so the floor can
                # only ever forgive a difference the relative test would also
                # have forgiven on a full-scale component. It exists to stop
                # a SMALL component being held to more precision than it has,
                # never to relax the standard the caller asked for.
                difference = abs(x - y)
                floor = min(ABSOLUTE_FLOOR_FRACTION, tolerance) * response
                if response and difference <= floor:
                    result.indistinguishable_components += 1
                    continue
                relative = difference / scale
                worst = getattr(result, f"worst_{attribute}_relative")
                if relative > worst:
                    setattr(result, f"worst_{attribute}_relative", relative)
                    setattr(result, f"worst_{attribute}_at",
                            (index, component, x, y))

    if result.non_finite_components:
        result.reason = (
            f"{result.non_finite_components} compared values are not finite, "
            f"so nothing about this pair is established: a comparison against "
            f"NaN is False and leaves the worst difference reading as zero")
        return result
    if not result.resolved_components:
        result.reason = (
            f"no resolvable response: nothing to compare. "
            f"{result.unresolved_components} components sit below "
            f"{near_zero_fraction:.0e} of the response and the rest are zero, "
            f"so agreement here would only say that neither build computed "
            f"anything")
        return result

    result.agrees = (result.worst_stress_relative <= tolerance
                     and result.worst_state_relative <= tolerance)
    if not result.agrees:
        result.reason = (
            f"worst stress difference {result.worst_stress_relative:.3e}, "
            f"worst state difference {result.worst_state_relative:.3e}, "
            f"against a tolerance of {tolerance:.0e}")
    return result


@dataclass
class SweepPoint:
    """One step size, and what the centred difference gave at it."""

    step: float
    absolute: float
    relative: float
    frobenius: float
    columns: tuple = ()


@dataclass
class TangentComparison:
    """An OTI tangent against centred differences, over a range of steps."""

    increment: int = 0
    point: int = 1
    sweep: tuple[SweepPoint, ...] = ()
    best: Optional[SweepPoint] = None
    #: The steps whose Frobenius error is within an order of magnitude of the
    #: best. A finite difference that is only good at one step is not
    #: converged; a plateau is what convergence looks like.
    stable_range: tuple[float, float] = (0.0, 0.0)
    near_zero_entries: int = 0
    #: Entries that were not finite, in the tangent or in a difference. A
    #: sweep point holding one cannot be the step a reader is pointed at.
    non_finite_entries: int = 0
    #: Step sizes whose reconstructed matrix was identically zero. A centred
    #: difference of zero is not a measurement of the tangent: it says the
    #: perturbation moved nothing. Scored as a difference it yields a relative
    #: error of exactly 1.0 at every step -- which reads as "the tangent is
    #: 100%% wrong" when the truth is that nothing was measured at all.
    #: Fourteen rows of one batch carried exactly this signature, with the
    #: absolute error bit-identical from a step of 1e-3 to one of 1e-8.
    zero_difference_steps: int = 0
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "increment": self.increment,
            "point": self.point,
            "sweep": [{"step": p.step, "absolute": p.absolute,
                       "relative": p.relative, "frobenius": p.frobenius}
                      for p in self.sweep],
            "best_step": self.best.step if self.best else None,
            "best_frobenius": self.best.frobenius if self.best else None,
            "best_relative": self.best.relative if self.best else None,
            "stable_range": list(self.stable_range),
            "near_zero_entries": self.near_zero_entries,
            "non_finite_entries": self.non_finite_entries,
            "zero_difference_steps": self.zero_difference_steps,
            "notes": self.notes,
        }


def _frobenius(values: Iterable[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def compare_tangent(
    oti: Sequence[Sequence[float]],
    differences: dict[float, list[list[float]]],
    *,
    near_zero_fraction: float = 1e-8,
) -> TangentComparison:
    """Score the OTI tangent against a centred difference at each step size.

    ``differences`` maps a step to the reconstructed matrix. A component whose
    magnitude is a vanishing fraction of the largest entry is scored against
    that largest entry rather than against itself, and counted -- dividing a
    rounding residue by another rounding residue produces a relative error of
    order one that says nothing.

    A step whose matrix holds a value that is not finite is scored and kept in
    the sweep, but is excluded from the choice of best step and from the stable
    range. Otherwise it wins: every comparison against NaN is False, so its
    error reads as zero and the reader is pointed at the one step where the
    difference failed.
    """
    comparison = TangentComparison()
    if not oti or not differences:
        comparison.notes = "nothing to compare"
        return comparison

    finite_oti = [value for row in oti for value in row if math.isfinite(value)]
    comparison.non_finite_entries = sum(
        1 for row in oti for value in row if not math.isfinite(value))
    scale = max((abs(value) for value in finite_oti), default=0.0)
    floor = near_zero_fraction * scale
    comparison.near_zero_entries = sum(
        1 for value in finite_oti if abs(value) <= floor)

    points: list[SweepPoint] = []
    usable: list[SweepPoint] = []
    for step in sorted(differences, reverse=True):
        approximation = differences[step]
        # A reconstructed matrix that is identically zero is not a measurement
        # of the tangent. It says the perturbation moved nothing -- the
        # forward and backward replays returned the same stress -- so there is
        # no difference to compare the OTI value against. Scored as one, it
        # gives a relative error of exactly 1.0 at every step size, which
        # reads as "the tangent is 100% wrong" when nothing was measured at
        # all. Counted and excluded from the sweep, so the verdict says the
        # difference produced nothing rather than accusing the transform.
        if all(not value for row in approximation for value in row):
            comparison.zero_difference_steps += 1
            continue
        absolute = relative = 0.0
        residuals: list[float] = []
        non_finite_here = 0
        for i, row in enumerate(oti):
            for j, exact in enumerate(row):
                if i >= len(approximation) or j >= len(approximation[i]):
                    continue
                other = approximation[i][j]
                if not (math.isfinite(exact) and math.isfinite(other)):
                    non_finite_here += 1
                    absolute = relative = math.inf
                    continue
                delta = abs(exact - other)
                residuals.append(delta)
                absolute = max(absolute, delta)
                # A vanishing entry is scored against the size of the matrix,
                # not against itself: dividing one rounding residue by another
                # gives an error of order one that is about neither.
                denominator = abs(exact) if abs(exact) > floor else scale
                relative = max(relative, delta / denominator) if denominator else relative
        frobenius = math.inf if non_finite_here else _frobenius(residuals)
        point = SweepPoint(step, absolute, relative, frobenius)
        points.append(point)
        comparison.non_finite_entries += non_finite_here
        if not non_finite_here:
            usable.append(point)

    comparison.sweep = tuple(points)
    if not usable:
        comparison.notes = (
            f"every step produced a value that is not finite "
            f"({comparison.non_finite_entries} entries), so no step size "
            f"establishes anything about this tangent")
        return comparison

    comparison.best = min(usable, key=lambda p: p.frobenius)
    within = [p.step for p in usable
              if comparison.best.frobenius and
              p.frobenius <= 10.0 * comparison.best.frobenius]
    if within:
        comparison.stable_range = (min(within), max(within))
    if comparison.non_finite_entries:
        comparison.notes = (
            f"{comparison.non_finite_entries} entries were not finite and were "
            f"excluded from the choice of step; the sweep still reports them")
    return comparison
