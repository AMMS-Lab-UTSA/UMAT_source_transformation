"""A stage that has not run is an explicit state string. Never absent, never null.

This is a project rule and it is here because the alternative has cost real
money twice. 108 entries that never ran were reported as "agreement only" --
an agreement that never happened. And a published count of 7 not-established
was really 11, because four records carried the key ABSENT rather than null and
a ``.get()`` dropped them without the census failing to sum.

So: every job record carries all nine stages from the moment it is created,
each at ``"not_run"``. The list is fixed-length and fixed-order. There is no
code path that yields a short list and none that yields a null state. A
progress panel can therefore tell "did not run" from "failed" by string
equality, with no truthiness shortcut anywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from umat_oti.jobs import (  # noqa: E402
    JobManager, JobRecord, StageReporter, STAGE_KEYS, STAGE_STATES,
    STATE_NOT_RUN, STATE_RUNNING, STATE_SUCCEEDED,
)

pytestmark = pytest.mark.unit


def test_a_new_record_carries_every_stage_at_not_run():
    record = JobRecord(job_id="j", case_id="c")
    assert [s.key for s in record.stages] == list(STAGE_KEYS)
    assert len(record.stages) == 9
    assert {s.state for s in record.stages} == {STATE_NOT_RUN}


def test_no_stage_is_ever_absent_or_null_in_the_serialised_record():
    """The GUI reads the dict, so the guarantee has to survive serialisation."""
    payload = JobRecord(job_id="j", case_id="c").as_dict()
    stages = payload["stages"]
    assert len(stages) == 9
    for entry in stages:
        assert entry["state"] is not None
        assert entry["state"] in STAGE_STATES
        assert entry["state"] == STATE_NOT_RUN
        assert entry["key"] in STAGE_KEYS
        assert entry["label"], "every stage carries the plain-language label"
    # And it survives a JSON round trip, which is what actually crosses to a UI.
    again = json.loads(json.dumps(payload))
    assert [s["state"] for s in again["stages"]] == [STATE_NOT_RUN] * 9


def test_a_stage_only_moves_when_the_running_process_says_so(tmp_path):
    """Nothing infers a stage. The manager folds in what was written, and
    every stage nobody wrote about stays at not_run."""
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case", command=[], start=False)
    work_dir = Path(record.work_dir)

    reporter = StageReporter(work_dir)
    reporter.started("entry_detected", "reading the source")
    reporter.succeeded("dependencies_resolved", "closure resolved, 3 helpers")

    refreshed = manager.status(record.job_id)
    by_key = {s.key: s for s in refreshed.stages}
    assert by_key["analyze_umat"].state == STATE_SUCCEEDED
    # The other eight were never written about.
    others = [s for s in refreshed.stages if s.key != "analyze_umat"]
    assert len(others) == 8
    assert {s.state for s in others} == {STATE_NOT_RUN}


def test_progress_counts_only_stages_that_reported_and_says_so(tmp_path):
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case", command=[], start=False)
    progress = record.progress
    assert progress.finished == 0
    assert progress.not_run == 9
    assert progress.fraction == 0.0
    assert "no stage has reported yet" in progress.basis

    StageReporter(Path(record.work_dir)).succeeded(
        "entry_detected", "found SUBROUTINE UMAT")
    progress = manager.status(record.job_id).progress
    assert progress.finished == 1
    assert progress.not_run == 8
    assert progress.fraction == pytest.approx(1 / 9)
    assert "8 have not run" in progress.basis


def test_skipped_is_not_the_same_state_as_not_run(tmp_path):
    """Deliberately not attempted, and never attempted, are different answers."""
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case", command=[], start=False)
    reporter = StageReporter(Path(record.work_dir))
    reporter.skipped("reference_resolved",
                     "no finite-difference reference was asked for")
    refreshed = manager.status(record.job_id)
    stage = {s.key: s for s in refreshed.stages}["verify_derivatives"]
    assert stage.state == "skipped"
    assert stage.state != STATE_NOT_RUN
    assert stage.detail
    assert refreshed.progress.skipped == 1
    assert refreshed.progress.finished == 0, (
        "a skipped stage must not be counted as finished")


def test_the_verification_ladder_reports_unreached_rungs_as_not_run():
    """The same rule on the read side, over a real record shape."""
    from umat_oti.services import VerificationService  # noqa: PLC0415

    record = {"stage": "needs_material_data", "reason": "no deck declares it",
              "searched_for_material_data": {"decks_scanned": 4}}
    ladder = VerificationService().ladder(record)
    assert len(ladder) == 9
    states = {rung.key: rung.state for rung in ladder}
    assert states["find_material_data"] == "refused"
    for key in ("build_experiment", "search_activation", "run_original",
                "run_transformed", "compare_histories", "verify_derivatives",
                "create_regression"):
        assert states[key] == STATE_NOT_RUN, key
    # And every rung says why it is where it is.
    assert all(rung.detail for rung in ladder)
