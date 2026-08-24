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

    does the FD estimate sit on a plateau -- a run of consecutive *admissible*
    step sizes that agree with each other -- and is the OTI value inside it?

Three things decide whether a row counts.

**Branch admissibility.** These are elasto-plastic models: the response is only
piecewise smooth. A stencil whose nodes straddle a yield or unloading boundary
is differencing across a kink, so its value is not an estimate of the nominal
branch's derivative at all -- however stable it looks. Every step records the
nominal branch, the branch at each stencil node, and whether they agree. Steps
that cross a boundary are marked inadmissible with a reason and are excluded
from plateau detection entirely.

**Plateau.** Among admissible steps, at least ``PLATEAU_MIN_POINTS``
consecutive ones must agree to ``RESOLVED_REL_SPREAD``. A plateau means
truncation has decayed but cancellation has not yet taken over, so the FD value
is a genuine estimate rather than an artifact of one lucky step. The plateau's
own spread then sets the tolerance the OTI value is judged against.

**Zero support.** A derivative that is zero cannot be verified by a plateau --
there is nothing to plateau onto -- so it needs a separate argument, and that
argument must not come from the OTI result. Crucially it must also not come
from *sampled equality alone*: bit-identical responses at finitely many stencil
nodes show the response did not vary over the points that were tried, which is
empirical local invariance, not proof of exact structural independence.
Supports are therefore split.

*Strong* (sufficient on their own):

``high_precision``
    The reference re-evaluated in extended precision, where cancellation cannot
    manufacture a spurious zero, resolves the value as zero.
``analytic``
    A symbolic or closed-form derivation that the derivative vanishes.
``source_affine_branch`` / ``source_independent``
    A stated, citable fact about the model source -- the active branch is affine
    in the seeded directions, or the response component does not depend on them
    at all. Because such a fact is a property *of one branch*, it is accepted
    only when branch consistency has been verified at every stencil node of
    every admissible step; otherwise the cited branch is not the branch that was
    sampled.

*Weak* (never sufficient alone):

``empirical_stencil_invariance``
    The component was bit-identical across the stencil nodes that were sampled.
``empirical_affine_probe``
    Second and mixed differences sat at the arithmetic rounding floor at the
    probed amplitudes.

A row whose zero rests only on weak support is classified
``empirically_zero_over_stencil``. That is an honest description of what was
observed and it does **not** count as verification evidence.

Classifications, and whether they support a verification claim:

===========================================  =========
``resolved`` (and agreeing with OTI)         supports
``expected_zero_independently_supported``    supports
``empirically_zero_over_stencil``            does not
``cancellation_limited``                     does not
``reference_unresolved``                     does not
===========================================  =========

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
from typing import Any, Sequence

# Step multipliers applied to each model's previously published step, spanning
# two decades either side of it so both the truncation-dominated and the
# cancellation-dominated regimes appear in the sweep.
STEP_FACTORS: tuple[float, ...] = (16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625)

# A plateau needs at least this many consecutive admissible steps agreeing.
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
EMPIRICALLY_ZERO = "empirically_zero_over_stencil"
CANCELLATION_LIMITED = "cancellation_limited"
UNRESOLVED = "reference_unresolved"

#: Classifications whose reference is strong enough to support a verification claim.
SUPPORTING_CLASSIFICATIONS = frozenset({RESOLVED, EXPECTED_ZERO})

CLASSIFICATIONS = (
    RESOLVED, EXPECTED_ZERO, EMPIRICALLY_ZERO, CANCELLATION_LIMITED, UNRESOLVED,
)

#: Zero-support kinds that are sufficient on their own.
STRONG_ZERO_SUPPORTS = frozenset({
    "high_precision", "analytic", "source_affine_branch", "source_independent",
})
#: Zero-support kinds that describe sampling, not proof.
WEAK_ZERO_SUPPORTS = frozenset({
    "empirical_stencil_invariance", "empirical_affine_probe",
})
#: Source-level proofs are branch-local: they apply only where the branch held.
BRANCH_DEPENDENT_SUPPORTS = frozenset({"source_affine_branch", "source_independent"})


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


