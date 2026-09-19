"""An absent ifort, and an absent OTI runtime, are reported by name.

Abaqus and OTILib are optional, and so is the Intel compiler Abaqus builds user
subroutines with. When one of them is missing the run cannot succeed, and the
only useful outcome is a message that names what is missing and what to do
about it. The Abaqus-absent and missing-template messages are asserted
elsewhere (``test_abaqus_support_links``, ``test_run_suite``,
``test_packaging``); these tests assert the other two.

Absence is real, not simulated by replacing a check: each test runs with a
``PATH`` from which every directory holding the tool has been removed, so the
shell or the interpreter that looks for it genuinely does not find it.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from umat_oti.abaqus import runner
from umat_oti.abaqus.job_status import classify_job
from umat_oti.services.transformation import run_transformation
from umat_oti.validation.abaqus_runner import run_original_job
from umat_oti.validation.job_builder import build_validation_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
ELASTIC_CONTRACT = REPO_ROOT / "examples" / "elastic_minimal.json"
M5_UMAT = REPO_ROOT / "parameter_sensitivity" / "models" / "m5_cpflow" / "umat.for"


def _path_without(*tools: str) -> str:
    """This PATH with every directory that holds one of ``tools`` removed."""
    kept = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry and not any((Path(entry) / tool).exists() for tool in tools)]
    path = os.pathsep.join(kept)
    for tool in tools:
        assert shutil.which(tool, path=path) is None, f"{tool} is still reachable"
    return path


# --------------------------------------------------------------------------- #
# ifort
# --------------------------------------------------------------------------- #
#: The one step of the Abaqus launcher these tests need: given ``user=``, it
#: hands its ``compile_fortran`` line, whose compiler is ifort, to the shell.
#: The shell is named explicitly because the two that ``/bin/sh`` usually is
#: word the failure differently: bash, ``/bin/sh`` on the Red Hat family
#: machines the validation scripts target (``module load ... intel/oneapi``),
#: prints ``ifort: command not found``; dash, ``/bin/sh`` on Debian and
#: Ubuntu, prints ``ifort: not found``.
_LAUNCHER = """#!/usr/bin/env bash
for argument in "$@"; do
  case "$argument" in user=*) source_file="${{argument#user=}}" ;; esac
done
exec {shell} -c 'ifort -c "$1"' compile_fortran "$source_file"
"""


def _validation_run_whose_compile_line_cannot_find_ifort(tmp_path, monkeypatch, shell: str):
    """Run the original job through a launcher whose compile line goes through ``shell``."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not on PATH; the launcher step runs its compile line through {shell}")
    summary, code = run_transformation(ELASTIC_CONTRACT, tmp_path / "oti")
    assert code == 0, summary
    launcher = tmp_path / "bin" / "abaqus"
    launcher.parent.mkdir()
    launcher.write_text(_LAUNCHER.format(shell=shell), encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)

    validation_dir = tmp_path / "validation"
    build_validation_workspace(
        validation_dir=validation_dir, original_umat=Path(summary["source"]),
        transformed_umat=Path(summary["transformed_source"]),
        generated_dir=tmp_path / "oti", ntens=int(summary["ntens"]),
        abaqus_command=str(launcher), abaqus_modules="", run_prefix="",
        run_compile_smoke=False)

    monkeypatch.setenv("PATH", _path_without("ifort"))
    result = run_original_job(validation_dir, abaqus_command=str(launcher),
                              abaqus_modules="", run_prefix="", timeout_seconds=120)
    report = json.loads((validation_dir / "validation_report.json").read_text())
    return result, report


def test_the_validation_runner_names_ifort_when_the_compile_line_cannot_find_it(
        tmp_path, monkeypatch):
    """``validation.abaqus_runner`` turns bash's 'ifort: command not found'
    into an instruction, and records it in validation_report.json."""
    result, report = _validation_run_whose_compile_line_cannot_find_ifort(
        tmp_path, monkeypatch, "bash")

    assert result.status == "failed"
    assert "ifort: command not found" in result.stderr_excerpt
    assert result.message.startswith("Abaqus started but could not find ifort.")
    assert "Load the Intel compiler module with Abaqus" in result.message
    assert report["original_run_status"]["message"] == result.message


def test_the_validation_runner_names_ifort_in_dash_wording_too(tmp_path, monkeypatch):
    """dash, ``/bin/sh`` on Ubuntu, says 'ifort: not found'; the message is the same."""
    result, report = _validation_run_whose_compile_line_cannot_find_ifort(
        tmp_path, monkeypatch, "dash")

    assert result.status == "failed"
    assert "ifort: not found" in result.stderr_excerpt
    assert "command not found" not in result.stderr_excerpt
    assert result.message.startswith("Abaqus started but could not find ifort.")
    assert "Load the Intel compiler module with Abaqus" in result.message
    assert report["original_run_status"]["message"] == result.message


