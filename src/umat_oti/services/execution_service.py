"""AbaqusExecutionService: request a run, track it, cancel it.

**This service does not run Abaqus.** The licence budget and the Abaqus process
controller belong to the project lead. What this service does is make a run a
*tracked* thing: it files a request into the lead's queue directory, creates a
persisted job record for it, and gives the interface one place to ask how it is
going and one place to stop it.

Two shapes of run, and they are not mixed up:

``submit_queue_request``
    the real thing. A JSON request lands in ``abaqus_queue/requests/`` in the
    shape the lead already uses, the job record is created at ``queued``, and
    :meth:`track` watches ``abaqus_queue/results/`` for the answer. No Abaqus
    process is started here and no licence token is taken.

``submit_local``
    a local command this workflow owns end to end (an offline probe, a
    regression replay). It really is spawned, and it really is tracked by pid.

Cancellation goes through :class:`~umat_oti.jobs.JobManager`, which signals the
exact tracked pid. A queued request that never became a local process has no pid
and reports that rather than signalling anything.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from ._support import REPO_ROOT
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs import JobManager, JobRecord
from umat_oti.jobs.records import STATUS_QUEUED, utc_now

__all__ = ["RunTicket", "AbaqusExecutionService", "DEFAULT_QUEUE",
           "default_queue_root", "QUEUE_ENVIRONMENT_VARIABLE"]

SERVICE = "abaqus_execution"

#: Environment variable naming the lead's Abaqus queue directory.
QUEUE_ENVIRONMENT_VARIABLE = "UMAT_OTI_ABAQUS_QUEUE"


def default_queue_root() -> Path:
    """Where the lead's queue lives, derived rather than written down.

    An absolute path to somebody's home directory in the source is a path that
    is wrong on every other machine, and this repository has a standards test
    that says so. The queue sits beside the checkout, so it is derived from the
    checkout; ``UMAT_OTI_ABAQUS_QUEUE`` overrides that for anyone whose layout
    differs.
    """
    override = os.environ.get(QUEUE_ENVIRONMENT_VARIABLE)
    if override:
        return Path(override).expanduser()
    return REPO_ROOT.parent / "abaqus_queue"


DEFAULT_QUEUE = default_queue_root()


@dataclass
class RunTicket:
    """A run this workflow has asked for and can now follow."""

    job_id: str
    case_id: str
    #: Where the request was filed, for a queued run. Empty for a local one.
    queue_request_path: str = ""
    results_expected_at: str = ""
    estimated_jobs: Optional[int] = None
    record: Optional[JobRecord] = None
    #: Populated once the lead's results file appears.
    results_path: str = ""

    def as_dict(self) -> dict:
        return {
            "job_id": self.job_id, "case_id": self.case_id,
            "queue_request_path": self.queue_request_path,
            "results_expected_at": self.results_expected_at,
            "estimated_jobs": self.estimated_jobs,
            "results_path": self.results_path,
            "record": self.record.as_dict() if self.record else None,
        }


class AbaqusExecutionService:
    """Request and track Abaqus work without ever spawning Abaqus."""

    def __init__(self, manager: JobManager, *,
                 queue_root: Optional[Path] = None,
                 repo_root: Path = REPO_ROOT,
                 filed_by: str = "Agent 5 (backend services)") -> None:
        self.manager = manager
        self.queue_root = Path(queue_root) if queue_root else default_queue_root()
        self.repo_root = Path(repo_root)
        self.filed_by = filed_by

    @property
    def requests_dir(self) -> Path:
        return self.queue_root / "requests"

    @property
    def results_dir(self) -> Path:
        return self.queue_root / "results"

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    # -- submitting --------------------------------------------------------

    def submit_queue_request(self, *, case_id: str, purpose: str,
                             source_id: Any, estimated_jobs: int,
                             outputs: Sequence[str] = (),
                             expected_regime: str = "",
                             acceptance: Sequence[str] = (),
                             needs_fd: bool = False,
                             members: Sequence[dict] = (),
                             notes: str = "",
                             request_name: str = "") -> ServiceResult:
        """File a run into the lead's queue and start tracking it.

        The job record is created **before** the request file is written, so a
        request that reaches the queue always has a record behind it. A request
        nobody can trace back to a job is a run nobody can follow or stop.
        """
        result = ServiceResult(
            service=SERVICE, outcome="queued",
            provenance=self._provenance(case_id=case_id,
                                        queue=str(self.queue_root)))
        commit, _ = repo_commit(self.repo_root)
        record = self.manager.submit(
            kind="abaqus_queue_request", case_id=case_id,
            command=[],  # nothing is spawned; the lead runs it
            start=False,
            metadata={"purpose": purpose, "estimated_jobs": estimated_jobs,
                      "queue_root": str(self.queue_root)})
        name = request_name or f"A5_{case_id}".replace("/", "_")
        request_path = self.requests_dir / f"{name}.json"
        expected = self.results_dir / f"{name}.json"

        payload = {
            "purpose": purpose,
            "source_id": source_id,
            "commit": commit,
            "estimated_jobs": int(estimated_jobs),
            "outputs": list(outputs),
            "expected_regime": expected_regime,
            "acceptance": list(acceptance),
            "needs_fd": bool(needs_fd),
            "filed_by": self.filed_by,
            "notes": notes,
            # Two keys of my own, flagged to the lead in A5_interface_services.md,
            # so a result landing in results/ can be tied back to the record.
            "a5_job_id": record.job_id,
            "a5_results_expected_at": str(expected),
        }
        if members:
            payload["members"] = list(members)
        try:
            self.requests_dir.mkdir(parents=True, exist_ok=True)
            request_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        except OSError as error:
            result.add("queue_write_failed",
                       f"the request could not be written to {request_path}: "
                       f"{error}. The job record exists at {record.job_id} and "
                       f"is still at 'queued'; nothing was asked of the lead.",
                       where=str(request_path))
            result.outcome = "refused"
            result.data = RunTicket(job_id=record.job_id, case_id=case_id,
                                    record=record)
            return result

        record.metadata["queue_request_path"] = str(request_path)
        record.metadata["results_expected_at"] = str(expected)
        record.status = STATUS_QUEUED
        record.notes.append(
            "this job is a request filed into the lead's Abaqus queue. No "
            "process was started here and no licence token was taken; the "
            "lead runs it.")
        self.manager.store.write(record)
        self.manager.store.append_event(record.job_id, {
            "event": "queue_request_filed", "path": str(request_path)})

        result.data = RunTicket(job_id=record.job_id, case_id=case_id,
                                queue_request_path=str(request_path),
                                results_expected_at=str(expected),
                                estimated_jobs=int(estimated_jobs),
                                record=record)
        result.evidence_paths["queue_request"] = str(request_path)
        return result

    def submit_local(self, *, case_id: str, command: Sequence[str],
                     kind: str = "local_run",
                     source_paths: Sequence[Path] = (),
                     metadata: Optional[dict] = None) -> ServiceResult:
        """Start a command this workflow owns, tracked by its exact pid."""
        result = ServiceResult(
            service=SERVICE, outcome="running",
            provenance=self._provenance(case_id=case_id,
                                        command=list(command)))
        if not command:
            result.add("no_command",
                       "a local run needs a command; nothing was started")
            result.outcome = "refused"
            return result
        record = self.manager.submit(kind=kind, case_id=case_id,
                                     command=command,
                                     source_paths=source_paths,
                                     metadata=metadata)
        result.data = RunTicket(job_id=record.job_id, case_id=case_id,
                                record=record)
        result.evidence_paths["log"] = record.log_path
        return result

    # -- tracking ----------------------------------------------------------

    def track(self, job_id: str) -> ServiceResult:
        """Where this run is, from the record and from the queue's results dir."""
        result = ServiceResult(service=SERVICE, outcome="tracked",
                               provenance=self._provenance(job_id=job_id))
        record = self.manager.status(job_id)
        ticket = RunTicket(
            job_id=record.job_id, case_id=record.case_id,
            queue_request_path=str(record.metadata.get("queue_request_path")
                                   or ""),
            results_expected_at=str(record.metadata.get("results_expected_at")
                                    or ""),
            estimated_jobs=record.metadata.get("estimated_jobs"),
            record=record)
        expected = ticket.results_expected_at
        if expected and Path(expected).exists():
            ticket.results_path = expected
            result.evidence_paths["results"] = expected
        elif expected:
            result.add("results_not_yet_returned",
                       f"the lead has not written {expected} yet, so this run "
                       f"has no result. That is not a failure and it is not a "
                       f"success.", where=expected, severity="note")
        result.data = ticket
        result.outcome = record.status
        if record.log_path:
            result.evidence_paths["log"] = record.log_path
        return result

    def cancel(self, job_id: str, *, reason: str = "") -> ServiceResult:
        """Stop a run. Exactly the tracked pid, or a refusal explaining why not."""
        result = ServiceResult(service=SERVICE, outcome="cancel_requested",
                               provenance=self._provenance(job_id=job_id))
        outcome = self.manager.cancel(job_id, reason=reason)
        result.data = outcome.as_dict()
        if not outcome.signalled:
            result.outcome = "not_signalled"
            result.add("cancel_not_delivered", outcome.reason, where=job_id,
                       severity="warning")
        if outcome.record is not None and outcome.record.metadata.get(
                "queue_request_path") and outcome.pid is None:
            result.add(
                "queued_request_must_be_withdrawn_by_hand",
                f"this job is a queue request, not a local process, so there "
                f"is no pid to signal. Withdrawing it means marking "
                f"{outcome.record.metadata['queue_request_path']} WITHDRAWN "
                f"and telling the lead; this service will not delete a file "
                f"out of the lead's queue.",
                where=job_id, severity="warning")
        return result
