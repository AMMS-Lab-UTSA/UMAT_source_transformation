"""How a running job tells the manager where it is.

Progress in this system is never inferred. The manager does not guess a stage
from elapsed time, from which files exist, or from how far a similar job got.
It reads what the running process itself wrote, and a stage the process never
wrote about stays at ``not_run``.

The process writes through :class:`StageReporter`, which appends one JSON
object per transition to ``<work_dir>/stages.jsonl``. Append-only and one line
per event, so a reader can tail it while the run is going and a crash mid-write
costs at most the last line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .records import utc_now
from .stages import (
    STATE_FAILED, STATE_REFUSED, STATE_RUNNING, STATE_SKIPPED, STATE_SUCCEEDED,
    require_stage_for_internal,
)

__all__ = ["STAGE_EVENTS", "StageReporter", "read_stage_events"]

STAGE_EVENTS = "stages.jsonl"


class StageReporter:
    """Written to by the job process; read by the manager.

    ``internal`` is the rung name from whichever internal vocabulary the caller
    works in. It is translated with
    :func:`~umat_oti.jobs.stages.require_stage_for_internal`, which raises on a
    name nobody mapped rather than filing it under a neighbouring stage.
    """

    def __init__(self, work_dir: Path) -> None:
        self.path = Path(work_dir) / STAGE_EVENTS
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, internal: str, state: str, detail: str,
               evidence: Optional[dict] = None) -> dict:
        stage = require_stage_for_internal(internal)
        event = {
            "stage": stage.key,
            "label": stage.label,
            "internal": internal,
            "state": state,
            "detail": detail,
            "evidence": dict(evidence or {}),
            "at": utc_now(),
            "pid": os.getpid(),
        }
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def started(self, internal: str, detail: str = "") -> dict:
        return self._write(internal, STATE_RUNNING, detail)

    def succeeded(self, internal: str, detail: str,
                  evidence: Optional[dict] = None) -> dict:
        """A stage that established what it was there to establish.

        ``detail`` is required and not defaulted: a stage that succeeded
        without saying what it established is a stage a reader cannot check.
        """
        return self._write(internal, STATE_SUCCEEDED, detail, evidence)

    def failed(self, internal: str, detail: str,
               evidence: Optional[dict] = None) -> dict:
        return self._write(internal, STATE_FAILED, detail, evidence)

    def skipped(self, internal: str, detail: str) -> dict:
        """Deliberately not attempted. Distinct from never having run."""
        return self._write(internal, STATE_SKIPPED, detail)

    def refused(self, internal: str, detail: str) -> dict:
        """Ran and declined to produce a result, which is an answer."""
        return self._write(internal, STATE_REFUSED, detail)


def read_stage_events(work_dir: Path) -> list[dict]:
    """Every stage event the job wrote, in order. Missing file means none."""
    path = Path(work_dir) / STAGE_EVENTS
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            # A torn final line from a crash mid-write. Kept as a note rather
            # than dropped: something was being written when the job stopped.
            events.append({"unparseable": line})
    return events
