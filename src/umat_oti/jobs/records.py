"""The job record: what a run is, written down so closing the interface
cannot lose it.

One JSON document per job, on disk, rewritten atomically at every transition.
The owner's requirement is that shutting the GUI does not lose a run, so
nothing that matters may live only in a Streamlit session or a Python object:
the process that is running, where it is running, what it has finished, and how
to stop it all have to survive the interface that started it.

Two rules are structural here rather than a matter of care:

*A stage that has not run reports as not run.* Every stage in the ladder is
present in the record from the moment it is created, at
:data:`~umat_oti.jobs.stages.STATE_NOT_RUN`. Progress is counted from the
stages that actually reported, never from the stage the job is "probably" on,
and :attr:`Progress.basis` says what the count was taken from.

*Attempted is never success.* :class:`ExitStatus` distinguishes "we have not
observed an exit" from "exited 0" from "exited non-zero" from "killed by a
signal" from "the process is gone and we never saw its exit". A job cannot
report success without a returncode of zero actually having been read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Optional

from .stages import (
    STAGE_KEYS, STAGES, STATE_FAILED, STATE_NOT_RUN, STATE_REFUSED,
    STATE_RUNNING, STATE_SKIPPED, STATE_SUCCEEDED, STAGE_STATES, stage_by_key,
)

__all__ = [
    "SCHEMA",
    "JOB_STATUSES",
    "STATUS_QUEUED", "STATUS_RUNNING", "STATUS_SUCCEEDED", "STATUS_FAILED",
    "STATUS_CANCELLED", "STATUS_KILLED_EXTERNALLY", "STATUS_LOST",
    "TERMINAL_STATUSES",
    "utc_now",
    "StageState", "Progress", "ExitStatus", "Cancellation", "Owner",
    "JobRecord",
]

SCHEMA = "umat-oti/job-record/1"

#: Submitted and recorded; no process exists yet.
STATUS_QUEUED = "queued"
#: A process exists and has not been observed to exit.
STATUS_RUNNING = "running"
#: The process exited with returncode 0.
STATUS_SUCCEEDED = "succeeded"
#: The process exited with a non-zero returncode, or a stage reported failure.
STATUS_FAILED = "failed"
#: We asked it to stop, and it stopped.
STATUS_CANCELLED = "cancelled"
#: It died on a signal nobody in this workflow sent. Distinct from cancelled,
#: because "somebody else's kill" and "our cancel" are different events and a
#: reader deciding whether to re-run needs to know which happened.
STATUS_KILLED_EXTERNALLY = "killed_externally"
#: The process is no longer on this machine and we never observed its exit.
#: This is the honest answer after the interface was closed mid-run and
#: restarted: the run is over, and its outcome is not known from the process.
STATUS_LOST = "lost"

JOB_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED,
                STATUS_CANCELLED, STATUS_KILLED_EXTERNALLY, STATUS_LOST)

TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED,
                     STATUS_KILLED_EXTERNALLY, STATUS_LOST)


def utc_now() -> str:
    """An ISO-8601 instant in UTC, with the offset written out."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class StageState:
    """One rung of the ladder as this job has it.

    ``state`` starts at ``not_run`` and only the running job may move it. The
    internal name is kept beside the displayed label because the evidence files
    are keyed on the internal one.
    """

    key: str
    state: str = STATE_NOT_RUN
    #: The internal rung name the running process reported, when it reported one.
    internal: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    #: Why it is in this state. Required for every state but ``not_run``.
    detail: str = ""
    #: Paths this stage produced. Never guessed; written by the stage itself.
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> Optional[str]:
        stage = stage_by_key(self.key)
        return stage.label if stage else None

    @property
    def ran(self) -> bool:
        return self.state != STATE_NOT_RUN

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "state": self.state,
                "internal": self.internal, "started_at": self.started_at,
                "ended_at": self.ended_at, "detail": self.detail,
                "evidence": dict(self.evidence)}