@dataclass(frozen=True)
class ZeroSupport:
    """One argument that a derivative is zero, and how much weight it carries."""

    kind: str
    detail: str

    @property
    def strong(self) -> bool:
        return self.kind in STRONG_ZERO_SUPPORTS

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "strong": self.strong, "detail": self.detail}


@dataclass
class SweepPoint:
    """One finite-difference evaluation of one row at one step size.

    ``admissible`` is False when the stencil left the nominal constitutive
    branch. Such a point differences across a kink and is excluded from plateau
    detection; ``rejection_reason`` records why.
    """

    step: float
    step_factor: float
    value: float
    invariant: bool = False
    nominal_branch: str | None = None
    node_branches: tuple[str, ...] = ()
    branch_consistent: bool = True
    #: Smallest distance to the branch surface over the stencil, when the model
    #: exposes one. ``None`` means the model provides no such measure.
    min_branch_margin: float | None = None
    min_branch_margin_unavailable_reason: str | None = None
    admissible: bool = True
    rejection_reason: str | None = None

    def as_dict(self, scale: NormalizationScale, order: int) -> dict[str, Any]:
        return {
            "step": self.step,
            "step_factor": self.step_factor,
            "value": self.value,
            "normalized": scale.normalize(self.value, order),
            "invariant_across_stencil": self.invariant,
            "nominal_branch": self.nominal_branch,
            "node_branches": list(self.node_branches),
            "branch_consistent": self.branch_consistent,
            "min_branch_margin": self.min_branch_margin,
            "min_branch_margin_unavailable_reason":
                self.min_branch_margin_unavailable_reason,
            "admissible": self.admissible,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class Plateau:
    """The most stable run of consecutive admissible steps found for a row."""

    value: float
    absolute_uncertainty: float
    relative_uncertainty: float
    points: int
    step_low: float
    step_high: float
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
    #: Empirical: component was bit-identical across the sampled stencil nodes.
    structurally_invariant: bool = False
    #: Empirical: second/mixed differences at the rounding floor over amplitudes.
    affine_in_directions: bool = False
    affine_amplitudes: tuple[float, ...] = ()
    affine_margin: float | None = None
    #: Strong: independent extended-precision evaluation of the same derivative.
    high_precision_value: float | None = None
    high_precision_step: float | None = None
    high_precision_digits: int | None = None
    #: Strong: a stated, citable source-level fact. Accepted only together with
    #: verified branch consistency, because it is a property of one branch.
    source_proof_kind: str | None = None
    source_proof_detail: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def direction_pattern(directions: Sequence[int]) -> str:
    """``repeated`` when every seed direction is the same, else ``mixed``."""
    return "repeated" if len(set(directions)) == 1 else "mixed"


def admissible_points(sweep: Sequence[SweepPoint]) -> list[SweepPoint]:
    """Steps whose whole stencil stayed on the nominal constitutive branch."""
    return [point for point in sweep if point.admissible]


def find_plateau(sweep: Sequence[SweepPoint]) -> Plateau | None:
    """Longest run of >= PLATEAU_MIN_POINTS admissible steps agreeing to spec.

    Only admissible steps count, and only *consecutive* ones: a run interrupted
    by a branch-crossing step is not a plateau, because the excluded step gives
    no reason to believe the two sides belong together.

    Returns ``None`` when there are not enough consecutive admissible steps to
    judge. Otherwise falls back to the minimum-spread window of the minimum
    length so a row without a plateau still reports how unstable it is.
    """
    runs: list[list[SweepPoint]] = []
    current: list[SweepPoint] = []
    for point in sweep:
        if point.admissible:
            current.append(point)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)

    usable = [run for run in runs if len(run) >= PLATEAU_MIN_POINTS]
    if not usable:
        return None

    def window_stats(values: Sequence[float]) -> tuple[float, float, float]:
        low, high = min(values), max(values)
        centre = sorted(values)[len(values) // 2]
        half_spread = (high - low) / 2.0
        denominator = max(abs(centre), 1.0e-300)
        return centre, half_spread, (high - low) / denominator

    widest = max(len(run) for run in usable)
    for width in range(widest, PLATEAU_MIN_POINTS - 1, -1):
        for run in usable:
            for start in range(0, len(run) - width + 1):
                window = run[start : start + width]
                centre, half_spread, relative = window_stats([p.value for p in window])
                if relative <= RESOLVED_REL_SPREAD:
                    steps = [p.step for p in window]
                    return Plateau(
                        value=centre,
                        absolute_uncertainty=half_spread,
                        relative_uncertainty=relative,
                        points=width,
                        step_low=min(steps),
                        step_high=max(steps),
                    )

    best: tuple[float, float, float, list[SweepPoint]] | None = None
    for run in usable:
        for start in range(0, len(run) - PLATEAU_MIN_POINTS + 1):
            window = run[start : start + PLATEAU_MIN_POINTS]
            centre, half_spread, relative = window_stats([p.value for p in window])
            if best is None or relative < best[0]:
                best = (relative, centre, half_spread, window)
    assert best is not None
    relative, centre, half_spread, window = best
    steps = [p.step for p in window]
    return Plateau(
        value=centre,
        absolute_uncertainty=half_spread,
        relative_uncertainty=relative,
        points=PLATEAU_MIN_POINTS,
        step_low=min(steps),
        step_high=max(steps),
        all_windows_rejected=True,
    )


def collect_zero_supports(row: RowInputs, scale: NormalizationScale,
                          branch_consistent: bool) -> list[ZeroSupport]:
    """Every argument available that this derivative is exactly zero.

    Never consults ``row.oti_value``: a zero must be established independently
    of the result being checked.
    """
    supports: list[ZeroSupport] = []

    if row.high_precision_value is not None:
        normalized = abs(scale.normalize(row.high_precision_value, row.order))
        if normalized <= ZERO_NORMALIZED_THRESHOLD:
            supports.append(ZeroSupport(
                "high_precision",
                "recomputed at %d decimal digits with step %.3e, where cancellation "
                "cannot manufacture a zero, giving normalized magnitude %.3e"
                % (row.high_precision_digits or 0, row.high_precision_step or 0.0,
                   normalized),
            ))

    if row.source_proof_kind:
        if branch_consistent:
            supports.append(ZeroSupport(
                row.source_proof_kind,
                (row.source_proof_detail or "")
                + " Branch consistency was verified at every stencil node of every "
                  "admissible step, so the cited branch is the branch that was sampled.",
            ))
        else:
            supports.append(ZeroSupport(
                "empirical_stencil_invariance",
                "a source-level proof (%s) was offered but the stencil did not stay "
                "on one branch, so the cited branch is not the branch that was "
                "sampled and the proof does not apply here" % row.source_proof_kind,
            ))

    if row.structurally_invariant:
        supports.append(ZeroSupport(
            "empirical_stencil_invariance",
            "the component was bit-identical at every sampled stencil node, which "
            "shows only that it did not vary over the points tried -- empirical "
            "local invariance, not a proof of exact independence",
        ))

    if row.affine_in_directions:
        supports.append(ZeroSupport(
            "empirical_affine_probe",
            "second and mixed differences stayed at the arithmetic rounding floor "
            "(largest residual %.3g of that floor) at amplitudes %s -- sampled "
            "equality at finitely many amplitudes, not a proof"
            % (row.affine_margin if row.affine_margin is not None else float("nan"),
               ", ".join("%.3e" % a for a in row.affine_amplitudes)),
        ))

    return supports


def classify_row(row: RowInputs, scale: NormalizationScale) -> dict[str, Any]:
    """Classify one row by what its independent reference can actually support."""
    usable = admissible_points(row.sweep)
    inadmissible = [point for point in row.sweep if not point.admissible]
    branch_consistent = bool(usable) and all(point.branch_consistent for point in usable)

    supports = collect_zero_supports(row, scale, branch_consistent)
    strong = [support for support in supports if support.strong]
    weak = [support for support in supports if not support.strong]
    normalized_oti = abs(scale.normalize(row.oti_value, row.order))
    oti_is_at_zero = normalized_oti <= ZERO_NORMALIZED_THRESHOLD

    plateau = find_plateau(row.sweep)
    normalized_plateau = (
        None if plateau is None else abs(scale.normalize(plateau.value, row.order))
    )

    classification: str
    justification: str
    agreement_tolerance: float | None = None
    absolute_error: float | None = None
    relative_error: float | None = None
    reference_value: float | None = None
    agrees: bool | None = None

    if (strong or weak) and not oti_is_at_zero:
        classification = UNRESOLVED
        reference_value = 0.0
        absolute_error = abs(row.oti_value)
        justification = (
            "Independent evidence points to a zero derivative, but OTI returned "
            "normalized magnitude %.3e above the %.1e zero threshold. This is a "
            "genuine disagreement, not a reference-quality problem."
            % (normalized_oti, ZERO_NORMALIZED_THRESHOLD)
        )
    elif strong and oti_is_at_zero:
        classification = EXPECTED_ZERO
        reference_value = 0.0
        absolute_error = abs(row.oti_value)
        agrees = True
        justification = (
            "Derivative is zero on evidence independent of the OTI result: "
            + "; ".join("%s -- %s" % (s.kind, s.detail) for s in strong)
        )
    elif weak and oti_is_at_zero:
        classification = EMPIRICALLY_ZERO
        reference_value = 0.0
        absolute_error = abs(row.oti_value)
        justification = (
            "The reference was zero over every point sampled, but only by sampled "
            "equality: " + "; ".join("%s -- %s" % (s.kind, s.detail) for s in weak)
            + ". Finitely many equal samples do not prove exact structural "
              "independence, so this row is reported, not counted as verification."
        )
    elif plateau is None:
        reasons = sorted({p.rejection_reason for p in inadmissible if p.rejection_reason})
        classification = UNRESOLVED
        justification = (
            "Fewer than %d consecutive admissible steps: %d of %d swept steps left "
            "the nominal branch (%s), so no plateau can be formed on the branch "
            "whose derivative is being verified."
            % (PLATEAU_MIN_POINTS, len(inadmissible), len(row.sweep),
               "; ".join(reasons) or "branch crossing")
        )
    elif normalized_plateau is not None and normalized_plateau <= ZERO_NORMALIZED_THRESHOLD:
        classification = UNRESOLVED
        reference_value = plateau.value
        justification = (
            "The finite-difference sweep is at the zero threshold (normalized %.3e) "
            "but nothing independent establishes the derivative as zero, so the "
            "reference cannot verify this row." % normalized_plateau
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
            "%d consecutive admissible steps from %.3e to %.3e agree to %.2e "
            "relative; the plateau is a genuine independent estimate and its own "
            "spread sets the agreement tolerance.%s"
            % (plateau.points, plateau.step_low, plateau.step_high,
               plateau.relative_uncertainty,
               "" if not inadmissible else
               " %d step(s) were excluded for leaving the nominal branch."
               % len(inadmissible))
        )
    elif plateau.relative_uncertainty <= CANCELLATION_REL_SPREAD:
        classification = CANCELLATION_LIMITED
        reference_value = plateau.value
        absolute_error = abs(row.oti_value - plateau.value)
        justification = (
            "The steadiest %d-step admissible window still spreads by %.2e relative, "
            "above the %.1e resolved threshold. Round-off cancellation dominates the "
            "order-%d reference at every admissible step, so it bounds the magnitude "
            "but cannot verify the value."
            % (plateau.points, plateau.relative_uncertainty, RESOLVED_REL_SPREAD,
               row.order)
        )
    else:
        classification = UNRESOLVED
        reference_value = plateau.value
        absolute_error = abs(row.oti_value - plateau.value)
        justification = (
            "No window of %d consecutive admissible steps agrees better than %.2e "
            "relative. The finite-difference reference does not resolve this "
            "derivative at all." % (PLATEAU_MIN_POINTS, plateau.relative_uncertainty)
        )

    supports_verification = classification in SUPPORTING_CLASSIFICATIONS and bool(agrees)

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
        "plateau_points": None if plateau is None else plateau.points,
        "plateau_step_low": None if plateau is None else plateau.step_low,
        "plateau_step_high": None if plateau is None else plateau.step_high,
        "plateau_absolute_uncertainty": (
            None if plateau is None else plateau.absolute_uncertainty
        ),
        "plateau_relative_uncertainty": (
            None if plateau is None else plateau.relative_uncertainty
        ),
        "steps_swept": len(row.sweep),
        "steps_admissible": len(usable),
        "steps_rejected_for_branch_crossing": len(inadmissible),
        "branch_consistent_over_admissible_steps": branch_consistent,
        "zero_supports": [support.as_dict() for support in supports],
        "zero_support_strength": "strong" if strong else ("weak" if weak else "none"),
        "structurally_invariant": row.structurally_invariant,
        "affine_in_directions": row.affine_in_directions,
        "affine_residual_over_rounding_floor": row.affine_margin,
        "high_precision_value": row.high_precision_value,
        "source_proof_kind": row.source_proof_kind,
        "absolute_error": absolute_error,
        "relative_error": relative_error,
        "agreement_tolerance": agreement_tolerance,
        "agrees_with_reference": agrees,
        "supports_verification": supports_verification,
        "sweep": [point.as_dict(scale, row.order) for point in row.sweep],
        **row.extra,
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate classified rows into the counts a claim matrix can consume.

    ``verified`` is deliberately strict: every row must carry usable supporting
    evidence *and* agree. Any row that is cancellation-limited, unresolved,
    empirically-zero-only, or that disagrees with a reference which did resolve
    it, blocks the whole study.
    """
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
    without_usable_reference = (
        counts[CANCELLATION_LIMITED] + counts[UNRESOLVED] + counts[EMPIRICALLY_ZERO]
    )
    branch_rejected = sum(
        int(row.get("steps_rejected_for_branch_crossing") or 0) for row in rows
    )

    by_order: dict[int, dict[str, int]] = {}
    for row in rows:
        bucket = by_order.setdefault(row["order"], {name: 0 for name in CLASSIFICATIONS})
        bucket[row["reference_classification"]] += 1

    verified = (
        bool(rows)
        and len(supporting) == len(rows)
        and not disagreeing
        and without_usable_reference == 0
    )

    return {
        "rows": len(rows),
        "classification_counts": counts,
        "rows_supporting_verification": len(supporting),
        "rows_with_reference_but_disagreeing": len(disagreeing),
        "rows_without_usable_reference": without_usable_reference,
        "rows_empirically_zero_only": counts[EMPIRICALLY_ZERO],
        "steps_rejected_for_branch_crossing": branch_rejected,
        "max_relative_error_on_resolved_rows": max(resolved_rel, default=None),
        "classification_counts_by_order": {
            str(order): value for order, value in sorted(by_order.items())
        },
        "verification_condition": (
            "every row supports verification (resolved and agreeing, or zero with "
            "strong independent support); no row is cancellation-limited, "
            "unresolved, or empirically-zero-only; no row disagrees with a "
            "reference that resolved it"
        ),
        "verified": verified,
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