def test_a_job_whose_shell_cannot_find_ifort_says_so_rather_than_blaming_the_source(
        tmp_path, monkeypatch):
    """The Abaqus job classifier names the absent compiler.

    Abaqus runs its compile line through ``/bin/sh``; so does this test, with
    ifort off PATH, and the classifier reads what that shell printed. Before,
    the reason said "the console kept no compiler diagnostic", which sent the
    reader looking for a fault in the UMAT.
    """
    source = tmp_path / "job_user.f"
    shutil.copyfile(M5_UMAT, source)
    monkeypatch.setenv("PATH", _path_without("ifort"))
    shell = subprocess.run(["/bin/sh", "-c", f"ifort -c {source.name}"],
                           cwd=tmp_path, capture_output=True, text=True)
    console = shell.stdout + shell.stderr
    assert shell.returncode == 127 and "ifort" in console, console

    status = classify_job(tmp_path, "job", exit_code=1, console=console)

    assert not status.analysis_completed
    build = next(r for r in status.reasons if "never reached its input processor" in r)
    assert "ifort: not found on PATH" in build
    assert "the build step that needs it never ran" in build
    assert "load the site's compiler module" in build
    assert "the console kept no compiler diagnostic" not in build


def test_a_build_that_did_run_still_quotes_the_compiler(tmp_path):
    """The new sentence is for an absent compiler only; a compiler that ran
    and failed is still quoted in its own words."""
    console = "u.f(12): error #6404: This name does not have a type\ncompilation aborted\n"
    status = classify_job(tmp_path, "job", exit_code=1, console=console)
    build = next(r for r in status.reasons if "never reached its input processor" in r)
    assert "error #6404" in build
    assert "not found on PATH" not in build


@pytest.mark.abaqus
def test_abaqus_itself_with_ifort_off_path_is_reported_by_name(tmp_path, monkeypatch):
    """The whole path: a real ``abaqus job=... user=...`` run with no ifort."""
    monkeypatch.setenv("PATH", _path_without("ifort", "ifx"))
    if runner.abaqus_command() is None:
        pytest.skip("Abaqus is not on PATH; this test runs a real Abaqus job")

    result = runner.run_job(tmp_path / "work", "job", "*HEADING\n",
                            user_source=M5_UMAT, timeout=600)

    assert not result.completed
    build = next(r for r in result.status.reasons
                 if "never reached its input processor" in r)
    assert "ifort: not found on PATH" in build, result.console


# --------------------------------------------------------------------------- #
# OTILib runtime
# --------------------------------------------------------------------------- #
_ASK_FOR_THE_OTI_BACKEND = """
from umat_oti.validation.j2_reference import J2Parameters, build_softwarex_j2_path
from umat_oti.validation.parameter_sensitivity import (
    OtilibUnavailable, compute_j2_parameter_sensitivities)
try:
    compute_j2_parameter_sensitivities(
        params=J2Parameters(), path=build_softwarex_j2_path(), backend="oti")
except OtilibUnavailable as refusal:
    print(refusal)
else:
    raise SystemExit("the OTI backend returned values without a runtime")
"""


def test_the_oti_backend_refusal_says_no_runtime_was_found_and_what_to_do(tmp_path):
    """No ``oti-config`` on PATH and no importable ``pyoti``: the refusal
    says which, and names both ways forward.

    The interpreter is started with ``-S`` and a PYTHONPATH of this checkout's
    ``src`` only, so no site-packages directory can supply an OTILib build.
    """
    empty = tmp_path / "empty_bin"
    empty.mkdir()
    environment = {"PATH": str(empty), "PYTHONPATH": str(REPO_ROOT / "src"),
                   "HOME": str(tmp_path)}
    done = subprocess.run([sys.executable, "-S", "-c", _ASK_FOR_THE_OTI_BACKEND],
                          env=environment, capture_output=True, text=True,
                          cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == (
        "OTI backend requested but no OTI runtime was detected on PATH. "
        "Install OTIlib (see scripts/setup_otilib.sh in the Residual "
        "Assembler repo) or rerun with backend='centered_fd'.")


def test_the_oti_backend_refusal_with_a_runtime_present_still_refuses_to_guess(monkeypatch):
    """With OTILib's Python build importable, the backend still produces no
    number, and says why: no compiled UMAT harness is wired in."""
    # PYOTI_PATH names the OTILib build directory, as the installation guide
    # of the connected workflow documents; sys.path is restored afterwards.
    if os.environ.get("PYOTI_PATH"):
        monkeypatch.syspath_prepend(os.environ["PYOTI_PATH"])
    try:
        import pyoti.sparse  # noqa: F401
    except ImportError:
        pytest.skip("OTILib's Python build (pyoti) is not importable here; "
                    "set PYOTI_PATH to its build directory")
    from umat_oti.validation.j2_reference import J2Parameters, build_softwarex_j2_path
    from umat_oti.validation.parameter_sensitivity import (
        OtilibUnavailable, compute_j2_parameter_sensitivities)

    with pytest.raises(OtilibUnavailable) as refusal:
        compute_j2_parameter_sensitivities(
            params=J2Parameters(), path=build_softwarex_j2_path(), backend="oti")
    assert str(refusal.value) == (
        "OTI backend detected but no compiled UMAT harness is wired in "
        "this build. Use backend='centered_fd' for the reference values.")
