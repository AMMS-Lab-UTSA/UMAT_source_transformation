#!/usr/bin/env python3
"""Transform every source the triage says the pipeline reaches, and keep the output.

The triage transformed each source into a scratch directory and deleted it, so
every later question -- does this still transform, has the Abaqus round got
anything to link, did that edit to the emitter change any output -- meant paying
for all 199 transforms again. This runs the same recipe and puts each result in
the transform store, which addresses an entry by the source's identity in the
cache, the bytes of that source, and a fingerprint of the transform code
together. The fingerprint is what makes a second run honest: change any file
under the package and every entry is stale, so this rebuilds them instead of
serving yesterday's output as today's evidence.

Two facts are kept apart everywhere below. "Transformed now" is work this run
did. "Already in the store" is work it did not do, and about which it can say
only that the fingerprint still matches. Pooling them into one "succeeded"
number would let a run that did nothing report the same total as the run that
built the corpus, and that total would be read as a result.

A source that fails keeps its reason and stays in the denominator. The whole
point of the triage was that the histogram of reasons is the finding; a batch
that quietly shrank to the sources it could handle would report a success rate
about itself rather than about the transformer.

Nothing here is verification. A stored entry has been compiled at most, and
compiling proves only that the output is Fortran: nothing was executed, and
nothing was compared against anything.

    python tools/transform_all.py --limit 5
    python tools/transform_all.py --jobs 8 --json <somewhere>/transform_all.json
"""
from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from umat_oti.store import TransformStore  # noqa: E402
from umat_oti.store.transform_store import file_digest  # noqa: E402

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO_ROOT.parent / "discovery_cache")
DEFAULT_TRIAGE = REPO_ROOT / "paper_results" / "discovery" / "discovery_triage.csv"
DEFAULT_WORK = Path(os.environ.get("UMAT_OTI_TRANSFORM_WORK")
                    or REPO_ROOT.parent / "transform_all_work")

#: The stage a row must reach to be attempted by default. The triage's own
#: word, so the two files cannot drift apart on what "it transformed" means.
DEFAULT_STAGE = "transformed"

#: Used only when the triage row carries no ntens -- a row that stopped before
#: anything read one. Recorded as such in the metadata: 6 is this corpus's
#: 3-D default, not a fact about the source.
DEFAULT_NTENS = 6

CAVEAT = (
    "A stored entry means the transform ran, and where the metadata says so "
    "that the generated Fortran compiled. Compiling is not verification: "
    "nothing here was executed against a material vector and nothing was "
    "compared against anything. 'reused_from_store' counts work this run did "
    "not do; it is not pooled with work it did."
)

OUTCOME_TRANSFORMED = "transformed"
OUTCOME_CACHED = "cached"
OUTCOME_FAILED = "failed"
OUTCOME_NOT_IN_CACHE = "not_in_cache"
#: Every outcome an attempted row can end at. The four partition the selection:
#: their counts sum to it, which is the check that no row was dropped.
OUTCOMES = (OUTCOME_TRANSFORMED, OUTCOME_CACHED, OUTCOME_FAILED,
            OUTCOME_NOT_IN_CACHE)


# ---------------------------------------------------------------------------
# Machine paths
# ---------------------------------------------------------------------------

def _find_scrubber() -> Optional[Callable[..., str]]:
    """The repository's machine-path filter, wherever it lives today.

    Asked for first as ``umat_oti.evidence.without_machine_paths``; the
    implementation is currently in tools/run_discovery_triage.py. Both are
    tried rather than one being hard-coded, so that moving the function into
    the package cannot silently leave this tool writing ``/home/<someone>``
    into published output -- which is exactly what audit_repository_standards
    fails the build on.
    """
    try:
        from umat_oti.evidence import without_machine_paths as found  # type: ignore
        return found
    except Exception:  # noqa: BLE001 - absence is the expected case today
        pass
    try:
        from run_discovery_triage import without_machine_paths as found
        return found
    except Exception:  # noqa: BLE001 - a tool import must not stop the batch
        return None


_SCRUBBER = _find_scrubber()

