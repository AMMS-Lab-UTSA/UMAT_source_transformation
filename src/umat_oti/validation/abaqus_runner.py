from __future__ import annotations

import shutil
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from umat_oti.validation.job_builder import ABAQUS_NOT_FOUND_MESSAGE, DEFAULT_ABAQUS_MODULES, DEFAULT_ABAQUS_RUN_PREFIX, update_validation_report


@dataclass
class AbaqusRunResult:
    status: str
    command: list[str]
    cwd: Path
    returncode: int | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    message: str = ""
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "command": self.command,
            "cwd": str(self.cwd),
            "returncode": self.returncode,
            "stdout_path": str(self.stdout_path or ""),
            "stderr_path": str(self.stderr_path or ""),
            "message": self.message,
            "stdout_excerpt": self.stdout_excerpt,
            "stderr_excerpt": self.stderr_excerpt,
        }


#: Abaqus's own statement, in the job's .dat, that the analysis finished. It is
#: the only thing that settles whether results exist; the process exit status
#: does not, because the solver can complete and then die in teardown.
ANALYSIS_COMPLETED_MARK = "THE ANALYSIS HAS BEEN COMPLETED"

#: Frames that only appear once the solve is over and Abaqus is shutting down.
#: A crash inside one of these happened after the analysis, not during it.
_TEARDOWN_FRAMES = (
    "SMAAspSupport_finalize",
    "SMAAspBcu_finalize",
    "bcu_cleanup",
)


def analysis_completed(validation_dir: Path, job_name: str) -> bool:
    """Did Abaqus itself say the analysis finished?"""
    dat = Path(validation_dir) / f"{job_name}.dat"
    if not dat.is_file():
        return False
    return ANALYSIS_COMPLETED_MARK in dat.read_text(errors="replace")


def teardown_abort(validation_dir: Path, job_name: str) -> str:
    """The crash report for a job that died shutting down, or "".

    Abaqus 2021's bundled Intel Fortran runtime calls ``for_inquire`` from its
    own cleanup, and against a glibc built with ``_FORTIFY_SOURCE`` that path
    reaches ``__chk_fail`` and aborts. It happens after the solve, after the
    results are written and after the ODB is closed, so the analysis is
    unaffected -- but the process exits non-zero and every job on the machine
    looks like a failed run.

    Returning the frame that proves it, rather than a bare flag, so a report
    can say why a non-zero exit was not counted against the model.
    """
    directory = Path(validation_dir)
    for candidate in sorted(directory.glob(f"{job_name}.*.exception")):
        text = candidate.read_text(errors="replace")
        for frame in _TEARDOWN_FRAMES:
            if frame in text:
                return f"{candidate.name}: aborted inside {frame}"
    return ""


def completed_despite_teardown_abort(validation_dir: Path,
                                     job_name: str) -> str:
    """Evidence that a non-zero exit is an environment defect, or "".

    Both halves are required. Without the completion mark this says nothing:
    an analysis that stopped early and then crashed in cleanup is a failed
    analysis, and must stay one.
    """
    if not analysis_completed(validation_dir, job_name):
        return ""
    return teardown_abort(validation_dir, job_name)


def abaqus_available(abaqus_command: str) -> bool:
    tokens = _command_tokens(abaqus_command)
    return bool(tokens and shutil.which(tokens[0]))


def run_original_job(
    validation_dir: Path,
    abaqus_command: str = "abaqus",
    abaqus_modules: str = DEFAULT_ABAQUS_MODULES,
    run_prefix: str = DEFAULT_ABAQUS_RUN_PREFIX,
    timeout_seconds: int = 1800,
) -> AbaqusRunResult:
    result = _run_generated_script(validation_dir, "run_original_abaqus.sh", abaqus_command, abaqus_modules, run_prefix, "original_abaqus_stdout.log", "original_abaqus_stderr.log", timeout_seconds, job_name="original_umat_validation")
    _update_run_report(validation_dir, "original_run_status", result)
    return result


def run_transformed_job(
    validation_dir: Path,
    abaqus_command: str = "abaqus",
    abaqus_modules: str = DEFAULT_ABAQUS_MODULES,
    run_prefix: str = DEFAULT_ABAQUS_RUN_PREFIX,
    timeout_seconds: int = 1800,
) -> AbaqusRunResult:
    result = _run_generated_script(validation_dir, "run_otis_abaqus.sh", abaqus_command, abaqus_modules, run_prefix, "otis_abaqus_stdout.log", "otis_abaqus_stderr.log", timeout_seconds, job_name="otis_umat_validation")
    _update_run_report(validation_dir, "transformed_run_status", result)
    return result


