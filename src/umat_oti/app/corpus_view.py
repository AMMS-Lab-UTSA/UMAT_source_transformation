"""What the interface needs to show about a corpus, as data rather than widgets.

The rule this module exists to keep is the one the workbench service keeps: the
interface a user drives and the pipeline a paper cites run the same code. So
nothing here renders anything and nothing here computes a verdict. It reads the
artefacts the batch wrote -- the results file, the transform report, the job
directories -- and returns them in one declared shape, so that a Streamlit tab,
a test and a report generator all see the same thing.

Everything a reader of the interface is entitled to ask is answerable from
here: which UMATs were acquired, what was inferred about each one and from
where, what is missing, which experiment was generated, what Abaqus did with
it, where the deck and the logs are, what the two builds computed, where the
material activated, whether the finite difference converged, and which
component of which tangent disagreed.

Two things it deliberately does NOT do. It does not decide anything the batch
did not already decide -- a verdict rendered differently in the interface than
in the evidence is a second opinion nobody can cite. And it does not read the
sources: the corpus is not redistributable, and the interface shows paths,
digests and provenance rather than text.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from umat_oti.abaqus.terminal_states import (EXTERNAL, INTERNAL,  # noqa: F401
                                             FULLY_VERIFIED, from_stage,
                                             kind_of)

#: The file the batch appends a record to as each entry settles. Read rather
#: than the summary JSON, because it exists while the run is still going and
#: is what makes live progress possible without asking the run anything.
RESULTS_FILE = "store_verification.jsonl"

#: The version of the shape this module returns. A front end pinned to it can
#: refuse to render something it does not understand instead of showing a
#: blank panel.
SCHEMA = "umat-oti/corpus-view/1"


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _latest(rows: list) -> list:
    """One record per entry: the last one written.

    The results file is append-only, and a resumed run that re-runs an entry
    appends a second record for it rather than editing the first. Counting
    both reports 254 outcomes for a 253-entry batch and, worse, counts a
    superseded verdict beside the one that replaced it.
    """
    seen: dict = {}
    for row in rows:
        key = str(row.get("key") or row.get("source") or id(row))
        seen[key] = row
    return list(seen.values())


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class Requirement:
    """One thing an entry needs before it can be run, and whether it has it."""

    name: str
    satisfied: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "satisfied": self.satisfied,
                "detail": self.detail}


@dataclass
class EntryView:
    """One corpus artefact, as much as is known about it, in one shape."""

    source_id: str
    repository: str = ""
    key: str = ""
    stage: str = ""
    terminal_state: str = ""
    kind: str = ""
    reason: str = ""
    is_umat: Optional[bool] = None
    #: What the manifest said: element, tensor shape, kinematics, constants.
    manifest: dict = field(default_factory=dict)
    #: How the formulation was decided and by which witnesses.
    formulation: dict = field(default_factory=dict)
    #: What the loading search did, including the time probes.
    discovery: dict = field(default_factory=dict)
    #: Per job: completed, increments, warnings, and where its files are.
    jobs: dict = field(default_factory=dict)
    primal: dict = field(default_factory=dict)
    tangent: dict = field(default_factory=dict)
    truncation: dict = field(default_factory=dict)
    precision_control: dict = field(default_factory=dict)
    requirements: list = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    seconds: Optional[float] = None

    def as_dict(self) -> dict:
        record = {name: getattr(self, name) for name in
                  ("source_id", "repository", "key", "stage", "terminal_state",
                   "kind", "reason", "is_umat", "manifest", "formulation",
                   "discovery", "jobs", "primal", "tangent", "truncation",
                   "precision_control", "artifacts", "seconds")}
        record["requirements"] = [r.as_dict() for r in self.requirements]
        return record


def _requirements(row: dict) -> list:
    """What this entry needed, and which of it was there.

    Written as questions with an answer each rather than as a single "ready"
    flag, because "not ready" is not a thing a user can act on and "no deck in
    this repository publishes constants for it" is.
    """
    manifest_refusals = row.get("refusals") or []
    material = str(row.get("material_provenance") or "")
    deck = str(row.get("deck") or "")
    formulation = row.get("formulation") or {}
    companions = ((row.get("original_diagnosis") or {}).get("companions") or {})
    missing_units = list(companions.get("missing_modules") or []) + \
        list(companions.get("missing_includes") or [])
    return [
        Requirement("a UMAT interface", row.get("stage") != "not_a_umat",
                    str(row.get("reason") or "")
                    if row.get("stage") == "not_a_umat" else ""),
        Requirement("published material constants", bool(material),
                    material or "no deck in this repository publishes "
                                "constants matching this source"),
        Requirement("a paired deck", bool(deck), deck),
        Requirement("a formulation this harness can drive",
                    bool(formulation.get("element")),
                    str(formulation.get("reason") or "")),
        Requirement("every companion source", not missing_units,
                    ", ".join(missing_units)),
        Requirement("a manifest with nothing missing", not manifest_refusals,
                    "; ".join(str(r) for r in manifest_refusals)),
    ]


def _artifacts(row: dict, work_dir: Optional[Path]) -> dict:
    """Where the files this entry produced are, named rather than embedded."""
    key = str(row.get("key") or "")
    if not work_dir or not key:
        return {}
    root = Path(work_dir) / key
    found: dict = {"work_dir": str(root)}
    for job in ("original", "transformed", "control"):
        directory = root / job if job != "control" else root / "precision_control"
        if not directory.is_dir():
            continue
        found[job] = {
            "directory": str(directory),
            "deck": str(directory / f"{job}.inp"),
            "status_file": str(directory / f"{job}.sta"),
            "message_file": str(directory / f"{job}.msg"),
            "data_file": str(directory / f"{job}.dat"),
            "probe": str(directory / f"{job}_probe.txt"),
            "history": str(directory / f"{job}_history.json"),
        }
    if (root / "discovery").is_dir():
        found["discovery_dir"] = str(root / "discovery")
    if (root / "replay").is_dir():
        found["replay_dir"] = str(root / "replay")
    return found


def entry_view(row: dict, work_dir: Optional[Path] = None) -> EntryView:
    """One results row in the shape the interface reads."""
    stage = str(row.get("stage") or "")
    verdict = from_stage(stage, str(row.get("reason") or ""))
    return EntryView(
        source_id=str(row.get("source") or ""),
        repository=str(row.get("repository") or ""),
        key=str(row.get("key") or ""),
        stage=stage,
        terminal_state=verdict.state,
        kind=verdict.kind,
        reason=str(row.get("reason") or ""),
        is_umat=None if stage == "not_a_umat" else True,
        manifest={
            "element_type": row.get("element_type"),
            "ntens": row.get("ntens"),
            "kinematics": row.get("kinematics"),
            "kinematics_provenance": row.get("kinematics_provenance"),
            "kinematics_note": row.get("kinematics_note"),
            "props_count": row.get("props_count"),
            "nstatv": row.get("nstatv"),
            "unsymmetric": row.get("unsymmetric"),
            "material_block": row.get("material_block"),
            "material_provenance": row.get("material_provenance"),
            "deck": row.get("deck"),
            "deck_digest": row.get("deck_digest"),
            "source_form": row.get("source_form"),
            "source_form_note": row.get("source_form_note"),
        },
        formulation=dict(row.get("formulation") or {}),
        discovery=dict(row.get("discovery") or {}),
        jobs={name: dict(row.get(name) or {})
              for name in ("original", "transformed", "support")
              if row.get(name)},
        primal=dict(row.get("primal") or {}),
        tangent=dict(row.get("tangent") or {}),
        truncation=dict(row.get("truncation") or {}),
        precision_control=dict(row.get("precision_control") or {}),
        requirements=_requirements(row),
        artifacts=_artifacts(row, work_dir),
        seconds=row.get("seconds"),
    )


@dataclass
class RunView:
    """A whole verification run: its entries, its counts and whether it is done."""

    schema: str = SCHEMA
    results_dir: str = ""
    work_dir: str = ""
    entries: list = field(default_factory=list)
    finished: bool = False
    attempted: int = 0
    expected: Optional[int] = None

    @property
    def by_terminal_state(self) -> dict:
        counts: dict = {}
        for entry in self.entries:
            counts[entry.terminal_state] = counts.get(entry.terminal_state, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    @property
    def by_kind(self) -> dict:
        counts = {"verified": 0, "external": 0, "internal": 0}
        for entry in self.entries:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return counts

    def verified(self) -> list:
        return [e for e in self.entries if e.terminal_state == FULLY_VERIFIED]

    def as_dict(self) -> dict:
        return {"schema": self.schema, "results_dir": self.results_dir,
                "work_dir": self.work_dir, "finished": self.finished,
                "attempted": self.attempted, "expected": self.expected,
                "by_terminal_state": self.by_terminal_state,
                "by_kind": self.by_kind,
                "entries": [e.as_dict() for e in self.entries]}


def load_run(results_dir: Path, work_dir: Optional[Path] = None) -> RunView:
    """Every entry a run has settled so far, whether or not it has finished.

    Reads the append-only record, so calling it while a batch is running gives
    live progress without asking the batch anything -- which is what lets an
    interface show a job list that fills in.
    """
    results_dir = Path(results_dir)
    rows = _latest(_read_jsonl(results_dir / RESULTS_FILE))
    summary = _read_json(results_dir / "store_verification.json")
    finished = bool(isinstance(summary, dict) and summary.get("summary"))
    expected = None
    if isinstance(summary, dict):
        expected = (summary.get("summary") or {}).get("attempted")
    view = RunView(results_dir=str(results_dir),
                   work_dir=str(work_dir or ""), finished=finished,
                   attempted=len(rows), expected=expected)
    view.entries = [entry_view(row, work_dir) for row in rows]
    return view


def histories(work_dir: Path, key: str) -> dict:
    """The original, converted and control stress histories, for plotting.

    Returned as parallel series keyed by what they are, with the increment
    numbers beside them, so a caller can draw them against each other without
    knowing anything about the probe's format.
    """
    root = Path(work_dir) / key
    series: dict = {}
    for name, directory in (("original", root / "original"),
                            ("transformed", root / "transformed"),
                            ("control", root / "precision_control")):
        job = "control" if name == "control" else name
        payload = _read_json(directory / f"{job}_history.json")
        if not isinstance(payload, list) or not payload:
            continue
        from umat_oti.abaqus.activation import strain_at

        series[name] = {
            "increment": [record.get("increment") for record in payload],
            "time": [record.get("time") for record in payload],
            "stress": [list(record.get("STRESS") or ()) for record in payload],
            "strain": [strain_at(record) for record in payload],
            "state": [list(record.get("STATEV") or ()) for record in payload],
        }
    return series


def job_log(work_dir: Path, key: str, job: str, *,
            limit: int = 20000) -> dict:
    """What Abaqus wrote for one job, for a reader looking at a failure.

    The status, message and data files, trimmed. Named separately rather than
    concatenated: which file a diagnostic came from is part of reading it.
    """
    directory = Path(work_dir) / key / (
        "precision_control" if job == "control" else job)
    found: dict = {"directory": str(directory), "files": {}}
    for suffix in (".sta", ".msg", ".dat", ".log"):
        path = directory / f"{job}{suffix}"
        if path.is_file():
            try:
                found["files"][suffix] = path.read_text(
                    errors="replace")[-limit:]
            except OSError as error:               # pragma: no cover
                found["files"][suffix] = f"could not be read: {error}"
    return found


def deck_text(work_dir: Path, key: str, job: str = "original") -> str:
    """The generated .inp both builds were driven by."""
    path = Path(work_dir) / key / job / f"{job}.inp"
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def componentwise_errors(entry: EntryView, state: int = 0) -> list:
    """Per-component tangent error at one state, worst first.

    The batch records the sweep and the worst component; this puts them in a
    table a reader can sort, because "the tangent disagreed by 3e-4" is a
    number and "DDSDDE(4,4) disagreed by 3e-4 and every other entry agreed to
    1e-12" is a finding.
    """
    states = (entry.tangent or {}).get("states") or []
    if not 0 <= state < len(states):
        return []
    comparison = (states[state] or {}).get("comparison") or {}
    rows = []
    for point in comparison.get("sweep") or ():
        rows.append({"step": point.get("step"),
                     "relative": point.get("relative"),
                     "absolute": point.get("absolute"),
                     "frobenius": point.get("frobenius")})
    return rows


# ---------------------------------------------------------------------------
# starting a run from the interface
# ---------------------------------------------------------------------------
#: The two modes the corpus is run in, and what each means. Named here because
#: the interface offers them as buttons and a button with an unexplained name
#: is how a user starts the wrong one.
MODES = {
    "discovery": ("infer what is missing, generate an experiment, search for "
                  "an amplitude and a rate that make the material do "
                  "something, and choose the states to differentiate at"),
    "regression": ("re-run the frozen manifests, decks, states and step sizes "
                   "of everything that has verified before, and fail if any of "
                   "it stops verifying"),
}


@dataclass
class RunHandle:
    """A batch started from the interface, and where to watch it."""

    mode: str
    results_dir: str
    work_dir: str
    command: list = field(default_factory=list)
    pid: Optional[int] = None
    started: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {"mode": self.mode, "results_dir": self.results_dir,
                "work_dir": self.work_dir, "command": list(self.command),
                "pid": self.pid, "started": self.started, "reason": self.reason}


def run_command(mode: str, results_dir: Path, work_dir: Path, *,
                only: str = "", limit: int = 0, jobs: int = 1,
                baseline: Optional[Path] = None,
                repo_root: Optional[Path] = None) -> list:
    """The exact command a run would be, so the interface can show it first.

    Separated from starting it because a user is entitled to see what a button
    will do, and because a test can then check the command without running
    Abaqus.
    """
    if mode not in MODES:
        raise ValueError(f"{mode!r} is not a mode; known: {', '.join(MODES)}")
    root = Path(repo_root or Path(__file__).resolve().parents[3])
    command = [sys.executable, str(root / "tools" / "verify_store_in_abaqus.py"),
               "--work-dir", str(work_dir), "--results-dir", str(results_dir),
               "--jobs", str(max(1, int(jobs)))]
    if mode == "regression":
        command += ["--mode", "regression", "--no-discovery"]
        if baseline is not None:
            command += ["--baseline", str(baseline)]
    if only:
        command += ["--only", only]
    if limit:
        command += ["--limit", str(int(limit))]
    return command


def start_run(mode: str, results_dir: Path, work_dir: Path, **options) -> RunHandle:
    """Start a batch in the background and hand back where to watch it.

    Detached on purpose: an Abaqus corpus round is hours, and an interface that
    blocks on it is an interface nobody can use to watch it. Progress comes
    from :func:`load_run` reading the record the batch appends to.
    """
    command = run_command(mode, results_dir, work_dir, **options)
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    handle = RunHandle(mode=mode, results_dir=str(results_dir),
                       work_dir=str(work_dir), command=command)
    log = Path(results_dir) / f"{mode}.log"
    try:
        with open(log, "wb") as stream:
            process = subprocess.Popen(
                command, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(Path(command[1]).resolve().parents[1]),
                env=dict(os.environ))
        handle.pid, handle.started = process.pid, True
    except OSError as error:
        handle.reason = f"{type(error).__name__}: {error}"
    return handle


def progress(results_dir: Path) -> dict:
    """How far a run has got, cheap enough to poll."""
    view = load_run(results_dir)
    return {"attempted": view.attempted, "expected": view.expected,
            "finished": view.finished, "by_kind": view.by_kind,
            "by_terminal_state": view.by_terminal_state,
            "latest": [e.source_id for e in view.entries[-5:]]}
