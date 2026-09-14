"""The job manager: submit, track, cancel, and survive being closed.

What it is for
--------------
A verification run takes hours and holds Abaqus licence tokens. The owner's
requirement is that closing the GUI does not lose one. So the manager keeps
nothing that matters in memory: the record is on disk before the process
starts, the process is put in a session of its own so it outlives the
interface, and a fresh :class:`JobManager` over the same root reconciles every
record against the machine it finds.

What it refuses to do
---------------------
*It does not invent progress.* Stages come from what the running process wrote
(:mod:`umat_oti.jobs.reporter`) and from nothing else. A stage nobody reported
stays ``not_run``.

*It does not turn an attempt into a success.* ``succeeded`` requires a
returncode of zero that was actually read. A job whose process is gone and
whose exit was never observed is ``lost`` -- not failed, not succeeded.

*It does not kill by pattern.* Cancellation goes to the exact pid in the
record, guarded by that pid's kernel start-time so a recycled pid is refused
rather than signalled. See :mod:`umat_oti.jobs.process`.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import signal as signal_module
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import process as process_module
from .records import (
    Cancellation, ExitStatus, JobRecord, Owner, STATUS_CANCELLED,
    STATUS_FAILED, STATUS_KILLED_EXTERNALLY, STATUS_LOST, STATUS_QUEUED,
    STATUS_RUNNING, STATUS_SUCCEEDED, utc_now,
)
from .reporter import read_stage_events
from .stages import (
    STAGE_KEYS, STATE_FAILED, STATE_NOT_RUN, STATE_RUNNING, STATE_SUCCEEDED,
)
from .store import JobStore

__all__ = ["CancelOutcome", "JobManager", "UnknownJob"]


class UnknownJob(KeyError):
    """A job id this store has no record of. Never cancelled, never guessed."""

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id

    def __str__(self) -> str:
        return (f"no job {self.job_id!r} in this store. Only jobs this "
                f"workflow started may be tracked or cancelled.")


@dataclass
class CancelOutcome:
    """What cancel actually did, in terms of the signal it actually sent."""

    job_id: str
    signalled: bool
    pid: Optional[int]
    signal: Optional[int]
    scope: str
    reason: str
    record: Optional[JobRecord] = None

    def as_dict(self) -> dict:
        return {"job_id": self.job_id, "signalled": self.signalled,
                "pid": self.pid, "signal": self.signal, "scope": self.scope,
                "reason": self.reason,
                "record": self.record.as_dict() if self.record else None}


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_state(repo_root: Optional[Path]) -> tuple[str, Optional[bool]]:
    """``(commit, dirty)``. ``("", None)`` where git cannot answer.

    An empty commit is not the same as an unknown one and neither is the same
    as a clean tree, so ``dirty`` stays ``None`` rather than defaulting to
    ``False`` when the question could not be asked.
    """
    if repo_root is None:
        return "", None
    try:
        commit = subprocess.run(  # noqa: S603 - list form, fixed arguments
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False)
        if commit.returncode != 0:
            return "", None
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30, check=False)
        dirty = None if status.returncode != 0 else bool(status.stdout.strip())
        return commit.stdout.strip(), dirty
    except (OSError, subprocess.SubprocessError):
        return "", None


class JobManager:
    """Submit, track and cancel runs, over a persistent store."""

    def __init__(self, root: Path, *, repo_root: Optional[Path] = None,
                 workflow: str = "umat-oti") -> None:
        self.store = JobStore(root)
        self.repo_root = Path(repo_root) if repo_root else None
        self.workflow = workflow

    # -- submitting --------------------------------------------------------

    def submit(self, kind: str, case_id: str, *,
               command: Sequence[str],
               source_paths: Iterable[Path] = (),
               metadata: Optional[dict] = None,
               start: bool = True,
               spawn=None) -> JobRecord:
        """Record a job, then start it. The record exists before the process.

        The order is deliberate. If the record were written after the spawn, a
        crash in between would leave a running process with no record -- a job
        nobody can find and nobody can stop, which is exactly the situation
        that makes somebody reach for a pattern kill.

        ``spawn`` is an injection point for tests; production leaves it None
        and gets :func:`umat_oti.jobs.process.spawn_detached`.
        """
        job_id = uuid.uuid4().hex
        work_dir = self.store.work_dir(job_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        log_path = work_dir / "job.log"

        commit, dirty = _git_state(self.repo_root)
        hashes: dict[str, str] = {}
        for path in source_paths:
            path = Path(path)
            if path.is_file():
                hashes[str(path)] = _sha256_of(path)
            else:
                # Recorded as missing rather than omitted: a source that was
                # not there is a fact about the run, and dropping the key would
                # make the record look like it was never asked for.
                hashes[str(path)] = ""

        record = JobRecord(
            job_id=job_id,
            case_id=case_id,
            kind=kind,
            commit=commit,
            commit_dirty=dirty,
            source_hashes=hashes,
            work_dir=str(work_dir),
            log_path=str(log_path),
            command=[str(part) for part in command],
            metadata=dict(metadata or {}),
            owner=Owner(workflow=self.workflow,
                        host=socket.gethostname(),
                        user=_current_user(),
                        submitted_by_pid=os.getpid()),
        )
        for name, digest in hashes.items():
            if not digest:
                record.notes.append(
                    f"source {name} was not a file at submit time, so no hash "
                    f"was taken; the run's inputs are not fully pinned")
        self.store.write(record)
        self.store.append_event(job_id, {"event": "submitted", "kind": kind,
                                         "case_id": case_id,
                                         "command": record.command})
        if not start:
            return record
        return self.start(job_id, spawn=spawn)

    def start(self, job_id: str, *, spawn=None) -> JobRecord:
        record = self._require(job_id)
        if record.pid is not None:
            return self.status(job_id)
        spawn = spawn or process_module.spawn_detached
        result = spawn(record.command, cwd=Path(record.work_dir),
                       log_path=Path(record.log_path))
        record.pid = int(result.pid)
        record.pid_identity = result.identity
        record.owns_process_group = bool(result.owns_process_group)
        record.status = STATUS_RUNNING
        record.started_at = utc_now()
        if result.identity is None:
            record.notes.append(
                "this machine would not report a start-time for the tracked "
                "pid, so the pid-reuse guard cannot be armed; cancellation "
                "will proceed without it only because no identity was ever "
                "recorded to contradict")
        self.store.write(record)
        self.store.append_event(job_id, {"event": "started", "pid": record.pid,
                                         "pid_identity": record.pid_identity})
        return record

    # -- tracking ----------------------------------------------------------

    def status(self, job_id: str) -> JobRecord:
        """The record, refreshed from the stage log and from the machine."""
        return self._refresh(self._require(job_id))

    def list_jobs(self, *, kind: Optional[str] = None,
                  status: Optional[str] = None,
                  case_id: Optional[str] = None) -> list[JobRecord]:
        """Every job, newest first, each refreshed. Filters narrow; nothing hides."""
        records = [self._refresh(record) for record in self.store.read_all()]
        if kind is not None:
            records = [r for r in records if r.kind == kind]
        if status is not None:
            records = [r for r in records if r.status == status]
        if case_id is not None:
            records = [r for r in records if r.case_id == case_id]
        return records

    def events(self, job_id: str) -> list[dict]:
        return self.store.events(job_id)

    def _require(self, job_id: str) -> JobRecord:
        record = self.store.read(job_id)
        if record is None:
            raise UnknownJob(job_id)
        return record

    def _refresh(self, record: JobRecord) -> JobRecord:
        before = record.to_json()
        self._apply_stage_events(record)
        self._reconcile_process(record)
        if record.to_json() != before:
            self.store.write(record)
        return record

    def _apply_stage_events(self, record: JobRecord) -> None:
        """Fold what the process wrote into the record. Nothing else moves a stage."""
        if not record.work_dir:
            return
        for event in read_stage_events(Path(record.work_dir)):
            key = event.get("stage")
            if key not in STAGE_KEYS:
                if "unparseable" in event:
                    note = ("a stage event was being written when the job "
                            "stopped and could not be read back: "
                            f"{event['unparseable'][:200]}")
                    if note not in record.notes:
                        record.notes.append(note)
                continue
            stage = record.stage(key)
            if stage is None:
                continue
            stage.state = event.get("state", stage.state)
            stage.internal = event.get("internal") or stage.internal
            stage.detail = event.get("detail", "") or stage.detail
            if event.get("evidence"):
                stage.evidence.update(event["evidence"])
                record.evidence_paths.update(event["evidence"])
            when = event.get("at")
            if event.get("state") == STATE_RUNNING:
                stage.started_at = stage.started_at or when
            elif event.get("state") != STATE_NOT_RUN:
                stage.started_at = stage.started_at or when
                stage.ended_at = when
            record.current_stage = key

    def _reconcile_process(self, record: JobRecord) -> None:
        """Decide the status from what the machine says, and nothing softer."""
        if record.pid is None or record.status in (STATUS_SUCCEEDED,
                                                   STATUS_FAILED,
                                                   STATUS_CANCELLED,
                                                   STATUS_KILLED_EXTERNALLY,
                                                   STATUS_LOST):
            return

        # If we are the parent, waitpid is the authoritative answer and it also
        # reaps the zombie. It is asked first for exactly that reason.
        reaped = self._try_wait(record)
        if not reaped and process_module.is_alive(record.pid,
                                                  record.pid_identity):
            record.status = STATUS_RUNNING
            return
        if not reaped:
            # The process is gone and we never read its exit. Say that.
            record.exit_status = ExitStatus(
                observed=False, source="/proc",
                description=(
                    f"pid {record.pid} is no longer running and this manager "
                    f"never observed its exit, so the outcome is not known "
                    f"from the process. The log at {record.log_path} is what "
                    f"there is."))
            record.status = STATUS_LOST
            record.ended_at = record.ended_at or utc_now()
            record.notes.append(
                "the process ended while no manager was watching it; its "
                "status is reported as lost rather than guessed from the "
                "stages it managed to write")
            self.store.append_event(record.job_id, {"event": "lost",
                                                    "pid": record.pid})
        self._settle_status(record)

    def _try_wait(self, record: JobRecord) -> bool:
        """Reap our own child if it has exited. False if it is not our child."""
        try:
            pid, raw = os.waitpid(int(record.pid), os.WNOHANG)
        except (ChildProcessError, OSError):
            return False
        if pid == 0:
            return False
        killed_by = os.WTERMSIG(raw) if os.WIFSIGNALED(raw) else None
        code = os.WEXITSTATUS(raw) if os.WIFEXITED(raw) else None
        record.exit_status = ExitStatus(
            observed=True,
            returncode=code if killed_by is None else -killed_by,
            signal=killed_by,
            source="waitpid",
            description=(f"exited with status {code}" if killed_by is None
                         else f"terminated by signal {killed_by}"))
        record.ended_at = record.ended_at or utc_now()
        self.store.append_event(record.job_id, {
            "event": "exited", "pid": record.pid,
            "returncode": record.exit_status.returncode,
            "signal": killed_by})
        return True

    def _settle_status(self, record: JobRecord) -> None:
        """Map an observed exit onto a status. Nothing is charitable here."""
        exit_status = record.exit_status
        if not exit_status.observed:
            return
        if exit_status.signal is not None:
            if record.cancellation.requested and record.cancellation.delivered:
                record.status = STATUS_CANCELLED
            else:
                record.status = STATUS_KILLED_EXTERNALLY
                record.notes.append(
                    f"this process was terminated by signal "
                    f"{exit_status.signal} and no cancellation was requested "
                    f"through this manager, so the signal came from outside "
                    f"this workflow")
            record.ended_at = record.ended_at or utc_now()
            return
        if exit_status.returncode == 0:
            record.status = STATUS_SUCCEEDED
        else:
            record.status = STATUS_FAILED
        record.ended_at = record.ended_at or utc_now()

    # -- cancelling --------------------------------------------------------

    def cancel(self, job_id: str, *, reason: str = "",
               requested_by: str = "",
               sig: int = signal_module.SIGTERM,
               process_group: bool = False) -> CancelOutcome:
        """Stop exactly this job's process, or refuse and say why.

        ``process_group`` is only honoured for a group this workflow created
        with ``setsid``, whose group id equals the tracked pid. It is never a
        pattern and there is no argument that makes it one.
        """
        record = self.store.read(job_id)
        if record is None:
            raise UnknownJob(job_id)
        record = self._refresh(record)

        record.cancellation.requested = True
        record.cancellation.requested_at = utc_now()
        record.cancellation.requested_by = requested_by or _current_user()

        if record.terminal:
            record.cancellation.refused_reason = (
                f"this job is already {record.status}; nothing was signalled")
            self.store.write(record)
            return CancelOutcome(job_id, False, None, None, "",
                                 record.cancellation.refused_reason, record)
        if record.pid is None:
            record.cancellation.refused_reason = (
                "this job has no process yet, so there is nothing to signal")
            self.store.write(record)
            return CancelOutcome(job_id, False, None, None, "",
                                 record.cancellation.refused_reason, record)

        outcome = process_module.signal_exact_pid(
            record.pid,
            expected_identity=record.pid_identity,
            sig=sig,
            process_group=process_group,
            owns_process_group=record.owns_process_group)

        record.cancellation.delivered = outcome.signalled
        record.cancellation.signal = outcome.signal
        record.cancellation.pid_signalled = outcome.pid if outcome.signalled else None
        record.cancellation.scope = outcome.scope if outcome.signalled else ""
        if outcome.signalled:
            record.cancellation.delivered_at = utc_now()
            record.cancellation.refused_reason = ""
            if reason:
                record.notes.append(f"cancellation requested: {reason}")
        else:
            record.cancellation.refused_reason = outcome.reason
        self.store.write(record)
        self.store.append_event(job_id, {
            "event": "cancel_requested", "signalled": outcome.signalled,
            "pid_signalled": record.cancellation.pid_signalled,
            "signal": outcome.signal, "scope": outcome.scope,
            "reason": outcome.reason})
        return CancelOutcome(job_id, outcome.signalled,
                             record.cancellation.pid_signalled,
                             outcome.signal, record.cancellation.scope,
                             outcome.reason, record)


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - a missing passwd entry is not fatal
        return ""
