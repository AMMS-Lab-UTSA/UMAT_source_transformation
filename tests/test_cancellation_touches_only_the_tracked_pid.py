"""Cancelling one run must not touch any other process on this machine.

This is a safety test, not a style test. This machine runs other researchers'
Abaqus jobs and 150 licence tokens are held by someone else right now. A
``pkill -f abaqus`` in a cancel button would take those down, and the failure
would look like their solver crashing rather than like our button.

So: cancellation sends one signal, to the integer pid in the job record, and to
nothing else. A bystander process running beside the tracked one is still
running afterwards. The package contains no pattern match that could reach it.
"""
from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from umat_oti.jobs import JobManager, UnknownJob  # noqa: E402
from umat_oti.jobs import process as process_module  # noqa: E402

pytestmark = pytest.mark.unit

JOBS_PACKAGE = SRC / "umat_oti" / "jobs"
SERVICES_PACKAGE = SRC / "umat_oti" / "services"


def code_only(path: Path) -> str:
    """The module's executable text, with comments and string literals removed.

    Necessary because this package *documents* the forbidden calls in order to
    explain why they are absent. A naive substring scan flags that prose and
    would push the next author into deleting the explanation to get a green
    suite, which is the opposite of what this test is for.
    """
    pieces = []
    with open(path, "rb") as stream:
        for token in tokenize.tokenize(stream.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if token.type in (tokenize.NEWLINE, tokenize.NL):
                pieces.append("\n")
                continue
            pieces.append(token.string)
    return "".join(pieces)


def _sleeper(seconds: int = 30) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c",
                             f"import time; time.sleep({seconds})"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def _still_running(pid: int) -> bool:
    """True while the pid exists and has not become a zombie."""
    return process_module.process_state(pid) not in (None, process_module.ZOMBIE)


def test_a_bystander_process_is_untouched_by_a_cancel(tmp_path):
    """The whole point. Two processes, one cancel, one survivor."""
    bystander = _sleeper()
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case-a",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(30)"])
    try:
        assert record.pid is not None
        assert record.pid != bystander.pid
        assert _still_running(bystander.pid)

        outcome = manager.cancel(record.job_id)
        assert outcome.signalled is True
        assert outcome.pid == record.pid
        assert outcome.scope == "exact_pid"

        deadline = time.time() + 10
        while time.time() < deadline and _still_running(record.pid):
            time.sleep(0.05)
        assert not _still_running(record.pid), "the tracked job did not stop"

        # The one that matters.
        assert _still_running(bystander.pid), (
            "a process this workflow never started was killed by a cancel")
    finally:
        bystander.terminate()
        bystander.wait(timeout=10)
        manager.status(record.job_id)


def test_exactly_one_signal_is_sent_and_it_names_the_tracked_pid(tmp_path, monkeypatch):
    """Not "a signal was sent somewhere" -- this pins the argument."""
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case-b",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(30)"])
    calls: list[tuple] = []
    real_kill = os.kill

    def recording_kill(pid, sig):
        calls.append(("kill", pid, sig))
        return real_kill(pid, sig)

    def forbidden_killpg(pgid, sig):  # pragma: no cover - must never run
        calls.append(("killpg", pgid, sig))
        raise AssertionError("a plain cancel must not signal a process group")

    monkeypatch.setattr(process_module.os, "kill", recording_kill)
    monkeypatch.setattr(process_module.os, "killpg", forbidden_killpg)

    manager.cancel(record.job_id)

    # identity_of does not signal; only the delivery does. The guard's
    # os.kill(pid, 0) liveness probe may appear, so filter to real signals.
    delivered = [c for c in calls if c[2] != 0]
    assert len(delivered) == 1, delivered
    assert delivered[0] == ("kill", record.pid, signal.SIGTERM)

    monkeypatch.undo()
    deadline = time.time() + 10
    while time.time() < deadline and _still_running(record.pid):
        time.sleep(0.05)
    manager.status(record.job_id)


