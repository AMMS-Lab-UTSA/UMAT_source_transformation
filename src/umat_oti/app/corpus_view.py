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


# ---------------------------------------------------------------------------
# where a piece of evidence lives in a record
# ---------------------------------------------------------------------------
#: Fields the batch writes at the top of a record when the verification ran,
#: and inside ``discovery`` when the search settled them and the verification
#: never got that far. Read from both, top level first, because a panel that
#: looks in one place shows a blank and a blank reads as "not measured" when
#: the measurement is there under another key.
#:
#: Measured on pass9: of 250 records, NONE carries ``failure_mechanism``,
#: ``segment_repair``, ``coverage_given_up``, ``safe_loading_reconstructed`` or
#: ``discovery_usable_prefix`` at the top, and 139 carry all five inside
#: ``discovery``. What was being hidden: 139 usable prefixes, 30 named failure
#: mechanisms, 23 repaired segments, 13 experiments that gave up coverage and 7
#: loadings rebuilt inside the part a run had proved safe.
EITHER_LEVEL = (
    "complete_finite_verification_run",
    "discovery_usable_prefix",
    "safe_loading_reconstructed",
    "failure_mechanism",
    "segment_repair",
    "coverage_given_up",
    "history_grouping",
    "time_scale_coverage",
    "activation_on_the_frozen_run",
    "mechanically_informative",
    "primal_signature",
    "searched_for_material_data",
    "safety_distance",
)


def field_anywhere(row: dict, name: str) -> Any:
    """One recorded field, from wherever in the record the batch put it.

    Top level wins, then ``discovery`` -- but only for the names in
    :data:`EITHER_LEVEL`. Falling back into ``discovery`` for anything at all
    would let an unrelated key of the same name inside the search's own
    bookkeeping stand in for a field the verification never recorded, and a
    borrowed value is worse than a missing one: it reads as measured.

    Nothing is derived and nothing is defaulted. A field absent from both
    comes back as ``None``, which is "never recorded" and is shown as that
    rather than as a false.
    """
    value = row.get(name)
    if value is not None:
        return value
    if name not in EITHER_LEVEL:
        return None
    inner = row.get("discovery")
    if isinstance(inner, dict):
        return inner.get(name)
    return None


#: The gates a verdict rests on, in the order the batch decides them, with what
#: each one measures and which part of the record carries it. Written out
#: because "verified" is a word and these six are the measurements under it:
#: Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement about
#: the solver, not about the constitutive routine it called.
EVIDENCE_GATES = (
    ("abaqus_job_completed",
     "the solver reached the end of the deck it was given",
     "original.sta / transformed.sta"),
    ("all_requested_outputs_present",
     "every increment produced every material point it was asked for -- an "
     "increment short of a point did not produce the state a comparison "
     "would compare",
     "history_grouping[side].first_incomplete_increment"),
    ("complete_history_finite",
     "no NaN and no infinity anywhere in either history, which a job Abaqus "
     "calls successful can still be full of",
     "history_grouping[side].first_non_finite_material_point"),
    ("primal_agreed",
     "the original and the converted build computed the same stress and the "
     "same state at every increment they both walked",
     "primal"),
    ("derivatives_verified",
     "the converted build's tangent matched a centred difference of the "
     "ORIGINAL, over a plateau of step sizes rather than at one step",
     "tangent.states[].comparison"),
    ("mechanically_informative",
     "the material did something over the run that was verified, and the run "
     "was long enough to reach the time scale the source declares -- "
     "agreement about a material sitting still is agreement about the part "
     "every build gets right",
     "mechanically_informative / time_scale_coverage"),
)

#: What :data:`EVIDENCE_GATES` names, per history, in the grouping the batch
#: writes. Shown as a table rather than a JSON blob because the two sides have
#: to be read against each other: a transformed history two increments shorter
#: than the original is the finding.
HISTORY_FIELDS = ("raw_output_records", "complete_increments",
                  "material_points_per_increment",
                  "first_incomplete_increment",
                  "first_non_finite_material_point")

