"""Explicit, unverified Abaqus trials of generated UMAT candidates."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from uuid import uuid4

from umat_oti.services.transformation import _write_combined_source
from umat_oti.validation.abaqus_runner import analysis_completed, completed_despite_teardown_abort
from umat_oti.validation.job_builder import DEFAULT_ABAQUS_MODULES, DEFAULT_ABAQUS_RUN_PREFIX


def run_abaqus_trial(run, input_deck: Path | None = None, *, allow_semantic_failures: bool = False,
                     smoke: bool = False,
                     abaqus_command: str = "abaqus",
                     abaqus_modules: str = DEFAULT_ABAQUS_MODULES,
                     run_prefix: str = DEFAULT_ABAQUS_RUN_PREFIX,
                     job_name: str | None = None) -> dict:
    output = run.contract_path.parent.resolve()
    failed = sorted(name for name, passed in run.summary.get("semantic_checks", {}).items()
                    if passed is False)
    report = {"status": "blocked", "verified": False, "failed_semantic_checks": failed,
              "semantic_override": bool(failed and allow_semantic_failures),
              "mode": "build_smoke" if smoke else "analysis_trial",
              "input": str(input_deck.resolve()) if input_deck else None,
              "working_directory": str(output)}
    try:
        if not smoke and (input_deck is None or not input_deck.is_file()):
            raise ValueError(f"Abaqus input deck not found: {input_deck}")
        if run.summary.get("blockers"):
            raise ValueError("Hard transformation blockers cannot be overridden.")
        if failed and not allow_semantic_failures:
            raise ValueError("Semantic checks failed; use --abaqus-allow-semantic-failures for an unverified trial.")
        if not run.summary.get("transform_success") and not (failed and allow_semantic_failures):
            raise ValueError("Transformation failed without an overridable semantic-check result.")
        transformed = run.transformed_source
        if transformed is None:
            raise ValueError("No generated UMAT candidate is available.")
        order_file = output / "compile_order.txt"
        units = [output / name.strip() for name in order_file.read_text().splitlines() if name.strip()]
        if not units or transformed.resolve() not in [unit.resolve() for unit in units]:
            raise ValueError("Compile order does not contain the generated UMAT candidate.")
        if any(not unit.is_file() for unit in units):
            raise ValueError("A required generated compilation unit is missing.")
        combined = _write_combined_source(output, transformed)
        if combined is None:
            raise ValueError("Could not assemble the Abaqus user source.")
        if job_name is not None and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}", job_name):
            raise ValueError(f"Abaqus job name {job_name!r}: letters, digits, '_', '.' and '-' only")
        job = job_name or "oti_trial_" + uuid4().hex[:12]
        invocation = shlex.split(abaqus_command)
        if not invocation:
            raise ValueError("Abaqus command must not be empty.")
        working_directory = output
        if smoke:
            working_directory = output / job
            working_directory.mkdir()
            shutil.copy2(combined, working_directory / combined.name)
            if (output / "dependencies").is_dir():
                shutil.copytree(output / "dependencies", working_directory / "dependencies")
            if (output / "abaqus_v6.env").is_file():
                shutil.copy2(output / "abaqus_v6.env", working_directory / "abaqus_v6.env")
            invocation += ["make", f"library={combined.name}", "directory=."]
        else:
            invocation += [f"job={job}", f"input={input_deck.resolve()}",
                           f"user={combined.resolve()}", "ask_delete=OFF", "interactive"]
        inner = "set -e; "
        if abaqus_modules.strip():
            inner += "module load " + shlex.join(shlex.split(abaqus_modules)) + "; "
        inner += "exec " + shlex.join(invocation)
        command = shlex.split(run_prefix) + ["bash", "-lc", inner]
        stdout_path = output / f"{job}_stdout.log"
        stderr_path = output / f"{job}_stderr.log"
        # A UMAT that writes to the console (WRITE(*,*), PRINT) aborts an
        # "interactive" job: the solver's unit 6 is then a pipe, and the Intel
        # Fortran runtime fails while naming it (fname_from_piped_fd, signal 6
        # in the element loop). FOR_PRINT sends that output to a file instead;
        # nothing the routine computes changes. A FOR_PRINT already set is kept.
        environment = dict(os.environ)
        console = environment.get("FOR_PRINT") or str(working_directory / f"{job}_console.txt")
        environment["FOR_PRINT"] = console
        report.update(job=job, command=command, user_source=str(combined),
                      stdout=str(stdout_path), stderr=str(stderr_path), status="running",
                      working_directory=str(working_directory), console_output=console)
        # A named job may find the files of an earlier run of the same name in
        # --out. Only what this run wrote counts: an evidence file (.dat,
        # .exception) counts when it is new or changed since the run started.
        before = _evidence_stamps(working_directory, job)
        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            process = subprocess.run(command, cwd=working_directory, stdout=stdout, stderr=stderr,
                                     check=False, timeout=3600, env=environment)
        if smoke:
            libraries = sorted(str(path) for path in working_directory.iterdir()
                               if path.suffix.lower() in {".so", ".dll", ".dylib"}
                               and path.is_file() and path.stat().st_size > 0)
            report.update(returncode=process.returncode, analysis_completed=False,
                          libraries=libraries,
                          status="built" if process.returncode == 0 and libraries else "failed")
        else:
            completed = (_written_by_this_run(output / f"{job}.dat", before)
                         and analysis_completed(output, job))
            # Abaqus 2021's runtime can abort in its own clean-up after the
            # solve, after the results are written and the ODB is closed; a
            # non-zero exit with that evidence is not a failed analysis.
            teardown = (_fresh_teardown_abort(output, job, before)
                        if process.returncode != 0 and completed else "")
            report.update(returncode=process.returncode, analysis_completed=completed,
                          status="completed" if completed and (process.returncode == 0 or teardown)
                          else "failed")
            if teardown:
                report["teardown_abort"] = teardown
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        report.update(status="failed" if report["status"] == "running" else "blocked",
                      error=str(error))
    report_path = output / "abaqus_trial.json"
    report["report"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report

def _evidence_stamps(directory: Path, job: str) -> dict:
    """``{name: (mtime_ns, size)}`` of the job's .dat and .exception files now."""
    stamps = {}
    for path in [Path(directory) / f"{job}.dat", *Path(directory).glob(f"{job}.*.exception")]:
        try:
            info = path.stat()
        except OSError:
            continue
        stamps[path.name] = (info.st_mtime_ns, info.st_size)
    return stamps


def _written_by_this_run(path: Path, before: dict) -> bool:
    """Whether ``path`` exists and is new or changed since ``before`` was taken."""
    try:
        info = path.stat()
    except OSError:
        return False
    return before.get(path.name) != (info.st_mtime_ns, info.st_size)


def _fresh_teardown_abort(output: Path, job: str, before: dict) -> str:
    """:func:`completed_despite_teardown_abort`, from exception files this run wrote."""
    from umat_oti.validation.abaqus_runner import _TEARDOWN_FRAMES

    if not completed_despite_teardown_abort(output, job):
        return ""
    for candidate in sorted(Path(output).glob(f"{job}.*.exception")):
        if not _written_by_this_run(candidate, before):
            continue
        text = candidate.read_text(errors="replace")
        for frame in _TEARDOWN_FRAMES:
            if frame in text:
                return f"{candidate.name}: aborted inside {frame}"
    return ""
