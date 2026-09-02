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
    worst_stress_relative: float = 0.0
    worst_stress_at: tuple = ()
    worst_state_relative: float = 0.0
    worst_state_at: tuple = ()
    #: Components too small a fraction of the response to compare, counted
    #: rather than silently averaged away.
    unresolved_components: int = 0
    agrees: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "increments": self.increments,
            "worst_stress_relative": self.worst_stress_relative,
            "worst_stress_at": list(self.worst_stress_at),
            "worst_state_relative": self.worst_state_relative,
            "worst_state_at": list(self.worst_state_at),
            "unresolved_components": self.unresolved_components,
            "agrees": self.agrees,
            "reason": self.reason,
        }


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
    """
    result = PrimalComparison()
    paired = list(zip(original, transformed))
    result.increments = len(paired)
    if not paired:
        result.reason = "no records to compare"
        return result

    for index, (left, right) in enumerate(paired, start=1):
        for field_name, attribute in (("STRESS", "stress"), ("STATEV", "state")):
            a, b = left.get(field_name) or [], right.get(field_name) or []
            if len(a) != len(b):
                result.reason = (
                    f"{field_name} has {len(a)} components in one build and "
                    f"{len(b)} in the other at increment {index}")
                return result
            response = max((abs(value) for value in a), default=0.0)
            for component, (x, y) in enumerate(zip(a, b), start=1):
                scale = max(abs(x), abs(y))
                if not scale:
                    continue
                if response and scale <= near_zero_fraction * response:
                    result.unresolved_components += 1
                    continue
                relative = abs(x - y) / scale
                worst = getattr(result, f"worst_{attribute}_relative")
                if relative > worst:
                    setattr(result, f"worst_{attribute}_relative", relative)
                    setattr(result, f"worst_{attribute}_at",
                            (index, component, x, y))
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
    """
    comparison = TangentComparison()
    if not oti or not differences:
        comparison.notes = "nothing to compare"
        return comparison

    scale = max((abs(value) for row in oti for value in row), default=0.0)
    floor = near_zero_fraction * scale
    comparison.near_zero_entries = sum(
        1 for row in oti for value in row if abs(value) <= floor)

    points: list[SweepPoint] = []
    for step in sorted(differences, reverse=True):
        approximation = differences[step]
        absolute = relative = 0.0
        residuals: list[float] = []
        for i, row in enumerate(oti):
            for j, exact in enumerate(row):
                if i >= len(approximation) or j >= len(approximation[i]):
                    continue
                delta = abs(exact - approximation[i][j])
                residuals.append(delta)
                absolute = max(absolute, delta)
                # A vanishing entry is scored against the size of the matrix,
                # not against itself: dividing one rounding residue by another
                # gives an error of order one that is about neither.
                denominator = abs(exact) if abs(exact) > floor else scale
                relative = max(relative, delta / denominator) if denominator else relative
        points.append(SweepPoint(step, absolute, relative, _frobenius(residuals)))

    comparison.sweep = tuple(points)
    comparison.best = min(points, key=lambda p: p.frobenius)
    within = [p.step for p in points
              if comparison.best.frobenius and
              p.frobenius <= 10.0 * comparison.best.frobenius]
    if within:
        comparison.stable_range = (min(within), max(within))
    return comparison