#: What a gate with no recorded measurement is called. Distinct from "no" on
#: purpose: a step whose result was never established is not a step that
#: failed, and reporting it as one invents a failure the batch did not record.
NOT_MEASURED = "not measured"


def _said(value: Any) -> str:
    """One recorded value as a phrase, with absence said rather than blank."""
    if value is None:
        return "--"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def what_the_batch_recorded_after(row: dict, gate: str) -> str:
    """What else the record says about a gate that did not pass.

    A disagreement is not yet a verdict, and the batch says so in the record
    rather than in a log: it re-runs the ORIGINAL with the author's own
    declared precision widened, and where that does not settle it, with the
    same mathematics reassociated. Either can end with the entry at
    ``verified`` while ``evidence.primal_agreed`` stays the false the raw
    comparison measured -- those are two different claims and both are kept.

    On pass9 that is 17 entries reaching ``verified`` with
    ``evidence.primal_agreed`` false. A page that showed the gate alone would
    read as a contradiction; one that showed only the verdict would hide that
    the raw builds differ. Both are shown, and the sentence between them is
    the batch's own, quoted rather than composed here.
    """
    if gate != "primal_agreed":
        return ""
    primal = row.get("primal") or {}
    control = row.get("precision_control") or {}
    association = row.get("association_control") or {}
    if primal.get("explained_by_declared_precision"):
        return ("the raw comparison disagreed, and the batch recorded the "
                "difference as the author's own declared precision: "
                + str(control.get("reason") or row.get("reason") or ""))
    if association:
        return ("the raw comparison disagreed, and the batch put the model "
                "against itself compiled with the same mathematics "
                "reassociated: " + str(row.get("reason") or ""))
    if control:
        return ("the raw comparison disagreed and a precision control was "
                "run; it is recorded under precision_control")
    return ""


def evidence_rows(row: dict) -> list:
    """The six gates, each with what it measures and what was measured.

    Nothing here decides anything: the batch wrote ``evidence`` and this puts
    it beside the sentence that says what each entry of it means, so a reader
    can see which of the six a verdict rests on and which of them nobody
    measured.
    """
    measured = row.get("evidence") or {}
    rows = []
    for name, what, where in EVIDENCE_GATES:
        value = measured.get(name)
        rows.append({
            "gate": name.replace("_", " "),
            "field": name,
            "measured": NOT_MEASURED if value is None else _said(value),
            "passed": None if value is None else bool(value),
            "what it measures": what,
            "read from": where,
            "and then": (what_the_batch_recorded_after(row, name)
                         if value is False else ""),
        })
    return rows


def history_rows(row: dict) -> list:
    """How each history grouped into increments and material points.

    Three rows where there are three: the original, the converted build, and
    the run the amplitude search itself walked. The last is there because a
    record that never reached a verification still has one history in it, and
    a panel that shows nothing for such an entry is hiding the only thing
    measured about it.
    """
    grouping = field_anywhere(row, "history_grouping") or {}
    sides: list = []
    if isinstance(grouping, dict):
        for side in ("original", "transformed"):
            payload = grouping.get(side)
            if isinstance(payload, dict):
                sides.append((side, payload))
    prefix = field_anywhere(row, "discovery_usable_prefix")
    if isinstance(prefix, dict):
        sides.append(("discovery (the search's own run)", prefix))
    rows = []
    for side, payload in sides:
        entry = {"history": side, "complete": _said(payload.get("complete"))}
        for name in HISTORY_FIELDS:
            entry[name.replace("_", " ")] = _said(payload.get(name))
        entry["total increments"] = _said(payload.get("total_increments"))
        rows.append(entry)
    return rows


