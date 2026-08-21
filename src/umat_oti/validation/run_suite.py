"""Unified Abaqus validation entry point.

Provides ``python -m umat_oti.validation.run_suite`` — a single command that:

1. Detects the current environment (Fortran compiler, Abaqus executable).
2. Runs the offline suite (Python tests + 19-contract transformation batch).
3. Runs the Abaqus paired validation, when an ``--abaqus-command`` is available,
   for every contract in ``benchmarks/`` that carries a validation block.
4. Emits an explicit JSON/Markdown report with, per contract:

   * status: ``passed``, ``failed``, ``skipped``, ``blocked``
   * reason: precise, one-line explanation
   * environment metadata (Fortran compiler, Abaqus command / version)

When Abaqus or a Fortran compiler is not available, the corresponding suite
is *skipped* with an explicit reason -- never falsely reported as a pass.
This matches the SoftwareX rule:

    "A missing package, compiler, OTILib installation, or Abaqus license is
     not a passing test. Report it as a named environmental blocker."
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from umat_oti.validation.abaqus import find_fortran_compiler


@dataclass
class EnvironmentReport:
    fortran_compiler: Optional[str]
    fortran_compiler_version: str
    abaqus_command: Optional[str]
    abaqus_ok: bool
    abaqus_message: str


@dataclass
class SuiteResult:
    name: str
    status: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def detect_environment(abaqus_command: str = "abaqus") -> EnvironmentReport:
    compiler = find_fortran_compiler()
    compiler_version = ""
    if compiler:
        try:
            proc = subprocess.run(
                [compiler, "--version"], check=False, capture_output=True, text=True, timeout=10
            )
            compiler_version = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
        except (OSError, subprocess.SubprocessError) as exc:
            compiler_version = f"<probe failed: {exc}>"
    abaqus_binary = shutil.which(abaqus_command) if abaqus_command else None
    abaqus_ok = False
    abaqus_message = ""
    if abaqus_binary is None:
        abaqus_message = (
            f"Abaqus command {abaqus_command!r} not on PATH. Configure your "
            "site's Abaqus module (e.g. `module load abaqus/2024`) and rerun."
        )
    else:
        try:
            proc = subprocess.run(
                [abaqus_binary, "information=version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            abaqus_ok = proc.returncode == 0
            abaqus_message = (proc.stdout or proc.stderr or "").strip().splitlines()[:1]
            abaqus_message = abaqus_message[0] if abaqus_message else "Abaqus responded with no output."
            if not abaqus_ok:
                abaqus_message = (
                    f"Abaqus binary at {abaqus_binary} exited with code "
                    f"{proc.returncode}: {abaqus_message}"
                )
        except (OSError, subprocess.SubprocessError) as exc:
            abaqus_message = f"Failed to invoke Abaqus at {abaqus_binary}: {exc}"
    return EnvironmentReport(
        fortran_compiler=compiler,
        fortran_compiler_version=compiler_version.strip(),
        abaqus_command=abaqus_command,
        abaqus_ok=abaqus_ok,
        abaqus_message=abaqus_message,
    )


def run_python_tests(repo_root: Path, *, tests_target: Optional[Path] = None) -> SuiteResult:
    """Run the offline pytest suite.

    ``tests_target`` overrides the default (``repo_root / "tests"``) and is
    used by the run_suite self-tests to point the nested pytest at a
    non-recursive subset (avoiding an infinite pytest-in-pytest loop).
    """
    tests_dir = tests_target or (repo_root / "tests")
    if not tests_dir.exists():
        return SuiteResult(
            name="python_tests",
            status="blocked",
            reason=f"tests target not found: {tests_dir}",
        )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", str(tests_dir)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    status = "passed" if proc.returncode == 0 else "failed"
    return SuiteResult(
        name="python_tests",
        status=status,
        reason=("all offline tests passed" if status == "passed" else "pytest reported failures"),
        details={
            "returncode": proc.returncode,
            "stdout_tail": _tail(proc.stdout, 40),
            "stderr_tail": _tail(proc.stderr, 40),
        },
    )


def run_benchmark_batch(repo_root: Path) -> SuiteResult:
    """Run the 19-contract transformation batch."""
    tool = repo_root / "tools" / "run_completed_json_batch.py"
    if not tool.is_file():
        return SuiteResult(
            name="benchmark_batch",
            status="blocked",
            reason=f"batch runner not found at {tool}",
        )
    proc = subprocess.run(
        [sys.executable, str(tool)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    status = "passed" if proc.returncode == 0 else "failed"
    return SuiteResult(
        name="benchmark_batch",
        status=status,
        reason=(
            "all 19 completed benchmark contracts transformed successfully"
            if status == "passed"
            else "one or more contracts failed to transform"
        ),
        details={
            "returncode": proc.returncode,
            "stdout_tail": _tail(proc.stdout, 30),
        },
    )


def run_abaqus_paired_validation(repo_root: Path, env: EnvironmentReport) -> SuiteResult:
    """Run the paired-Abaqus validation when the environment is ready.

    In an environment without Abaqus (or without a Fortran compiler), this
    returns a ``blocked`` result with a precise reason. It never returns
    ``passed`` on a missing environment.
    """
    if env.fortran_compiler is None:
        return SuiteResult(
            name="abaqus_paired_validation",
            status="blocked",
            reason="no Fortran compiler on PATH (need gfortran, ifort or ifx)",
        )
    if not env.abaqus_ok:
        return SuiteResult(
            name="abaqus_paired_validation",
            status="blocked",
            reason=env.abaqus_message,
        )
    tool = repo_root / "tools" / "run_completed_json_batch.py"
    proc = subprocess.run(
        [sys.executable, str(tool), "--validate", "--abaqus-command", env.abaqus_command or "abaqus"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    status = "passed" if proc.returncode == 0 else "failed"
    return SuiteResult(
        name="abaqus_paired_validation",
        status=status,
        reason=(
            "paired Abaqus validation succeeded for every contract with a validation block"
            if status == "passed"
            else "one or more Abaqus paired validations failed"
        ),
        details={
            "returncode": proc.returncode,
            "stdout_tail": _tail(proc.stdout, 30),
        },
    )


def run_suite(
    *,
    repo_root: Path,
    abaqus_command: str = "abaqus",
    include_abaqus: bool = True,
    report_path: Optional[Path] = None,
    tests_target: Optional[Path] = None,
    include_benchmark_batch: bool = True,
) -> dict[str, Any]:
    env = detect_environment(abaqus_command=abaqus_command)
    results: list[SuiteResult] = []
    results.append(run_python_tests(repo_root, tests_target=tests_target))
    if include_benchmark_batch:
        results.append(run_benchmark_batch(repo_root))
    else:
        results.append(
            SuiteResult(
                name="benchmark_batch",
                status="skipped",
                reason="Benchmark batch skipped by caller.",
            )
        )
    if include_abaqus:
        results.append(run_abaqus_paired_validation(repo_root, env))
    else:
        results.append(
            SuiteResult(
                name="abaqus_paired_validation",
                status="skipped",
                reason="Abaqus validation not requested (--no-abaqus).",
            )
        )
    report = {
        "environment": asdict(env),
        "suites": [asdict(r) for r in results],
        "overall_status": _overall(results),
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _overall(results: list[SuiteResult]) -> str:
    if any(r.status == "failed" for r in results):
        return "failed"
    if all(r.status == "passed" for r in results):
        return "passed"
    if any(r.status == "passed" for r in results):
        return "partial"
    return "blocked"


def _tail(text: str, n: int) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m umat_oti.validation.run_suite",
        description="Run the UMAT-OTI offline + Abaqus validation suite with honest environment detection.",
    )
    parser.add_argument(
        "--abaqus-command",
        default="abaqus",
        help="Command used to invoke Abaqus (defaults to 'abaqus'). Set to any executable on your PATH.",
    )
    parser.add_argument(
        "--no-abaqus",
        action="store_true",
        help="Skip Abaqus paired validation even if it appears available.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root (defaults to the containing UMAT-OTI checkout).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write a JSON report to this path (in addition to stdout).",
    )
    args = parser.parse_args(argv)
    report = run_suite(
        repo_root=args.repo_root,
        abaqus_command=args.abaqus_command,
        include_abaqus=not args.no_abaqus,
        report_path=args.report,
    )
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["overall_status"] in {"passed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