#: Shapes that are machine paths whatever their prefix. Only consulted when no
#: scrubber was found at all, in which case free text is withheld entirely and
#: a row is reported by its cache-relative identity alone.
_MACHINE_SHAPE = re.compile(r"(?:/home/|/Users/|/tmp/)")
_WITHHELD = "<withheld: no machine-path filter available in this build>"


def scrub(text: Any, *roots: Any) -> str:
    """``text`` with this machine's directories replaced by named roots.

    Every reason, blocker and compiler message passes through here on its way
    into a record, and it is applied at that one boundary rather than at each
    site that produces a message. Filtering per site is how the triage let a
    baseline compiler error through: it named the file it had been handed, in
    a column nobody had thought of as carrying a path.
    """
    if text is None:
        return ""
    text = str(text)
    if not text:
        return ""
    if _SCRUBBER is not None:
        return _SCRUBBER(text, *[r for r in roots if r])
    return _WITHHELD if _MACHINE_SHAPE.search(text) else text


def _portable(value: Any, *roots: Any, depth: int = 0) -> Any:
    """``value`` reduced to JSON-safe types with every string scrubbed.

    The store writes metadata through ``json.dumps``, so a report fragment
    carrying a Path or an exception object would abort the put after the
    transform had already been paid for.
    """
    if depth > 6:
        return scrub(repr(value), *roots)[:300]
    if isinstance(value, str):
        return scrub(value, *roots)[:300]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return {str(k)[:120]: _portable(v, *roots, depth=depth + 1)
                for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_portable(v, *roots, depth=depth + 1) for v in value[:20]]
    return scrub(str(value), *roots)[:300]


# ---------------------------------------------------------------------------
# What a row becomes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkItem:
    """One source this run intends to transform."""

    #: The source's path within the discovery cache -- "owner__name/dir/u.for".
    #: Never the basename: eighteen UMATs here share one with something else,
    #: and a basename key once paired sources with another project's constants.
    source_id: str
    path: Path
    sha256: str
    ntens: int
    #: False when the triage row carried no ntens and DEFAULT_NTENS was used.
    #: Recorded so a reader can tell a source's declared size from this file's
    #: assumption about it.
    ntens_declared: bool = True
    #: The stage the triage recorded, carried through for context under --all.
    stage: str = ""


@dataclass
class Outcome:
    """What became of one selected row. Every selected row gets exactly one."""

    source_id: str
    outcome: str
    reason: str = ""
    #: Seconds this run spent. Zero for a cached row, which is the point of it.
    seconds: float = 0.0
    #: None when nothing was compiled; False is "compiled and did not pass",
    #: and "skipped" is not "passed" either -- see transform_one.
    compiled: Optional[bool] = None
    ntens: int = 0
    kinematics: str = ""
    key: str = ""
    stage: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source_id, "outcome": self.outcome,
                "reason": self.reason, "seconds": round(self.seconds, 2),
                "compiled": self.compiled, "ntens": self.ntens,
                "kinematics": self.kinematics, "key": self.key,
                "triage_stage": self.stage}


@dataclass
class TransformResult:
    """What one transform attempt produced, before the store sees it."""

    source_id: str
    ok: bool
    seconds: float = 0.0
    out_dir: Optional[Path] = None
    entry_source: Optional[Path] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class WorkPlan:
    """The split of a selection into work to do and work already decided."""

    todo: list[WorkItem] = field(default_factory=list)
    #: Rows settled before any transform ran: served from the store, or not
    #: present in the cache at all. They stay in the denominator.
    settled: list[Outcome] = field(default_factory=list)

    @property
    def selected(self) -> int:
        return len(self.todo) + len(self.settled)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def read_work_list(triage_csv: Path) -> list[dict[str, str]]:
    """The triage rows, in file order.

    csv.DictReader and not a line split: blocker columns contain embedded
    newlines, and the 391-row file is 856 lines long because of them.
    """
    with Path(triage_csv).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def select_work(rows: Iterable[dict[str, str]], *, every: bool = False,
                only: str = "", limit: int = 0,
                stage: str = DEFAULT_STAGE) -> list[dict[str, str]]:
    """The rows this run will attempt.

    ``only`` matches the cache-relative identity, so "owner__repo/sub/u.for"
    and a bare "u.for" are both usable and the first one distinguishes sources
    that share a basename. ``limit`` is applied last, after filtering, so
    --only X --limit 5 means five of X rather than five rows of which some
    might be X.

    A row naming no source is kept rather than dropped: it is reported as
    unresolvable further down. Dropping it here would shrink the denominator
    where nobody could see it happen.
    """
    chosen: list[dict[str, str]] = []
    needle = (only or "").strip().lower()
    for row in rows:
        identity = str(row.get("source") or "").strip()
        if not every and str(row.get("stage") or "").strip() != stage:
            continue
        if needle and needle not in identity.lower():
            continue
        chosen.append(row)
    return chosen[:limit] if limit and limit > 0 else chosen


