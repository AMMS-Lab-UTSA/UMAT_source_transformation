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
import os
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

from umat_oti.environment import detect_abaqus, detect_toolchain
from umat_oti.pipeline.status import StageStatus

#: Files that together identify a source checkout rather than an installed
#: package. Reproduction reads benchmark models, contracts and round runners
#: that are repository content and deliberately not shipped in the wheel.
_REPO_MARKERS = ("pyproject.toml", "tools", "parameter_sensitivity")


def find_repository_root() -> Optional[Path]:
    """Locate the source checkout, or None when running from an installed wheel.

    ``parents[2]`` finds the repository for an editable install and lands inside
    site-packages for a real one, where the sweep runner does not exist and the
    step fails with "can't open file .../tools/...". Searching explicitly turns
    that into a statement about what is missing.
    """
    candidates: list[Path] = []
    override = os.environ.get("UMAT_OTI_REPO_ROOT")
    if override:
        candidates.append(Path(override))
    candidates.append(Path(__file__).resolve().parents[2])
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents])
    for candidate in candidates:
        if all((candidate / marker).exists() for marker in _REPO_MARKERS):
            return candidate
    return None


_FOUND_ROOT = find_repository_root()
#: Kept importable for callers that only need a path to join against.
REPO_ROOT = _FOUND_ROOT if _FOUND_ROOT is not None else Path(__file__).resolve().parents[2]

PROFILES = ("smoke", "offline", "paper", "corpus", "abaqus")


@dataclass
class StepResult:
    name: str
    status: str
    detail: str = ""
    seconds: float = 0.0
    supports: tuple[str, ...] = ()
    reason: Optional[str] = None
    command: Optional[list[str]] = None
    inputs: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
            "supports_claims": list(self.supports),
        }
        if self.command:
            payload["command"] = self.command
        if self.inputs:
            payload["input_sha256"] = self.inputs
        if self.counts:
            payload["counts"] = self.counts
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

