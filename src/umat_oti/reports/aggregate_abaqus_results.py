"""Aggregate paired-Abaqus validation results into a paper-ready table.

Reads each ``paper_results/arc_<jobid>/paired_batch/validation/<name>/validation_report.json``
and produces a single ``table2_ddsdde_abaqus.csv`` + JSON summary that
records, per UMAT case:

  - the source .inp path
  - the transformed .inp path
  - the Abaqus job's returncode / status
  - STRESS max abs / max rel difference vs. the original UMAT
  - STATEV comparison status
  - DDSDDE max abs / max rel difference
  - convergence match
  - overall pass / fail
  - provenance: Slurm job id, submission time, evaluator, commit hash

The evidence command consumes this table when building the SoftwareX
claim matrix so ``abaqus_paired_stress_state_ddsdde_j2`` is marked
``verified_from_transformed_source`` only if the real Abaqus job passed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


PROVENANCE_KEYS = (
    "case_name",
    "slurm_job_id",
    "hostname",
    "commit_sha",
    "generated_at",
    "abaqus_command",
    "compiler",
)


def aggregate_abaqus_results(
    arc_dir: Path,
    *,
    output_csv: Path,
    output_json: Path,
    commit_sha: str = "",
) -> dict[str, Any]:
    """Walk ``arc_dir/paired_batch/validation/*/validation_report.json`` and emit
    per-case pass/fail metrics with provenance."""
    validation_dir = arc_dir / "paired_batch" / "validation"
    if not validation_dir.is_dir():
        raise FileNotFoundError(f"no paired_batch/validation dir under {arc_dir}")

    slurm_job_id = arc_dir.name.replace("arc_", "")
    system_path = arc_dir / "system.txt"
    hostname = ""
    compiler = ""
    if system_path.is_file():
        for line in system_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("hostname="):
                hostname = line.split("=", 1)[1].strip()
            elif "GNU Fortran" in line and not compiler:
                compiler = line.strip()

    rows: list[dict[str, Any]] = []
    for case_dir in sorted(validation_dir.iterdir()):
        report = case_dir / "validation_report.json"
        if not report.is_file():
            rows.append(
                {
                    "case_name": case_dir.name,
                    "slurm_job_id": slurm_job_id,
                    "status": "no_report",
                    "note": "validation_report.json missing",
                }
            )
            continue
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rows.append(
                {
                    "case_name": case_dir.name,
                    "slurm_job_id": slurm_job_id,
                    "status": "invalid_report",
                    "note": str(exc),
                }
            )
            continue
        row = _flatten_report(data, case_dir, slurm_job_id, hostname, compiler, commit_sha)
        rows.append(row)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    field_order = list(PROVENANCE_KEYS) + [
        "status",
        "stress_status",
        "stress_max_abs_diff",
        "stress_max_rel_diff",
        "statev_status",
        "ddsdde_status",
        "ddsdde_max_abs_diff",
        "ddsdde_max_rel_diff",
        "convergence_status",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=field_order, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    summary = {
        "total": len(rows),
        "passed": sum(1 for r in rows if r.get("status") == "passed"),
        "failed": sum(1 for r in rows if r.get("status") == "failed"),
        "failed_execution": sum(1 for r in rows if r.get("status") == "failed_execution"),
        "no_report": sum(1 for r in rows if r.get("status") == "no_report"),
    }
    output_json.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {"summary": summary, "csv": str(output_csv), "json": str(output_json)}


def _flatten_report(
    data: dict[str, Any],
    case_dir: Path,
    slurm_job_id: str,
    hostname: str,
    compiler: str,
    commit_sha: str,
) -> dict[str, Any]:
    stress = data.get("stress_comparison", {}) or {}
    statev = data.get("state_variable_comparison", {}) or {}
    ddsdde = data.get("ddsdde_comparison", {}) or {}
    convergence = data.get("convergence_comparison", {}) or {}
    comparison_status = data.get("comparison_status", {}) or {}
    overall_status = "passed" if data.get("final_pass") else comparison_status.get("status", data.get("status", "failed"))
    audit = _audit_record(data, case_dir)
    return {
        "case_name": case_dir.name,
        "slurm_job_id": slurm_job_id,
        "hostname": hostname,
        "compiler": compiler,
        "commit_sha": commit_sha,
        "generated_at": data.get("generated_at", ""),
        "abaqus_command": data.get("abaqus_command", "abaqus"),
        "status": overall_status,
        "stress_status": stress.get("status", ""),
        "stress_max_abs_diff": stress.get("max_abs_difference"),
        "stress_max_rel_diff": stress.get("max_rel_difference"),
        "statev_status": statev.get("status", ""),
        "ddsdde_status": ddsdde.get("status", ""),
        "ddsdde_max_abs_diff": ddsdde.get("max_abs_difference"),
        "ddsdde_max_rel_diff": ddsdde.get("max_rel_difference"),
        "convergence_status": convergence.get("status", ""),
        "audit": audit,
    }


def _audit_record(data: dict[str, Any], case_dir: Path) -> dict[str, Any]:
    generated = data.get("generated_files", {}) or {}
    original_source = _file_identity(_optional_path(data.get("original_umat_path")))
    transformed_source = _file_identity(_optional_path(data.get("transformed_umat_path")))
    original_user_path = _optional_path(generated.get("instrumented_original_user"))
    transformed_user_path = _optional_path(generated.get("combined_oti_user"))
    original_user = _file_identity(original_user_path)
    transformed_user = _file_identity(transformed_user_path)
    original_text = _read_text(original_user_path)
    transformed_text = _read_text(transformed_user_path)
    original_results_path = _optional_path(generated.get("original_results_json")) or case_dir / "original_results.json"
    transformed_results_path = _optional_path(generated.get("otis_results_json")) or case_dir / "otis_results.json"
    original_matrix = _final_matrix(_load_json(original_results_path))
    transformed_matrix = _final_matrix(_load_json(transformed_results_path))
    compiled_artifacts = [
        _file_identity(path)
        for path in sorted(case_dir.iterdir())
        if path.suffix.lower() in {".o", ".obj", ".so", ".dll", ".a"}
    ]
    log_names = (
        "original_abaqus_stdout.log",
        "original_abaqus_stderr.log",
        "otis_abaqus_stdout.log",
        "otis_abaqus_stderr.log",
        "original_umat_validation.msg",
        "otis_umat_validation.msg",
    )
    return {
        "working_directory": str(case_dir),
        "original_source": original_source,
        "transformed_source": transformed_source,
        "original_user_subroutine": original_user,
        "transformed_user_subroutine": transformed_user,
        "jobs": {
            "original": {"name": "original_umat_validation", "user_subroutine": original_user["path"]},
            "transformed": {"name": "otis_umat_validation", "user_subroutine": transformed_user["path"]},
        },
        "compiled_artifacts": compiled_artifacts,
        "compiled_artifact_status": "retained" if compiled_artifacts else "not_retained_by_abaqus_job",
        "compile_and_link_logs": [_file_identity(case_dir / name) for name in log_names],
        "transformed_source_checks": {
            "contains_oti_seeding": bool(re.search(r"DSTRAN_OTI\s*\([^)]*\)\s*=\s*DSTRAN_OTI\s*\([^)]*\)\s*\+\s*OTI_E", transformed_text, re.IGNORECASE)),
            "contains_getim_stress": bool(re.search(r"GETIM\s*\(\s*STRESS_OTI\s*\(", transformed_text, re.IGNORECASE)),
            "original_ddsdde_assignments": _matching_lines(original_text, r"^\s*DDSDDE\s*\([^)]*\)\s*="),
            "bypassed_ddsdde_assignments": _matching_lines(transformed_text, r"OTIS-SKIP:.*DDSDDE\s*\([^)]*\)\s*="),
            "compiled_ddsdde_extraction": _matching_lines(transformed_text, r"GETIM\s*\(\s*STRESS_OTI"),
            "validation_export": _matching_lines(transformed_text, r"STATEV\s*\([^)]*\)\s*=\s*DDSDDE"),
        },
        "result_extraction": _file_identity(_optional_path(generated.get("extract_results_script"))),
        "result_files_are_distinct": original_results_path.resolve() != transformed_results_path.resolve(),
        "original_results": _file_identity(original_results_path),
        "transformed_results": _file_identity(transformed_results_path),
        "original_final_ddsdde": original_matrix,
        "transformed_final_ddsdde": transformed_matrix,
        "absolute_difference": _matrix_difference(original_matrix, transformed_matrix, relative=False),
        "relative_difference": _matrix_difference(original_matrix, transformed_matrix, relative=True),
    }


def _optional_path(value: Any) -> Path | None:
    return Path(value) if value else None


def _file_identity(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "sha256": None, "exists": False}
    exists = path.is_file()
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
    return {"path": str(path), "sha256": digest, "exists": exists}


def _read_text(path: Path | None) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path and path.is_file() else ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _final_matrix(results: dict[str, Any]) -> list[list[float]]:
    increments = results.get("increments") if isinstance(results.get("increments"), list) else []
    payload = increments[-1] if increments else results
    matrix = payload.get("ddsdde", payload.get("final_ddsdde", [])) if isinstance(payload, dict) else []
    return [[float(value) for value in row] for row in matrix if isinstance(row, list)]


def _matrix_difference(left: list[list[float]], right: list[list[float]], *, relative: bool) -> list[list[float]]:
    result: list[list[float]] = []
    for left_row, right_row in zip(left, right):
        row: list[float] = []
        for left_value, right_value in zip(left_row, right_row):
            difference = abs(left_value - right_value)
            row.append(difference / max(abs(left_value), abs(right_value), 1.0) if relative else difference)
        result.append(row)
    return result


def _matching_lines(text: str, pattern: str) -> list[dict[str, Any]]:
    expression = re.compile(pattern, re.IGNORECASE)
    return [
        {"line": line_number, "source": line.strip()}
        for line_number, line in enumerate(text.splitlines(), start=1)
        if expression.search(line)
    ]


def _current_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m umat_oti.reports.aggregate_abaqus_results",
        description="Roll up paired-Abaqus paper_results/arc_<jobid> into one CSV + JSON.",
    )
    parser.add_argument("--arc-dir", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args(argv)
    result = aggregate_abaqus_results(
        args.arc_dir,
        output_csv=args.out_csv,
        output_json=args.out_json,
        commit_sha=_current_commit(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