def run_both_jobs(
    validation_dir: Path,
    abaqus_command: str = "abaqus",
    abaqus_modules: str = DEFAULT_ABAQUS_MODULES,
    run_prefix: str = DEFAULT_ABAQUS_RUN_PREFIX,
    timeout_seconds: int = 1800,
) -> dict[str, dict[str, Any]]:
    original = run_original_job(validation_dir, abaqus_command, abaqus_modules, run_prefix, timeout_seconds)
    transformed = run_transformed_job(validation_dir, abaqus_command, abaqus_modules, run_prefix, timeout_seconds)
    return {"original": original.to_json(), "transformed": transformed.to_json()}


def extract_results(
    validation_dir: Path,
    abaqus_command: str = "abaqus",
    abaqus_modules: str = DEFAULT_ABAQUS_MODULES,
    run_prefix: str = DEFAULT_ABAQUS_RUN_PREFIX,
    timeout_seconds: int = 600,
) -> AbaqusRunResult:
    validation_dir = Path(validation_dir)
    tokens = _command_tokens(abaqus_command)
    script = validation_dir / "extract_results.py"
    commands = [
        ("original_umat_validation.odb", "original_results.json"),
        ("otis_umat_validation.odb", "otis_results.json"),
    ]
    stdout_path = validation_dir / "extract_results_stdout.log"
    stderr_path = validation_dir / "extract_results_stderr.log"
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    status = "completed"
    returncode = 0
    message = ""
    for odb_name, output_name in commands:
        odb_path = validation_dir / odb_name
        if not odb_path.is_file():
            status = "failed"
            returncode = 1
            message = f"ODB file not found: {odb_path}"
            stderr_chunks.append(message + "\n")
            break
        command = _abaqus_python_command(abaqus_command, abaqus_modules, run_prefix, script, odb_path, validation_dir / output_name)
        try:
            process = subprocess.run(command, cwd=validation_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            returncode = None
            stdout_chunks.append(exc.stdout or "")
            stderr_chunks.append(exc.stderr or "")
            message = f"Abaqus result extraction timed out after {timeout_seconds} seconds."
            break
        stdout_chunks.append(process.stdout)
        stderr_chunks.append(process.stderr)
        if process.returncode != 0:
            status = "failed"
            returncode = process.returncode
            message = f"Abaqus result extraction failed for {odb_name}."
            break
    stdout_path.write_text("".join(stdout_chunks), encoding="utf-8")
    stderr_path.write_text("".join(stderr_chunks), encoding="utf-8")
    stdout_text = "".join(stdout_chunks)
    stderr_text = "".join(stderr_chunks)
    result = AbaqusRunResult(status, tokens + ["python", str(script), "<odb>", "<output.json>"], validation_dir, returncode, stdout_path, stderr_path, message, _excerpt(stdout_text), _excerpt(stderr_text))
    _update_extraction_report(validation_dir, result)
    return result


def _run_generated_script(
    validation_dir: Path,
    script_name: str,
    abaqus_command: str,
    abaqus_modules: str,
    run_prefix: str,
    stdout_name: str,
    stderr_name: str,
    timeout_seconds: int,
    job_name: str = "",
) -> AbaqusRunResult:
    validation_dir = Path(validation_dir)
    script = validation_dir / script_name
    if not script.is_file():
        return AbaqusRunResult("failed", [str(script)], validation_dir, message=f"Generated Abaqus script not found: {script}")
    command = [str(script)]
    stdout_path = validation_dir / stdout_name
    stderr_path = validation_dir / stderr_name
    env = None
    import os

    env = dict(os.environ)
    env.update({"ABAQUS_CMD": abaqus_command, "ABAQUS_MODULES": abaqus_modules, "ABAQUS_RUN_PREFIX": run_prefix})
    try:
        process = subprocess.run(command, cwd=validation_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
        return AbaqusRunResult("timeout", command, validation_dir, None, stdout_path, stderr_path, f"Abaqus job timed out after {timeout_seconds} seconds.", _excerpt(exc.stdout or ""), _excerpt(exc.stderr or ""))
    stdout_path.write_text(process.stdout, encoding="utf-8")
    stderr_path.write_text(process.stderr, encoding="utf-8")
    message = _runner_message(process.stderr + "\n" + process.stdout)
    if process.returncode == 0:
        status = "completed"
    else:
        # A non-zero exit is not automatically a failed analysis. Ask the job
        # what happened: if Abaqus recorded that the analysis completed and the
        # only crash is in its own shutdown, the results on disk are real and
        # the exit status is describing the machine, not the model. Both halves
        # are required, so an analysis that stopped early stays failed.
        teardown = completed_despite_teardown_abort(validation_dir, job_name) if job_name else ""
        if teardown:
            status = "completed_after_teardown_abort"
            message = (
                "The analysis completed and wrote its results, then the "
                f"process aborted while shutting down ({teardown}). This is a "
                "defect in the Abaqus installation, not in the model or the "
                "transformation: it reproduces on this machine for a job with "
                "no user subroutine at all. The results are read from the "
                "files the completed analysis wrote."
            ) + (f" Runner note: {message}" if message else "")
        else:
            status = "failed"
    return AbaqusRunResult(status, command, validation_dir, process.returncode, stdout_path, stderr_path, message, _excerpt(process.stdout), _excerpt(process.stderr))


def _abaqus_python_command(abaqus_command: str, abaqus_modules: str, run_prefix: str, script: Path, odb_path: Path, output_path: Path) -> list[str]:
    script = Path(script).resolve()
    odb_path = Path(odb_path).resolve()
    output_path = Path(output_path).resolve()
    inner = (
        "set -euo pipefail; "
        f"cd {shlex.quote(str(script.parent))}; "
        f"if [[ -n {shlex.quote(abaqus_modules)} ]]; then module load {abaqus_modules}; fi; "
        f"{abaqus_command} python {shlex.quote(str(script))} {shlex.quote(str(odb_path))} {shlex.quote(str(output_path))}"
    )
    if run_prefix.strip():
        return _command_tokens(run_prefix) + ["bash", "-lc", inner]
    return ["bash", "-lc", inner]


def _runner_message(stderr: str) -> str:
    lowered = stderr.lower()
    if "time limit specification required" in lowered or "the time was empty" in lowered:
        return "Slurm rejected the Abaqus launch because the srun prefix has no time limit. Add --time=00-00:30:00 or rebuild validation scripts with the current defaults."
    if "ifort: command not found" in lowered:
        return "Abaqus started but could not find ifort. Load the Intel compiler module with Abaqus, for example: abaqus/2024 intel/oneapi/2024.2.0.634."
    if "problem during compilation" in lowered:
        return "Abaqus reached user-subroutine compilation, but compilation failed. See the stdout/stderr excerpts for the compiler error."
    if "input file processor exited with an error" in lowered:
        return "Abaqus reached input preprocessing, but the input deck was rejected. See the .dat file and stdout/stderr excerpts."
    if "job nodes" in lowered or ("module" in lowered and "abaqus" in lowered and ("not found" in lowered or "unknown" in lowered or "failed" in lowered)):
        return "Abaqus module could not be loaded in this shell. Use the generated srun scripts or allocate a compute node."
    if "command not found" in lowered and "abaqus" in lowered:
        return ABAQUS_NOT_FOUND_MESSAGE
    return ""


def _excerpt(text: str, max_chars: int = 2000) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _update_run_report(validation_dir: Path, key: str, result: AbaqusRunResult) -> None:
    updates = {key: result.to_json()}
    if result.status == "skipped" and result.message == ABAQUS_NOT_FOUND_MESSAGE:
        updates["abaqus_status"] = {"status": "not_found", "message": ABAQUS_NOT_FOUND_MESSAGE}
    update_validation_report(validation_dir, updates)


def _update_extraction_report(validation_dir: Path, result: AbaqusRunResult) -> None:
    update_validation_report(validation_dir, {"extraction_status": result.to_json()})


def _original_user_file(validation_dir: Path) -> Path:
    report_path = Path(validation_dir) / "validation_report.json"
    if report_path.is_file():
        import json

        report = json.loads(report_path.read_text(encoding="utf-8"))
        return Path(str(report.get("original_umat_path", "")))
    return Path("original_umat.f")


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command or "abaqus")
    except ValueError:
        return []