"""Aggregate paired-Abaqus validation results into a paper-ready table.

Reads each ``paper_results/arc_<jobid>/paired_batch/validation/<name>/comparison_report.json``
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
import json
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
    """Walk ``arc_dir/paired_batch/validation/*/comparison_report.json`` and emit
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
        report = case_dir / "comparison_report.json"
        if not report.is_file():
            rows.append(
                {
                    "case_name": case_dir.name,
                    "slurm_job_id": slurm_job_id,
                    "status": "no_report",
                    "note": "comparison_report.json missing",
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
        row = _flatten_report(data, case_dir.name, slurm_job_id, hostname, compiler, commit_sha)
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
        writer = csv.DictWriter(fh, fieldnames=field_order, extrasaction="ignore")
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
    case_name: str,
    slurm_job_id: str,
    hostname: str,
    compiler: str,
    commit_sha: str,
) -> dict[str, Any]:
    stress = data.get("stress_comparison", {}) or {}
    statev = data.get("statev_comparison", {}) or {}
    ddsdde = data.get("ddsdde_comparison", {}) or {}
    convergence = data.get("convergence_comparison", {}) or {}
    overall_status = "passed" if data.get("pass") else data.get("status", "failed")
    return {
        "case_name": case_name,
        "slurm_job_id": slurm_job_id,
        "hostname": hostname,
        "compiler": compiler,
        "commit_sha": commit_sha,
        "generated_at": data.get("generated_at", ""),
        "abaqus_command": data.get("abaqus_command", "abaqus"),
        "status": overall_status,
        "stress_status": stress.get("status", ""),
        "stress_max_abs_diff": stress.get("max_absolute_difference"),
        "stress_max_rel_diff": stress.get("max_relative_difference"),
        "statev_status": statev.get("status", ""),
        "ddsdde_status": ddsdde.get("status", ""),
        "ddsdde_max_abs_diff": ddsdde.get("max_absolute_difference"),
        "ddsdde_max_rel_diff": ddsdde.get("max_relative_difference"),
        "convergence_status": convergence.get("status", ""),
    }


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