def _ntens_of(row: dict[str, str]) -> tuple[int, bool]:
    raw = str(row.get("ntens") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_NTENS, False
    return (value, True) if value > 0 else (DEFAULT_NTENS, False)


def plan_work(rows: Iterable[dict[str, str]], cache_root: Path, store: Any, *,
              force: bool = False) -> WorkPlan:
    """Split selected rows into what must be transformed and what need not be.

    ``store`` is anything with ``get(source_id, source_sha256)``; the real
    TransformStore returns None when the transform code has moved on, which is
    what makes an edit to the emitter re-transform the whole corpus rather than
    reuse output that predates it.
    """
    plan = WorkPlan()
    cache_root = Path(cache_root)
    for row in rows:
        identity = str(row.get("source") or "").strip()
        stage = str(row.get("stage") or "").strip()
        if not identity:
            plan.settled.append(Outcome(
                source_id="", outcome=OUTCOME_NOT_IN_CACHE, stage=stage,
                reason="the triage row names no source"))
            continue
        path = cache_root / identity
        if not path.is_file():
            plan.settled.append(Outcome(
                source_id=identity, outcome=OUTCOME_NOT_IN_CACHE, stage=stage,
                reason="no file at this identity under the discovery cache"))
            continue
        digest = file_digest(path)
        ntens, declared = _ntens_of(row)
        if not force:
            stored = store.get(identity, digest)
            if stored is not None:
                metadata = dict(getattr(stored, "metadata", {}) or {})
                plan.settled.append(Outcome(
                    source_id=identity, outcome=OUTCOME_CACHED, stage=stage,
                    key=str(getattr(stored, "key", "")),
                    compiled=metadata.get("compiled"),
                    ntens=int(metadata.get("ntens") or ntens),
                    kinematics=str(metadata.get("kinematics") or "")))
                continue
        plan.todo.append(WorkItem(source_id=identity, path=path, sha256=digest,
                                  ntens=ntens, ntens_declared=declared,
                                  stage=stage))
    return plan


# ---------------------------------------------------------------------------
# The transform
# ---------------------------------------------------------------------------

def work_dir_for(work_root: Path, item: WorkItem) -> Path:
    """A directory no other item writes to, named after the identity.

    Per item rather than per worker: the transform writes contract.json and
    ABA_PARAM.INC under fixed names, so two sources sharing a directory would
    overwrite each other's contract, and under --jobs they would do it at a
    timing that changes run to run. The digest suffix keeps two identities that
    sanitise to the same string apart.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.source_id).strip("_")[:100]
    tail = hashlib.sha256(item.source_id.encode("utf-8")).hexdigest()[:8]
    return Path(work_root) / f"{safe}-{tail}"


def reason_for_report(report: dict[str, Any], *roots: Any) -> str:
    """Why a transform that did not succeed did not succeed.

    The order matters and was learned from the triage. A crashed transform
    returns a report carrying only ``error``, which read as "no reason given";
    and ``completion_issues`` -- where the transform says it could not find its
    own anchors -- is populated exactly when blockers and warnings are both
    empty, so seventeen sources were reported as failing for no stated reason
    while the reason sat in the report unread.
    """
    blockers = report.get("blockers") or []
    if blockers:
        return scrub("; ".join(str(b) for b in blockers), *roots)[:300]
    if report.get("error"):
        return scrub(str(report["error"]), *roots)[:300]
    completion = report.get("completion_issues") or []
    if completion:
        kinds = sorted({str(c.get("kind", "")) for c in completion
                        if isinstance(c, dict)} - {""})
        detail = "; ".join(kinds) if kinds else "; ".join(
            str(c) for c in completion)
        return scrub(f"anchors not located: {detail}", *roots)[:300]
    warnings = report.get("warnings") or []
    if warnings:
        return scrub("; ".join(str(w) for w in warnings), *roots)[:300]
    return "the transform reported neither success nor a reason"


def compiled_cleanly(report: dict[str, Any]) -> bool:
    """Whether the generated Fortran actually compiled.

    Anything but a clean compile is False, "skipped" and "not_requested"
    included: a check that did not run is not a check that passed, and the two
    are indistinguishable in the status field unless it is read. This says the
    output is Fortran and says nothing else -- compiling is never verification.
    """
    compilation = report.get("compilation") or {}
    try:
        code = int(compilation.get("returncode", 1) or 0)
    except (TypeError, ValueError):
        code = 1
    return str(compilation.get("status", "")) == "compiled" and code == 0


def transform_one(item: WorkItem, work: Path) -> TransformResult:
    """Transform one source into ``work/out``, and say what happened.

    The recipe is the triage's, unchanged, so that a source reaching
    "transformed" there reaches it here. In particular the seed is "auto" and
    not "DSTRAN": forcing the strain increment tells a finite-strain source to
    differentiate something it never reads, and the transform then correctly
    reports that nothing on the stress path consumes the seed -- a true answer
    to a question nobody should have asked. The ABA_PARAM.INC stub is written
    beside both the staged source and the output because without it a UMAT that
    includes it has its compile silently skipped, and a skipped check reads as
    a passed one in the status field.

    Runs in a worker process under --jobs, so it returns plain data and puts
    nothing in the store: TransformStore.put rewrites the index on every call,
    and two processes doing that at once lose entries from it.
    """
    from umat_oti.app.engine import _build_contract
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.transformation import (
        TransformationOptions, run_transformation)

    started = time.time()
    work = Path(work)
    source = Path(item.path)
    try:
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        text = source.read_text(errors="replace")
        staged = work / source.name
        staged.write_text(text, encoding="utf-8")
        _write_aba_param_stub(work)
        config, finite = _build_contract(
            source.stem, "auto", "STRESS", "DDSDDE", item.ntens, 1, staged)
        contract_path = work / "contract.json"
        contract_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        out_dir = work / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_aba_param_stub(out_dir)
        report, _code = run_transformation(
            contract_path, out_dir, TransformationOptions(compile_generated=True))
    except Exception as exc:  # noqa: BLE001 - a crash is a result, not an abort
        return TransformResult(
            source_id=item.source_id, ok=False,
            seconds=round(time.time() - started, 2),
            reason=scrub(f"{type(exc).__name__}: {exc}", work)[:300],
            metadata={"traceback": scrub(traceback.format_exc(), work)[-400:]})

    seconds = round(time.time() - started, 2)
    kinematics = "finite" if finite else "small strain"
    compiles = compiled_cleanly(report)
    compilation = report.get("compilation") or {}
    metadata: dict[str, Any] = {
        "source_id": item.source_id,
        "ntens": item.ntens,
        "ntens_provenance": ("triage row" if item.ntens_declared
                             else f"default {DEFAULT_NTENS}; the row carried none"),
        "kinematics": kinematics,
        "compiled": compiles,
        "compile_status": str(compilation.get("status") or ""),
        "compile_error": ("" if compiles else _portable(
            compilation.get("stderr") or compilation.get("status") or "", work)),
        "blockers": _portable(report.get("blockers") or [], work),
        "warnings": _portable(report.get("warnings") or [], work),
        "completion_issues": _portable(report.get("completion_issues") or [], work),
        "anchor_status": _portable(report.get("anchor_status") or "", work),
        "seconds": seconds,
        "triage_stage": item.stage,
        "caveat": CAVEAT,
    }
    if not report.get("transform_success"):
        return TransformResult(source_id=item.source_id, ok=False, seconds=seconds,
                               metadata=metadata,
                               reason=reason_for_report(report, work))
    entry = str(report.get("transformed_source") or "")
    if not entry or not Path(entry).is_file():
        # Success with nothing to store is not success this tool can use: the
        # Abaqus round links the entry source by name, and an entry recording
        # a file that is not there would fail there instead of here.
        return TransformResult(
            source_id=item.source_id, ok=False, seconds=seconds, metadata=metadata,
            reason="the transform reported success but wrote no entry source")
    return TransformResult(source_id=item.source_id, ok=True, seconds=seconds,
                           out_dir=out_dir, entry_source=Path(entry),
                           metadata=metadata)


def put_into(store: Any, item: WorkItem, result: TransformResult) -> Any:
    """Copy one finished transform into the store. Parent process only.

    `store.put` raises ValueError when the transform named an entry source that
    is missing or sits outside its output directory. It used to return a record
    describing a file that did not exist, so the row was counted transformed
    while the store counted nothing and the two totals disagreed with no way to
    tell which was wrong. Letting the exception through makes it a failure of
    that row, which is what it is.
    """
    stored = store.put(item.source_id, item.sha256, result.out_dir,
                       result.entry_source, result.metadata)
    if not stored.exists:
        raise ValueError(
            "the store accepted the entry but its file is not on disk")
    return stored


def record_outcome(item: WorkItem, result: TransformResult,
                   put: Callable[[WorkItem, TransformResult], Any]) -> Outcome:
    """Turn one attempt into the single Outcome that row is entitled to.

    A failure keeps a reason here even when the transform supplied none, so
    that no row can reach the summary as a bare count. "It failed" without a
    cause is the shape of a defect list nobody can act on.
    """
    metadata = result.metadata or {}
    kinematics = str(metadata.get("kinematics") or "")
    if not result.ok or result.out_dir is None or result.entry_source is None:
        return Outcome(
            source_id=item.source_id, outcome=OUTCOME_FAILED, stage=item.stage,
            reason=scrub(result.reason)[:300]
            or "the transform reported neither success nor a reason",
            seconds=result.seconds, ntens=item.ntens, kinematics=kinematics,
            compiled=metadata.get("compiled"))
    try:
        stored = put(item, result)
    except Exception as exc:  # noqa: BLE001 - a store that refused is a failure
        return Outcome(
            source_id=item.source_id, outcome=OUTCOME_FAILED, stage=item.stage,
            reason=scrub(f"transformed, but the store refused it: "
                         f"{type(exc).__name__}: {exc}")[:300],
            seconds=result.seconds, ntens=item.ntens, kinematics=kinematics,
            compiled=metadata.get("compiled"))
    return Outcome(
        source_id=item.source_id, outcome=OUTCOME_TRANSFORMED, stage=item.stage,
        seconds=result.seconds, ntens=item.ntens, kinematics=kinematics,
        compiled=bool(metadata.get("compiled")),
        key=str(getattr(stored, "key", "")))


def run_plan(plan: WorkPlan, *, work_root: Path,
             put: Callable[[WorkItem, TransformResult], Any],
             transform: Callable[[WorkItem, Path], TransformResult] = transform_one,
             jobs: int = 1, keep_work: bool = False,
             announce: Optional[Callable[[Outcome, int, int], None]] = None,
             ) -> list[Outcome]:
    """Do the plan's work and return one Outcome per selected row.

    The store put happens here, in the parent, however many workers ran: see
    transform_one on why a worker must not touch the index.
    """
    outcomes: list[Outcome] = list(plan.settled)
    pairs = [(item, work_dir_for(work_root, item)) for item in plan.todo]
    total = len(pairs)
    done = 0

    def finish(item: WorkItem, produce: Callable[[], TransformResult]) -> None:
        nonlocal done
        try:
            result = produce()
        except Exception as exc:  # noqa: BLE001 - a dead worker is a failure
            result = TransformResult(
                source_id=item.source_id, ok=False,
                reason=scrub(f"{type(exc).__name__}: {exc}")[:300])
        outcome = record_outcome(item, result, put)
        outcomes.append(outcome)
        done += 1
        if announce is not None:
            announce(outcome, done, total)
        # A successful entry is in the store now; its scratch copy is only
        # taking disc. A failure keeps its directory, which is the only place
        # the cause can still be looked at.
        if outcome.outcome == OUTCOME_TRANSFORMED and not keep_work:
            shutil.rmtree(work_dir_for(work_root, item), ignore_errors=True)

    if jobs > 1 and total > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(transform, item, work): item
                       for item, work in pairs}
            for future in as_completed(futures):
                finish(futures[future], future.result)
    else:
        for item, work in pairs:
            finish(item, functools.partial(transform, item, work))
    return outcomes


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------

def summarise(outcomes: Sequence[Outcome], *, selected: int, fingerprint: str = "",
              stage: str = DEFAULT_STAGE, only: str = "", forced: bool = False,
              store_root_name: str = "") -> dict[str, Any]:
    """Counts by outcome, with cached and new work reported separately.

    ``unaccounted`` exists because the rule it enforces has been broken before:
    a denominator that changes where nobody can see it turns a defect list into
    a success rate. It is zero unless a row went missing between selection and
    here, and the human summary shouts when it is not.
    """
    counts = Counter(o.outcome for o in outcomes)
    by_outcome = {name: int(counts.get(name, 0)) for name in OUTCOMES}
    for name, count in counts.items():
        by_outcome.setdefault(name, int(count))
    transformed_now = by_outcome[OUTCOME_TRANSFORMED]
    failed = by_outcome[OUTCOME_FAILED]
    attempted = transformed_now + failed
    return {
        "selected": int(selected),
        "attempted": attempted,
        "by_outcome": by_outcome,
        "transformed_now": transformed_now,
        "reused_from_store": by_outcome[OUTCOME_CACHED],
        "failed": failed,
        "not_in_cache": by_outcome[OUTCOME_NOT_IN_CACHE],
        # Kept apart on purpose: one is a compile this run watched, the other
        # is a compile some earlier run recorded. They are different facts.
        "compiled_cleanly": {
            "transformed_now": sum(1 for o in outcomes
                                   if o.outcome == OUTCOME_TRANSFORMED and o.compiled),
            "reused_from_store": sum(1 for o in outcomes
                                     if o.outcome == OUTCOME_CACHED and o.compiled),
        },
        "unaccounted": int(selected) - sum(by_outcome.values()),
        # Not just "nothing was attempted": a wiped discovery cache
        # attempts nothing either, and reporting that as "every selected
        # source was already in the store" in the same breath as "not in
        # the cache 3" reads as a fully cached corpus.
        "nothing_to_do": (attempted == 0
                          and by_outcome[OUTCOME_NOT_IN_CACHE] == 0),
        "seconds": round(sum(o.seconds for o in outcomes), 2),
        "fingerprint": fingerprint,
        "selection": {"stage": None if stage is None else str(stage),
                      "only": only, "every_row": stage is None,
                      "forced": bool(forced)},
        "store_root_name": store_root_name,
        "failures": [{"source": o.source_id, "reason": o.reason,
                      "triage_stage": o.stage}
                     for o in outcomes if o.outcome == OUTCOME_FAILED],
        "not_in_cache_sources": [o.source_id for o in outcomes
                                 if o.outcome == OUTCOME_NOT_IN_CACHE],
        "rows": [o.as_dict() for o in sorted(outcomes, key=lambda o: o.source_id)],
        "caveat": CAVEAT,
    }


def report_lines(summary: dict[str, Any]) -> list[str]:
    """The human summary. Counts by outcome, never a single success number."""
    selection = summary.get("selection") or {}
    where = "every triage row" if selection.get("every_row") else \
        f"rows at stage '{selection.get('stage')}'"
    if selection.get("only"):
        where += f" matching '{selection['only']}'"
    compiled = summary.get("compiled_cleanly") or {}
    lines = [
        f"transform_all: {summary['selected']} sources selected ({where})",
        f"  transformed now       {summary['transformed_now']:>5}"
        f"   ({compiled.get('transformed_now', 0)} produced Fortran that compiles)",
        f"  already in the store  {summary['reused_from_store']:>5}"
        f"   (not re-transformed and not re-checked;"
        f" fingerprint {summary.get('fingerprint') or '?'})",
        f"  failed                {summary['failed']:>5}"
        + ("   (kept in the denominator, reasons below)"
           if summary['failed'] else ""),
        f"  not in the cache      {summary['not_in_cache']:>5}",
        f"  {sum((summary.get('by_outcome') or {}).values())} accounted for;"
        f" {summary['attempted']} attempted, {summary['seconds']}s of transform"
        f" time (summed over workers, not wall clock)",
    ]
    if summary.get("unaccounted"):
        lines.append(f"  ACCOUNTING ERROR: {summary['unaccounted']} selected rows "
                     f"reached no outcome; the denominator is not trustworthy")
    if summary.get("nothing_to_do"):
        lines.append("  nothing to transform: every selected source was already "
                     "in the store for this fingerprint, so this run did no "
                     "work and changed nothing")
    for failure in summary.get("failures", []):
        lines.append(f"  failed: {failure['source'] or '<row names no source>'}"
                     f"  -- {failure['reason']}")
    for missing in summary.get("not_in_cache_sources", []):
        lines.append(f"  not in the cache: {missing or '<row names no source>'}")
    lines.append(f"  note: {summary['caveat']}")
    return lines


def default_jobs() -> int:
    """Workers when nobody says otherwise: leave two cores for the machine."""
    return max(1, min(8, (os.cpu_count() or 3) - 2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE,
                        help="the triage CSV that says which sources reach where")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--store-root", type=Path, default=None,
                        help="the transform store (default: the store's own)")
    parser.add_argument("--all", dest="every", action="store_true",
                        help="attempt every triage row, not only those that "
                             "reached 'transformed'")
    parser.add_argument("--only", default="",
                        help="attempt only rows whose cache-relative identity "
                             "contains this substring")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true",
                        help="re-transform even sources the store already holds "
                             "for this fingerprint")
    parser.add_argument("--jobs", type=int, default=default_jobs())
    parser.add_argument("--keep-work", action="store_true",
                        help="keep the scratch directory of every source, not "
                             "only of the ones that failed")
    parser.add_argument("--json", dest="json_path", type=Path, default=None,
                        help="write the machine-readable summary here")
    args = parser.parse_args(argv)

    if not args.triage.is_file():
        print(f"no triage CSV at {args.triage.name}; run tools/run_discovery_triage.py")
        return 2
    rows = select_work(read_work_list(args.triage), every=args.every,
                       only=args.only, limit=args.limit)
    if not rows:
        print("no triage rows match this selection")
        return 2

    store = TransformStore(root=args.store_root)
    plan = plan_work(rows, args.cache_dir, store, force=args.force)
    print(f"  {plan.selected} selected; {len(plan.todo)} to transform, "
          f"{sum(1 for o in plan.settled if o.outcome == OUTCOME_CACHED)} "
          f"already in the store", flush=True)

    def announce(outcome: Outcome, done: int, total: int) -> None:
        print(f"[{done}/{total}] {outcome.source_id} -> {outcome.outcome}"
              f"{' (' + outcome.reason[:120] + ')' if outcome.reason else ''}"
              f" {outcome.seconds}s", flush=True)

    outcomes = run_plan(plan, work_root=args.work_dir,
                        put=functools.partial(put_into, store),
                        jobs=max(1, args.jobs), keep_work=args.keep_work,
                        announce=announce)
    summary = summarise(
        outcomes, selected=plan.selected, fingerprint=store.fingerprint,
        stage=None if args.every else DEFAULT_STAGE, only=args.only,
        forced=args.force, store_root_name=Path(store.root).name)
    print("\n".join(report_lines(summary)))

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8")
        print(f"  wrote {args.json_path.name}")
    # A failure under the default selection is a regression: every one of
    # those rows transformed when the triage last ran. Under --all failures are
    # the expected majority and reporting them is the point, so they are not an
    # error exit -- but a row that reached no outcome at all always is.
    if summary["unaccounted"]:
        return 1
    # A vanished source is the same regression class as a failure: every row
    # in the default selection transformed at triage time, so if one is no
    # longer in the cache something changed that a caller has to know about.
    unwell = summary["failed"] or summary.get("not_in_cache")
    return 1 if unwell and not args.every else 0


if __name__ == "__main__":
    raise SystemExit(main())