def test_a_recycled_pid_is_refused_by_the_signaller_itself(tmp_path):
    """A pid is not an identity, and the guard is in the signalling function.

    If the tracked process ended and the kernel handed its pid to somebody
    else, the record still names that integer. Signalling it would kill a
    stranger. This drives :func:`signal_exact_pid` directly, because that is
    the function anything in this package must go through to send a signal,
    and it proves the guard REFUSES rather than signalling and hoping.
    """
    live = _sleeper()
    try:
        real_identity = process_module.identity_of(live.pid)
        assert real_identity is not None, (
            "this platform reported no start-time, so the guard cannot be tested")

        outcome = process_module.signal_exact_pid(
            live.pid,
            expected_identity=str(int(real_identity) + 1),
            sig=signal.SIGKILL)

        assert outcome.signalled is False
        assert outcome.pid is None
        assert "recycled" in outcome.reason
        assert _still_running(live.pid), (
            "a process whose recorded identity did not match was signalled")
    finally:
        live.terminate()
        live.wait(timeout=10)


def test_the_manager_will_not_signal_a_job_whose_identity_no_longer_matches(
        tmp_path, monkeypatch):
    """End to end: a record whose pid identity has moved signals nothing.

    The manager refuses one step earlier than the signaller does -- it
    reconciles first, sees that the tracked process is no longer the one it
    started, and reports the job as lost. Either way the safety property is
    the same and it is the one asserted here: no signal left this process.
    """
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case-c",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(30)"])
    assert record.pid_identity is not None

    stored = manager.store.read(record.job_id)
    stored.pid_identity = str(int(stored.pid_identity) + 1)
    manager.store.write(stored)

    signalled: list = []
    real_kill = os.kill

    def recording_kill(pid, sig):
        if sig != 0:
            signalled.append((pid, sig))
        return real_kill(pid, sig)

    monkeypatch.setattr(process_module.os, "kill", recording_kill)
    outcome = manager.cancel(record.job_id)
    monkeypatch.undo()

    assert outcome.signalled is False
    assert signalled == [], "a pid whose identity did not match was signalled"
    # And the job is not reported as cancelled, because nothing cancelled it.
    assert manager.store.read(record.job_id).status != "cancelled"

    real_kill(record.pid, signal.SIGKILL)
    deadline = time.time() + 10
    while time.time() < deadline and _still_running(record.pid):
        time.sleep(0.05)


def test_a_job_this_store_never_started_cannot_be_cancelled(tmp_path):
    """Only jobs this workflow owns. An unknown id raises; it never guesses."""
    manager = JobManager(tmp_path)
    with pytest.raises(UnknownJob):
        manager.cancel("0123456789abcdef0123456789abcdef")


def test_a_process_group_stop_is_refused_for_a_group_we_did_not_create(tmp_path):
    """The only group that may be signalled is one this workflow made itself."""
    manager = JobManager(tmp_path)
    record = manager.submit("verification", "case-d",
                            command=[sys.executable, "-c",
                                     "import time; time.sleep(30)"])
    stored = manager.store.read(record.job_id)
    stored.owns_process_group = False
    manager.store.write(stored)

    outcome = manager.cancel(record.job_id, process_group=True)
    assert outcome.signalled is False
    assert "did not create" in outcome.reason

    os.kill(record.pid, signal.SIGKILL)
    deadline = time.time() + 10
    while time.time() < deadline and _still_running(record.pid):
        time.sleep(0.05)
    manager.status(record.job_id)


@pytest.mark.parametrize("package", [JOBS_PACKAGE, SERVICES_PACKAGE])
def test_no_pattern_kill_exists_anywhere_in_the_package(package):
    """There is no code path to reach for, so nobody can reach for it later.

    Checked over the source text rather than by behaviour, because the danger
    is a future edit adding one, and a behavioural test only catches the paths
    it happens to walk.
    """
    forbidden = ("pkill", "killall", "psutil", "os.system", "pgrep",
                 "shell", "system")
    for path in sorted(package.rglob("*.py")):
        code = code_only(path)
        for needle in forbidden:
            assert needle not in code, (
                f"{path} contains {needle!r} in executable code. A pattern "
                f"kill on this machine would take down another researcher's "
                f"Abaqus jobs.")


def test_the_only_signal_calls_in_the_package_take_an_integer_pid():
    """``os.kill`` and ``os.killpg`` appear in exactly one module."""
    signalling = []
    for path in sorted(JOBS_PACKAGE.rglob("*.py")):
        code = code_only(path)
        if "os.kill(" in code or "os.killpg(" in code:
            signalling.append(path.name)
    assert signalling, "no signalling code found at all; the test is stale"
    assert set(signalling) == {"process.py"}, signalling