def loading_rows(row: dict) -> list:
    """The loading path the experiment walked, segment by segment.

    Off the manifest that was RUN, not off the discovery summary: the summary
    says what amplitude the search chose and the manifest says what was
    actually driven, including the hold a rate probe added and the segments a
    repair shortened or dropped. A page that shows only the amplitude cannot
    show that the reversal is gone.
    """
    manifest = row.get("manifest") or {}
    rows = []
    for segment in manifest.get("loading") or ():
        if not isinstance(segment, dict):
            continue
        rows.append({
            "segment": segment.get("name"),
            "what it does": segment.get("description"),
            "strain": segment.get("strain"),
            "increments": segment.get("increments"),
            "step time": segment.get("period"),
            "held": segment.get("held") or "--",
            "body force": segment.get("body_force") or "--",
        })
    return rows


def experiment_settlement(row: dict) -> dict:
    """What the search had to do to get an experiment that runs whole.

    A verdict that rests on a repaired experiment is a verdict about the
    repaired experiment. Every part of that repair is named here: how far the
    model walked before it left its domain, what was rebuilt inside the part
    it proved safe, which mechanism stopped it, which segment was shortened or
    dropped, and what the experiment therefore stopped exercising.
    """
    return {name: field_anywhere(row, name) for name in (
        "complete_finite_verification_run",
        "discovery_usable_prefix",
        "safe_loading_reconstructed",
        "failure_mechanism",
        "segment_repair",
        "coverage_given_up",
        "time_scale_coverage",
        "activation_on_the_frozen_run",
        "mechanically_informative",
    )}


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
    #: The model against itself, compiled so the same mathematics is computed
    #: in a different order. Run when a precision control did not settle a
    #: disagreement, and recorded whether or not it did.
    association_control: dict = field(default_factory=dict)
    requirements: list = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    seconds: Optional[float] = None
    #: The six gates a verdict rests on, each with what it measures and
    #: whether it was measured. See :data:`EVIDENCE_GATES`.
    evidence: list = field(default_factory=list)
    #: How each history grouped into increments and material points, and
    #: where the first incomplete increment and the first value that is not a
    #: number are. See :func:`history_rows`.
    history: list = field(default_factory=list)
    #: What the search had to do to get an experiment that runs whole, and
    #: what the experiment therefore stopped exercising.
    experiment: dict = field(default_factory=dict)
    #: What the pairing scan read while looking for material constants.
    material_search: dict = field(default_factory=dict)
    #: What kind of disagreement a primal disagreement is, where one was
    #: classified. A stage is not a diagnosis.
    primal_signature: dict = field(default_factory=dict)
    #: The manifest the batch actually ran: constants, tensor split, loading
    #: segments, step ladder, tolerances and outputs. Distinct from
    #: :attr:`manifest`, which is what was INFERRED about the source. A
    #: regression replays this one, so a reader has to be able to see it.
    run_manifest: dict = field(default_factory=dict)
    #: The loading path, segment by segment. See :func:`loading_rows`.
    loading: list = field(default_factory=list)

    def as_dict(self) -> dict:
        record = {name: getattr(self, name) for name in
                  ("source_id", "repository", "key", "stage", "terminal_state",
                   "kind", "reason", "is_umat", "manifest", "formulation",
                   "discovery", "jobs", "primal", "tangent", "truncation",
                   "precision_control", "association_control",
                   "artifacts", "seconds", "evidence",
                   "history", "experiment", "material_search",
                   "primal_signature", "run_manifest", "loading")}
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
                    material or _where_constants_were_looked_for(row)),
        Requirement("a paired deck", bool(deck), deck),
        Requirement("a formulation this harness can drive",
                    bool(formulation.get("element")),
                    str(formulation.get("reason") or "")),
        Requirement("every companion source", not missing_units,
                    ", ".join(missing_units)),
        Requirement("a manifest with nothing missing", not manifest_refusals,
                    "; ".join(str(r) for r in manifest_refusals)),
        # The one a verdict actually rests on. Abaqus printing THE ANALYSIS
        # HAS COMPLETED SUCCESSFULLY is a statement about the solver; this is
        # about the routine it called.
        Requirement("an analysis finite from end to end",
                    bool(field_anywhere(
                        row, "complete_finite_verification_run")),
                    _how_the_experiment_was_settled(row)),
        # Agreement about a material that did nothing is agreement about the
        # part every build gets right, so it is a requirement of its own
        # rather than a footnote under the tangent.
        Requirement("an experiment the material did something in",
                    (row.get("evidence") or {}).get(
                        "mechanically_informative") is not False,
                    _what_the_experiment_exercised(row)),
    ]


