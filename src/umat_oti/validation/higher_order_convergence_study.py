"""Run the higher-order finite-difference convergence study for the verified models.

Reuses the existing evidence runners to produce the transformed source, the OTI
higher-order output and (for ``code_imp``) the independently compiled original
UMAT. It then sweeps the finite-difference step across two decades either side
of the previously published step and classifies every reference row with
:mod:`umat_oti.validation.higher_order_convergence`.

Nothing archived is modified. Outputs land in a directory chosen by the caller.

    python -m umat_oti.validation.higher_order_convergence_study \\
        --model j2 --out paper_results/higher_order_convergence/j2
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

import mpmath as mp

from umat_oti.oti.oti_directions import deriv_factor
from umat_oti.validation import higher_order_convergence as hoc
from umat_oti.validation.actual_legacy_higher_order import (
    CODE_IMP_INCREMENTS,
    FD_STEP as CODE_IMP_BASE_STEP,
    run_code_imp_higher_order_evidence,
)
from umat_oti.validation.actual_umat_higher_order import (
    J2_INCREMENTS,
    SELECTED_DIRECTIONS,
    _integrate_increment_mp,
    run_actual_j2_higher_order_evidence,
)

STENCIL_NODES = tuple(range(-4, 5))
# How many units in the last place of the response a second-difference residual
# may occupy and still count as exact affineness. The reference model rounds
# internally, so a couple of ulp of drift carries no information.
ULP_MARGIN = 16.0
J2_BASE_STEP = 2.0e-5

# Working precision for the J2 sweep. The published evidence used 80 digits;
# the sweep keeps that so the swept values are comparable to the archive.
J2_SWEEP_DIGITS = 80
# Independent zero support for J2: many more digits and a far smaller step, a
# regime where round-off cancellation cannot produce a spurious zero.
J2_HIGH_PRECISION_DIGITS = 200
J2_HIGH_PRECISION_STEP_FACTOR = 1.0e-3

J2_SCALE = hoc.NormalizationScale(
    stress_scale=250.0,
    strain_scale=1.0e-3,
    stress_units="MPa",
    strain_units="dimensionless",
    stress_scale_meaning="initial yield stress SIGY0 of the controlled J2 model",
    strain_scale_meaning=(
        "characteristic strain-increment magnitude of the three J2 load steps"
    ),
)
CODE_IMP_SCALE = hoc.NormalizationScale(
    stress_scale=240.0,
    strain_scale=1.0e-3,
    stress_units="MPa",
    strain_units="dimensionless",
    stress_scale_meaning="initial yield stress SIGY0 hard-coded in code_imp.f",
    strain_scale_meaning=(
        "characteristic strain-increment magnitude of the four code_imp load steps"
    ),
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- #
# Shared sweep machinery
# --------------------------------------------------------------------------- #
def _sweep_one_direction_set(
    evaluate: Callable[[Sequence[Any]], Sequence[Any]],
    base_increment: Sequence[float],
    directions: tuple[int, ...],
    step: float,
    n_components: int,
    *,
    weight_digits: int = 60,
    extended: bool = False,
) -> tuple[tuple[float, ...], tuple[bool, ...]]:
    """One tensor-product FD estimate plus per-component stencil invariance.

    ``invariant[c]`` is True when component ``c`` took the same value at every
    stencil node, which means the component does not depend on the perturbed
    strain components at all.

    With ``extended=True`` the stencil nodes, weights and accumulation all stay
    in ``mpmath`` at the ambient working precision; only the final value is
    narrowed to ``float``. Perturbing or accumulating in double precision would
    inject a ~1e-16 relative error into every sample, which an order-4 stencil
    amplifies by ``1/step**4`` -- reintroducing precisely the cancellation an
    extended-precision reference exists to avoid.
    """
    multiplicities = {d: directions.count(d) for d in sorted(set(directions))}
    weighted = [
        (direction, hoc.stencil_weights(order, step, STENCIL_NODES, mp, weight_digits,
                                        as_float=not extended))
        for direction, order in multiplicities.items()
    ]
    if extended:
        node_values = tuple(mp.mpf(node) for node in STENCIL_NODES)
        step_value: Any = mp.mpf(str(step))
        base = [mp.mpf(str(value)) for value in base_increment]
        one: Any = mp.mpf("1")
    else:
        node_values = tuple(float(node) for node in STENCIL_NODES)
        step_value = step
        base = [float(value) for value in base_increment]
        one = 1.0

    terms: list[list[Any]] = [[] for _ in range(n_components)]
    observed: list[list[Any]] = [[] for _ in range(n_components)]
    for node_indices in itertools.product(range(len(STENCIL_NODES)), repeat=len(weighted)):
        perturbed = list(base)
        coefficient = one
        for (direction, weights), node_index in zip(weighted, node_indices):
            perturbed[direction - 1] += node_values[node_index] * step_value
            coefficient = coefficient * weights[node_index]
        response = evaluate(perturbed)
        for component in range(n_components):
            terms[component].append(coefficient * response[component])
            observed[component].append(response[component])

    summation = mp.fsum if extended else math.fsum
    values = tuple(float(summation(column)) for column in terms)
    invariant = tuple(
        all(sample == column[0] for sample in column) for column in observed
    )
    return values, invariant


def _affine_probe(
    evaluate: Callable[[Sequence[Any]], Sequence[Any]],
    base_increment: Sequence[float],
    directions: tuple[int, ...],
    amplitudes: Sequence[float],
    n_components: int,
    *,
    extended: bool = False,
) -> tuple[tuple[bool, ...], tuple[float, ...]]:
    """Is the response affine in ``directions`` over these amplitudes?

    Checks the second difference along each involved direction and the mixed
    difference across each involved pair. Exact affineness over a neighbourhood
    containing the plateau stencil means every derivative of order two and above
    vanishes there -- an independent constitutive-structure fact about the
    reference model, established without consulting the OTI result.

    The residual is required to sit at the arithmetic's own rounding level,
    ``ULP_MARGIN * eps * max|f|`` over the probed points, rather than to be
    bitwise zero: the reference model rounds internally, so one or two ulp of
    drift is expected and means nothing. The separation is enormous either way.
    A genuine second derivative of magnitude ``D`` produces a residual ``D*A**2``;
    at ``A ~ 1e-4`` and ``D ~ 1e7`` that is ``~1e-1``, some thirteen orders of
    magnitude above a ``~1e-14`` rounding floor. Returns the per-component
    verdict and the largest observed residual-to-floor ratio, so the margin that
    justified each verdict stays auditable.
    """
    cast = (lambda v: mp.mpf(str(v))) if extended else float
    if extended:
        eps = float(mp.mpf(2) ** (-mp.mp.prec + 1))
    else:
        eps = sys.float_info.epsilon
    base = [cast(value) for value in base_increment]
    involved = sorted(set(directions))

    def at(offsets: dict[int, Any]) -> Sequence[Any]:
        point = list(base)
        for direction, delta in offsets.items():
            point[direction - 1] += delta
        return evaluate(point)

    centre = at({})
    affine = [True] * n_components
    margin = [0.0] * n_components
    magnitude = [abs(float(value)) for value in centre]

    def check(component: int, residual: Any, samples: Sequence[Any]) -> None:
        magnitude[component] = max(
            [magnitude[component]] + [abs(float(v)) for v in samples]
        )
        floor = ULP_MARGIN * eps * magnitude[component]
        value = abs(float(residual))
        ratio = value / floor if floor > 0.0 else (0.0 if value == 0.0 else float("inf"))
        margin[component] = max(margin[component], ratio)
        if ratio > 1.0:
            affine[component] = False

    for amplitude in amplitudes:
        step = cast(amplitude)
        singles: dict[int, tuple[Sequence[Any], Sequence[Any]]] = {}
        for direction in involved:
            plus, minus = at({direction: step}), at({direction: -step})
            singles[direction] = (plus, minus)
            for component in range(n_components):
                check(component,
                      plus[component] + minus[component] - 2 * centre[component],
                      (plus[component], minus[component], centre[component]))
        for first_index, first in enumerate(involved):
            for second in involved[first_index + 1:]:
                both = at({first: step, second: step})
                for component in range(n_components):
                    residual = (both[component] - singles[first][0][component]
                                - singles[second][0][component] + centre[component])
                    check(component, residual,
                          (both[component], singles[first][0][component],
                           singles[second][0][component], centre[component]))
        if not any(affine):
            break
    return tuple(affine), tuple(margin)


def _collect_sweep(
    evaluate_for_increment: Callable[[int], Callable[[Sequence[float]], Sequence[float]]],
    increments: Sequence[Sequence[float]],
    base_step: float,
    n_components: int,
    progress: Callable[[str], None],
    extended: bool = False,
) -> tuple[dict[tuple[int, tuple[int, ...]], list[Any]],
           dict[tuple[int, tuple[int, ...]], tuple[bool, ...]],
           tuple[float, ...]]:
    """FD values for every (increment, direction set) at every swept step.

    Also returns, per row group, whether the reference is exactly affine in the
    involved directions over amplitudes spanning the plateau stencil.
    """
    collected: dict[tuple[int, tuple[int, ...]], list[Any]] = {}
    affine: dict[tuple[int, tuple[int, ...]], tuple[bool, ...]] = {}
    affine_margin: dict[tuple[int, tuple[int, ...]], tuple[float, ...]] = {}
    # Amplitudes reach as far as the stencil of the smaller, plateau-forming
    # steps; deliberately not the largest swept steps, which for these load
    # paths leave the branch entirely.
    amplitudes = tuple(base_step * factor for factor in (4.0, 2.0, 1.0))
    steps = hoc.sweep_steps(base_step)
    for increment_index in range(len(increments)):
        evaluate = evaluate_for_increment(increment_index)
        base_increment = increments[increment_index]
        for directions in SELECTED_DIRECTIONS:
            entries = []
            for factor, step in steps:
                values, invariant = _sweep_one_direction_set(
                    evaluate, base_increment, directions, step, n_components,
                    weight_digits=mp.mp.dps if extended else 60,
                    extended=extended,
                )
                entries.append((factor, step, values, invariant))
            collected[(increment_index + 1, directions)] = entries
            verdict, ratios = _affine_probe(
                evaluate, base_increment, directions, amplitudes, n_components,
                extended=extended,
            )
            affine[(increment_index + 1, directions)] = verdict
            affine_margin[(increment_index + 1, directions)] = ratios
            progress(
                "    increment %d directions %s: %d steps"
                % (increment_index + 1, "|".join(map(str, directions)), len(steps))
            )
    return collected, affine, affine_margin, amplitudes


def _build_rows(
    collected: dict[tuple[int, tuple[int, ...]], list[Any]],
    oti_values: dict[tuple[int, int, tuple[int, ...], int], float],
    branch_of: Callable[[int], str],
    n_components: int,
    scale: hoc.NormalizationScale,
    high_precision: dict[tuple[int, tuple[int, ...]], tuple[float, ...]] | None,
    high_precision_step: float | None,
    high_precision_digits: int | None,
    affine: dict[tuple[int, tuple[int, ...]], tuple[bool, ...]],
    affine_margin: dict[tuple[int, tuple[int, ...]], tuple[float, ...]],
    affine_amplitudes: tuple[float, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (increment, directions), entries in sorted(collected.items()):
        for component in range(1, n_components + 1):
            sweep = [
                hoc.SweepPoint(
                    step=step,
                    step_factor=factor,
                    value=values[component - 1],
                    invariant=invariant[component - 1],
                )
                for factor, step, values, invariant in entries
            ]
            structurally_invariant = all(point.invariant for point in sweep)
            hp_value = None
            if high_precision is not None:
                hp_value = high_precision[(increment, directions)][component - 1]
            rows.append(
                hoc.classify_row(
                    hoc.RowInputs(
                        increment=increment,
                        branch=branch_of(increment),
                        stress_component=component,
                        order=len(directions),
                        directions=directions,
                        direction_pattern=hoc.direction_pattern(directions),
                        recovery_factor=deriv_factor(directions),
                        oti_value=oti_values[(increment, len(directions), directions, component)],
                        sweep=sweep,
                        structurally_invariant=structurally_invariant,
                        affine_in_directions=affine[(increment, directions)][component - 1],
                        affine_amplitudes=affine_amplitudes,
                        affine_margin=affine_margin[(increment, directions)][component - 1],
                        high_precision_value=hp_value,
                        high_precision_step=high_precision_step,
                        high_precision_digits=high_precision_digits,
                    ),
                    scale,
                )
            )
    return rows


# --------------------------------------------------------------------------- #
# Controlled J2 (extended-precision reference)
# --------------------------------------------------------------------------- #
def _j2_state_before(increment_index: int) -> tuple[tuple[Any, ...], Any]:
    """Converged mp state entering ``increment_index`` (0-based)."""
    stress = tuple(mp.mpf("0") for _ in range(6))
    eqplas = mp.mpf("0")
    for previous in range(increment_index):
        stress, eqplas, _, _ = _integrate_increment_mp(stress, eqplas, J2_INCREMENTS[previous])
    return stress, eqplas


def _j2_evaluator(increment_index: int) -> Callable[[Sequence[float]], Sequence[float]]:
    stress, eqplas = _j2_state_before(increment_index)

    def evaluate(perturbed: Sequence[Any]) -> Sequence[Any]:
        # Returned as mpmath numbers: narrowing here would defeat the whole
        # point of an extended-precision reference.
        updated, _, _, _ = _integrate_increment_mp(stress, eqplas, perturbed)
        return updated

    return evaluate


def _j2_branches() -> dict[int, str]:
    branches: dict[int, str] = {}
    stress = tuple(mp.mpf("0") for _ in range(6))
    eqplas = mp.mpf("0")
    for index, increment in enumerate(J2_INCREMENTS, start=1):
        stress, eqplas, yielded, _ = _integrate_increment_mp(stress, eqplas, increment)
        branches[index] = "plastic" if yielded else "elastic"
    return branches


def _j2_high_precision(progress: Callable[[str], None]) -> tuple[dict[Any, tuple[float, ...]], float]:
    """Near-exact derivatives: many digits, tiny step, cancellation negligible."""
    previous = mp.mp.dps
    mp.mp.dps = J2_HIGH_PRECISION_DIGITS
    step = J2_BASE_STEP * J2_HIGH_PRECISION_STEP_FACTOR
    result: dict[Any, tuple[float, ...]] = {}
    try:
        for increment_index in range(len(J2_INCREMENTS)):
            evaluate = _j2_evaluator(increment_index)
            for directions in SELECTED_DIRECTIONS:
                values, _ = _sweep_one_direction_set(
                    evaluate,
                    J2_INCREMENTS[increment_index],
                    directions,
                    step,
                    6,
                    weight_digits=J2_HIGH_PRECISION_DIGITS,
                    extended=True,
                )
                result[(increment_index + 1, directions)] = values
            progress("    high-precision increment %d done" % (increment_index + 1))
    finally:
        mp.mp.dps = previous
    return result, step


def run_j2_convergence(output_dir: Path, progress: Callable[[str], None]) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    progress("  regenerating OTI higher-order output for controlled J2")
    with tempfile.TemporaryDirectory() as scratch:
        evidence = run_actual_j2_higher_order_evidence(
            REPO_ROOT / "examples" / "j2_actual_higher_order.json", Path(scratch) / "evidence"
        )
        oti_values = _read_oti_from_csv(Path(evidence["comparison"]["csv"]))
        source_sha = evidence["source"]["sha256"]
        source_path = evidence["source"]["path"]

    mp.mp.dps = J2_SWEEP_DIGITS
    progress("  sweeping %d finite-difference steps" % len(hoc.STEP_FACTORS))
    collected, affine, affine_margin, affine_amplitudes = _collect_sweep(
        _j2_evaluator, J2_INCREMENTS, J2_BASE_STEP, 6, progress, extended=True)

    progress("  independent high-precision evaluation at %d digits" % J2_HIGH_PRECISION_DIGITS)
    high_precision, hp_step = _j2_high_precision(progress)

    branches = _j2_branches()
    rows = _build_rows(
        collected, oti_values, lambda i: branches[i], 6, J2_SCALE,
        high_precision, hp_step, J2_HIGH_PRECISION_DIGITS,
        affine, affine_margin, affine_amplitudes,
    )
    return _write_outputs(
        output_dir=output_dir,
        model="controlled_j2_actual_umat",
        rows=rows,
        scale=J2_SCALE,
        base_step=J2_BASE_STEP,
        reference_method=(
            "independent tensor-product finite differences of "
            "validation.j2_reference.integrate_increment evaluated in mpmath at "
            f"{J2_SWEEP_DIGITS} decimal digits"
        ),
        reference_precision=f"mpmath, {J2_SWEEP_DIGITS} decimal digits",
        zero_support=(
            "structural stencil invariance, exact local affineness, and an "
            f"independent recomputation at {J2_HIGH_PRECISION_DIGITS} decimal digits "
            f"with step {hp_step:.3e}"
        ),
        source_path=source_path,
        source_sha256=source_sha,
    )


# --------------------------------------------------------------------------- #
# Legacy code_imp (double-precision compiled reference)
# --------------------------------------------------------------------------- #
def _code_imp_evaluator(executable: Path, increment_index: int):
    history = [list(values) for values in CODE_IMP_INCREMENTS[: increment_index + 1]]

    def evaluate(perturbed: Sequence[float]) -> Sequence[float]:
        increments = [list(row) for row in history]
        increments[increment_index] = list(perturbed)
        text = str(len(increments)) + "\n" + "\n".join(
            " ".join(f"{value:.17e}" for value in row) for row in increments
        ) + "\n"
        result = subprocess.run(
            [str(executable)], input=text, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"original code_imp reference failed: {result.stderr}")
        return tuple(float(value) for value in result.stdout.split())

    return evaluate


def run_code_imp_convergence(output_dir: Path, progress: Callable[[str], None]) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    progress("  regenerating OTI output and original-UMAT reference for code_imp")
    # The compiled reference executable has to outlive the transform step, so the
    # scratch tree is kept for the whole sweep and removed on the way out --
    # build products must never be left behind, let alone committed.
    with tempfile.TemporaryDirectory(prefix="code_imp_convergence_") as scratch_name:
        scratch = Path(scratch_name)
        evidence = run_code_imp_higher_order_evidence(
            REPO_ROOT / "examples" / "code_imp_actual_higher_order.json", scratch / "evidence"
        )
        oti_values = _read_oti_from_csv(Path(evidence["comparison"]["csv"]))
        executable = scratch / "evidence" / "code_imp_reference_driver"
        if not executable.exists():
            raise RuntimeError(f"independent original-UMAT executable missing: {executable}")

        branch_history = {row["increment"]: row["branch"] for row in evidence["branch_history"]}
        progress("  sweeping %d finite-difference steps (compiled double-precision reference)"
                 % len(hoc.STEP_FACTORS))
        collected, affine, affine_margin, affine_amplitudes = _collect_sweep(
            lambda index: _code_imp_evaluator(executable, index),
            CODE_IMP_INCREMENTS, CODE_IMP_BASE_STEP, 4, progress,
        )

        rows = _build_rows(
            collected, oti_values, lambda i: branch_history[i], 4, CODE_IMP_SCALE,
            None, None, None, affine, affine_margin, affine_amplitudes,
        )
    return _write_outputs(
        output_dir=output_dir,
        model="code_imp_legacy_umat",
        rows=rows,
        scale=CODE_IMP_SCALE,
        base_step=CODE_IMP_BASE_STEP,
        reference_method=(
            "independently compiled original code_imp UMAT replayed for each "
            "tensor-product centred finite-difference stencil node"
        ),
        reference_precision="IEEE double precision (compiled Fortran, gfortran)",
        zero_support=(
            "structural stencil invariance and exact local affineness (bitwise-zero "
            "second and mixed differences at amplitudes "
            + ", ".join("%.3e" % a for a in affine_amplitudes)
            + "); the reference is a double-precision executable, so no "
            "higher-precision recomputation is available for this model"
        ),
        source_path=evidence["source"]["path"],
        source_sha256=evidence["source"]["sha256"],
    )


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _read_oti_from_csv(path: Path) -> dict[tuple[int, int, tuple[int, ...], int], float]:
    """OTI derivatives keyed by (increment, order, directions, component)."""
    values: dict[tuple[int, int, tuple[int, ...], int], float] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            directions = tuple(int(v) for v in row["directions"].split("|"))
            key = (int(row["increment"]), int(row["order"]), directions,
                   int(row["stress_component"]))
            values[key] = float(row["oti_derivative"])
    return values


_ROW_COLUMNS = (
    "increment", "branch", "stress_component", "order", "directions",
    "direction_pattern", "recovery_factor", "oti_derivative", "oti_normalized",
    "reference_value", "reference_normalized", "reference_classification",
    "plateau_points", "plateau_step_low", "plateau_step_high",
    "plateau_absolute_uncertainty", "plateau_relative_uncertainty",
    "structurally_invariant", "affine_in_directions",
    "affine_residual_over_rounding_floor", "high_precision_value",
    "absolute_error",
    "relative_error", "agreement_tolerance", "agrees_with_reference",
    "supports_verification", "reference_justification",
)


def _write_outputs(*, output_dir: Path, model: str, rows: list[dict[str, Any]],
                   scale: hoc.NormalizationScale, base_step: float,
                   reference_method: str, reference_precision: str,
                   zero_support: str, source_path: str, source_sha256: str) -> dict[str, Any]:
    rows_path = output_dir / "convergence_rows.csv"
    with rows_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_ROW_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in _ROW_COLUMNS})

    sweep_path = output_dir / "convergence_sweep.csv"
    with sweep_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "increment", "branch", "stress_component", "order", "directions",
            "direction_pattern", "step_factor", "step", "fd_value",
            "fd_value_normalized", "invariant_across_stencil", "oti_derivative",
            "reference_classification",
        ])
        for row in rows:
            for point in row["sweep"]:
                writer.writerow([
                    row["increment"], row["branch"], row["stress_component"],
                    row["order"], row["directions"], row["direction_pattern"],
                    point["step_factor"], point["step"], point["value"],
                    point["normalized"], point["invariant_across_stencil"],
                    row["oti_derivative"], row["reference_classification"],
                ])

    summary = hoc.summarize(rows)
    summary_by_view = {
        "by_order": _group_counts(rows, lambda r: str(r["order"])),
        "by_branch": _group_counts(rows, lambda r: r["branch"]),
        "by_direction_pattern": _group_counts(rows, lambda r: r["direction_pattern"]),
        "by_increment": _group_counts(rows, lambda r: str(r["increment"])),
        "by_stress_component": _group_counts(rows, lambda r: str(r["stress_component"])),
    }

    dataset = {
        "schema": "umat-oti-higher-order-convergence/1",
        "model": model,
        "source": {"path": _relative(source_path), "sha256": source_sha256},
        "reference": {
            "method": reference_method,
            "precision": reference_precision,
            "stencil": "9-point centred per active strain component",
            "published_step": base_step,
            "step_factors": list(hoc.STEP_FACTORS),
            "steps": [step for _, step in hoc.sweep_steps(base_step)],
            "zero_support": zero_support,
        },
        "normalization": scale.as_dict(),
        "classification_policy": {
            "classifications": list(hoc.CLASSIFICATIONS),
            "supporting": sorted(hoc.SUPPORTING_CLASSIFICATIONS),
            "plateau_min_points": hoc.PLATEAU_MIN_POINTS,
            "resolved_relative_spread": hoc.RESOLVED_REL_SPREAD,
            "cancellation_relative_spread": hoc.CANCELLATION_REL_SPREAD,
            "zero_normalized_threshold": hoc.ZERO_NORMALIZED_THRESHOLD,
            "agreement_relative_floor": hoc.AGREEMENT_REL_FLOOR,
            "agreement_uncertainty_multiple": hoc.AGREEMENT_UNCERTAINTY_MULTIPLE,
            "note": (
                "A row is never passed for being below a large absolute tolerance. "
                "Only resolved rows agreeing with their plateau, and zero rows with "
                "independent support, count as verification evidence."
            ),
        },
        "summary": summary,
        "summary_views": summary_by_view,
        "artifacts": {
            "rows_csv": _relative(rows_path),
            "sweep_csv": _relative(sweep_path),
        },
    }
    dataset_path = output_dir / "convergence_evidence.json"
    dataset_path.write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")

    for path in (rows_path, sweep_path, dataset_path):
        dataset.setdefault("artifact_sha256", {})[path.name] = _sha256(path)
    dataset_path.write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")

    dataset["rows"] = rows
    dataset["dataset_path"] = str(dataset_path)
    return dataset


def _group_counts(rows: Sequence[dict[str, Any]], key: Callable[[dict[str, Any]], str]):
    grouped: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = grouped.setdefault(key(row), {name: 0 for name in hoc.CLASSIFICATIONS})
        bucket[row["reference_classification"]] += 1
    return dict(sorted(grouped.items()))


def _relative(path: Path | str) -> str:
    """Repo-relative POSIX path: evidence must not record this machine's layout."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("j2", "code_imp"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    def progress(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    progress(f"convergence study: {args.model}")
    if args.model == "j2":
        dataset = run_j2_convergence(args.out, progress)
    else:
        dataset = run_code_imp_convergence(args.out, progress)

    summary = dataset["summary"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
