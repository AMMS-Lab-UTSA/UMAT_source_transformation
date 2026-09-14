"""Where job records live, so that closing the interface does not lose a run.

One JSON document per job under ``<root>/jobs/<job_id>.json``, plus an
append-only ``<job_id>.events.jsonl`` beside it. The directory listing *is* the
index: there is no second index file that could disagree with the records, and
therefore no way for a job to exist in the index and not on disk or the reverse.

Every write is atomic -- a temporary file in the same directory followed by
``os.replace`` -- so a reader that arrives mid-write sees the previous complete
record rather than half of the new one. That matters here more than usual,
because the reader is a GUI polling while a run is going.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterator, Optional

from .records import JobRecord, utc_now

__all__ = ["JobStore", "atomic_write_text"]


def atomic_write_text(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` so no reader ever sees a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


class JobStore:
    """The persisted set of job records under one root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.jobs_dir = self.root / "jobs"
        self.work_root = self.root / "work"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.work_root.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------

    def record_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def events_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.events.jsonl"

    def work_dir(self, job_id: str) -> Path:
        return self.work_root / job_id

    # -- reading -----------------------------------------------------------

    def exists(self, job_id: str) -> bool:
        return self.record_path(job_id).is_file()

    def read(self, job_id: str) -> Optional[JobRecord]:
        """The record, or None when there is no such job.

        A record whose JSON is unreadable is *not* silently treated as absent:
        it raises, because a corrupt record for a job that may still be running
        is a thing an operator has to know about, not a thing to skip past.
        """
        path = self.record_path(job_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return JobRecord.from_dict(payload)

    def read_all(self) -> list[JobRecord]:
        """Every record, newest first. Unreadable files are reported, not hidden."""
        records: list[JobRecord] = []
        for path in sorted(self.jobs_dir.glob("*.json")):
            if path.name.endswith(".events.jsonl"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                records.append(self._unreadable(path, error))
                continue
            try:
                records.append(JobRecord.from_dict(payload))
            except (KeyError, TypeError) as error:
                records.append(self._unreadable(path, error))
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records

    @staticmethod
    def _unreadable(path: Path, error: BaseException) -> JobRecord:
        """A placeholder that says the record could not be read.

        Deliberately not an omission. A job whose record is damaged is not a
        job that did not happen, and dropping it from the listing would make
        the count of jobs disagree with the files on disk.
        """
        record = JobRecord(job_id=path.stem, case_id="",
                           status="lost")
        record.notes.append(
            f"this job's record at {path} could not be read "
            f"({type(error).__name__}: {error}); it is listed so the count "
            f"matches the files on disk, and its contents are not known")
        return record

    def __iter__(self) -> Iterator[JobRecord]:
        return iter(self.read_all())

    # -- writing -----------------------------------------------------------

    def write(self, record: JobRecord) -> Path:
        return atomic_write_text(self.record_path(record.job_id),
                                 record.to_json())

    def append_event(self, job_id: str, event: dict) -> Path:
        """Append one line to the job's event log.

        The log is the audit trail behind the record: the record says where a
        job is now, the log says how it got there. It is append-only and is
        never rewritten, so a transition cannot be edited out of the history.
        """
        payload = dict(event)
        payload.setdefault("at", utc_now())
        path = self.events_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
        return path

    def events(self, job_id: str) -> list[dict]:
        path = self.events_path(job_id)
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"unparseable": line})
        return out
