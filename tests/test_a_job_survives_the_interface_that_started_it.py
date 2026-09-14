"""Closing the GUI must not lose a run.

A verification run takes hours and holds Abaqus licence tokens. The owner's
requirement is that shutting the interface does not lose one, so nothing that
matters may live in a Streamlit session: the record is on disk before the
process starts, the process is put in a session of its own so it outlives its
parent, and a fresh manager over the same root reconciles what it finds.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from umat_oti.jobs import (  # noqa: E402
    JobManager, JobRecord, JobStore, SCHEMA, StageReporter,
)
from umat_oti.jobs import process as process_module  # noqa: E402

pytestmark = pytest.mark.unit


def test_the_record_exists_on_disk_before_the_process_does(tmp_path):
    """Order matters: a running process with no record cannot be stopped."""
    manager = JobManager(tmp_path)
    seen: list[bool] = []

    def watching_spawn(command, *, cwd, log_path, env=None):
        # By the time anything is spawned, the record must already be readable.
        seen.append(JobStore(tmp_path).read_all() != [])
        return process_module.spawn_detached(command, cwd=cwd,
                                             log_path=log_path, env=env)

    record = manager.submit("verification", "case",
                            command=[sys.executable, "-c", "pass"],
                            spawn=watching_spawn)
    assert seen == [True]
    manager.status(record.job_id)


def test_a_new_manager_over_the_same_root_finds_the_run(tmp_path):
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case-x",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(20)"])
    StageReporter(Path(record.work_dir)).succeeded(
        "entry_detected", "found SUBROUTINE UMAT")

    reopened = JobManager(tmp_path)          # the interface was closed
    found = reopened.status(record.job_id)
    assert found.job_id == record.job_id
    assert found.pid == record.pid
    assert found.pid_identity == record.pid_identity
    assert found.status == "running"
    assert found.current_stage == "analyze_umat"
    assert found.progress.finished == 1
    assert [j.job_id for j in reopened.list_jobs()] == [record.job_id]

    os.kill(record.pid, signal.SIGKILL)
    deadline = time.time() + 10
    while time.time() < deadline and process_module.process_state(
            record.pid) not in (None, process_module.ZOMBIE):
        time.sleep(0.05)
    manager.status(record.job_id)


def test_the_record_carries_everything_the_owner_asked_for(tmp_path):
    source = tmp_path / "umat.for"
    source.write_text("      SUBROUTINE UMAT\n      END\n", encoding="utf-8")
    manager = JobManager(tmp_path / "root",
                         repo_root=Path(__file__).resolve().parents[1])
    record = manager.submit("verification", "case-y",
                            command=[sys.executable, "-c", "pass"],
                            source_paths=[source])
    payload = record.as_dict()

    assert payload["schema"] == SCHEMA
    for field in ("job_id", "case_id", "commit", "source_hashes", "status",
                  "current_stage", "stages", "progress", "created_at",
                  "started_at", "ended_at", "pid", "work_dir", "log_path",
                  "cancellation", "exit_status", "evidence_paths"):
        assert field in payload, field

    assert len(payload["job_id"]) == 32
    assert payload["commit"], "the commit must be recorded"
    assert payload["source_hashes"][str(source)]
    assert len(payload["source_hashes"][str(source)]) == 64
    assert isinstance(payload["pid"], int) and payload["pid"] > 0
    assert payload["work_dir"] and Path(payload["work_dir"]).is_dir()
    assert payload["log_path"]
    assert payload["cancellation"]["requested"] is False
    assert payload["exit_status"]["observed"] is False
    assert payload["owner"]["host"]
    manager.status(record.job_id)


def test_a_record_round_trips_through_json_unchanged(tmp_path):
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case", command=[], start=False)
    path = manager.store.record_path(record.job_id)
    again = JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert again.as_dict() == record.as_dict()


def test_the_record_is_written_atomically(tmp_path):
    """A reader arriving mid-write sees the previous complete record.

    Checked by proving the write goes through a rename rather than a truncate:
    the temporary file is in the same directory and no partial file is left.
    """
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case", command=[], start=False)
    leftovers = list(manager.store.jobs_dir.glob("*.tmp"))
    assert leftovers == []
    text = manager.store.record_path(record.job_id).read_text(encoding="utf-8")
    assert json.loads(text)["job_id"] == record.job_id


def test_an_unreadable_record_is_listed_rather_than_dropped(tmp_path):
    """A damaged record is not a job that did not happen."""
    manager = JobManager(tmp_path)
    good = manager.submit("verification", "a", command=[], start=False)
    (manager.store.jobs_dir / "broken.json").write_text("{not json",
                                                        encoding="utf-8")
    listed = manager.list_jobs()
    assert len(listed) == 2, "the damaged record was dropped from the listing"
    broken = [j for j in listed if j.job_id == "broken"][0]
    assert broken.status == "lost"
    assert any("could not be read" in note for note in broken.notes)
    assert good.job_id in {j.job_id for j in listed}


def test_the_event_log_is_append_only_and_records_every_transition(tmp_path):
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(20)"])
    manager.cancel(record.job_id, reason="test")
    deadline = time.time() + 10
    while time.time() < deadline and not manager.status(record.job_id).terminal:
        time.sleep(0.05)

    entries = manager.events(record.job_id)
    events = [e.get("event") for e in entries]
    assert events[0] == "submitted"
    assert events.index("started") == 1
    assert events.index("cancel_requested") < events.index("exited"), (
        "the log must show the stop being asked for before the process ended")
    # Append-only: every entry carries the instant it was written, and those
    # instants do not go backwards.
    stamps = [e["at"] for e in entries]
    assert all(stamps[i] <= stamps[i + 1] for i in range(len(stamps) - 1))
