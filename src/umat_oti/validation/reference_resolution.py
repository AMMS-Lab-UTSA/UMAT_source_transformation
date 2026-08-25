"""How well a centred-difference reference determines a value, measured.

``fd_noise_floor`` models only cancellation: ``eps*|f|/(2h)``. A centred
difference also carries truncation error, ``O(h^2 f''')``, and for a stiff model
that term dominates at every step where cancellation is still small. Judging a
comparison against the cancellation term alone therefore overstates how well the
reference is determined, and reports a disagreement the reference cannot
actually adjudicate.

The resolution is measured here instead of modelled, and measured *without*
reference to the value being checked. Evaluating the same derivative over a
ladder of step sizes gives a curve that falls as ``h^2`` while truncation
dominates and rises as ``1/h`` once cancellation takes over. The closest two
consecutive points approach each other is how tightly the method pins the value
down; nothing outside the finite-difference family enters that estimate, so
using it to adjudicate an OTI value is not circular.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from umat_oti.validation.parameter_sensitivity_validation import centered_fd

__all__ = ["ResolutionLadder", "measure_reference_resolution",
           "select_reference_step", "DEFAULT_LADDER"]

#: Relative step sizes spanning truncation-dominated to cancellation-dominated.
DEFAULT_LADDER = (1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7)


@dataclass
class ResolutionLadder:
    """One parameter's finite-difference convergence evidence."""

    props_index: int
    array: str
    steps: tuple[float, ...]
    values: dict[tuple[int, int], tuple[float, ...]] = field(default_factory=dict)

    def window(self, increment: int, component: int,
               size: int = 3) -> Optional[tuple[int, int]]:
        """Index range of the flattest ``size``-point stretch of the curve.

        The ends of the ladder are dominated by truncation at large steps and by
        cancellation at small ones. The flattest stretch is where the method is
        behaving best, and it is chosen by spread rather than by picking a step
        in advance.
        """
        series = self.values.get((increment, component))
        if not series or len(series) < 2:
            return None
        size = min(size, len(series))
        best, best_spread = 0, None
        for start in range(len(series) - size + 1):
            chunk = series[start:start + size]
            spread = max(chunk) - min(chunk)
            if best_spread is None or spread < best_spread:
                best, best_spread = start, spread
        return best, best + size

    def resolution(self, increment: int, component: int) -> Optional[float]:
        """How far apart the method's own answers are where it behaves best.

        A single pair of consecutive steps can coincide by accident, reporting a
        resolution of zero and turning a reference that cannot adjudicate into
        one that appears infinitely precise. The spread of a short window does
        not have that failure mode.
        """
        bounds = self.window(increment, component)
        if bounds is None:
            return None
        series = self.values[(increment, component)][bounds[0]:bounds[1]]
        return max(series) - min(series)

    def envelope(self, increment: int, component: int) -> Optional[tuple[float, float]]:
        """Range of values the method produces over its flattest window."""
        bounds = self.window(increment, component)
        if bounds is None:
            return None
        series = self.values[(increment, component)][bounds[0]:bounds[1]]
        return min(series), max(series)

    def brackets(self, increment: int, component: int, value: float) -> Optional[bool]:
        """Whether some legitimate step reproduces ``value``.

        This is the criterion that needs no tolerance at all: if the reference's
        own answers straddle the value being checked, the reference cannot call
        that value wrong. Nothing from outside the finite-difference family
        enters the decision.
        """
        span = self.envelope(increment, component)
        if span is None:
            return None
        return span[0] <= value <= span[1]

    def best_estimate(self, increment: int, component: int) -> Optional[float]:
        """The value at the centre of the flattest window."""
        bounds = self.window(increment, component)
        if bounds is None:
            return None
        series = self.values[(increment, component)][bounds[0]:bounds[1]]
        return series[len(series) // 2]

    def as_dict(self, increment: int, component: int) -> dict:
        series = self.values.get((increment, component))
        return {
            "props_index": self.props_index,
            "array": self.array,
            "relative_steps": list(self.steps),
            "values": list(series) if series else [],
            "resolution": self.resolution(increment, component),
            "envelope": list(self.envelope(increment, component) or ()),
            "best_estimate": self.best_estimate(increment, component),
            "method": ("centred differences over a step ladder; the resolution is "
                       "the smallest gap between consecutive steps and uses no "
                       "value from outside the finite-difference family"),
        }


def measure_reference_resolution(
    executable: Path,
    props: Sequence[float],
    path: Sequence[Sequence[float]],
    *,
    ntens: int,
    nstatv: int,
    props_index: int,
    array: str = "DSIGMA_DP",
    ladder: Sequence[float] = DEFAULT_LADDER,
) -> ResolutionLadder:
    """Evaluate one parameter's derivative across a ladder of step sizes."""
    key = "dsigma" if array == "DSIGMA_DP" else "dstatev"
    steps: list[float] = []
    per_step: list[list[list[float]]] = []
    for relative_step in ladder:
        try:
            reference = centered_fd(
                executable, props, path, ntens=ntens, nstatv=nstatv,
                props_indices=[props_index], rel_step=relative_step)
        except RuntimeError:
            # A step that drives the model out of its valid range contributes
            # nothing; it must not silently become a zero.
            continue
        steps.append(relative_step)
        per_step.append(reference[props_index][key])

    result = ResolutionLadder(props_index=props_index, array=array,
                              steps=tuple(steps))
    if not per_step:
        return result
    for increment in range(1, len(per_step[0]) + 1):
        for component in range(1, len(per_step[0][increment - 1]) + 1):
            result.values[(increment, component)] = tuple(
                table[increment - 1][component - 1] for table in per_step)
    return result


def select_reference_step(ladder: ResolutionLadder,
                          *, minimum_points: int = 3) -> Optional[float]:
    """Choose the step at which the centred difference is best converged.

    A fixed step is a guess about a model's third derivative, and for a stiff
    one it is usually a poor guess. m6_fcc showed this exactly: at the default
    relative step of 1e-4 its state sensitivities carried 1.37e-6 of truncation
    error, enough to fail a 1e-6 comparison, while the same derivative agreed
    with the OTI value to 2.6e-10 once the step was small enough. Nothing was
    wrong with the derivative; the reference was being read at the wrong step.

    The step is chosen by the method's own self-consistency: as the step falls,
    consecutive answers converge as ``h^2`` until cancellation takes over and
    they diverge again. The turning point is where the reference is most
    trustworthy, and finding it uses no value from outside the
    finite-difference family.

    Returns ``None`` when the ladder is too short to show a turning point,
    which leaves the caller to fall back to a declared default rather than
    inventing one.
    """
    if len(ladder.steps) < minimum_points:
        return None
    # Aggregate over every (increment, component) so one step serves the whole
    # parameter: a per-entry step would make the reference inconsistent across
    # the array it is supposed to check.
    totals: list[float] = []
    for index in range(len(ladder.steps) - 1):
        total = 0.0
        counted = 0
        for series in ladder.values.values():
            if len(series) <= index + 1:
                continue
            scale = max(abs(series[index]), abs(series[index + 1]))
            if scale == 0.0:
                continue
            total += abs(series[index + 1] - series[index]) / scale
            counted += 1
        totals.append(total / counted if counted else float("inf"))
    if not totals or all(value == float("inf") for value in totals):
        return None
    best = min(range(len(totals)), key=totals.__getitem__)
    return ladder.steps[best + 1]


def converged_value(ladder: ResolutionLadder, increment: int,
                    component: int) -> Optional[tuple[float, float, float]]:
    """Best-converged reference value, the step it came from, and its uncertainty.

    Each entry of a derivative array is an independent scalar and they reach
    their turning points at different steps, so the choice is made per entry.

    The step is chosen as the middle of the flattest short window of the ladder.
    Two alternatives were tried and both misbehave: the smallest consecutive gap
    can land deep in the cancellation region where two steps coincide by chance,
    and breaking at the first non-decreasing gap stops on an early wobble and
    returns a step far too coarse -- that is what left one m6_fcc row judged at
    1e-3 with a 3e-3 relative error. A window is insensitive to both.

    The remaining gap at that point is the method's own residual uncertainty. It
    is returned alongside the value because a difference smaller than it is
    something the reference cannot adjudicate, which is a distinct outcome from
    agreement and from disagreement.
    """
    bounds = ladder.window(increment, component)
    if bounds is None:
        return None
    series = ladder.values[(increment, component)]
    chunk = series[bounds[0]:bounds[1]]
    spread = max(chunk) - min(chunk)
    middle = bounds[0] + len(chunk) // 2
    return series[middle], ladder.steps[middle], spread