def _how_the_experiment_was_settled(row: dict) -> str:
    """What the discovery had to do to get an experiment that runs whole.

    Named rather than summarised, because "not ready" is not something a
    reader can act on and "the model will not be driven backwards, so the
    reversal was dropped and this experiment no longer exercises it" is.
    """
    grouping = (field_anywhere(row, "history_grouping") or {}).get(
        "original") or {}
    if field_anywhere(row, "complete_finite_verification_run"):
        said = (f"{grouping.get('complete_increments', '?')} complete "
                f"increment(s) at "
                f"{grouping.get('material_points_per_increment', '?')} "
                f"material points each, every one finite")
        given_up = str(field_anywhere(row, "coverage_given_up") or "")
        return f"{said}; {given_up}" if given_up else said
    mechanism = (field_anywhere(row, "failure_mechanism") or {}).get("kind") or ""
    repair = str(field_anywhere(row, "segment_repair") or "")
    prefix = field_anywhere(row, "discovery_usable_prefix") or {}
    said = (f"{prefix.get('complete_increments', 0)} complete increment(s) of "
            f"{prefix.get('total_increments', '?')} before it left its domain")
    where = (prefix.get("first_non_finite_material_point") or {})
    if where:
        said += (f"; the first value that was not a number is element "
                 f"{where.get('element')} point {where.get('point')} at "
                 f"increment {where.get('increment')}")
    if mechanism:
        said += f"; the failure is {mechanism.replace('_', ' ')}"
    rebuilt = field_anywhere(row, "safe_loading_reconstructed") or {}
    if rebuilt:
        said += (f"; the loading was rebuilt at "
                 f"{rebuilt.get('amplitude')}, {rebuilt.get('fraction')} of "
                 f"the part the run proved safe")
    return f"{said}; {repair}" if repair else said


def _what_the_experiment_exercised(row: dict) -> str:
    """Whether the run a verdict rests on exercised anything, and how that
    was measured -- the indicators read off the frozen run, and whether the
    experiment was long enough for the time scale the source declares."""
    informative = field_anywhere(row, "mechanically_informative")
    if isinstance(informative, dict) and informative.get("reason"):
        return str(informative["reason"])
    activation = field_anywhere(row, "activation_on_the_frozen_run") or {}
    coverage = field_anywhere(row, "time_scale_coverage") or {}
    said = [str(activation.get("summary") or ""), str(coverage.get("reason") or "")]
    said = [part for part in said if part]
    if said:
        return "; ".join(said)
    if (row.get("evidence") or {}).get("mechanically_informative") is None:
        return ("this run predates the informativeness gate, so whether the "
                "material did anything over it was never measured")
    return str(row.get("reason") or "")


