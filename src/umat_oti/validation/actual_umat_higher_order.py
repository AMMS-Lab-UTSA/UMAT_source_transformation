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
from umat_oti.validation.j2_reference import J2Parameters, J2State, integrate_increment


J2_INCREMENTS = (
    (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
    (2.0e-3, 0.0, 0.0, 0.0, 0.0, 0.0),
    (3.0e-4, -1.0e-4, 0.0, 2.0e-4, 0.0, 0.0),
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
    comparisons, branch_history = _compare_with_finite_difference(oti_values)
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
    ]
    max_abs = max(row["absolute_error"] for row in comparisons)
    max_rel = max(row["relative_error"] for row in comparisons)
    significant_relative_errors = [
        row["relative_error"]
        for row in comparisons
        if row["absolute_error"] > row["absolute_tolerance"]
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
            "absolute_tolerances_by_order": ABSOLUTE_TOLERANCES,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "csv": str(comparison_path),
            "publication_table": str(table_path),
        },
        "primal_rows": primal_rows,
        "artifacts": [
            {"path": str(path), "sha256": _sha256(path)} for path in generated_paths
        ],
    }
    evidence_path = output_dir / "actual_umat_higher_order_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def _compare_with_finite_difference(
    oti_values: dict[tuple[int, int, tuple[int, ...], int], float],
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
                absolute_error = abs(oti_value - reference_value)
                relative_error = absolute_error / max(abs(oti_value), abs(reference_value), 1.0e-300)
                passed = absolute_error <= ABSOLUTE_TOLERANCES[len(directions)] or relative_error <= RELATIVE_TOLERANCE
                rows.append(
                    {
                        "increment": increment,
                        "branch": "plastic" if baseline.yielded else "elastic",
                        "stress_component": component,
                        "order": len(directions),
                        "directions": "|".join(str(value) for value in directions),
                        "recovery_factor": factor,
                        "oti_derivative": oti_value,
                        "fd_reference": reference_value,
                        "absolute_error": absolute_error,
                        "relative_error": relative_error,
                        "absolute_tolerance": ABSOLUTE_TOLERANCES[len(directions)],
                        "relative_tolerance": RELATIVE_TOLERANCE,
                        "passed": passed,
                    }
                )
        state = J2State(stress=baseline.stress, statev=baseline.statev, stran=baseline.stran)
        reference_stress, reference_eqplas, _, _ = _integrate_increment_mp(
            reference_stress, reference_eqplas, dstran
        )
    return rows, history


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
            significant = [row["relative_error"] for row in selected if row["absolute_error"] > row["absolute_tolerance"]]
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
  INTEGER, PARAMETER :: NTENS=6, NSTATV=1, NPROPS=4, NINC=3
  REAL(8) :: STRESS(NTENS), STATEV(NSTATV), DDSDDE(NTENS,NTENS)
  REAL(8) :: SSE, SPD, SCD, RPL, DDSDDT(NTENS), DRPLDE(NTENS), DRPLDT
  REAL(8) :: STRAN(NTENS), DSTRAN(NTENS), TIME(2), DTIME, TEMP, DTEMP
  REAL(8) :: PREDEF(1), DPRED(1), PROPS(NPROPS), COORDS(3), DROT(3,3)
  REAL(8) :: PNEWDT, CELENT, DFGRD0(3,3), DFGRD1(3,3)
  REAL(8) :: PATH(NTENS,NINC)
  INTEGER :: NDI, NSHR, NOEL, NPT, LAYER, KSPT, KSTEP, KINC, I, INC, U
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
  DO INC=1,NINC
    DSTRAN=PATH(:,INC); KINC=INC
    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
      NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
      NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
    WRITE(U,'(I0,7(",",ES24.16))') INC,STRESS,STATEV(1)
    STRAN=STRAN+DSTRAN; TIME(1)=TIME(1)+DTIME; TIME(2)=TIME(2)+DTIME
  END DO
  CLOSE(U)
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
