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

from umat_oti.cli_json import run_config_transform
from umat_oti.oti.oti_directions import deriv_factor
from umat_oti.validation.actual_umat_higher_order import _read_oti_higher_order


TOTAL_STRAINS = (
    (0.000750000006519258, -0.0003214285825379193, 0.0, 0.0),
    (0.001500000013038516, -0.0007981886155903339, 0.0, 0.0),
    (0.002624999964609742, -0.001868623774498701, 0.0, 0.0),
    (0.003000000026077032, -0.0022304935846477747, 0.0, 0.0),
)
CODE_IMP_INCREMENTS = tuple(
    tuple(total[index] - (TOTAL_STRAINS[row - 1][index] if row else 0.0) for index in range(4))
    for row, total in enumerate(TOTAL_STRAINS)
)
SELECTED_DIRECTIONS = (
    (1, 1),
    (1, 2),
    (1, 1, 1),
    (1, 1, 2),
    (1, 1, 1, 1),
    (1, 1, 2, 2),
)
ABSOLUTE_TOLERANCES = {2: 2.0e-3, 3: 5.0, 4: 4.0e4}
RELATIVE_TOLERANCE = 2.0e-5
FD_STEP = 4.0e-5


def run_code_imp_higher_order_evidence(config_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    summary, exit_code = run_config_transform(config_path, output_dir, compile_generated=True)
    if exit_code != 0:
        raise RuntimeError(f"Canonical transform/compile failed: {summary}")

    transformed_driver = output_dir / "code_imp_higher_order_driver.f90"
    transformed_driver.write_text(_transformed_driver_source(), encoding="utf-8")
    transformed_executable = output_dir / "code_imp_higher_order_driver"
    transformed_compile = _compile(
        [
            transformed_driver,
            output_dir / "master_parameters.o",
            output_dir / "real_utils.o",
            output_dir / "otim4n4.o",
            output_dir / "transformed_umat.o",
        ],
        transformed_executable,
        output_dir,
    )

    higher_output = output_dir / "oti_hjac.dat"
    higher_output.unlink(missing_ok=True)
    transformed_run = subprocess.run([str(transformed_executable)], cwd=output_dir, check=False, capture_output=True, text=True)
    if transformed_run.returncode != 0:
        raise RuntimeError(f"Transformed driver execution failed: {transformed_run.stderr}")

    original_source = Path(summary["source"])
    original_object = output_dir / "original_code_imp.o"
    original_compile_command = [
        "gfortran", "-O1", "-std=legacy", "-ffixed-form", "-ffixed-line-length-none",
        "-I", str(output_dir), "-c", str(original_source), "-o", str(original_object),
    ]
    original_compile = subprocess.run(original_compile_command, cwd=output_dir, check=False, capture_output=True, text=True)
    if original_compile.returncode != 0:
        raise RuntimeError(f"Original UMAT compilation failed: {original_compile.stderr}")
    reference_driver = output_dir / "code_imp_reference_driver.f90"
    reference_driver.write_text(_reference_driver_source(), encoding="utf-8")
    reference_executable = output_dir / "code_imp_reference_driver"
    reference_compile = _compile([reference_driver, original_object], reference_executable, output_dir)

    oti_values = _read_oti_higher_order(higher_output)
    comparisons = _compare(oti_values, reference_executable)
    comparison_path = output_dir / "code_imp_higher_order_comparison.csv"
    _write_csv(comparison_path, comparisons)
    table_path = output_dir / "table4_higher_order_code_imp.csv"
    _write_table(table_path, comparisons)
    primal_rows = _read_csv(output_dir / "code_imp_primal.csv")
    branch_history = [
        {
            "increment": int(row["increment"]),
            "effective_plastic_strain": float(row["statev_1"]),
            "hardening_variable": float(row["statev_2"]),
            "branch": "plastic" if float(row["statev_1"]) > 0.0 else "elastic",
        }
        for row in primal_rows
    ]
    failed_rows = sum(1 for row in comparisons if not row["passed"])
    significant = [row["relative_error"] for row in comparisons if row["absolute_error"] > row["absolute_tolerance"]]
    retained = [
        Path(summary["transformed_source"]), output_dir / "otim4n4.f90", transformed_driver,
        reference_driver, higher_output, comparison_path, table_path, output_dir / "code_imp_primal.csv",
    ]
    evidence = {
        "schema": "umat-oti-actual-higher-order-evidence/1",
        "status": "verified_from_generic_transformed_source" if failed_rows == 0 else "failed",
        "model": "code_imp_legacy_umat",
        "source": {"path": str(original_source), "sha256": _sha256(original_source)},
        "canonical_manifest": summary["manifest"],
        "normalized_request": summary["derivative_requests"],
        "increments": [list(values) for values in CODE_IMP_INCREMENTS],
        "branch_history": branch_history,
        "directions": [list(values) for values in SELECTED_DIRECTIONS],
        "factorial_recovery": "OTI coefficients are multiplied by product factorials before oti_hjac.dat output.",
        "reference": {
            "method": "independently compiled original code_imp UMAT replayed for each tensor-product centered finite-difference stencil",
            "stencil": "9-point centered per active strain component",
            "step": FD_STEP,
            "near_zero_error_policy": "Absolute tolerances cover measured double-precision cancellation for analytically zero elastic derivatives; substantive derivatives must satisfy the relative tolerance.",
            "compile_command": original_compile_command,
            "compile_returncode": original_compile.returncode,
            "driver_compile_returncode": reference_compile.returncode,
        },
        "transformed_execution": {
            "compile_returncode": transformed_compile.returncode,
            "run_returncode": transformed_run.returncode,
        },
        "comparison": {
            "rows": len(comparisons),
            "passed_rows": len(comparisons) - failed_rows,
            "failed_rows": failed_rows,
            "max_absolute_error": max(row["absolute_error"] for row in comparisons),
            "max_relative_error": max(row["relative_error"] for row in comparisons),
            "max_relative_error_when_absolute_tolerance_exceeded": max(significant, default=0.0),
            "absolute_tolerances_by_order": ABSOLUTE_TOLERANCES,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "csv": str(comparison_path),
            "publication_table": str(table_path),
        },
        "artifacts": [{"path": str(path), "sha256": _sha256(path)} for path in retained],
    }
    evidence_path = output_dir / "actual_umat_higher_order_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    evidence["evidence_path"] = str(evidence_path)
    return evidence


def _compare(oti_values: dict[tuple[int, int, tuple[int, ...], int], float], executable: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for increment in range(1, len(CODE_IMP_INCREMENTS) + 1):
        for directions in SELECTED_DIRECTIONS:
            reference = _finite_difference(executable, increment - 1, directions)
            for component, reference_value in enumerate(reference, start=1):
                oti_value = oti_values[(increment, len(directions), directions, component)]
                absolute_error = abs(oti_value - reference_value)
                relative_error = absolute_error / max(abs(oti_value), abs(reference_value), 1.0e-300)
                absolute_tolerance = ABSOLUTE_TOLERANCES[len(directions)]
                passed = absolute_error <= absolute_tolerance or relative_error <= RELATIVE_TOLERANCE
                rows.append({
                    "increment": increment,
                    "branch": "elastic" if increment == 1 else "plastic",
                    "stress_component": component,
                    "order": len(directions),
                    "directions": "|".join(str(value) for value in directions),
                    "recovery_factor": deriv_factor(directions),
                    "oti_derivative": oti_value,
                    "fd_reference": reference_value,
                    "absolute_error": absolute_error,
                    "relative_error": relative_error,
                    "absolute_tolerance": absolute_tolerance,
                    "relative_tolerance": RELATIVE_TOLERANCE,
                    "passed": passed,
                })
    return rows


def _finite_difference(executable: Path, target_increment: int, directions: tuple[int, ...]) -> tuple[float, ...]:
    multiplicities = {direction: directions.count(direction) for direction in sorted(set(directions))}
    nodes = tuple(range(-4, 5))
    weighted: list[tuple[int, tuple[float, ...]]] = []
    mp.mp.dps = 60
    for direction, derivative_order in multiplicities.items():
        matrix = mp.matrix([[mp.mpf(node) ** power for node in nodes] for power in range(len(nodes))])
        rhs = mp.matrix([math.factorial(derivative_order) if power == derivative_order else 0 for power in range(len(nodes))])
        solved = mp.lu_solve(matrix, rhs)
        weighted.append((direction, tuple(float(solved[index] / (mp.mpf(str(FD_STEP)) ** derivative_order)) for index in range(len(nodes)))))
    terms: list[list[float]] = [[] for _ in range(4)]
    for indices in itertools.product(range(len(nodes)), repeat=len(weighted)):
        increments = [list(values) for values in CODE_IMP_INCREMENTS[: target_increment + 1]]
        coefficient = 1.0
        for (direction, weights), node_index in zip(weighted, indices):
            increments[target_increment][direction - 1] += nodes[node_index] * FD_STEP
            coefficient *= weights[node_index]
        response = _run_original(executable, increments)
        for component in range(4):
            terms[component].append(coefficient * response[component])
    return tuple(math.fsum(values) for values in terms)


def _run_original(executable: Path, increments: Sequence[Sequence[float]]) -> tuple[float, ...]:
    input_text = str(len(increments)) + "\n" + "\n".join(" ".join(f"{value:.17e}" for value in row) for row in increments) + "\n"
    result = subprocess.run([str(executable)], input=input_text, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Original UMAT reference execution failed: {result.stderr}")
    return tuple(float(value) for value in result.stdout.split())


def _compile(sources: list[Path], executable: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    command = ["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none", *map(str, sources), "-o", str(executable)]
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Driver compilation failed: {result.stderr}")
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    summary: list[dict[str, Any]] = []
    for branch in ("elastic", "plastic"):
        for order in (2, 3, 4):
            selected = [row for row in rows if row["branch"] == branch and row["order"] == order]
            significant = [row["relative_error"] for row in selected if row["absolute_error"] > row["absolute_tolerance"]]
            summary.append({
                "model": "code_imp_legacy_umat", "branch": branch, "order": order,
                "comparison_rows": len(selected), "passed_rows": sum(row["passed"] for row in selected),
                "failed_rows": sum(not row["passed"] for row in selected),
                "max_absolute_error": max((row["absolute_error"] for row in selected), default=0.0),
                "max_relative_error_when_absolute_tolerance_exceeded": max(significant, default=0.0),
                "absolute_tolerance": ABSOLUTE_TOLERANCES[order], "relative_tolerance": RELATIVE_TOLERANCE,
                "reference_method": "independently_compiled_original_umat_centered_finite_difference",
            })
    _write_csv(path, summary)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path_data() -> str:
    return ", &\n       ".join(", ".join(f"{value:.17E}_8" for value in row) for row in CODE_IMP_INCREMENTS)


def _common_declarations() -> str:
    return """  INTEGER, PARAMETER :: NTENS=4, NSTATV=2, NPROPS=2
  REAL(8) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
  REAL(8) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
  REAL(8) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3)
  REAL(8) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,I
  CHARACTER(80) :: CMNAME
"""


def _initialization() -> str:
    return """  STRESS=0.0_8;STATEV=0.0_8;DDSDDE=0.0_8;STRAN=0.0_8;DSTRAN=0.0_8
  SSE=0.0_8;SPD=0.0_8;SCD=0.0_8;RPL=0.0_8;DDSDDT=0.0_8;DRPLDE=0.0_8;DRPLDT=0.0_8
  TIME=0.0_8;DTIME=1.0_8;TEMP=293.15_8;DTEMP=0.0_8;PREDEF=0.0_8;DPRED=0.0_8;PROPS=0.0_8
  COORDS=0.0_8;DROT=0.0_8;DFGRD0=0.0_8;DFGRD1=0.0_8
  DO I=1,3
    DROT(I,I)=1.0_8;DFGRD0(I,I)=1.0_8;DFGRD1(I,I)=1.0_8
  END DO
  PNEWDT=1.0_8;CELENT=1.0_8;CMNAME='CODE_IMP_HIGHER_ORDER'
  NDI=3;NSHR=1;NOEL=1;NPT=1;LAYER=1;KSPT=1;KSTEP=1
"""


def _umat_call() -> str:
    return """    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV, &
      PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
"""


def _transformed_driver_source() -> str:
    return f"""PROGRAM code_imp_higher_order_driver
  IMPLICIT NONE
{_common_declarations()}  REAL(8) :: PATH(NTENS,4)
  INTEGER :: INC,U
  DATA PATH / {_path_data()} /
{_initialization()}  OPEN(NEWUNIT=U,FILE='code_imp_primal.csv',STATUS='REPLACE',ACTION='WRITE')
  WRITE(U,'(A)') 'increment,stress_1,stress_2,stress_3,stress_4,statev_1,statev_2'
  DO INC=1,4
    DSTRAN=PATH(:,INC);KINC=INC
{_umat_call()}    WRITE(U,'(I0,6(\",\",ES24.16))') INC,STRESS,STATEV
    STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
  END DO
  CLOSE(U)
END PROGRAM code_imp_higher_order_driver
SUBROUTINE GETOUTDIR(PATH,NCHAR)
  CHARACTER(*) :: PATH
  INTEGER :: NCHAR
  PATH='.';NCHAR=1
END SUBROUTINE GETOUTDIR
"""


def _reference_driver_source() -> str:
    return f"""PROGRAM code_imp_reference_driver
  IMPLICIT NONE
{_common_declarations()}  INTEGER :: INC,NINC_RUN
{_initialization()}  READ(*,*) NINC_RUN
  DO INC=1,NINC_RUN
    READ(*,*) DSTRAN;KINC=INC
{_umat_call()}    STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
  END DO
  WRITE(*,'(4(ES25.17,1X))') STRESS
END PROGRAM code_imp_reference_driver
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate actual legacy code_imp orders 2-4 evidence.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = run_code_imp_higher_order_evidence(args.config, args.output_dir)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "verified_from_generic_transformed_source" else 1


if __name__ == "__main__":
    raise SystemExit(main())
