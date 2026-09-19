"""The clean-clone acceptance run stops on a failing suite and names the failing test.

``scripts/clean_clone_acceptance.sh`` piped pytest into ``tail``: the run
stopped on a failure, but printed the last lines of one assertion message,
which did not name the test that failed (c43e0e7). Its ``run_pytest`` keeps
the whole log, prints the short test summary on a failure and exits with
pytest's status. The function is taken from the script as written and run by
bash on a small suite with one failing test.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "clean_clone_acceptance.sh"

SUITE = '''
def test_that_passes():
    assert True


def test_that_breaks():
    assert sum([1, 1]) == 3, "one plus one"
'''


def _run(tmp_path: Path, suite: str) -> tuple:
    match = re.search(r"(?ms)^run_pytest\(\) \{\n.*?^\}\n", SCRIPT.read_text(encoding="utf-8"))
    assert match, f"{SCRIPT.name} defines no run_pytest"
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "test_suite.py").write_text(suite)
    log = tmp_path / "pytest.log"
    driver = ("set -euo pipefail\n" + match.group(0)
              + 'run_pytest "$LOG" -p no:cacheprovider\necho "the run went on"\n')
    environment = dict(os.environ, CLONE=str(clone), VENV_PY=sys.executable, LOG=str(log))
    completed = subprocess.run(["bash", "-c", driver], env=environment, capture_output=True, text=True)
    return completed, log.read_text()


def test_a_failing_suite_stops_the_run_and_names_the_failing_test(tmp_path):
    completed, log = _run(tmp_path, SUITE)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "the run went on" not in completed.stdout
    assert "FAILED: pytest exited with status 1" in completed.stderr
    assert "test_suite.py::test_that_breaks" in completed.stderr
    # the whole log is kept, the passing test included
    assert "1 failed, 1 passed" in log


def test_a_passing_suite_lets_the_run_go_on(tmp_path):
    completed, log = _run(tmp_path, SUITE.split("\n\n\ndef test_that_breaks")[0] + "\n")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout
    assert completed.stdout.rstrip().endswith("the run went on")
    assert "1 passed" in log
