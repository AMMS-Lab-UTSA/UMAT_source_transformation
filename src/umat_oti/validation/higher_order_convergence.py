"""Step-size convergence study and reference-quality classification for
higher-order derivative verification.

A single finite-difference (FD) step cannot establish that an FD value is a
trustworthy independent reference. An order-``n`` FD estimate carries a
truncation error that falls with the step ``h`` and a cancellation error that
*grows* as ``h`` shrinks -- roughly ``eps * |f| / h**n`` in the working
precision. For ``n = 4`` in double precision that floor is severe: at
``h = 4e-5`` and ``|f| ~ 1e5`` it is already ``~1e6``. An absolute tolerance
large enough to absorb that floor will absorb almost any wrong answer too, so
"error below tolerance" proves nothing on its own.

This module replaces the single-step comparison with a step sweep and asks the
only question that actually matters:

    does the FD estimate sit on a plateau -- a run of consecutive step sizes
    that agree with each other -- and is the OTI value inside it?

A plateau means truncation has decayed but cancellation has not yet taken over,
so the FD value is a genuine estimate of the derivative rather than an artifact
of one lucky step. Every row is classified by what the reference can actually
support:

``resolved``
    At least ``PLATEAU_MIN_POINTS`` consecutive steps agree to within
    ``RESOLVED_REL_SPREAD``. The plateau value is a real reference and the
    OTI value is checked against it with the plateau's own spread as the
    uncertainty.

``expected_zero_independently_supported``
    The derivative is zero, established *without* consulting the OTI result --
    see `structural invariance`_ below and, where available, an independent
    high-precision evaluation.

``cancellation_limited``
    The estimate is stable only to within ``CANCELLATION_REL_SPREAD``. The
    reference constrains the magnitude but cannot verify the value to a useful
    relative accuracy.

``reference_unresolved``
    No usable plateau. The reference says nothing about this row.

Only the first two count as verification support. ``cancellation_limited`` and
``reference_unresolved`` rows are reported, never silently passed, and never
promoted by being smaller than a generous absolute tolerance.

.. _structural invariance:

**Independent zero support.** A zero derivative must not be justified by "OTI
returned 0". Two independent supports are used here:

*Structural invariance* -- if the response component is bit-identical across
every stencil node at every step, it does not depend on the perturbed strain
components at all, so every derivative in those directions is exactly zero.
This is a property of the model source, established by running it, and is
available even for a double-precision compiled reference.

*Exact local affineness* -- if the second difference
``f(x+A) + f(x-A) - 2 f(x)`` and the mixed difference
``f(x+A_i+A_j) - f(x+A_i) - f(x+A_j) + f(x)`` sit at the arithmetic's own
rounding level at several amplitudes ``A`` spanning the stencil the plateau
uses, the response is affine in those directions over that neighbourhood, so
every derivative of order two and above vanishes there. This test is well
conditioned exactly where finite differencing is not: it uses *large*
amplitudes, so a real second derivative ``D`` would show up as ``D*A**2`` --
at ``A ~ 1e-4`` and ``D ~ 1e7`` that is ``~1e-1``, thirteen orders of magnitude
clear of a ``~1e-14`` rounding floor. There is no tuned tolerance in that gap.
It is what rescues the elastic branch of a double-precision reference, where no
higher-precision recomputation is available.

*High-precision agreement* -- where the reference can be evaluated in extended
precision (the controlled J2 model runs in ``mpmath``), the derivative is
recomputed with far more digits and a far smaller step, where cancellation is
negligible. A value that is zero there is zero.

**Scale-aware normalization.** Derivative magnitudes grow by roughly
``1 / strain_scale`` per order, so a threshold in raw units means something
different at each order. Magnitudes are normalized to

    ``D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale``

which is dimensionless and O(1) when the response varies over ``strain_scale``.
Both scales are recorded in the output with their physical units.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# Step multipliers applied to each model's previously published step, spanning
# two decades either side of it so both the truncation-dominated and the
# cancellation-dominated regimes appear in the sweep.
STEP_FACTORS: tuple[float, ...] = (16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625)

# A plateau needs at least this many consecutive steps agreeing.
PLATEAU_MIN_POINTS = 3
# Relative spread across the plateau window for the reference to count as resolved.
RESOLVED_REL_SPREAD = 1.0e-3
# Spread up to which the reference still bounds the magnitude but cannot verify it.
CANCELLATION_REL_SPREAD = 1.0e-1
# Normalized magnitude at or below which a derivative is treated as "at zero".
ZERO_NORMALIZED_THRESHOLD = 1.0e-9
# Floor on the OTI/reference agreement tolerance, relative to the reference.
AGREEMENT_REL_FLOOR = 1.0e-6
# The plateau spread is the reference's own uncertainty; allow this multiple of it.
AGREEMENT_UNCERTAINTY_MULTIPLE = 4.0

RESOLVED = "resolved"
EXPECTED_ZERO = "expected_zero_independently_supported"
CANCELLATION_LIMITED = "cancellation_limited"
UNRESOLVED = "reference_unresolved"

#: Classifications whose reference is strong enough to support a verification claim.
SUPPORTING_CLASSIFICATIONS = frozenset({RESOLVED, EXPECTED_ZERO})

CLASSIFICATIONS = (RESOLVED, EXPECTED_ZERO, CANCELLATION_LIMITED, UNRESOLVED)


@dataclass(frozen=True)
class NormalizationScale:
    """Physical scales used to make cross-order magnitude thresholds meaningful."""

    stress_scale: float
    strain_scale: float
    stress_units: str = "MPa"
    strain_units: str = "dimensionless"
    stress_scale_meaning: str = ""
    strain_scale_meaning: str = ""

    def normalize(self, value: float, order: int) -> float:
        """Map a raw order-``n`` derivative to its dimensionless magnitude."""
        return value * (self.strain_scale ** order) / self.stress_scale

    def as_dict(self) -> dict[str, Any]:
        return {
            "stress_scale": self.stress_scale,
            "stress_units": self.stress_units,
            "stress_scale_meaning": self.stress_scale_meaning,
            "strain_scale": self.strain_scale,
            "strain_units": self.strain_units,
            "strain_scale_meaning": self.strain_scale_meaning,
            "normalized_quantity": (
                "D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale"
            ),
            "normalized_units": "dimensionless",
        }


@dataclass
class SweepPoint:
    """One finite-difference evaluation of one row at one step size."""

    step: float
    step_factor: float
    value: float
    invariant: bool = False


@dataclass
class Plateau:
    """The most stable run of consecutive steps found for a row."""

    value: float
    absolute_uncertainty: float
    relative_uncertainty: float
    points: int
    step_low: float
    step_high: float
    window_start: int = 0
    all_windows_rejected: bool = False


@dataclass
class RowInputs:
    """Everything needed to classify one (increment, directions, component) row."""

    increment: int
    branch: str
    stress_component: int
    order: int
    directions: tuple[int, ...]
    direction_pattern: str
    recovery_factor: float
    oti_value: float
    sweep: list[SweepPoint]
    structurally_invariant: bool
    affine_in_directions: bool = False
    affine_amplitudes: tuple[float, ...] = ()
    affine_margin: float | None = None
    high_precision_value: float | None = None
    high_precision_step: float | None = None
    high_precision_digits: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def direction_pattern(directions: Sequence[int]) -> str:
    """``repeated`` when every seed direction is the same, else ``mixed``."""
    return "repeated" if len(set(directions)) == 1 else "mixed"


def find_plateau(sweep: Sequence[SweepPoint]) -> Plateau:
    """Longest run of >= PLATEAU_MIN_POINTS steps agreeing to RESOLVED_REL_SPREAD.

    Falls back to the minimum-spread window of the minimum length so that a row
    without a plateau still reports how unstable it actually is.
    """
    values = [point.value for point in sweep]
    n = len(values)
    if n < PLATEAU_MIN_POINTS:
        raise ValueError(f"need at least {PLATEAU_MIN_POINTS} sweep points, got {n}")

    def window_stats(start: int, width: int) -> tuple[float, float, float]:
        window = values[start : start + width]
        low, high = min(window), max(window)
        centre = sorted(window)[width // 2]
        half_spread = (high - low) / 2.0
        denominator = max(abs(centre), 1.0e-300)
        return centre, half_spread, (high - low) / denominator

    # Prefer the longest window that actually meets the resolved criterion.
    for width in range(n, PLATEAU_MIN_POINTS - 1, -1):
        for start in range(0, n - width + 1):
            centre, half_spread, relative = window_stats(start, width)
            if relative <= RESOLVED_REL_SPREAD:
                return Plateau(
                    value=centre,
                    absolute_uncertainty=half_spread,
                    relative_uncertainty=relative,
                    points=width,
                    step_low=min(sweep[start + width - 1].step, sweep[start].step),
                    step_high=max(sweep[start + width - 1].step, sweep[start].step),
                    window_start=start,
                )

    # No resolved plateau: report the steadiest short window we did find.
    best: tuple[float, int, float, float] | None = None
    for start in range(0, n - PLATEAU_MIN_POINTS + 1):
        centre, half_spread, relative = window_stats(start, PLATEAU_MIN_POINTS)
        if best is None or relative < best[0]:
            best = (relative, start, centre, half_spread)
    assert best is not None
    relative, start, centre, half_spread = best
    return Plateau(
        value=centre,
        absolute_uncertainty=half_spread,
        relative_uncertainty=relative,
        points=PLATEAU_MIN_POINTS,
        step_low=min(sweep[start + PLATEAU_MIN_POINTS - 1].step, sweep[start].step),
        step_high=max(sweep[start + PLATEAU_MIN_POINTS - 1].step, sweep[start].step),
        window_start=start,
        all_windows_rejected=True,
    )


def classify_row(row: RowInputs, scale: NormalizationScale) -> dict[str, Any]:
    """Classify one row by what its independent reference can actually support.

    Returns a record carrying the raw OTI value, every swept FD value, the
    plateau, the classification and its justification. ``relative_error`` is
    populated only when the reference magnitude is resolved (requirement: do not
    quote a relative error against a reference that is itself noise).
    """
    plateau = find_plateau(row.sweep)
    normalized_plateau = abs(scale.normalize(plateau.value, row.order))
    normalized_oti = abs(scale.normalize(row.oti_value, row.order))

    zero_supports: list[str] = []
    if row.structurally_invariant:
        zero_supports.append(
            "structural invariance: the response component is bit-identical at every "
            "stencil node and every step, so it does not depend on the perturbed "
            "strain components and all derivatives in these directions are exactly zero"
        )
    if row.affine_in_directions:
        zero_supports.append(
            "exact local affineness: second and mixed differences of the independent "
            "reference stay at the arithmetic rounding floor (largest observed "
            "residual %.3g of that floor) at amplitudes %s spanning the plateau "
            "stencil, so the response is affine in these directions and every "
            "derivative of order two or above vanishes"
            % (row.affine_margin if row.affine_margin is not None else float("nan"),
               ", ".join("%.3e" % a for a in row.affine_amplitudes))
        )
    if row.high_precision_value is not None:
        normalized_hp = abs(scale.normalize(row.high_precision_value, row.order))
        if normalized_hp <= ZERO_NORMALIZED_THRESHOLD:
            zero_supports.append(
                "high-precision evaluation: recomputed at %d decimal digits with step "
                "%.3e, where cancellation is negligible, giving normalized magnitude "
                "%.3e" % (row.high_precision_digits or 0, row.high_precision_step or 0.0,
                          normalized_hp)
            )

    classification: str
    justification: str
    agreement_tolerance: float | None = None
    absolute_error: float | None = None
    relative_error: float | None = None
    reference_value: float | None = None
    agrees: bool | None = None

    if zero_supports and normalized_oti <= ZERO_NORMALIZED_THRESHOLD:
        classification = EXPECTED_ZERO
        reference_value = 0.0
        absolute_error = abs(row.oti_value)
        justification = (
            "Derivative is zero and independently supported without reference to the "
            "OTI result. " + " Also: ".join(zero_supports)
        )
    elif zero_supports and normalized_oti > ZERO_NORMALIZED_THRESHOLD:
        classification = UNRESOLVED
        reference_value = 0.0
        absolute_error = abs(row.oti_value)
        justification = (
            "Independent support says this derivative is exactly zero, but OTI "
            "returned normalized magnitude %.3e above the %.1e zero threshold. This "
            "is a genuine disagreement, not a reference-quality problem."
            % (normalized_oti, ZERO_NORMALIZED_THRESHOLD)
        )
    elif normalized_plateau <= ZERO_NORMALIZED_THRESHOLD:
        # The sweep collapses to zero but nothing independent supports that.
        classification = UNRESOLVED
        reference_value = plateau.value
        justification = (
            "The finite-difference sweep is at the zero threshold (normalized %.3e) "
            "but no independent structural or high-precision support establishes the "
            "derivative as zero, so the reference cannot verify this row."
            % normalized_plateau
        )
    elif plateau.relative_uncertainty <= RESOLVED_REL_SPREAD and not plateau.all_windows_rejected:
        classification = RESOLVED
        reference_value = plateau.value
        absolute_error = abs(row.oti_value - plateau.value)
        relative_error = absolute_error / abs(plateau.value)
        agreement_tolerance = max(
            AGREEMENT_UNCERTAINTY_MULTIPLE * plateau.absolute_uncertainty,
            AGREEMENT_REL_FLOOR * abs(plateau.value),
        )
        agrees = absolute_error <= agreement_tolerance
        justification = (
            "%d consecutive steps from %.3e to %.3e agree to %.2e relative; the "
            "plateau is a genuine independent estimate and its own spread sets the "
            "agreement tolerance."
            % (plateau.points, plateau.step_low, plateau.step_high,
               plateau.relative_uncertainty)
        )
    elif plateau.relative_uncertainty <= CANCELLATION_REL_SPREAD:
        classification = CANCELLATION_LIMITED
        reference_value = plateau.value
        absolute_error = abs(row.oti_value - plateau.value)
        justification = (
            "The steadiest %d-step window still spreads by %.2e relative, above the "
            "%.1e resolved threshold. Round-off cancellation dominates the order-%d "
            "reference at every step tried, so it bounds the magnitude but cannot "
            "verify the value."
            % (plateau.points, plateau.relative_uncertainty, RESOLVED_REL_SPREAD,
               row.order)
        )
    else:
        classification = UNRESOLVED
        reference_value = plateau.value
        absolute_error = abs(row.oti_value - plateau.value)
        justification = (
            "No window of %d consecutive steps agrees better than %.2e relative. The "
            "finite-difference reference does not resolve this derivative at all."
            % (PLATEAU_MIN_POINTS, plateau.relative_uncertainty)
        )

    if classification == EXPECTED_ZERO:
        agrees = True
    passed = classification in SUPPORTING_CLASSIFICATIONS and bool(agrees)

    return {
        "increment": row.increment,
        "branch": row.branch,
        "stress_component": row.stress_component,
        "order": row.order,
        "directions": "|".join(str(value) for value in row.directions),
        "direction_pattern": row.direction_pattern,
        "recovery_factor": row.recovery_factor,
        "oti_derivative": row.oti_value,
        "oti_normalized": scale.normalize(row.oti_value, row.order),
        "reference_value": reference_value,
        "reference_normalized": (
            None if reference_value is None else scale.normalize(reference_value, row.order)
        ),
        "reference_classification": classification,
        "reference_justification": justification,
        "plateau_points": plateau.points,
        "plateau_step_low": plateau.step_low,
        "plateau_step_high": plateau.step_high,
        "plateau_absolute_uncertainty": plateau.absolute_uncertainty,
        "plateau_relative_uncertainty": plateau.relative_uncertainty,
        "structurally_invariant": row.structurally_invariant,
        "affine_in_directions": row.affine_in_directions,
        "affine_residual_over_rounding_floor": row.affine_margin,
        "high_precision_value": row.high_precision_value,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "agreement_tolerance": agreement_tolerance,
        "agrees_with_reference": agrees,
        "supports_verification": passed,
        "sweep": [
            {
                "step": point.step,
                "step_factor": point.step_factor,
                "value": point.value,
                "normalized": scale.normalize(point.value, row.order),
                "invariant_across_stencil": point.invariant,
            }
            for point in row.sweep
        ],
        **row.extra,
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate classified rows into the counts a claim matrix can consume."""
    counts = {name: 0 for name in CLASSIFICATIONS}
    for row in rows:
        counts[row["reference_classification"]] += 1

    supporting = [row for row in rows if row["supports_verification"]]
    disagreeing = [
        row for row in rows
        if row["reference_classification"] in SUPPORTING_CLASSIFICATIONS
        and not row["supports_verification"]
    ]
    resolved_rel = [
        row["relative_error"] for row in rows
        if row["reference_classification"] == RESOLVED and row["relative_error"] is not None
    ]

    by_order: dict[int, dict[str, int]] = {}
    for row in rows:
        bucket = by_order.setdefault(row["order"], {name: 0 for name in CLASSIFICATIONS})
        bucket[row["reference_classification"]] += 1

    return {
        "rows": len(rows),
        "classification_counts": counts,
        "rows_supporting_verification": len(supporting),
        "rows_with_reference_but_disagreeing": len(disagreeing),
        "rows_without_usable_reference": counts[CANCELLATION_LIMITED] + counts[UNRESOLVED],
        "max_relative_error_on_resolved_rows": max(resolved_rel, default=None),
        "classification_counts_by_order": {
            str(order): value for order, value in sorted(by_order.items())
        },
        "verified": bool(rows) and not disagreeing and counts[UNRESOLVED] == 0,
    }


