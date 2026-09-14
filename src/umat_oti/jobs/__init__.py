"""The job manager: runs that survive the interface that started them.

A verification run takes hours and holds Abaqus licence tokens, so a run must
not live inside a GUI session. Everything that matters is a file:
``<root>/jobs/<job_id>.json`` is the record, ``<root>/jobs/<job_id>.events.jsonl``
is how it got there, and ``<root>/work/<job_id>/`` is where it ran.

Three rules are structural rather than a matter of care, and each has a test:

*A stage that has not run reports as not run.* All nine stages are present from
the moment a job is created, each at an explicit ``"not_run"`` -- never absent,
never null. Progress counts stages that reported and says so.

*Attempted is never success.* ``succeeded`` requires a returncode of zero that
was actually read. A process that is gone with no observed exit is ``lost``.

*Cancellation touches the exact tracked pid and nothing else.* No pattern
match exists in this package. The pid is guarded by the kernel's start-time for
it, so a recycled pid is refused rather than signalled.
"""

from .manager import CancelOutcome, JobManager, UnknownJob
from .process import (
    SignalOutcome, SpawnResult, identity_of, is_alive, process_state,
    signal_exact_pid, spawn_detached,
)
from .records import (
    JOB_STATUSES, SCHEMA, STATUS_CANCELLED, STATUS_FAILED,
    STATUS_KILLED_EXTERNALLY, STATUS_LOST, STATUS_QUEUED, STATUS_RUNNING,
    STATUS_SUCCEEDED, TERMINAL_STATUSES, Cancellation, ExitStatus, JobRecord,
    Owner, Progress, StageState, utc_now,
)
from .reporter import STAGE_EVENTS, StageReporter, read_stage_events
from .stages import (
    STAGE_KEYS, STAGE_LABELS, STAGE_STATES, STAGES, STATE_FAILED,
    STATE_NOT_RUN, STATE_REFUSED, STATE_RUNNING, STATE_SKIPPED,
    STATE_SUCCEEDED, Stage, UntranslatedStage, label_for_internal,
    require_stage_for_internal, stage_by_key, stage_for_internal,
    unmapped_internal_names,
)
from .store import JobStore, atomic_write_text

__all__ = [
    "CancelOutcome", "JobManager", "UnknownJob",
    "JobStore", "atomic_write_text",
    "JobRecord", "StageState", "Progress", "ExitStatus", "Cancellation",
    "Owner", "SCHEMA", "JOB_STATUSES", "TERMINAL_STATUSES", "utc_now",
    "STATUS_QUEUED", "STATUS_RUNNING", "STATUS_SUCCEEDED", "STATUS_FAILED",
    "STATUS_CANCELLED", "STATUS_KILLED_EXTERNALLY", "STATUS_LOST",
    "StageReporter", "read_stage_events", "STAGE_EVENTS",
    "Stage", "STAGES", "STAGE_KEYS", "STAGE_LABELS", "STAGE_STATES",
    "STATE_NOT_RUN", "STATE_RUNNING", "STATE_SUCCEEDED", "STATE_FAILED",
    "STATE_SKIPPED", "STATE_REFUSED",
    "UntranslatedStage", "stage_by_key", "stage_for_internal",
    "require_stage_for_internal", "label_for_internal",
    "unmapped_internal_names",
    "SpawnResult", "SignalOutcome", "spawn_detached", "signal_exact_pid",
    "identity_of", "is_alive", "process_state",
]
