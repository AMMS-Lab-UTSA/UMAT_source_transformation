from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Sequence

import mpmath as mp

from umat_oti.services.transformation import (
    TransformationOptions, run_transformation,
)
from umat_oti.oti.oti_directions import deriv_factor
REPO_ROOT = Path(__file__).resolve().parents[3]

from umat_oti.validation.j2_reference import J2Parameters, J2State, integrate_increment
from umat_oti.validation.higher_order_convergence import NormalizationScale


# Strain-increment path for the illustrative J2 example.
#
# The first twelve steps are a uniform uniaxial ramp. With E=200000, nu=0.3 and
# SIGY0=250 the von Mises stress reaches initial yield at a uniaxial strain of
# 1.625e-3, so the ramp crosses the yield surface inside step seven and leaves
# six converged elastic states and six converged plastic states rather than a
# single point on each branch. Step 13 is a multiaxial plastic probe, step 14
# unloads elastically from the plastic state, and step 15 reloads multiaxially
# with shear while staying elastic. That covers loading, the yield transition,
# hardening, unloading and reversed multiaxial response.
#
# Every step is positioned so that the widest reference stencil (+/-4 nodes at
# the base step of 2e-5) stays on one side of the yield surface; the closest
# case is step 6, whose 19.2 MPa margin is 1.6x the 12.3 MPa the stencil moves.
# Steps that do cross anyway are rejected by the branch guard, not averaged
# across the kink.
_J2_UNIAXIAL_RAMP = (2.5e-4, 0.0, 0.0, 0.0, 0.0, 0.0)
J2_INCREMENTS = (
    (_J2_UNIAXIAL_RAMP,) * 12
    + (
        (3.0e-4, -1.0e-4, 0.0, 2.0e-4, 0.0, 0.0),   # multiaxial, plastic
        (-1.0e-3, 0.0, 0.0, 0.0, 0.0, 0.0),         # elastic unloading
        (5.0e-4, 0.0, 0.0, -2.0e-4, 0.0, 0.0),      # multiaxial elastic reload
    )
)
SELECTED_DIRECTIONS = (
    (1, 1),
    (1, 2),
    (1, 1, 1),
    (1, 1, 2),
    (1, 1, 1, 1),
    (1, 1, 2, 2),
)
ABSOLUTE_TOLERANCES = {2: 1.0e-5, 3: 2.0e-2, 4: 1.0e-1}
RELATIVE_TOLERANCE = 1.0e-7

#: Below this fraction of the largest derivative of the same order at the same
#: increment, an entry is not a small number -- it is a zero of that derivative
#: family, and both sides of the comparison are rounding dust. Dividing dust by
#: dust yields a relative error near one, which says nothing about the
#: derivative; and the fixed absolute tolerances above cannot separate the two
#: cases, because they are constants unrelated to the magnitude of what is
#: being differentiated. On this path they let entries at 2.6e-13 of their
#: family through while stopping entries at 1.3e-12, which is an accident of
#: where the constants happen to fall rather than a finding.
#:
#: The measured separation is wide enough that the exact value does not matter:
#: no entry anywhere in the study lies between 2.3e-12 and 1.9e-05 of its
#: family scale, so every fraction across those seven decades classifies every
#: row identically. This one sits near the middle of that empty gap, and
#: ``test_the_structural_zero_gap_is_wide_enough_that_the_fraction_does_not_matter``
#: fails if the separation ever narrows to where the choice starts to matter.
#: The same rule, with the same reasoning, adjudicates the tangent below.
HIGHER_ORDER_ZERO_FRACTION = 1.0e-8