@dataclass
class Progress:
    """How far along, counted from stages that reported and nothing else.

    There is no interpolation, no "probably about half way", and no clock-based
    estimate. ``fraction`` is finished stages over total stages and
    ``basis`` says so in words, so a reader is never shown a number whose
    provenance they cannot check.
    """

    finished: int = 0
    total: int = len(STAGE_KEYS)
    running: int = 0
    not_run: int = len(STAGE_KEYS)
    failed: int = 0
    skipped: int = 0
    refused: int = 0

    @property
    def fraction(self) -> float:
        return (self.finished / self.total) if self.total else 0.0

    @property
    def basis(self) -> str:
        if self.finished == 0 and self.running == 0:
            return ("no stage has reported yet, so nothing is known about how "
                    "far this job got")
        parts = [f"{self.finished} of {self.total} stages succeeded"]
        # Each non-zero state is named. A bar drawn from `finished` alone
        # would show a job whose stages failed as simply behind schedule.
        for count, word in ((self.running, "running"),
                            (self.failed, "failed"),
                            (self.refused, "refused"),
                            (self.skipped, "skipped")):
            if count:
                parts.append(f"{count} {word}")
        parts.append(f"{self.not_run} have not run")
        return "; ".join(parts)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["fraction"] = self.fraction
        out["basis"] = self.basis
        return out


@dataclass
class ExitStatus:
    """What became of the process, or that we do not know.

    ``observed`` false is not a synonym for success and not a synonym for
    failure. It means no exit has been read, which is the state of every
    running job and of every job whose manager was closed before it finished.
    """

    observed: bool = False
    returncode: Optional[int] = None
    #: Set when the process was terminated by a signal: the signal number.
    signal: Optional[int] = None
    #: What we read it from: "waitpid", "the runner's exit file", "/proc".
    source: str = ""
    description: str = "no exit has been observed"

    @property
    def succeeded(self) -> bool:
        """True only for an exit code of zero that was actually read."""
        return self.observed and self.returncode == 0 and self.signal is None

    def as_dict(self) -> dict:
        out = asdict(self)
        out["succeeded"] = self.succeeded
        return out


