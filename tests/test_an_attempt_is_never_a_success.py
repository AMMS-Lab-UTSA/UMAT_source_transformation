""""Attempted" is never success. This project has violated that before.

A job whose process exited non-zero is failed, with its exit status and its
log. A job whose process is gone and whose exit was never read is ``lost`` --
not succeeded, and not failed either, because neither was established. A job
killed by somebody else's signal says so, and is not filed as our cancellation.

The load-bearing property is on :class:`ExitStatus`: ``succeeded`` is true only
for a returncode of zero that was actually read. ``observed=False`` is not a
synonym for either outcome.
"""
from __future__ import annotations

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
    ExitStatus, JobManager, STATUS_FAILED, STATUS_KILLED_EXTERNALLY,
    STATUS_LOST, STATUS_SUCCEEDED,
)
from umat_oti.jobs import process as process_module  # noqa: E402

pytestmark = pytest.mark.unit


def _settle(manager, job_id, *, timeout=15):
    deadline = time.time() + timeout
    record = manager.status(job_id)
    while time.time() < deadline and not record.terminal:
        time.sleep(0.05)
        record = manager.status(job_id)
    return record


def test_an_unobserved_exit_is_not_a_success_and_not_a_failure():
    status = ExitStatus()
    assert status.observed is False
    assert status.succeeded is False
    assert status.returncode is None
    assert "no exit has been observed" in status.description


def test_only_a_read_zero_counts_as_succeeded():
    assert ExitStatus(observed=True, returncode=0).succeeded is True
    assert ExitStatus(observed=True, returncode=1).succeeded is False
    # Zero that was never read is not a success.
    assert ExitStatus(observed=False, returncode=0).succeeded is False
    # Killed by a signal is never a success, whatever the code says.
    assert ExitStatus(observed=True, returncode=0, signal=15).succeeded is False


def test_a_command_that_exits_non_zero_is_failed_with_its_status(tmp_path):
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case",
                            command=[sys.executable, "-c",
                                     "import sys; sys.exit(3)"])
    settled = _settle(manager, record.job_id)
    assert settled.status == STATUS_FAILED
    assert settled.exit_status.observed is True
    assert settled.exit_status.returncode == 3
    assert settled.exit_status.succeeded is False
    assert Path(settled.log_path).exists()
    # It reached no stage, and does not pretend otherwise.
    assert settled.progress.finished == 0
    assert settled.current_stage is None


def test_a_command_that_exits_zero_is_succeeded(tmp_path):
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case",
                            command=[sys.executable, "-c", "pass"])
    settled = _settle(manager, record.job_id)
    assert settled.status == STATUS_SUCCEEDED
    assert settled.exit_status.returncode == 0
    assert settled.exit_status.source == "waitpid"


def test_a_process_killed_by_someone_else_is_not_filed_as_our_cancellation(tmp_path):
    """Somebody else's kill and our cancel are different events."""
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(30)"])
    os.kill(record.pid, signal.SIGKILL)  # not through the manager
    settled = _settle(manager, record.job_id)
    assert settled.status == STATUS_KILLED_EXTERNALLY
    assert settled.status != "cancelled"
    assert settled.exit_status.signal == signal.SIGKILL
    assert settled.cancellation.requested is False
    assert any("outside this workflow" in note for note in settled.notes)


def test_a_job_whose_process_vanished_unobserved_is_lost_not_succeeded(tmp_path):
    """The state after the interface was closed and the run ended meanwhile.

    A fresh manager is not the child's parent, so ``waitpid`` cannot answer and
    the exit code is genuinely unavailable. The honest report is ``lost`` with
    the log named -- not a success inferred from the stages it managed to write
    before it went.
    """
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case",
                            command=[sys.executable, "-c", "pass"])
    job_id, pid = record.job_id, record.pid

    deadline = time.time() + 15
    while time.time() < deadline and process_module.process_state(pid) not in (
            None, process_module.ZOMBIE):
        time.sleep(0.05)
    os.waitpid(pid, 0)  # a different process reaped it, as init would

    # A manager that never spawned this pid: exactly the post-restart case.
    reopened = JobManager(tmp_path)
    settled = reopened.status(job_id)
    assert settled.status == STATUS_LOST
    assert settled.exit_status.observed is False
    assert settled.exit_status.succeeded is False
    assert "never observed its exit" in settled.exit_status.description
    assert settled.log_path in settled.exit_status.description


def test_a_transformation_that_compiled_is_not_reported_as_verified():
    """The same rule on the services side, over the outcome vocabulary."""
    from umat_oti.services.transformation_service import (  # noqa: PLC0415
        NOT_A_VERIFICATION, TransformationReport,
    )

    report = TransformationReport(transform_success=True,
                                  status_category="succeeded",
                                  compilation={"status": "compiled"})
    payload = report.as_dict()
    assert "verified" not in payload["status_category"]
    assert "compilation is not verification" in payload["what_this_is_not"]
    assert NOT_A_VERIFICATION in payload["what_this_is_not"]