def _where_constants_were_looked_for(row: dict) -> str:
    """What the search for material constants actually read.

    "No deck publishes constants for this source" is a claim until it names
    a file. The verification records the pairing scan's own account -- the
    repository, how many decks were read, how many constants the source's
    PROPS references reach -- so the panel shows that rather than a sentence
    a reader cannot check.
    """
    searched = field_anywhere(row, "searched_for_material_data") or {}
    if not searched:
        return str(row.get("reason") or
                   "no deck in this repository publishes constants matching "
                   "this source")
    where = str(searched.get("repository") or "this source's repository")
    count = int(searched.get("decks_scanned") or 0)
    evidence = str(searched.get("evidence") or "")
    if not count:
        return (f"{where} contains no .inp file at all, and no document in "
                f"it carries a material block naming this routine")
    said = f"read {count} .inp file(s) in {where}"
    if evidence:
        said += f": {evidence}"
    return said


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
            "searched_for_material_data": field_anywhere(
                row, "searched_for_material_data"),
            # How the experiment was settled on, and what it cost. A reader
            # has to be able to see that a verdict rests on an analysis that
            # was finite throughout, which segment (if any) the model would
            # not walk, and what the experiment therefore stopped exercising.
            "discovery_usable_prefix": field_anywhere(
                row, "discovery_usable_prefix"),
            "safe_loading_reconstructed": field_anywhere(
                row, "safe_loading_reconstructed"),
            "complete_finite_verification_run": field_anywhere(
                row, "complete_finite_verification_run"),
            "failure_mechanism": field_anywhere(row, "failure_mechanism"),
            "segment_repair": field_anywhere(row, "segment_repair"),
            "coverage_given_up": field_anywhere(row, "coverage_given_up"),
            "safety_distance": field_anywhere(row, "safety_distance"),
            "history_grouping": field_anywhere(row, "history_grouping"),
            "time_scale_coverage": field_anywhere(row, "time_scale_coverage"),
            "evidence": row.get("evidence"),
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
        association_control=dict(row.get("association_control") or {}),
        requirements=_requirements(row),
        artifacts=_artifacts(row, work_dir),
        seconds=row.get("seconds"),
        evidence=evidence_rows(row),
        history=history_rows(row),
        experiment=experiment_settlement(row),
        material_search=dict(
            field_anywhere(row, "searched_for_material_data") or {}),
        primal_signature=dict(field_anywhere(row, "primal_signature") or {}),
        run_manifest=dict(row.get("manifest") or {}),
        loading=loading_rows(row),
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


def fd_plateau(entry: EntryView, state: int = 0, *,
               against: str = "comparison") -> list:
    """The finite-difference sweep at one state, step by step.

    One step size cannot separate a truncation error from a cancellation one:
    both shrink the error for a while and then grow it, and a single number
    taken anywhere on that curve is indistinguishable from a number taken at
    the one step where two different tangents happen to cross. What settles it
    is the PLATEAU -- a run of step sizes over which the error stops moving --
    so each row carries whether it is inside the stable range the batch
    recorded, and which step was the best.

    ``against`` picks which sweep: the converted build's tangent against a
    difference of the original (``comparison``, the one a verdict rests on),
    the author's own DDSDDE against the same difference
    (``against_the_authors_tangent``), or the reference's difference against
    itself (``the_references_own_error``).
    """
    states = (entry.tangent or {}).get("states") or []
    if not 0 <= state < len(states):
        return []
    comparison = (states[state] or {}).get(against) or {}
    stable = list(comparison.get("stable_range") or ())
    best = comparison.get("best_step")
    rows = []
    for point in comparison.get("sweep") or ():
        step = point.get("step")
        inside = None
        if len(stable) == 2 and step is not None:
            try:
                inside = float(stable[0]) <= float(step) <= float(stable[1])
            except (TypeError, ValueError):       # pragma: no cover
                inside = None
        rows.append({"step": step,
                     "relative": point.get("relative"),
                     "absolute": point.get("absolute"),
                     "frobenius": point.get("frobenius"),
                     "on the plateau": inside,
                     "best step": best is not None and step == best})
    return rows


