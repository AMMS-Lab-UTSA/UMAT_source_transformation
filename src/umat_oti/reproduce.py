"""Reproduction entry point: ``python -m umat_oti.reproduce --profile <name>``.

A profile is a named, bounded claim about what can be regenerated and what it
costs. Each one writes the same five artefacts into its output directory, so a
reviewer compares runs rather than reading prose:

===========================  ==========================================
``run_manifest.json``        every step, its status, and why
``environment.json``         interpreter, compiler, platform, commit
``claim_matrix.json``        which published claim each step supports
``artifact_checksums.sha256``  SHA-256 of every file the run produced
``reproduction_summary.md``  the same thing in a page a human reads
===========================  ==========================================

Exit status distinguishes three outcomes, because collapsing them is how a
reproduction report comes to overstate itself:

``0``  every requested step succeeded, or was reported as unavailable for a
       stated external reason
``1``  a step that should have worked failed
``2``  the profile could not start at all

A step that needs Abaqus, or the network, or a compiler that is not installed,
reports ``blocked_by_external_dependency`` and does not fail the run. What it
must never do is silently vanish from the denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from umat_oti.pipeline.status import StageStatus

REPO_ROOT = Path(__file__).resolve().parents[2]

PROFILES = ("smoke", "offline", "paper", "corpus", "abaqus")


@dataclass
class StepResult:
    name: str
    status: str
    detail: str = ""
    seconds: float = 0.0
    supports: tuple[str, ...] = ()
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        payload = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
            "supports_claims": list(self.supports),
        }
        if self.status != StageStatus.SUCCEEDED.value:
            payload["reason"] = self.reason or self.detail
        return payload


@dataclass
class Step:
    name: str
    supports: tuple[str, ...]
    run: Callable[[Path], StepResult]


@dataclass
class ProfileRun:
    profile: str
    out_dir: Path
    steps: list[StepResult] = field(default_factory=list)


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

def _command_version(*command: str) -> Optional[str]:
    if shutil.which(command[0]) is None:
        return None
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or proc.stderr).strip().splitlines()[0] if proc.returncode == 0 else None


def capture_environment() -> dict:
    def git(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(["git", *args], cwd=REPO_ROOT,
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.strip() or None if proc.returncode == 0 else None

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gfortran": _command_version("gfortran", "--version"),
        "make": _command_version("make", "--version"),
        "abaqus": _command_version("abaqus", "information=release"),
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "worktree_clean": git("status", "--porcelain") == "" or None,
        "package_version": _package_version(),
    }


def _package_version() -> Optional[str]:
    try:
        from importlib.metadata import version
        return version("umat-oti")
    except Exception:  # noqa: BLE001 - an uninstalled source checkout is normal
        return None


# --------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------

def _need_gfortran() -> Optional[StepResult]:
    if shutil.which("gfortran") is None:
        return StepResult(
            name="", status=StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY.value,
            reason="gfortran is not on PATH; no Fortran build or execution is possible")
    return None


def step_import_package(out_dir: Path) -> StepResult:
    """The package must import from a clean interpreter before anything else."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import umat_oti, umat_oti.pipeline, umat_oti.transform.source_transform; "
         "print(umat_oti.__name__)"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    if proc.returncode != 0:
        return StepResult("import_package", StageStatus.FAILED.value,
                          reason=proc.stderr.strip()[:600])
    return StepResult("import_package", StageStatus.SUCCEEDED.value,
                      detail="umat_oti imports and its transform modules load")


def step_unit_tests(out_dir: Path) -> StepResult:
    """The offline suite, excluding anything needing Abaqus, ARC or the network."""
    log = out_dir / "pytest_offline.log"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m",
         "not abaqus and not arc and not network"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    tail = (proc.stdout.strip().splitlines() or ["no output"])[-1]
    if proc.returncode != 0:
        return StepResult("offline_test_suite", StageStatus.FAILED.value,
                          detail=tail, reason=f"pytest exited {proc.returncode}; see {log.name}")
    return StepResult("offline_test_suite", StageStatus.SUCCEEDED.value, detail=tail)