def capture_environment() -> dict:
    """Everything needed to say what this run happened on and from what.

    A reproduction that records only "gfortran: yes" cannot be audited. Repo
    URL, exact commit, whether the tree was dirty, the resolved toolchain and
    its versions all belong in the record, because each of them can change a
    result.
    """
    def git(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(["git", *args], cwd=REPO_ROOT,
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return (proc.stdout.strip() or None) if proc.returncode == 0 else None

    dirty = git("status", "--porcelain")
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "repository": {
            "url": git("remote", "get-url", "origin"),
            "commit": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_dirty": bool(dirty),
            "dirty_paths": (dirty.splitlines() if dirty else []),
            "describe": git("describe", "--always", "--dirty"),
        },
        "repository_root": str(_FOUND_ROOT) if _FOUND_ROOT else None,
        "running_from_source_checkout": _FOUND_ROOT is not None,
        "toolchain": detect_toolchain(),
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

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _need_repository(step: str) -> Optional[StepResult]:
    if _FOUND_ROOT is not None:
        return None
    return StepResult(
        step, StageStatus.UNSUPPORTED.value,
        reason=("this step needs the source checkout, not just the installed "
                "package: it runs round runners from tools/ over the benchmark "
                "models in parameter_sensitivity/, neither of which ships in the "
                "wheel. Clone the repository and run from inside it, or set "
                "UMAT_OTI_REPO_ROOT to an existing checkout. The installed "
                "package itself is fine -- import_package proves that."))


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
    missing = _need_repository("offline_test_suite")
    if missing:
        return missing
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
    missing = _need_repository("material_point_smoke")
    if missing:
        return missing
    blocked = _need_gfortran()
    if blocked:
        return StepResult("material_point_smoke", blocked.status, reason=blocked.reason)
    log = out_dir / "smoke_sweep.log"
    # A one-model round must never land on the published Table 6 evidence.
    results = out_dir / "results"
    command = [sys.executable, "tools/run_parameter_sensitivity_sweep.py",
               "--model", "m3_j2", "--work-dir", str(out_dir / "work"),
               "--results-dir", str(results)]
    inputs = {}
    for relative in ("parameter_sensitivity/models/m3_j2/umat.for",
                     "parameter_sensitivity/models/m3_j2/contract_v2.json",
                     "parameter_sensitivity/loading_paths.json"):
        candidate = REPO_ROOT / relative
        if candidate.is_file():
            inputs[relative] = sha256_of(candidate)
    proc = subprocess.run(command, capture_output=True, text=True, cwd=REPO_ROOT)
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
    funnel = payload.get("funnel", {})
    counts = {k: funnel[k] for k in (
        "attempted", "primal_parity", "derivatives_verified",
        "parameter_directions_declared", "parameter_directions_verified",
        "comparison_rows_total", "comparison_rows_agreeing") if k in funnel}
    if status != "succeeded":
        return StepResult("material_point_smoke", StageStatus.FAILED.value,
                          command=command, inputs=inputs, counts=counts,
                          reason=f"m3_j2 derivatives_verified reported {status}")
    return StepResult("material_point_smoke", StageStatus.SUCCEEDED.value,
                      command=command, inputs=inputs, counts=counts,
                      detail="m3_j2 transformed, compiled, executed and verified "
                             "against centred differences of the original build")


def _tool_step(name: str, script: str, supports: tuple[str, ...],
               artifact: str) -> Step:
    def run(out_dir: Path) -> StepResult:
        missing = _need_repository(name)
        if missing:
            return missing
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
    missing = _need_repository("repository_audit")
    if missing:
        return missing
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
    """Paired Abaqus validation, or a precise account of why it cannot run.

    Availability is decided by umat_oti.environment.detect_abaqus, which checks
    that the launcher resolves, reports a version, and that a licence is
    actually obtainable. An installation with no licence cannot run anything and
    is reported as blocked, not as present.
    """
    report = detect_abaqus()
    (out_dir / "abaqus_detection.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    if not report.available:
        return StepResult(
            "abaqus_paired_validation",
            StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY.value,
            supports=("TABLE-2",), reason=(
                f"{report.reason}. The archived evidence from Slurm job 791506 "
                "in paper_results/arc_791506/ is readable without a licence."))
    # Abaqus is usable here. Running the paired batch is a separate, deliberate
    # command rather than part of a reproduction profile, because it writes
    # into a licensed solver's working directories and takes far longer than
    # every other step combined. Saying so is not the same as being blocked.
    return StepResult(
        "abaqus_paired_validation", StageStatus.NOT_REQUESTED.value,
        supports=("TABLE-2",), detail=f"Abaqus {report.version} is available",
        reason=("Abaqus " + str(report.version) + " resolved and licensed, so "
                "this is not an external blocker. Paired validation is run "
                "explicitly with tools/run_abaqus_paired_validation.py; see "
                "docs/SOFTWAREX_REPRODUCTION.md."))


def step_corpus(out_dir: Path) -> StepResult:
    """A corpus round is not driven from this entry point yet.

    Calling that ``blocked_by_external_dependency`` would be false comfort. The
    network is a real dependency of a *live* round, but it is not what stops
    this profile: no corpus round is wired into the reproduction interface at
    all. Reporting the honest reason keeps "we have not built it" from reading
    as "someone else's fault".
    """
    return StepResult(
        "corpus_round", StageStatus.UNSUPPORTED.value, supports=("CORPUS",),
        reason=("no corpus round is wired into this entry point yet. The corpus "
                "CLI is umat_oti.corpus.cli and the pinned source set is "
                "scripts/corpus_manifest.json; the last executed round is "
                "archived at paper_results/arc_791506/evidence/"
                "corpus_round_metrics.json. This is an unimplemented step, not "
                "an external blocker."))


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
        f"- gfortran: {environment['toolchain']['gfortran'].get('version') or 'not available'}",
        f"- Abaqus: {environment['toolchain']['abaqus'].get('version') or 'not available'}"
        f" ({'usable' if environment['toolchain']['abaqus']['available'] else environment['toolchain']['abaqus'].get('reason')})",
        f"- Repository: {environment['repository']['url'] or 'unknown'}",
        f"- Commit: {environment['repository']['commit'] or 'not a git checkout'}"
        f"{' (worktree dirty)' if environment['repository']['worktree_dirty'] else ' (clean)'}",
        "",
        "## Steps", "",
        "| Step | Status | Detail |", "|---|---|---|",
    ]
    for step in run.steps:
        detail = (step.detail or step.reason or "").replace("|", "\\|")
        lines_detail = detail.splitlines()[0][:160] if detail else ""
        lines.append("")
        summary.append(f"| `{step.name}` | {step.status} | {lines_detail} |")
    # A profile can finish with nothing actually checked -- every verifying step
    # unsupported because the inputs were absent. Exit status alone would not
    # say so, and "0 failed" reads like success.
    verifying = [s for s in run.steps if s.supports and s.supports != ("INSTALL",)]
    verified = [s for s in verifying if s.status == StageStatus.SUCCEEDED.value]
    summary += [
        "", "## Outcome", "",
        f"{len(succeeded)} succeeded, {len(failed)} failed, "
        f"{len(unavailable)} unavailable for a stated external reason.", "",
    ]
    if verifying and not verified:
        summary += [
            "> **Nothing was verified in this run.** Every step that checks a "
            "published claim was unavailable, so this report establishes only "
            "that the package imports. See the reasons below before treating "
            "the absence of failures as success.", "",
        ]
    manifest["counts"]["verifying_steps"] = len(verifying)
    manifest["counts"]["verifying_steps_succeeded"] = len(verified)
    manifest["nothing_was_verified"] = bool(verifying and not verified)
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