def sweep_steps(base_step: float) -> list[tuple[float, float]]:
    """(factor, step) pairs for the sweep, ordered from largest step to smallest."""
    return [(factor, base_step * factor) for factor in STEP_FACTORS]


def stencil_weights(derivative_order: int, step: float, nodes: Sequence[int],
                    mp_module: Any, digits: int = 60,
                    as_float: bool = True) -> tuple[Any, ...]:
    """Centred finite-difference weights for ``derivative_order`` on ``nodes``.

    Solves the Vandermonde system in extended precision so that the weights
    themselves never contribute to the cancellation being measured. Set
    ``as_float=False`` to keep them as extended-precision numbers, which is
    required when the reference model itself is evaluated in extended precision
    -- rounding the weights to double would reintroduce exactly the cancellation
    the extended-precision reference exists to avoid.
    """
    previous = mp_module.mp.dps
    mp_module.mp.dps = digits
    try:
        matrix = mp_module.matrix(
            [[mp_module.mpf(node) ** power for node in nodes] for power in range(len(nodes))]
        )
        rhs = mp_module.matrix([
            mp_module.mpf(math.factorial(derivative_order)) if power == derivative_order else 0
            for power in range(len(nodes))
        ])
        solved = mp_module.lu_solve(matrix, rhs)
        scaled = mp_module.mpf(str(step)) ** derivative_order
        weights = tuple(solved[index] / scaled for index in range(len(nodes)))
        return tuple(float(w) for w in weights) if as_float else weights
    finally:
        mp_module.mp.dps = previous