@dataclass
class Cancellation:
    """Whether a stop was asked for, and exactly what was signalled.

    ``pid_signalled`` is written from the argument actually passed to
    ``os.kill``, not from the pid the record wanted to signal, so the record
    cannot claim a narrower action than the one that was taken.
    """

    requested: bool = False
    requested_at: Optional[str] = None
    requested_by: str = ""
    #: True once a signal was delivered to the tracked pid without error.
    delivered: bool = False
    delivered_at: Optional[str] = None
    signal: Optional[int] = None
    pid_signalled: Optional[int] = None
    #: "exact_pid" or "process_group_we_created". Never a pattern; there is no
    #: value of this field that means a name or command-line match.
    scope: str = ""
    #: Why nothing was signalled, when nothing was.
    refused_reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Owner:
    """Who started this job. Only jobs this workflow owns may be cancelled."""

    #: A token identifying the workflow (not the interface session): jobs
    #: survive the GUI, so this is written once at submit and never rewritten.
    workflow: str = "umat-oti"
    host: str = ""
    user: str = ""
    #: The pid of the process that submitted it. Recorded for provenance only;
    #: it is explicitly NOT used to decide ownership, because the whole point
    #: is that the submitter may be gone.
    submitted_by_pid: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class JobRecord:
    """One run, in full. This is the persisted document."""

    job_id: str
    case_id: str
    kind: str = "verification"
    schema: str = SCHEMA

    #: Provenance of the code and the input, so a result can be tied to them.
    commit: str = ""
    commit_dirty: Optional[bool] = None
    source_hashes: dict[str, str] = field(default_factory=dict)

    status: str = STATUS_QUEUED
    #: The stage key currently running, or the last one that did. None until a
    #: stage reports; never seeded with the first stage as a guess.
    current_stage: Optional[str] = None
    stages: list[StageState] = field(default_factory=list)

    created_at: str = field(default_factory=utc_now)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    #: The exact tracked pid. Everything that signals this job signals this.
    pid: Optional[int] = None
    #: The process's own start time as the kernel records it, used to refuse to
    #: signal a recycled pid. Without this, a pid that was reused between the
    #: record being written and cancel being pressed would be somebody else's.
    pid_identity: Optional[str] = None
    #: The pid of the command under the tracked process, when the tracked
    #: process is a supervisor. Recorded so nothing is hidden; never signalled
    #: directly -- the supervisor is asked to stop and it stops its own child.
    command_pid: Optional[int] = None
    #: True only when this workflow created the process group (setsid at spawn)
    #: and the group id equals the tracked pid.
    owns_process_group: bool = False

    work_dir: str = ""
    log_path: str = ""
    command: list[str] = field(default_factory=list)

    cancellation: Cancellation = field(default_factory=Cancellation)
    exit_status: ExitStatus = field(default_factory=ExitStatus)
    owner: Owner = field(default_factory=Owner)

    #: Final evidence, by name. Empty until a stage or the job writes one.
    evidence_paths: dict[str, str] = field(default_factory=dict)
    #: Free-form provenance the caller wants carried (deck digest, fingerprint).
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Anything that went wrong which is about the harness rather than the model.
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = [StageState(key=key) for key in STAGE_KEYS]
        known = {s.key for s in self.stages}
        missing = [k for k in STAGE_KEYS if k not in known]
        for key in missing:
            self.stages.append(StageState(key=key))
        self.stages.sort(key=lambda s: STAGE_KEYS.index(s.key)
                         if s.key in STAGE_KEYS else len(STAGE_KEYS))

    # -- reading -----------------------------------------------------------

    def stage(self, key: str) -> Optional[StageState]:
        for entry in self.stages:
            if entry.key == key:
                return entry
        return None

    @property
    def progress(self) -> Progress:
        counts = {state: 0 for state in STAGE_STATES}
        for entry in self.stages:
            counts[entry.state] = counts.get(entry.state, 0) + 1
        return Progress(
            finished=counts[STATE_SUCCEEDED],
            total=len(self.stages),
            running=counts[STATE_RUNNING],
            not_run=counts[STATE_NOT_RUN],
            failed=counts[STATE_FAILED],
            skipped=counts[STATE_SKIPPED],
            refused=counts[STATE_REFUSED],
        )

    @property
    def current_stage_label(self) -> Optional[str]:
        stage = stage_by_key(self.current_stage) if self.current_stage else None
        return stage.label if stage else None

    @property
    def running(self) -> bool:
        return self.status == STATUS_RUNNING

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "job_id": self.job_id,
            "case_id": self.case_id,
            "kind": self.kind,
            "commit": self.commit,
            "commit_dirty": self.commit_dirty,
            "source_hashes": dict(self.source_hashes),
            "status": self.status,
            "current_stage": self.current_stage,
            "current_stage_label": self.current_stage_label,
            "stages": [s.as_dict() for s in self.stages],
            "progress": self.progress.as_dict(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "pid": self.pid,
            "pid_identity": self.pid_identity,
            "command_pid": self.command_pid,
            "owns_process_group": self.owns_process_group,
            "work_dir": self.work_dir,
            "log_path": self.log_path,
            "command": list(self.command),
            "cancellation": self.cancellation.as_dict(),
            "exit_status": self.exit_status.as_dict(),
            "owner": self.owner.as_dict(),
            "evidence_paths": dict(self.evidence_paths),
            "metadata": dict(self.metadata),
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"

    # -- writing -----------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: dict) -> "JobRecord":
        stages = [
            StageState(key=s.get("key", ""), state=s.get("state", STATE_NOT_RUN),
                       internal=s.get("internal"),
                       started_at=s.get("started_at"),
                       ended_at=s.get("ended_at"),
                       detail=s.get("detail", "") or "",
                       evidence=dict(s.get("evidence") or {}))
            for s in payload.get("stages") or []
            if s.get("key") in STAGE_KEYS
        ]
        cancellation = Cancellation(**{
            k: v for k, v in (payload.get("cancellation") or {}).items()
            if k in Cancellation.__dataclass_fields__})
        exit_status = ExitStatus(**{
            k: v for k, v in (payload.get("exit_status") or {}).items()
            if k in ExitStatus.__dataclass_fields__})
        owner = Owner(**{
            k: v for k, v in (payload.get("owner") or {}).items()
            if k in Owner.__dataclass_fields__})
        return cls(
            job_id=payload["job_id"],
            case_id=payload.get("case_id", ""),
            kind=payload.get("kind", "verification"),
            schema=payload.get("schema", SCHEMA),
            commit=payload.get("commit", "") or "",
            commit_dirty=payload.get("commit_dirty"),
            source_hashes=dict(payload.get("source_hashes") or {}),
            status=payload.get("status", STATUS_QUEUED),
            current_stage=payload.get("current_stage"),
            stages=stages,
            created_at=payload.get("created_at") or utc_now(),
            started_at=payload.get("started_at"),
            ended_at=payload.get("ended_at"),
            pid=payload.get("pid"),
            pid_identity=payload.get("pid_identity"),
            command_pid=payload.get("command_pid"),
            owns_process_group=bool(payload.get("owns_process_group")),
            work_dir=payload.get("work_dir", "") or "",
            log_path=payload.get("log_path", "") or "",
            command=list(payload.get("command") or []),
            cancellation=cancellation,
            exit_status=exit_status,
            owner=owner,
            evidence_paths=dict(payload.get("evidence_paths") or {}),
            metadata=dict(payload.get("metadata") or {}),
            notes=list(payload.get("notes") or []),
        )
