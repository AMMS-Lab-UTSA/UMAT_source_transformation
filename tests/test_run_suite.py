"""Tests for the unified Abaqus validator entry point.

The critical guarantee is *honest* environment detection: when Abaqus is
missing the suite must report ``skipped``/``blocked`` with an actionable
reason, and never report a false success.

Note: :func:`run_suite` internally invokes a nested ``pytest`` on the
offline suite. These tests point that nested pytest at a single leaf
file (``test_package.py``) rather than the whole ``tests/`` directory so
that the run_suite tests do not run themselves recursively.
"""

from __future__ import annotations

import json
from pathlib import Path

from umat_oti.validation.run_suite import (
    detect_environment,
    run_python_tests,
    run_suite,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
LEAF_TEST = REPO_ROOT / "tests" / "test_package.py"


def test_detect_environment_reports_missing_abaqus_when_binary_absent():
    env = detect_environment(abaqus_command="definitely-not-a-real-abaqus-binary-xyz")
    assert env.abaqus_ok is False
    assert "not on PATH" in env.abaqus_message


def test_detect_environment_reports_fortran_compiler_when_present():
    env = detect_environment(abaqus_command="definitely-not-a-real-abaqus-binary-xyz")
    # gfortran is installed on ARC; skip the assertion if not present.
    if env.fortran_compiler is not None:
        assert env.fortran_compiler_version


def test_run_python_tests_on_leaf_file_returns_passed():
    assert LEAF_TEST.is_file()
    result = run_python_tests(REPO_ROOT, tests_target=LEAF_TEST)
    assert result.name == "python_tests"
    assert result.status == "passed", result.details.get("stdout_tail", "")


def test_run_suite_marks_abaqus_blocked_when_command_missing(tmp_path: Path):
    """The invariant: no Abaqus binary ⇒ suite is never 'passed' for that stage."""
    report = run_suite(
        repo_root=REPO_ROOT,
        abaqus_command="definitely-not-a-real-abaqus-binary-xyz",
        include_abaqus=True,
        tests_target=LEAF_TEST,
        include_benchmark_batch=False,
        report_path=tmp_path / "report.json",
    )
    abaqus = next(s for s in report["suites"] if s["name"] == "abaqus_paired_validation")
    assert abaqus["status"] in {"blocked", "skipped"}
    assert abaqus["status"] != "passed"
    assert abaqus["reason"]
    replay = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert replay["overall_status"] in {"passed", "failed", "partial", "blocked"}


def test_run_suite_overall_partial_when_offline_passes_but_abaqus_blocked(tmp_path: Path):
    report = run_suite(
        repo_root=REPO_ROOT,
        abaqus_command="definitely-not-a-real-abaqus-binary-xyz",
        include_abaqus=True,
        tests_target=LEAF_TEST,
        include_benchmark_batch=False,
    )
    python_stage = next(s for s in report["suites"] if s["name"] == "python_tests")
    assert python_stage["status"] == "passed"
    assert report["overall_status"] in {"partial", "blocked"}