def componentwise_errors(entry: EntryView, state: int = 0, *,
                         work_dir: Optional[Path] = None) -> list:
    """Entry by entry, the DDSDDE the original returned against the converted
    build's, at one state.

    "The tangent disagreed by 3e-4" is a number; "DDSDDE(4,4) disagreed by
    3e-4 and every other entry agreed to 1e-12" is a finding, and only the
    second tells anybody which term of the constitutive law to open.

    The record carries norms, not matrices, so the matrices are read off the
    two probe histories on disk at the record the tangent was measured at.
    What a difference here means is worth being exact about: it is the
    AUTHOR'S own DDSDDE against the derivative the converted build extracted,
    which is the pair the record summarises as
    ``against_the_authors_tangent``. A verdict rests on ``comparison`` --
    the converted build's derivative against a centred difference of the
    original's STRESS -- so a large number in this table is a statement about
    the author's tangent, not about the transformation.

    Empty when the histories are not on disk, which is the honest answer: an
    interface that invents a table here would be showing a difference nobody
    computed.
    """
    states = (entry.tangent or {}).get("states") or []
    if not 0 <= state < len(states) or not work_dir or not entry.key:
        return []
    index = (states[state] or {}).get("record_index")
    if not isinstance(index, int):
        return []
    root = Path(work_dir) / entry.key
    original = _read_json(root / "original" / "original_history.json")
    converted = _read_json(root / "transformed" / "transformed_history.json")
    if not isinstance(original, list) or not isinstance(converted, list):
        return []
    if not 0 <= index < len(original) or not 0 <= index < len(converted):
        return []
    left = list((original[index] or {}).get("DDSDDE") or ())
    right = list((converted[index] or {}).get("DDSDDE") or ())
    size = int(entry.manifest.get("ntens") or 0)
    if not left or len(left) != len(right) or size <= 0:
        return []
    if len(left) < size * size:
        return []
    largest = max((abs(float(v)) for v in left[:size * size]), default=0.0)
    rows = []
    for i in range(size):
        for j in range(size):
            a, b = float(left[i * size + j]), float(right[i * size + j])
            difference = abs(a - b)
            scale = max(abs(a), abs(b))
            rows.append({
                "entry": f"DDSDDE({i + 1},{j + 1})",
                "the author's own": a,
                "the converted build's": b,
                "absolute": difference,
                # Relative to the entry itself where the entry carries any of
                # the response, and left unscored where it does not: a
                # component eight orders below the largest holds each build's
                # rounding and nothing else, and dividing by it manufactures a
                # disagreement out of round-off.
                "relative": (difference / scale
                             if scale > largest * 1e-8 and scale > 0 else None),
            })
    rows.sort(key=lambda r: (r["relative"] is None, -(r["relative"] or 0.0),
                             -r["absolute"]))
    return rows


#: Every claim the interface makes about an entry, and where the thing behind
#: it is. A panel that shows a number without saying which file it came out of
#: is asking to be believed; this is what makes a screenshot checkable.
EVIDENCE_LOCATIONS = (
    ("the manifest that was run", "manifest", "original/original.inp"),
    ("where the material constants came from", "manifest.material_provenance",
     ""),
    ("what was read while looking for constants",
     "searched_for_material_data", ""),
    ("the loading history the experiment walked", "manifest.loading",
     "original/original.inp"),
    ("what the search did to arrive at it", "discovery", "discovery"),
    ("what Abaqus did with it", "original / transformed",
     "original/original.sta"),
    ("what the routine wrote at every material point", "history_grouping",
     "original/original_history.json"),
    ("whether the material did anything", "mechanically_informative", ""),
    ("how long the experiment ran against the source's own clock",
     "time_scale_coverage", ""),
    ("the two builds' stress and state, compared", "primal",
     "transformed/transformed_history.json"),
    ("what kind of disagreement it is", "primal_signature", ""),
    ("the tangent against a difference of the original",
     "tangent.states[].comparison", "replay"),
    ("the author's own DDSDDE against the same difference",
     "tangent.states[].against_the_authors_tangent",
     "transformed/transformed_history.json"),
    ("what the arithmetic alone would have cost", "precision_control",
     "precision_control"),
    ("how far this model moves when its own arithmetic is reordered",
     "association_control", "association_control"),
    ("where a derivative was dropped on the way to the stress", "truncation",
     ""),
)


def evidence_paths(entry: EntryView) -> list:
    """For every claim on the page, the field and the file behind it.

    ``on disk`` is ``""`` where the claim rests on the record alone, and a
    path under this entry's work directory otherwise. ``present`` says whether
    that file is actually there, so a reader can tell a claim whose evidence
    was cleaned up from one whose evidence is sitting next to it.
    """
    root = entry.artifacts.get("work_dir") or ""
    rows = []
    for what, field_name, relative in EVIDENCE_LOCATIONS:
        path = str(Path(root) / relative) if (root and relative) else ""
        rows.append({
            "what the page claims": what,
            "field in the record": field_name,
            "on disk": path,
            "present": Path(path).exists() if path else None,
        })
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