def step_fortran_smoke(out_dir: Path) -> StepResult:
    """Transform, compile and run one model end to end, and verify its derivatives.

    This is the smallest complete claim the software makes: a UMAT in, a
    numerically verified derivative out, checked against finite differences of
    the independently compiled original.
    """
    blocked = _need_gfortran()
    if blocked:
        return StepResult("material_point_smoke", blocked.status, reason=blocked.reason)
    log = out_dir / "smoke_sweep.log"
    # A one-model round must never land on the published Table 6 evidence.
    results = out_dir / "results"
    proc = subprocess.run(
        [sys.executable, "tools/run_parameter_sensitivity_sweep.py",
         "--model", "m3_j2", "--work-dir", str(out_dir / "work"),
         "--results-dir", str(results)],
        capture_output=True, text=True, cwd=REPO_ROOT)
    log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    round_file = results / "parameter_sensitivity_round.json"
    if proc.returncode != 0:
        return StepResult("material_point_smoke", StageStatus.FAILED.value,
                          reason=f"sweep exited {proc.returncode}; see {log.name}")
    try:
        payload = json.loads(round_file.read_text(encoding="utf-8"))
        record = next(m for m in payload["models"] if m["model"] == "m3_j2")
        status = record["stages"]["derivatives_verified"]["status"]
    except (OSError, KeyError, ValueError, StopIteration) as exc:
        return StepResult("material_point_smoke", StageStatus.FAILED.value,
                          reason=f"sweep produced no readable verdict for m3_j2: {exc}")
    if status != "succeeded":
        return StepResult("material_point_smoke", StageStatus.FAILED.value,
                          reason=f"m3_j2 derivatives_verified reported {status}")
    return StepResult("material_point_smoke", StageStatus.SUCCEEDED.value,
                      detail="m3_j2 transformed, compiled, executed and verified "
                             "against centred differences of the original build")


def _tool_step(name: str, script: str, supports: tuple[str, ...],
               artifact: str) -> Step:
    def run(out_dir: Path) -> StepResult:
        blocked = _need_gfortran()
        if blocked and name != "generality_matrix":
            return StepResult(name, blocked.status, reason=blocked.reason)
        log = out_dir / f"{name}.log"
        proc = subprocess.run([sys.executable, script], capture_output=True,
                              text=True, cwd=REPO_ROOT)
        log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        if proc.returncode != 0:
            return StepResult(name, StageStatus.FAILED.value, supports=supports,
                              reason=f"{script} exited {proc.returncode}; see {log.name}")
        produced = REPO_ROOT / artifact
        if not produced.is_file():
            return StepResult(name, StageStatus.FAILED.value, supports=supports,
                              reason=f"{script} produced no {artifact}")
        return StepResult(name, StageStatus.SUCCEEDED.value, supports=supports,
                          detail=f"regenerated {artifact}")
    return Step(name, supports, run)