def run_actual_j2_higher_order_evidence(config_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    summary, exit_code = run_transformation(config_path, output_dir,
                                          TransformationOptions(compile_generated=True))
    if exit_code != 0:
        raise RuntimeError(f"Canonical transform/compile failed: {summary}")

    driver = output_dir / "actual_umat_higher_order_driver.f90"
    driver.write_text(_driver_source(), encoding="utf-8")
    executable = output_dir / "actual_umat_higher_order_driver"
    compile_command = [
        "gfortran",
        "-O1",
        "-std=legacy",
        "-ffree-line-length-none",
        "-I",
        str(output_dir),
        str(driver),
        str(output_dir / "master_parameters.o"),
        str(output_dir / "real_utils.o"),
        str(output_dir / "otim6n4.o"),
        str(output_dir / "transformed_umat.o"),
        "-o",
        str(executable),
    ]
    compiled = subprocess.run(compile_command, cwd=output_dir, check=False, capture_output=True, text=True)
    if compiled.returncode != 0:
        raise RuntimeError(f"Driver compilation failed: {compiled.stderr}")

    higher_output = output_dir / "oti_hjac.dat"
    higher_output.unlink(missing_ok=True)
    executed = subprocess.run([str(executable)], cwd=output_dir, check=False, capture_output=True, text=True)
    if executed.returncode != 0:
        raise RuntimeError(f"Driver execution failed: {executed.stderr}")

    oti_values = _read_oti_higher_order(higher_output)
    primal_rows = _read_primal(output_dir / "actual_umat_primal.csv")
    contract = json.loads(Path(config_path).read_text(encoding="utf-8"))
    validation = contract.get("validation", {})
    scales = NormalizationScale(
        stress_scale=float(validation["stress_scale"]),
        strain_scale=float(validation["strain_scale"]),
        stress_scale_meaning=validation.get("stress_scale_meaning", ""),
        strain_scale_meaning=validation.get("strain_scale_meaning", ""),
    )
    comparisons, branch_history = _compare_with_finite_difference(oti_values, scales)
    tangent_rows = _compare_tangent(_read_tangent(output_dir / "actual_umat_ddsdde.csv"))
    tangent_path = output_dir / "table2_ddsdde_illustrative.csv"
    _write_comparisons(tangent_path, tangent_rows)
    comparison_path = output_dir / "actual_umat_higher_order_comparison.csv"
    _write_comparisons(comparison_path, comparisons)
    table_path = output_dir / "table4_higher_order_actual_umat.csv"
    _write_summary_table(table_path, comparisons)

    source_path = Path(summary["source"])
    generated_paths = [
        Path(summary["transformed_source"]),
        output_dir / "otim6n4.f90",
        driver,
        executable,
        higher_output,
        comparison_path,
        table_path,
        output_dir / "actual_umat_primal.csv",
        output_dir / "actual_umat_ddsdde.csv",
        tangent_path,
    ]
    max_abs = max(row["absolute_error"] for row in comparisons)
    max_rel = max(row["relative_error"] for row in comparisons)
    # Rows judged as a zero of their derivative family are excluded: their
    # relative error is dust divided by dust, which is near one however well
    # the derivative was recovered. Including them made this statistic report
    # 1.0 while every row in it agreed. Those rows are counted separately, and
    # a generated value that is not zero at a structural zero is still a
    # failure -- it is caught by the classification, not hidden by it.
    significant_relative_errors = [
        row["relative_error"]
        for row in comparisons
        if row["judged_by"] == "tolerance"
        and row["absolute_error"] > row["absolute_tolerance"]
    ]
    failed_rows = sum(1 for row in comparisons if not row["passed"])
    evidence = {
        "schema": "umat-oti-actual-higher-order-evidence/1",
        "status": "verified_from_generic_transformed_source" if failed_rows == 0 else "failed",
        "model": "controlled_j2_actual_umat",
        "source": {"path": str(source_path), "sha256": _sha256(source_path)},
        "canonical_manifest": summary["manifest"],
        "normalized_request": summary["derivative_requests"],
        "compiler": summary["compilation"],
        "driver_compile": {
            "command": compile_command,
            "returncode": compiled.returncode,
            "stdout": compiled.stdout,
            "stderr": compiled.stderr,
        },
        "execution": {"command": [str(executable)], "returncode": executed.returncode},
        "increments": [list(values) for values in J2_INCREMENTS],
        "branch_history": branch_history,
        "directions": [list(values) for values in SELECTED_DIRECTIONS],
        "factorial_recovery": "OTI coefficients are multiplied by product factorials before oti_hjac.dat output.",
        "reference": {
            "method": "independent tensor-product finite differences of validation.j2_reference.integrate_increment",
            "stencil": "9-point centered per active strain component",
            "step": 2.0e-5,
        },
        "comparison": {
            "rows": len(comparisons),
            "passed_rows": len(comparisons) - failed_rows,
            "failed_rows": failed_rows,
            "max_absolute_error": max_abs,
            "max_relative_error": max_rel,
            "max_relative_error_when_absolute_tolerance_exceeded": max(significant_relative_errors, default=0.0),
            "rows_judged_by_tolerance": sum(
                1 for row in comparisons if row["judged_by"] == "tolerance"),
            "rows_that_are_zeros_of_their_family": sum(
                1 for row in comparisons if row["judged_by"] == "structural_zero"),
            "structural_zero_fraction": HIGHER_ORDER_ZERO_FRACTION,
            "absolute_tolerances_by_order": ABSOLUTE_TOLERANCES,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "csv": str(comparison_path),
            "publication_table": str(table_path),
        },
        "tangent": _tangent_summary(tangent_rows, tangent_path),
        "primal_rows": primal_rows,
        "artifacts": [
            {"path": str(path), "sha256": _sha256(path)} for path in generated_paths
        ],
    }
    # The written record is portable; the returned one keeps absolute paths,
    # because callers in this process still have to open those files.
    evidence_path = output_dir / "actual_umat_higher_order_evidence.json"
    evidence_path.write_text(
        json.dumps(_relative_paths(evidence, output_dir), indent=2, sort_keys=True),
        encoding="utf-8")
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def _compare_with_finite_difference(
    oti_values: dict[tuple[int, int, tuple[int, ...], int], float],
    scales: NormalizationScale,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = J2Parameters(E=200000.0, nu=0.3, SIGY0=250.0, H=2000.0)
    state = J2State()
    mp.mp.dps = 80
    reference_stress = tuple(mp.mpf("0") for _ in range(6))
    reference_eqplas = mp.mpf("0")
    rows: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for increment, dstran in enumerate(J2_INCREMENTS, start=1):
        baseline = integrate_increment(params, state, dstran)
        history.append(
            {
                "increment": increment,
                "yielded": baseline.yielded,
                "eqplas_before": state.statev[0],
                "eqplas_after": baseline.statev[0],
                "dgamma": baseline.dgamma,
            }
        )
        measured: list[dict[str, Any]] = []
        for directions in SELECTED_DIRECTIONS:
            reference = _finite_difference_response(
                reference_stress,
                reference_eqplas,
                dstran,
                directions,
                step=mp.mpf("0.00002"),
            )
            factor = deriv_factor(directions)
            for component, reference_value in enumerate(reference, start=1):
                oti_value = oti_values[(increment, len(directions), directions, component)]
                measured.append({
                    "order": len(directions),
                    "directions": "|".join(str(value) for value in directions),
                    "recovery_factor": factor,
                    "stress_component": component,
                    "oti_derivative": oti_value,
                    "fd_reference": reference_value,
                })

        # The scale a structural zero is measured against is the magnitude a
        # derivative of that order has in this problem -- the contract's own
        # stress and strain scales, the same pair the convergence study
        # normalizes by. Using the largest value observed at the increment
        # instead is degenerate exactly where it matters most: on an elastic
        # increment the response is linear, every derivative of order two and
        # above is genuinely zero, and the largest of them is rounding dust,
        # so each one sits above a floor derived from its neighbours and gets
        # compared against dust with a relative error of one.
        family_scale = {order: scales.stress_scale / scales.strain_scale ** order
                        for order in {entry["order"] for entry in measured}}

        for entry in measured:
            order = entry["order"]
            oti_value = entry["oti_derivative"]
            reference_value = entry["fd_reference"]
            absolute_error = abs(oti_value - reference_value)
            relative_error = absolute_error / max(abs(oti_value), abs(reference_value), 1.0e-300)
            scale = family_scale[order]
            floor = scale * HIGHER_ORDER_ZERO_FRACTION
            if max(abs(oti_value), abs(reference_value)) <= floor:
                # Both sides put this derivative at zero on the scale of the
                # family it belongs to. The generated value has to be zero
                # there too; one that is not is a real disagreement and is
                # reported as one.
                judged_by = "structural_zero"
                passed = abs(oti_value) <= floor
                justification = (
                    f"both the generated value and the reference lie below "
                    f"{floor:.3e}, which is {HIGHER_ORDER_ZERO_FRACTION:.0e} "
                    f"of the magnitude an order-{order} derivative has in "
                    f"this problem ({scale:.6e}, from the contract's stress "
                    f"scale {scales.stress_scale:g} and strain scale "
                    f"{scales.strain_scale:g}), so this is a zero of that "
                    f"family; the generated value is {abs(oti_value):.3e}")
            else:
                judged_by = "tolerance"
                passed = (absolute_error <= ABSOLUTE_TOLERANCES[order]
                          or relative_error <= RELATIVE_TOLERANCE)
                justification = (
                    f"absolute error {absolute_error:.3e} against a tolerance "
                    f"of {ABSOLUTE_TOLERANCES[order]:.0e}, relative error "
                    f"{relative_error:.3e} against {RELATIVE_TOLERANCE:.0e}")
            rows.append(
                {
                    "increment": increment,
                    "branch": "plastic" if baseline.yielded else "elastic",
                    "stress_component": entry["stress_component"],
                    "order": order,
                    "directions": entry["directions"],
                    "recovery_factor": entry["recovery_factor"],
                    "oti_derivative": oti_value,
                    "fd_reference": reference_value,
                    "absolute_error": absolute_error,
                    "relative_error": relative_error,
                    "absolute_tolerance": ABSOLUTE_TOLERANCES[order],
                    "relative_tolerance": RELATIVE_TOLERANCE,
                    "family_scale": scale,
                    "structural_zero_floor": floor,
                    "judged_by": judged_by,
                    "passed": passed,
                    "justification": justification,
                }
            )
        state = J2State(stress=baseline.stress, statev=baseline.statev, stran=baseline.stran)
        reference_stress, reference_eqplas, _, _ = _integrate_increment_mp(
            reference_stress, reference_eqplas, dstran
        )
    return rows, history


#: Relative agreement demanded of a tangent entry the references resolve.
TANGENT_RELATIVE_TOLERANCE = 1.0e-9

#: Below this fraction of the largest entry of the same tangent, an entry is
#: not a small number -- it is a zero of the matrix. Without a scale the zero
#: test has nothing to compare against, and the 1e-75 rounding dust the
#: extended-precision reference leaves at a structural zero reads as a 100%
#: disagreement with the closed form's exact 0. That is an artefact of dividing
#: dust by dust, not a finding about the tangent.
TANGENT_ZERO_FRACTION = 1.0e-12


def _relative_paths(value: Any, work_dir: Path) -> Any:
    """Rewrite absolute paths so the record can be committed and compared.

    This evidence is published. An absolute path pins it to one account on one
    machine -- the committed copy of this file carried a home directory from a
    different user entirely -- and it makes two runs of the same round differ
    for no scientific reason. Paths inside the repository become repository
    relative; paths inside the scratch build become "<work>/name".
    """
    if isinstance(value, dict):
        return {key: _relative_paths(item, work_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [_relative_paths(item, work_dir) for item in value]
    if not isinstance(value, str) or not value.startswith("/"):
        return value
    candidate = Path(value)
    for root, prefix in ((work_dir.resolve(), "<work>"),
                         (REPO_ROOT, "")):
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        return f"{prefix}/{relative}" if prefix else str(relative)
    return candidate.name


def _tangent_summary(rows: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    resolved = [r for r in rows if r["reference_classification"] == "resolved"]
    measured = [r for r in resolved if r["judged_by"] == "relative"]
    return {
        "entries": len(rows),
        "resolved": len(resolved),
        "reference_unresolved":
            sum(1 for r in rows
                if r["reference_classification"] == "reference_unresolved"),
        "structural_zeros": len(resolved) - len(measured),
        "structural_zeros_disagreeing":
            sum(1 for r in resolved
                if r["judged_by"] == "structural_zero" and r["agrees"] is False),
        "measured": len(measured),
        "agreeing": sum(1 for r in resolved if r["agrees"]),
        "disagreeing": sum(1 for r in resolved if r["agrees"] is False),
        "worst_measured_relative_error":
            max((r["relative_error"] for r in measured), default=None),
        # Only over the entries the spread actually adjudicates. At a
        # structural zero the ratio is dust over dust and is always about 1,
        # which would make the references look far worse than they are.
        "worst_reference_spread_relative_where_measured":
            max((r["reference_spread_relative"] for r in measured), default=None),
        "relative_tolerance": TANGENT_RELATIVE_TOLERANCE,
        "references": [
            "closed-form elastoplastic consistent tangent from "
            "umat_oti.validation.j2_reference",
            "80-digit centred difference of the independent integrator "
            "umat_oti.validation.actual_umat_higher_order._integrate_increment_mp",
        ],
        "csv": str(path),
    }


def _read_tangent(path: Path) -> dict[tuple[int, int, int], float]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {(int(row["increment"]), int(row["row"]), int(row["column"])):
                float(row["value"]) for row in csv.DictReader(handle)}


def _compare_tangent(
    tangent: dict[tuple[int, int, int], float],
) -> list[dict[str, Any]]:
    """Check the consistent tangent against two independent references.

    Nothing previously checked DDSDDE numerically for this model: the Abaqus
    paired runs compare the tangent between two builds that carry the same one,
    and the higher-order study starts at order two. A tangent both builds got
    wrong identically would have passed.

    Two references are used because they fail differently. The closed-form
    elastoplastic consistent tangent is exact but only correct if the algorithm
    it was derived for is the algorithm the UMAT implements. The 80-digit
    difference of the independent integrator makes no such assumption but is a
    difference, so it carries truncation. Agreement with both is what makes the
    check meaningful; where they disagree with each other, the entry is
    reported as unresolved rather than adjudicated.
    """
    params = J2Parameters(E=200000.0, nu=0.3, SIGY0=250.0, H=2000.0)
    state = J2State()
    mp.mp.dps = 80
    reference_stress = tuple(mp.mpf("0") for _ in range(6))
    reference_eqplas = mp.mpf("0")
    rows: list[dict[str, Any]] = []

    for increment, dstran in enumerate(J2_INCREMENTS, start=1):
        baseline = integrate_increment(params, state, dstran)
        branch = "plastic" if baseline.yielded else "elastic"
        analytic = baseline.ddsdde
        columns = {
            column: _finite_difference_response(
                reference_stress, reference_eqplas, dstran, (column,),
                step=mp.mpf("0.00002"))
            for column in range(1, 7)
        }
        matrix_scale = max(
            max(abs(float(analytic[i][j])) for j in range(6)) for i in range(6))
        matrix_scale = max(
            matrix_scale,
            max(abs(value) for column in columns.values() for value in column))
        for row_index in range(1, 7):
            for column in range(1, 7):
                oti_value = tangent.get((increment, row_index, column))
                analytic_value = float(analytic[row_index - 1][column - 1])
                numeric_value = columns[column][row_index - 1]
                rows.append(_tangent_row(increment, branch, row_index, column,
                                         oti_value, analytic_value, numeric_value,
                                         matrix_scale))
        state = J2State(stress=baseline.stress, statev=baseline.statev,
                        stran=baseline.stran)
        reference_stress, reference_eqplas, _, _ = _integrate_increment_mp(
            reference_stress, reference_eqplas, dstran)
    return rows


def _tangent_row(increment: int, branch: str, row_index: int, column: int,
                 oti_value: float | None, analytic: float, numeric: float,
                 matrix_scale: float) -> dict[str, Any]:
    """Adjudicate one tangent entry, or record why it cannot be adjudicated."""
    scale = max(abs(analytic), abs(numeric))
    floor = matrix_scale * TANGENT_ZERO_FRACTION
    # How far the two independent references sit from each other bounds how
    # finely they can adjudicate anything. Reporting an error smaller than that
    # spread would be claiming precision the references do not have.
    spread = abs(analytic - numeric)
    row: dict[str, Any] = {
        "increment": increment,
        "branch": branch,
        "row": row_index,
        "column": column,
        "oti": oti_value,
        "analytic_reference": analytic,
        "extended_precision_reference": numeric,
        "reference_spread": spread,
        "reference_spread_relative": spread / scale if scale else 0.0,
        "matrix_scale": matrix_scale,
        "structural_zero_floor": floor,
        "relative_tolerance": TANGENT_RELATIVE_TOLERANCE,
    }
    if oti_value is None:
        row.update({"absolute_error": None, "relative_error": None,
                    "reference_classification": "unresolved", "agrees": None,
                    "judged_by": None,
                    "justification": "the transformed build emitted no value here"})
        return row

    absolute = abs(oti_value - analytic)
    denominator = max(abs(analytic), abs(oti_value))
    row["absolute_error"] = absolute
    row["relative_error"] = absolute / denominator if denominator else 0.0

    if scale <= floor:
        # Both references put this entry at zero on the scale of the matrix it
        # belongs to. The value must be zero there too -- an OTI entry that is
        # not is a real disagreement, and is reported as one.
        row["reference_classification"] = "resolved"
        row["judged_by"] = "structural_zero"
        row["agrees"] = abs(oti_value) <= floor
        row["justification"] = (
            f"both references place this entry below {floor:.3e}, which is "
            f"{TANGENT_ZERO_FRACTION:.0e} of the largest entry of the same "
            f"tangent ({matrix_scale:.6e}), so it is a zero of the matrix; the "
            f"value is {abs(oti_value):.3e}")
        return row

    if scale and spread / scale > TANGENT_RELATIVE_TOLERANCE:
        row.update({"reference_classification": "reference_unresolved",
                    "agrees": None, "judged_by": None,
                    "justification":
                        f"the two references differ from each other by "
                        f"{spread / scale:.3e} relative, which is coarser than "
                        f"the {TANGENT_RELATIVE_TOLERANCE:.0e} being asked of "
                        "the value, so neither can adjudicate this entry"})
        return row

    row["reference_classification"] = "resolved"
    row["judged_by"] = "relative"
    row["agrees"] = row["relative_error"] <= TANGENT_RELATIVE_TOLERANCE
    row["justification"] = (
        f"relative error against the closed-form consistent tangent, with a "
        f"denominator of max(|reference|,|oti|) = {denominator:.6e}; the "
        f"extended-precision difference confirms the reference to "
        f"{spread / scale:.3e} relative")
    return row


def _finite_difference_response(
    stress: tuple[mp.mpf, ...],
    eqplas: mp.mpf,
    dstran: Sequence[float],
    directions: tuple[int, ...],
    *,
    step: mp.mpf,
) -> tuple[float, ...]:
    multiplicities = {direction: directions.count(direction) for direction in sorted(set(directions))}
    nodes = tuple(mp.mpf(value) for value in range(-4, 5))
    weighted_nodes: list[tuple[int, tuple[mp.mpf, ...]]] = []
    for direction, derivative_order in multiplicities.items():
        matrix = mp.matrix([[node**power for node in nodes] for power in range(len(nodes))])
        rhs = mp.matrix([mp.mpf(math.factorial(derivative_order)) if power == derivative_order else 0 for power in range(len(nodes))])
        solved = mp.lu_solve(matrix, rhs)
        weights = tuple(solved[index] / (step**derivative_order) for index in range(len(nodes)))
        weighted_nodes.append((direction, weights))

    result = [mp.mpf("0") for _ in range(6)]
    for node_indices in itertools.product(range(len(nodes)), repeat=len(weighted_nodes)):
        perturbed = [mp.mpf(str(value)) for value in dstran]
        weight = mp.mpf("1")
        for (direction, weights), node_index in zip(weighted_nodes, node_indices):
            perturbed[direction - 1] += nodes[node_index] * step
            weight *= weights[node_index]
        perturbed_stress, _, _, _ = _integrate_increment_mp(stress, eqplas, perturbed)
        for component in range(6):
            result[component] += weight * perturbed_stress[component]
    return tuple(float(value) for value in result)


def _integrate_increment_mp(
    stress: tuple[mp.mpf, ...],
    eqplas: mp.mpf,
    dstran: Sequence[float | mp.mpf],
) -> tuple[tuple[mp.mpf, ...], mp.mpf, bool, mp.mpf]:
    young = mp.mpf("200000")
    poisson = mp.mpf("0.3")
    yield_stress = mp.mpf("250")
    hardening = mp.mpf("2000")
    lame = young * poisson / ((1 + poisson) * (1 - 2 * poisson))
    shear = young / (2 * (1 + poisson))
    strain = tuple(mp.mpf(value) for value in dstran)
    trial = (
        stress[0] + (lame + 2 * shear) * strain[0] + lame * strain[1] + lame * strain[2],
        stress[1] + lame * strain[0] + (lame + 2 * shear) * strain[1] + lame * strain[2],
        stress[2] + lame * strain[0] + lame * strain[1] + (lame + 2 * shear) * strain[2],
        stress[3] + shear * strain[3],
        stress[4] + shear * strain[4],
        stress[5] + shear * strain[5],
    )
    pressure = (trial[0] + trial[1] + trial[2]) / 3
    deviator = (trial[0] - pressure, trial[1] - pressure, trial[2] - pressure, trial[3], trial[4], trial[5])
    q_trial = mp.sqrt(
        mp.mpf("1.5") * sum(value * value for value in deviator[:3])
        + 3 * sum(value * value for value in deviator[3:])
    )
    phi = q_trial - (yield_stress + hardening * eqplas)
    if phi <= 0 or q_trial <= 0:
        return trial, eqplas, False, mp.mpf("0")
    dgamma = phi / (3 * shear + hardening)
    scale = 3 * shear * dgamma / q_trial
    updated = (
        deviator[0] * (1 - scale) + pressure,
        deviator[1] * (1 - scale) + pressure,
        deviator[2] * (1 - scale) + pressure,
        deviator[3] * (1 - scale),
        deviator[4] * (1 - scale),
        deviator[5] * (1 - scale),
    )
    return updated, eqplas + dgamma, True, dgamma


def _read_oti_higher_order(path: Path) -> dict[tuple[int, int, tuple[int, ...], int], float]:
    result: dict[tuple[int, int, tuple[int, ...], int], float] = {}
    increment = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.split()
        if not parts:
            continue
        if parts[0] == "#":
            increment += 1
            continue
        component = int(parts[0])
        order = int(parts[1])
        directions = tuple(int(value) for value in parts[2 : 2 + order])
        result[(increment, order, directions, component)] = float(parts[2 + order].replace("D", "E"))
    return result


def _read_primal(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_comparisons(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_table(path: Path, rows: list[dict[str, Any]]) -> None:
    summary: list[dict[str, Any]] = []
    for branch in ("elastic", "plastic"):
        for order in (2, 3, 4):
            selected = [row for row in rows if row["branch"] == branch and row["order"] == order]
            significant = [row["relative_error"] for row in selected
                           if row["judged_by"] == "tolerance"
                           and row["absolute_error"] > row["absolute_tolerance"]]
            structural = [row for row in selected
                          if row["judged_by"] == "structural_zero"]
            summary.append(
                {
                    "model": "controlled_j2_actual_umat",
                    "branch": branch,
                    "order": order,
                    "comparison_rows": len(selected),
                    "passed_rows": sum(1 for row in selected if row["passed"]),
                    "failed_rows": sum(1 for row in selected if not row["passed"]),
                    "max_absolute_error": max((row["absolute_error"] for row in selected), default=0.0),
                    "max_relative_error_when_absolute_tolerance_exceeded": max(significant, default=0.0),
                    "rows_judged_by_tolerance": len(selected) - len(structural),
                    "rows_that_are_zeros_of_their_family": len(structural),
                    "structural_zero_fraction": HIGHER_ORDER_ZERO_FRACTION,
                    "absolute_tolerance": ABSOLUTE_TOLERANCES[order],
                    "relative_tolerance": RELATIVE_TOLERANCE,
                    "reference_method": "independent_high_precision_centered_finite_difference",
                }
            )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _driver_source() -> str:
    increments = ", &\n       ".join(
        ", ".join(f"{value:.17E}_8" for value in values) for values in J2_INCREMENTS
    )
    return f'''PROGRAM actual_umat_higher_order_driver
  IMPLICIT NONE
  INTEGER, PARAMETER :: NTENS=6, NSTATV=1, NPROPS=4, NINC={len(J2_INCREMENTS)}
  REAL(8) :: STRESS(NTENS), STATEV(NSTATV), DDSDDE(NTENS,NTENS)
  REAL(8) :: SSE, SPD, SCD, RPL, DDSDDT(NTENS), DRPLDE(NTENS), DRPLDT
  REAL(8) :: STRAN(NTENS), DSTRAN(NTENS), TIME(2), DTIME, TEMP, DTEMP
  REAL(8) :: PREDEF(1), DPRED(1), PROPS(NPROPS), COORDS(3), DROT(3,3)
  REAL(8) :: PNEWDT, CELENT, DFGRD0(3,3), DFGRD1(3,3)
  REAL(8) :: PATH(NTENS,NINC)
  INTEGER :: NDI, NSHR, NOEL, NPT, LAYER, KSPT, KSTEP, KINC, I, INC, U
  INTEGER :: UT, IR, IC
  CHARACTER(80) :: CMNAME
  DATA PATH / {increments} /
  STRESS=0.0_8; STATEV=0.0_8; DDSDDE=0.0_8; STRAN=0.0_8; DSTRAN=0.0_8
  SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8; DDSDDT=0.0_8
  DRPLDE=0.0_8; DRPLDT=0.0_8; TIME=0.0_8; DTIME=1.0_8
  TEMP=293.15_8; DTEMP=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PROPS=(/200000.0_8,0.3_8,250.0_8,2000.0_8/)
  COORDS=0.0_8; DROT=0.0_8; DFGRD0=0.0_8; DFGRD1=0.0_8
  DO I=1,3
    DROT(I,I)=1.0_8; DFGRD0(I,I)=1.0_8; DFGRD1(I,I)=1.0_8
  END DO
  PNEWDT=1.0_8; CELENT=1.0_8; CMNAME='J2_ACTUAL_HIGHER_ORDER'
  NDI=3; NSHR=3; NOEL=1; NPT=1; LAYER=1; KSPT=1; KSTEP=1
  OPEN(NEWUNIT=U,FILE='actual_umat_primal.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(U,'(A)') 'increment,stress_1,stress_2,stress_3,stress_4,stress_5,stress_6,eqplas'
  OPEN(NEWUNIT=UT,FILE='actual_umat_ddsdde.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(UT,'(A)') 'increment,row,column,value'
  DO INC=1,NINC
    DSTRAN=PATH(:,INC); KINC=INC
    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
      NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
      NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
    WRITE(U,'(I0,7(",",ES24.16))') INC,STRESS,STATEV(1)
    DO IR=1,NTENS
      DO IC=1,NTENS
        WRITE(UT,'(I0,",",I0,",",I0,",",ES24.16)') INC,IR,IC,DDSDDE(IR,IC)
      END DO
    END DO
    STRAN=STRAN+DSTRAN; TIME(1)=TIME(1)+DTIME; TIME(2)=TIME(2)+DTIME
  END DO
  CLOSE(U)
  CLOSE(UT)
END PROGRAM actual_umat_higher_order_driver

SUBROUTINE GETOUTDIR(PATH,NCHAR)
  IMPLICIT NONE
  CHARACTER(*) :: PATH
  INTEGER :: NCHAR
  PATH='.'
  NCHAR=1
END SUBROUTINE GETOUTDIR
'''


__all__ = ["run_actual_j2_higher_order_evidence"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate actual transformed-J2 orders 2-4 evidence.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = run_actual_j2_higher_order_evidence(args.config, args.output_dir)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "verified_from_generic_transformed_source" else 1


if __name__ == "__main__":
    raise SystemExit(main())
