"""Re-run the promoted materials in Abaqus and fail if any stops verifying.

This is the durable gate. The tests in ``test_verified_umat_collection.py``
check that the committed evidence is internally sound; this one checks that it
is still TRUE, by executing the materials again.

Marked ``abaqus`` and deselected by default, because it needs a licence and
takes as long as the batch does. The offline suite must never depend on it,
and -- the point that matters -- its absence must never read as a pass. A run
without Abaqus SKIPS here and FAILS in the strict command:

    python tools/verify_store_in_abaqus.py --mode regression \\
        --baseline umat/baseline.json

Use the command in CI. This test exists so the same gate can be reached from
pytest on a machine that has Abaqus.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

COLLECTION = REPO / "umat"
BASELINE = COLLECTION / "baseline.json"

pytestmark = [
    pytest.mark.abaqus,
    pytest.mark.skipif(not BASELINE.is_file(),
                       reason="nothing has been promoted into umat/ yet"),
    pytest.mark.skipif(shutil.which("abaqus") is None,
                       reason="Abaqus is not on PATH. A skip here is not a "
                              "pass: use --mode regression, which fails."),
]


def _required():
    return [entry["source"] for entry in
            json.loads(BASELINE.read_text(encoding="utf-8"))["entries"]]


def test_every_promoted_material_still_verifies(tmp_path):
    """The whole baseline, in one strict run.

    Passing means every material in ``umat/`` executed in Abaqus again -- both
    builds -- agreed on its histories, and agreed with a finite difference of
    the original at every state. Failing names the ones that did not.
    """
    results = tmp_path / "results"
    completed = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_store_in_abaqus.py"),
         "--mode", "regression",
         "--baseline", str(BASELINE),
         "--jobs", "4",
         "--timeout", "1200",
         "--work-dir", str(tmp_path / "work"),
         "--results-dir", str(results)],
        capture_output=True, text=True, timeout=6 * 60 * 60)

    tail = "\n".join(completed.stdout.splitlines()[-40:])
    assert completed.returncode == 0, (
        f"the regression gate failed (exit {completed.returncode}).\n{tail}")


def test_the_gate_fails_when_a_required_material_is_missing():
    """Not an Abaqus run -- the semantics, checked directly.

    A material that silently stops being attempted leaves no failing row to
    notice, which is exactly what a regression exists to catch. This is the
    case a gate is most likely to get wrong, so it is asserted rather than
    assumed.
    """
    from verify_store_in_abaqus import exit_verdict

    ran = [{"source": name, "stage": "verified"} for name in _required()[:1]]
    verdict = exit_verdict("regression", ran, set(_required()))
    if len(_required()) > 1:
        assert verdict.code == 1
        assert any("missing" in line for line in verdict.lines)


def test_a_blocked_material_is_not_an_exemption():
    from verify_store_in_abaqus import exit_verdict

    name = _required()[0]
    for blocked in ("needs_material_data", "support_build_failed",
                    "original_job_failed", "manifest_refused"):
        verdict = exit_verdict("regression", [{"source": name, "stage": blocked}],
                               {name})
        assert verdict.code == 1, blocked
