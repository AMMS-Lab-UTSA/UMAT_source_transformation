"""Watching a long run from the interface, and surviving a restart of it.

Three things, and the third is the one that makes the other two honest.

**An adapter over the job manager.** The interface talks to a narrow protocol
-- submit, status, cancel, list -- so that whichever service implements it, the
screens do not change. Nothing here builds a command line: a UI callback that
assembles a shell command is a second implementation of the pipeline, and the
interface is not allowed one.

**A three-valued boundary.** A stage that did not run and a stage that failed
are different facts, and the way this project has settled that everywhere else
is true / false / not-established, where a MISSING key and a NULL key are BOTH
not-established. :func:`stage_state` enforces it at the edge: whatever shape a
job manager reports, what leaves this module says "did not run" as a value and
never as an absence. Letting absence mean something on its own is how 108
entries that never ran were once told "agreement only".

**A record of what this interface is watching.** :class:`TrackedJobs` is a
small file the interface owns. It is not a second job manager -- it stores no
progress and decides nothing -- it is the list of job ids this interface had
open, so that closing the browser and coming back finds the run still there
instead of an empty screen over a job that is still going.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol

from umat_oti.app.corpus_view import NOT_ESTABLISHED
from umat_oti.app.plain_language import Failure

__all__ = ["STAGES", "StageState", "stage_state", "JobManager", "TrackedJobs",
           "JobView", "job_view", "stages_for", "plain_stage"]


# ---------------------------------------------------------------------------
# the stages a user watches, in their words
# ---------------------------------------------------------------------------
#: What "Transform and Verify" does, as a user sees it.
#:
#: The keys and labels are Agent 5's, from ``umat_oti.jobs.stages.STAGES``,
#: which is the authority. :func:`_load_stages` prefers that module wherever it
#: is importable; this table is the fallback for an environment where the job
#: manager is not installed, and it is kept identical on purpose. Two
#: vocabularies for one ladder is how a progress panel and a job record end up
#: disagreeing about which step a run is on.
#:
#: The internal rung names stay out of the labels entirely -- they are on the
#: row underneath, in the Advanced panel, where a reader who wants them can
#: have them. ``internal`` is every pipeline name that maps onto the step.
_FALLBACK_STAGES: tuple[dict, ...] = (
    {"key": "analyze_umat", "label": "Analyzing the UMAT",
     "explains": "working out what the subroutine expects and what it does",
     "internal": ("analyse", "analysis", "entry_routines", "classify",
                  "not_a_umat", "incomplete_or_corrupt_source",
                  "published_stub_no_constitutive_content")},
    {"key": "find_material_data", "label": "Finding material data",
     "explains": "looking for the numbers your material needs, and where "
                 "somebody wrote them down",
     "internal": ("material", "material_data", "needs_material_data",
                  "pairing")},
    {"key": "build_experiment", "label": "Building a mechanical experiment",
     "explains": "building a loading that will actually make this material "
                 "do what it is for",
     "internal": ("manifest", "experiment", "manifest_refused",
                  "experiment_not_generated", "transform", "transformed",
                  "transform_refused", "support", "support_build_failed")},
    {"key": "search_activation",
     "label": "Searching for yielding, damage or time dependence",
     "explains": "finding a loading big enough or slow enough to make the "
                 "material actually do what it is for",
     "internal": ("discovery", "activation", "experiment_not_informative",
                  "informativeness_not_established")},
    {"key": "run_original", "label": "Running the original routine",
     "explains": "putting your material, unchanged, through the test",
     "internal": ("original", "original_job_failed", "original_run")},
    {"key": "run_transformed", "label": "Running the transformed routine",
     "explains": "putting the converted material through the same test",
     "internal": ("transformed_run", "transformed_job_failed",
                  "transformed_executed")},
    {"key": "compare_histories", "label": "Comparing mechanical histories",
     "explains": "checking that converting the material did not change what "
                 "it computes",
     "internal": ("primal", "primal_disagreed", "compare",
                  "both_builds_non_finite",
                  "arguments_diverged_before_the_routine",
                  "disagreement_not_in_any_recorded_call")},
    {"key": "verify_derivatives", "label": "Verifying derivatives",
     "explains": "comparing the converted version's derivatives against a "
                 "numerical estimate, over a range of step sizes",
     "internal": ("tangent", "tangent_not_verified", "derivative_truncated",
                  "derivatives")},
    {"key": "create_regression", "label": "Creating the regression test",
     "explains": "saving what was measured so a later run can check that "
                 "nothing has moved",
     "internal": ("regression", "fixture", "verified")},
)


def _load_stages() -> tuple:
    """Agent 5's stage table where it is installed, this module's where not.

    The service owns the ladder. Preferring it means a stage added there
    appears here without anybody editing this file, and it means the label a
    user reads is the label the job record carries.
    """
    try:
        from umat_oti.jobs import stages as service_stages   # noqa: PLC0415
    except Exception:
        return _FALLBACK_STAGES
    # Which internal rungs the SERVICE claims, and under which step. The
    # service owns the ladder, so where the two tables disagree about where a
    # rung belongs, the service decides. Unioning them instead let one rung be
    # claimed by two steps -- experiment_not_generated, support_build_failed,
    # transformed and verified all were -- and then plain_stage() resolved it
    # to whichever came last, so the round trip from a step to its own rung
    # and back landed somewhere else.
    claimed: dict = {}
    for stage in getattr(service_stages, "STAGES", ()) or ():
        key = getattr(stage, "key", None) or (
            stage.get("key") if isinstance(stage, dict) else None)
        for name in (getattr(stage, "internal_names", None) or (
                stage.get("internal_names") if isinstance(stage, dict) else ())
                or ()):
            claimed.setdefault(name, key)

    loaded = []
    for stage in getattr(service_stages, "STAGES", ()) or ():
        key = getattr(stage, "key", None) or (
            stage.get("key") if isinstance(stage, dict) else None)
        if not key:
            continue
        label = getattr(stage, "label", None) or (
            stage.get("label") if isinstance(stage, dict) else key)
        internal = tuple(getattr(stage, "internal_names", None) or (
            stage.get("internal_names") if isinstance(stage, dict) else ())
            or ())
        fallback = next((s for s in _FALLBACK_STAGES if s["key"] == key), {})
        loaded.append({
            "key": key, "label": label,
            # The service names the step; this module keeps the sentence that
            # says what it is doing while it runs, which a progress panel
            # needs and a job record has no reason to carry.
            "explains": fallback.get("explains", ""),
            # The fallback contributes only names the service does not place
            # somewhere else. A name the service assigns to another step is
            # that step's, not this one's.
            "internal": tuple(sorted(
                set(internal) | {name for name in fallback.get("internal", ())
                                 if claimed.get(name, key) == key})),
        })

    table = tuple(loaded) or _FALLBACK_STAGES
    _refuse_an_ambiguous_table(table)
    return table


def _refuse_an_ambiguous_table(table) -> None:
    """A rung belongs to one step, or the translation is not a translation.

    Raised rather than resolved, because every way of resolving it silently
    picks a winner by table order, and the reader of a progress panel has no
    way to know a step was chosen by accident.
    """
    seen: dict = {}
    clashes: dict = {}
    for stage in table:
        for name in stage["internal"]:
            if name in seen and seen[name] != stage["key"]:
                clashes.setdefault(name, [seen[name]]).append(stage["key"])
            seen.setdefault(name, stage["key"])
    if clashes:
        raise ValueError(
            "these internal rungs are claimed by more than one plain stage, "
            "so translating one and back does not return it: "
            + "; ".join(f"{name} -> {sorted(set(keys))}"
                        for name, keys in sorted(clashes.items())))


#: The ladder this interface renders. Nine steps, fixed order.
STAGES: tuple[dict, ...] = _load_stages()

_BY_INTERNAL: dict[str, str] = {
    name: spec["key"] for spec in STAGES for name in spec["internal"]}
_BY_KEY: dict[str, dict] = {spec["key"]: spec for spec in STAGES}


def plain_stage(name: str) -> dict:
    """The user-facing step one reported stage name belongs to.

    Accepts either of the two things a job manager may report: the stage KEY
    from :data:`STAGES`, which is what Agent 5's records carry, or one of the
    internal rung names underneath it, which is what a process reports while
    it runs. Both resolve to the same row.

    Taking only internal names was a real bug in this module: every record the
    job manager writes uses the key, so every step of every real job came back
    untranslated and the nine known steps all read "not established" beside
    them -- a progress panel that showed nothing about a job that was running
    fine.

    An unknown name does NOT get quietly dropped and does not get attached to
    whichever step happens to be last. It comes back as its own row marked
    untranslated, because a step this interface cannot name is still a step
    that ran, and hiding it would under-report what happened.
    """
    raw = str(name or "")
    if raw in _BY_KEY:
        return dict(_BY_KEY[raw])
    key = _BY_INTERNAL.get(raw)
    if key:
        return dict(_BY_KEY[key])
    return {"key": f"untranslated:{name}", "label": str(name),
            "explains": "this program has no plain-language name for this "
                        "step yet; it is shown under the name the pipeline "
                        "uses so that it is not hidden",
            "internal": (str(name),), "untranslated": True}


# ---------------------------------------------------------------------------
# the three-valued boundary
# ---------------------------------------------------------------------------
#: The states a step may be in. ``DID_NOT_RUN`` is a value, never an absence.
class StageState:
    """Agent 5's six, plus the two this interface needs on top of them.

    ``DID_NOT_RUN``, ``RUNNING``, ``PASSED``, ``FAILED``, ``SKIPPED`` and
    ``REFUSED`` are ``umat_oti.jobs.STAGE_STATES`` under this module's names.
    ``REFUSED`` is not a failure -- it is a step that ran and declined to
    produce a result, which is an answer -- and ``SKIPPED`` is a deliberate
    non-attempt, which is not the same as ``DID_NOT_RUN``. Collapsing either
    into "failed" would report a refusal as a defect.

    ``CANCELLED`` and ``NOT_ESTABLISHED`` are this interface's. A job manager
    that reports nothing about a step has not told us the step did not run,
    and that distinction is the whole reason this class is a set of strings
    rather than a boolean.
    """

    DID_NOT_RUN = "did not run"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    NOT_ESTABLISHED = NOT_ESTABLISHED


_STATE_WORDS = {
    "pending": StageState.DID_NOT_RUN,
    "not_run": StageState.DID_NOT_RUN,
    "not run": StageState.DID_NOT_RUN,
    "did not run": StageState.DID_NOT_RUN,
    "queued": StageState.DID_NOT_RUN,
    # Agent 5's two that are neither a pass nor a failure. Given their own
    # words because rendering either as "failed" invents a defect: a manifest
    # that refuses an underdetermined model has answered the question.
    "skipped": StageState.SKIPPED,
    "refused": StageState.REFUSED,
    "running": StageState.RUNNING,
    "started": StageState.RUNNING,
    "in_progress": StageState.RUNNING,
    "ok": StageState.PASSED,
    "passed": StageState.PASSED,
    "done": StageState.PASSED,
    "succeeded": StageState.PASSED,
    "complete": StageState.PASSED,
    "completed": StageState.PASSED,
    "failed": StageState.FAILED,
    "error": StageState.FAILED,
    "failure": StageState.FAILED,
    "cancelled": StageState.CANCELLED,
    "canceled": StageState.CANCELLED,
    "aborted": StageState.CANCELLED,
}


def stage_state(reported: Any, *, present: bool = True) -> str:
    """One reported step state, as exactly one of this module's words.

    ``present`` is what a caller passes when it knows whether the key was in
    the payload at all. The rule, and the reason this takes two arguments
    rather than one:

    * key absent  -> :data:`StageState.NOT_ESTABLISHED`
    * key present and ``None`` -> :data:`StageState.NOT_ESTABLISHED`
    * ``True`` / ``False`` -> passed / failed
    * a word this module knows -> that word
    * a word it does not know -> :data:`StageState.NOT_ESTABLISHED`, because
      guessing which of five states an unrecognised string meant is how a
      failure gets rendered as a pass.

    What this function will not do under any input is return
    :data:`StageState.DID_NOT_RUN` for an absence. "Nobody recorded this" and
    "this was recorded as not having run" are different claims and the second
    one is a measurement.
    """
    if not present or reported is None:
        return StageState.NOT_ESTABLISHED
    if reported is True:
        return StageState.PASSED
    if reported is False:
        return StageState.FAILED
    word = str(reported).strip().lower()
    return _STATE_WORDS.get(word, StageState.NOT_ESTABLISHED)


def _stage_rows(payload: Any) -> list:
    """Steps out of whatever a job manager reported, none of them invented.

    A manager that reports nothing at all yields every step at
    ``not established`` -- not at ``did not run``, because a manager that told
    us nothing has not told us that nothing ran.
    """
    reported: dict[str, Any] = {}
    raw_seen: dict[str, Any] = {}
    present: set = set()

    if isinstance(payload, dict):
        items = payload.items()
    elif isinstance(payload, (list, tuple)):
        items = [((s or {}).get("key") or (s or {}).get("name")
                  or (s or {}).get("stage"), s)
                 for s in payload if isinstance(s, dict)]
    else:
        items = []

    order: list = []
    for name, value in items:
        if not name:
            continue
        spec = plain_stage(str(name))
        key = spec["key"]
        if key not in order:
            order.append(key)
        state = value
        if isinstance(value, dict):
            has = any(k in value for k in ("state", "status", "ok", "passed"))
            state = (value.get("state") if "state" in value else
                     value.get("status") if "status" in value else
                     value.get("ok") if "ok" in value else
                     value.get("passed"))
            if has:
                present.add(key)
        else:
            present.add(key)
        reported[key] = state
        raw_seen[key] = value

    rows = []
    known = [spec["key"] for spec in STAGES]
    for key in known + [k for k in order if k not in known]:
        spec = _BY_KEY.get(key) or plain_stage(key.split(":", 1)[-1])
        rows.append({
            "step": spec["label"],
            "key": key,
            "what it is doing": spec["explains"],
            "state": stage_state(reported.get(key),
                                 present=key in present),
            "untranslated": bool(spec.get("untranslated")),
            # The manager's own payload for this step, kept so the Advanced
            # panel can show what was actually reported rather than this
            # module's reading of it.
            "as reported": raw_seen.get(key),
        })
    return rows


# ---------------------------------------------------------------------------
# the protocol the interface talks to
# ---------------------------------------------------------------------------
class JobManager(Protocol):
    """What the interface needs from whatever runs long work.

    Deliberately four methods. Anything the interface wants beyond these is a
    thing it should be reading from the run's own artefacts instead.
    """

    def submit(self, kind: str, params: dict) -> str: ...

    def status(self, job_id: str) -> dict: ...

    def cancel(self, job_id: str) -> dict: ...

    def list_jobs(self) -> list: ...


# ---------------------------------------------------------------------------
# what this interface remembers across a restart
# ---------------------------------------------------------------------------
@dataclass
class TrackedJobs:
    """The job ids this interface had open, on disk.

    Owned by the interface and nothing else. It records no progress and no
    verdicts: progress is the job manager's to report and verdicts are the
    run's to write. What would otherwise be lost when a browser is closed is
    only the knowledge that this user had these jobs open, and that is exactly
    what this file holds.

    Written atomically, because a half-written registry read on the next start
    is a worse failure than no registry at all.
    """

    path: Path
    records: dict = field(default_factory=dict)

    @classmethod
    def open(cls, path: Path) -> "TrackedJobs":
        path = Path(path)
        records: dict = {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(
                    payload.get("jobs"), dict):
                records = payload["jobs"]
        except (OSError, ValueError):
            records = {}
        return cls(path=path, records=records)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".partial")
        temporary.write_text(json.dumps(
            {"schema": "umat-oti/tracked-jobs/1", "jobs": self.records},
            indent=1), encoding="utf-8")
        os.replace(temporary, self.path)

    def track(self, job_id: str, *, kind: str = "", label: str = "",
              params: Optional[dict] = None) -> dict:
        record = {"job_id": job_id, "kind": kind, "label": label,
                  "params": dict(params or {}), "opened": time.time()}
        self.records[str(job_id)] = record
        self._flush()
        return record

    def forget(self, job_id: str) -> None:
        if str(job_id) in self.records:
            del self.records[str(job_id)]
            self._flush()

    def ids(self) -> list:
        return sorted(self.records, key=lambda j: self.records[j]["opened"])

    def recover(self, manager: JobManager) -> list:
        """What this interface was watching, re-read from the job manager.

        The registry says WHICH jobs; the manager says what became of them.
        A job the manager no longer knows is reported as such rather than
        dropped silently -- a job that vanished is a thing the user is
        entitled to be told about, not a row to quietly remove.
        """
        recovered = []
        for job_id in self.ids():
            remembered = self.records[job_id]
            try:
                status = manager.status(job_id)
            except Exception as error:
                recovered.append(job_view(
                    job_id, None, remembered=remembered,
                    lost=f"{type(error).__name__}: {error}"))
                continue
            if not status:
                recovered.append(job_view(job_id, None,
                                          remembered=remembered,
                                          lost="the job manager no longer has "
                                               "a record of this job"))
                continue
            recovered.append(job_view(job_id, status, remembered=remembered))
        return recovered


# ---------------------------------------------------------------------------
# one job, as a screen shows it
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class JobView:
    """One run in progress, with nothing about it assumed."""

    job_id: str
    state: str
    steps: list = field(default_factory=list)
    label: str = ""
    kind: str = ""
    started: Optional[float] = None
    finished: Optional[float] = None
    #: Non-empty only where the job manager could not be asked about this job.
    lost: str = ""
    failure: Optional[dict] = None
    raw: dict = field(default_factory=dict)

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def can_cancel(self) -> bool:
        return self.state in ("running", "queued")

    @property
    def steps_done(self) -> int:
        return sum(1 for s in self.steps if s["state"] == StageState.PASSED)

    @property
    def headline(self) -> str:
        """What the top of the panel says. Never a percentage that is guessed.

        A step count is reported against the steps that were REPORTED, not
        against the nine this module knows about, because a manager that has
        told us about three steps has not told us the other six did not run.
        """
        established = [s for s in self.steps
                       if s["state"] != StageState.NOT_ESTABLISHED]
        if self.lost:
            return "This run cannot be found"
        if self.state == "cancelled":
            return f"Stopped -- {self.steps_done} of {len(established)} steps had finished"
        if self.state == "failed":
            return "Stopped on a problem"
        if self.state == "finished":
            return "Finished"
        if not established:
            return "Starting -- nothing has been reported yet"
        return (f"Working -- {self.steps_done} of {len(established)} reported "
                f"steps have finished")

    def as_dict(self) -> dict:
        return {"job id": self.job_id, "state": self.state,
                "headline": self.headline, "steps": list(self.steps),
                "label": self.label, "kind": self.kind,
                "started": self.started, "finished": self.finished,
                "lost": self.lost, "failure": self.failure}


#: Agent 5's seven job statuses, plus the synonyms other callers use.
#:
#: ``killed_externally`` and ``lost`` are kept as themselves rather than
#: folded into ``failed``. A job whose process is gone and whose exit was
#: never read did not fail -- nobody knows what it did -- and reporting it as
#: a failure is the same fabrication as reporting it as a success.
_JOB_STATES = {
    "queued": "queued", "pending": "queued", "submitted": "queued",
    "running": "running", "started": "running",
    "finished": "finished", "done": "finished", "completed": "finished",
    "succeeded": "finished", "ok": "finished",
    "failed": "failed", "error": "failed",
    "cancelled": "cancelled", "canceled": "cancelled", "aborted": "cancelled",
    "killed_externally": "killed externally",
    "lost": "lost",
}


def job_view(job_id: str, status: Optional[dict], *,
             remembered: Optional[dict] = None, lost: str = "") -> JobView:
    """One job manager status payload, as the progress panel reads it."""
    remembered = remembered or {}
    if status is None:
        return JobView(job_id=str(job_id),
                       state=NOT_ESTABLISHED,
                       steps=_stage_rows(None),
                       label=str(remembered.get("label") or ""),
                       kind=str(remembered.get("kind") or ""),
                       lost=lost or "this job could not be read",
                       raw={})
    raw_state = status.get("state", status.get("status"))
    state = _JOB_STATES.get(str(raw_state or "").strip().lower(),
                            NOT_ESTABLISHED)
    steps = _stage_rows(status.get("stages", status.get("steps")))

    failure = None
    error = status.get("error") or status.get("failure")
    broken = [s["step"] for s in steps if s["state"] == StageState.FAILED]
    # A step that failed is reported whether or not the job as a whole has
    # stopped. A run that is still going with a failed step behind it has a
    # failure a reader is entitled to see now, not when the process exits --
    # and a panel that waited for the job status would show a green bar over
    # a step that did not work.
    if state == "failed" or error or broken:
        failure = Failure(
            what_failed=(f"{broken[0]} did not finish" if broken
                         else "This run stopped before it finished"),
            why=(str(error) if isinstance(error, str) and error.strip()
                 else "The run reported that it stopped, and the step it "
                      "stopped on is marked below."),
            evidence=[{"finding": s["step"], "result": s["state"],
                       "where it was read": "the job manager's report"}
                      for s in steps
                      if s["state"] != StageState.NOT_ESTABLISHED],
            can_retry_automatically=bool(status.get("retryable", False)),
            whose_move="this program",
            full_log=str(status.get("log") or status.get("output") or ""),
        ).as_dict()

    return JobView(
        job_id=str(job_id), state=state, steps=steps,
        label=str(status.get("label") or remembered.get("label") or ""),
        kind=str(status.get("kind") or remembered.get("kind") or ""),
        started=status.get("started"), finished=status.get("finished"),
        lost=lost, failure=failure, raw=dict(status),
    )


def stages_for(status: Optional[dict]) -> list:
    """The step rows for one status payload, for a caller that wants only them."""
    return _stage_rows((status or {}).get("stages",
                                          (status or {}).get("steps")))