def step_repository_audit(out_dir: Path) -> StepResult:
    proc = subprocess.run(
        [sys.executable, "tools/audit_repository_standards.py", "--json"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    (out_dir / "repository_audit.json").write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        try:
            failed = json.loads(proc.stdout)["failed"]
        except (ValueError, KeyError):
            failed = ["audit did not produce a report"]
        return StepResult("repository_audit", StageStatus.FAILED.value,
                          reason=f"failing checks: {', '.join(failed)}")
    return StepResult("repository_audit", StageStatus.SUCCEEDED.value,
                      detail="required files, no tracked build products, no secrets, "
                             "no absolute home paths outside archived records")


def step_abaqus(out_dir: Path) -> StepResult:
    if shutil.which("abaqus") is None:
        return StepResult(
            "abaqus_paired_validation",
            StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY.value,
            supports=("TABLE-2",),
            reason=("no Abaqus installation is on PATH. Paired validation needs a "
                    "licensed Abaqus and the documented ARC environment; the "
                    "archived evidence from Slurm job 791506 remains in "
                    "paper_results/arc_791506/ and is readable without it."))
    return StepResult("abaqus_paired_validation", StageStatus.UNSUPPORTED.value,
                      supports=("TABLE-2",),
                      reason=("an Abaqus installation was found, but paired validation "
                              "is driven by the ARC Slurm workflow in scripts/, not by "
                              "this entry point; see docs/SOFTWAREX_REPRODUCTION.md"))


def step_corpus(out_dir: Path) -> StepResult:
    return StepResult("corpus_round", StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY.value,
                      supports=("CORPUS",),
                      reason=("a corpus round fetches third-party sources over the "
                              "network and is subject to their licences and upstream "
                              "availability; it is not run as part of an offline "
                              "reproduction. Run it deliberately with "
                              "--profile corpus --allow-network."))


def build_steps(profile: str, allow_network: bool) -> list[Step]:
    smoke = [
        Step("import_package", ("INSTALL",), step_import_package),
        Step("material_point_smoke", ("TABLE-6",), step_fortran_smoke),
    ]
    if profile == "smoke":
        return smoke

    offline = smoke + [
        Step("offline_test_suite", ("INSTALL", "TABLE-3", "TABLE-6"), step_unit_tests),
        Step("repository_audit", ("REPO",), step_repository_audit),
    ]
    if profile == "offline":
        return offline

    if profile == "paper":
        return offline + [
            _tool_step("parameter_sensitivity_round",
                       "tools/run_parameter_sensitivity_sweep.py", ("TABLE-6",),
                       "paper_results/parameter_sensitivity/parameter_sensitivity_round.json"),
            _tool_step("internal_jacobian_round",
                       "tools/run_internal_jacobian_round.py", ("TABLE-3",),
                       "paper_results/internal_jacobians/table3_internal_jacobians.csv"),
            _tool_step("generality_matrix",
                       "tools/build_generality_matrix.py", ("GENERALITY",),
                       "paper_results/generality/generality_matrix.csv"),
            Step("abaqus_paired_validation", ("TABLE-2",), step_abaqus),
        ]

    if profile == "corpus":
        if not allow_network:
            return smoke + [Step("corpus_round", ("CORPUS",), step_corpus)]
        return smoke + [Step("corpus_round", ("CORPUS",), step_corpus)]

    return smoke + [Step("abaqus_paired_validation", ("TABLE-2",), step_abaqus)]


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def write_outputs(run: ProfileRun, environment: dict) -> None:
    out = run.out_dir
    results = [s.to_dict() for s in run.steps]
    succeeded = [s for s in run.steps if s.status == StageStatus.SUCCEEDED.value]
    failed = [s for s in run.steps if s.status == StageStatus.FAILED.value]
    unavailable = [s for s in run.steps if s.status in {
        StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY.value,
        StageStatus.UNSUPPORTED.value, StageStatus.NOT_REQUESTED.value}]

    manifest = {
        "profile": run.profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": results,
        "counts": {"succeeded": len(succeeded), "failed": len(failed),
                   "unavailable": len(unavailable), "total": len(run.steps)},
    }
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    claims: dict[str, list] = {}
    for step in run.steps:
        for claim in step.supports:
            claims.setdefault(claim, []).append(
                {"step": step.name, "status": step.status})
    (out / "claim_matrix.json").write_text(
        json.dumps({"profile": run.profile, "claims": claims}, indent=2,
                   sort_keys=True) + "\n", encoding="utf-8")

    lines = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "artifact_checksums.sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(out)}")
    (out / "artifact_checksums.sha256").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    summary = [
        f"# Reproduction summary: `{run.profile}` profile", "",
        f"Generated {manifest['generated_at']}.", "",
        f"- Python {environment['python']} on {environment['platform']}",
        f"- gfortran: {environment['gfortran'] or 'not installed'}",
        f"- Abaqus: {environment['abaqus'] or 'not installed'}",
        f"- Commit: {environment['commit'] or 'not a git checkout'}", "",
        "## Steps", "",
        "| Step | Status | Detail |", "|---|---|---|",
    ]
    for step in run.steps:
        detail = (step.detail or step.reason or "").replace("|", "\\|")
        lines_detail = detail.splitlines()[0][:160] if detail else ""
        lines.append("")
        summary.append(f"| `{step.name}` | {step.status} | {lines_detail} |")
    summary += [
        "", "## Outcome", "",
        f"{len(succeeded)} succeeded, {len(failed)} failed, "
        f"{len(unavailable)} unavailable for a stated external reason.", "",
    ]
    if unavailable:
        summary += ["An unavailable step is not a pass. It means the result could "
                    "not be produced here and says why:", ""]
        summary += [f"- `{s.name}`: {s.reason}" for s in unavailable] + [""]
    if failed:
        summary += ["### Failures", ""] + [f"- `{s.name}`: {s.reason}" for s in failed] + [""]
    (out / "reproduction_summary.md").write_text("\n".join(summary), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m umat_oti.reproduce", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="where to write the five artefacts "
                             "(default: reproduce/<profile>/)")
    parser.add_argument("--allow-network", action="store_true",
                        help="permit steps that fetch third-party sources")
    args = parser.parse_args(argv)

    out_dir = args.out_dir or (REPO_ROOT / "reproduce" / args.profile)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"cannot create {out_dir}: {exc}", file=sys.stderr)
        return 2

    environment = capture_environment()
    run = ProfileRun(profile=args.profile, out_dir=out_dir)
    print(f"reproduce: profile={args.profile} out={out_dir}", flush=True)

    for step in build_steps(args.profile, args.allow_network):
        started = time.monotonic()
        try:
            result = step.run(out_dir)
        except Exception as exc:  # noqa: BLE001 - a crashed step is a failed step
            result = StepResult(step.name, StageStatus.FAILED.value,
                                reason=f"{type(exc).__name__}: {exc}"[:600])
        result.seconds = time.monotonic() - started
        if not result.supports:
            result.supports = step.supports
        if not result.name:
            result.name = step.name
        run.steps.append(result)
        print(f"  [{result.status:>34}] {result.name} "
              f"({result.seconds:.1f}s)", flush=True)
        if result.status == StageStatus.FAILED.value:
            print(f"       {result.reason}", flush=True)

    write_outputs(run, environment)
    failed = [s for s in run.steps if s.status == StageStatus.FAILED.value]
    print(f"\nwrote {out_dir}/reproduction_summary.md")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
