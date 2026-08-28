#!/usr/bin/env python3
"""Attempt a transformation of every discovered source and record where it stops.

Discovery says which sources this project is allowed to use. This says what the
pipeline actually does with them, and it exists to be read as a defect list
rather than as a score: a source that stops at an unsupported Fortran construct
is naming a gap in the transformer, and the histogram of those reasons is the
most direct statement available of what the tool cannot yet do.

Nothing is verified here. A source that transforms has produced Fortran that
compiles nowhere yet and has been compared against nothing; that is the corpus
round's job and it needs a material vector this step does not have. What this
round reports is reach -- how far a source authored by somebody else, with no
adaptation, gets through the front of the pipeline.

    python tools/run_discovery_triage.py --cache-dir <where discovery cached>
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.app.engine import _build_contract  # noqa: E402
from umat_oti.core.roles import role_summary, suggest_variable_roles  # noqa: E402
from umat_oti.fortran.scanner import analyze_fortran_source  # noqa: E402
from umat_oti.services.transformation import (  # noqa: E402
    TransformationOptions, run_transformation,
)

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO_ROOT.parent / "discovery_cache")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "discovery"

COLUMNS = (
    "source", "repository", "bytes", "lines", "form", "kinematics", "ntens", "nstatv_hint",
    "anchor_status",
    "helper_routines", "declared_unsupported",
    "stage", "blocker_kind", "blocker", "seconds",
)

#: Coarse causes, so the histogram groups a defect rather than listing every
#: message. Ordered: the first pattern that matches names the cause.
_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unsupported_intrinsic", ("unsupported intrinsic",)),
    ("unresolved_dependency", ("differing definitions", "ambiguous",
                               "could not be resolved", "no local definition")),
    # "has no confirmed shape" is tested before anything matching the word
    # "stress", because the message that carries it -- "Promoted variable X is
    # indexed in a stress region but has no confirmed shape" -- names a
    # declaration the transformer could not read, not a stress update it could
    # not find. Matching the bare word "stress" filed fourteen sources under a
    # cause that was not theirs and hid a whole defect class behind a count.
    ("shape_unknown", ("has no confirmed shape",)),
    ("no_stress_update_found", ("stress update region is required",
                               "no assignment to")),
    ("io_on_stress_path", ("file i/o", "write(", "read(")),
    ("unparsed_construct", ("unsupported", "cannot be transformed",
                            "syntax", "parse")),
    ("missing_ddsdde_extraction_point",
     ("not covered by an old tangent replacement region",)),
    ("semantic_check", ("semantic check",)),
    ("scanner_error", ("traceback", "exception")),
)


def _classify(text: str) -> str:
    lowered = (text or "").lower()
    for kind, needles in _KINDS:
        if any(needle in lowered for needle in needles):
            return kind
    return "other" if lowered else "none"


def triage_one(source: Path, work_root: Path, *, ntens: int = 6,
               cache_root: Path | None = None) -> dict[str, Any]:
    started = time.time()
    row = {name: "" for name in COLUMNS}
    text = source.read_text(errors="replace")
    # Relative to the cache root: an absolute path here would record this
    # machine's home directory in published evidence.
    shown = source
    if cache_root is not None:
        try:
            shown = source.relative_to(cache_root)
        except ValueError:
            shown = source
    row.update(source=str(shown), bytes=len(text.encode()),
               lines=text.count("\n") + 1,
               repository=source.parent.name if source.parent != source else "")
    try:
        analysis = analyze_fortran_source(source)
    except Exception as exc:  # noqa: BLE001 - a scanner crash is a finding
        row.update(stage="scan_failed", blocker_kind="scanner_error",
                   blocker=f"{type(exc).__name__}: {exc}"[:300],
                   seconds=round(time.time() - started, 2))
        return row
    row["form"] = str(analysis.get("form", ""))
    # Constructs the transformer declares up front that it does not
    # handle. Reading them matters because their consequences surface far
    # downstream: fourteen sources keep their arrays in COMMON blocks and
    # were filed under "no confirmed shape", which is what a COMMON-
    # declared bound looks like to a reader that never learned to read
    # one. Naming the declared limitation says which of these is a gap to
    # close and which is a symptom of a gap already known.
    unsupported = sorted({
        str(f.get("code", "")) for f in
        (analysis.get("unsupported_features") or [])
        if isinstance(f, dict) and f.get("severity") == "error"})
    row["declared_unsupported"] = ";".join(unsupported)
    row["helper_routines"] = len(analysis.get("detected_subroutines") or [])
    if not analysis.get("has_subroutine_umat"):
        row.update(stage="not_a_umat", blocker_kind="not_a_umat",
                   blocker="the scanner finds no UMAT subroutine in this file",
                   seconds=round(time.time() - started, 2))
        return row

    work = work_root / source.parent.name / source.stem
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    staged = work / f"{source.stem}{source.suffix}"
    staged.write_text(text, encoding="utf-8")

    try:
        summary = role_summary(suggest_variable_roles(analysis, text))
        row["nstatv_hint"] = len(summary.get("promoted_variables") or [])
        # "auto", not "DSTRAN". Forcing the strain increment as the seed
        # tells a finite-strain source to differentiate something it never
        # reads, and the transform then correctly reports that nothing on the
        # stress path consumes the seed -- a true statement about a question
        # nobody should have asked. The engine detects the kinematics.
        config, finite = _build_contract(
            source.stem, "auto", "STRESS", "DDSDDE", ntens, 1, staged)
        row["kinematics"] = "finite" if finite else "small strain"
        contract_path = work / "contract.json"
        contract_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        report, _code = run_transformation(
            contract_path, work / "out", TransformationOptions(compile_generated=False))
    except Exception as exc:  # noqa: BLE001 - a crash is the most useful finding
        row.update(stage="transform_crashed", blocker_kind="scanner_error",
                   blocker=f"{type(exc).__name__}: {exc}"[:300],
                   seconds=round(time.time() - started, 2))
        row["traceback"] = traceback.format_exc()[-400:]
        return row

    row["ntens"] = ntens
    # A crashed transform returns a report carrying only the error, which was
    # being read as "no reason given".
    if report.get("error") and not report.get("transform_success"):
        row.update(stage="transform_error", blocker_kind="transform_error",
                   blocker=str(report["error"])[:300],
                   seconds=round(time.time() - started, 2))
        return row
    blockers = report.get("blockers") or []
    warnings = report.get("warnings") or []
    # completion_issues is where the transform says it could not locate its
    # own anchors, and it is populated when blockers and warnings are both
    # empty. Reading only those two reported seventeen sources as failing for
    # no stated reason while the reason sat in the report unread.
    completion = report.get("completion_issues") or []
    row["anchor_status"] = str(report.get("anchor_status") or "")
    if report.get("transform_success"):
        row.update(stage="transformed", blocker_kind="none", blocker="")
    elif blockers:
        # The blocker says what failed; declared_unsupported says what the
        # transformer had already announced it cannot read. Letting the second
        # overwrite the first repeated the mistake it was meant to correct:
        # fifteen sources whose blocker is an uncovered DDSDDE assignment were
        # filed under "unsupported_data" because a DATA statement appears
        # somewhere in the file. The two are reported side by side instead,
        # which is what makes the COMMON-block group legible -- its fourteen
        # sources fail on a shape the reader could not confirm, and the reason
        # it could not is in the other column.
        row.update(stage="blocked", blocker_kind=_classify(blockers[0]),
                   blocker="; ".join(str(b) for b in blockers)[:300])
    elif completion:
        kinds = sorted({str(c.get("kind", "")) for c in completion
                        if isinstance(c, dict)})
        row.update(stage="anchors_not_located",
                   blocker_kind=kinds[0] if kinds else "anchor_incomplete",
                   blocker="; ".join(kinds)[:300])
    elif warnings:
        row.update(stage="semantic_checks_failed",
                   blocker_kind=_classify(warnings[0]),
                   blocker="; ".join(str(w) for w in warnings)[:300])
    else:
        row.update(stage="failed", blocker_kind="other",
                   blocker="the transform reported neither success nor a reason")
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    sources = sorted(p for p in args.cache_dir.rglob("*")
                     if p.suffix.lower() in {".f", ".for", ".f90", ".f95", ".ftn"})
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        print(f"no cached sources under {args.cache_dir}")
        return 2
    print(f"  {len(sources)} cached sources to triage")

    rows: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        row = triage_one(source, args.work_dir, cache_root=args.cache_dir)
        rows.append(row)
        print(f"[{index}/{len(sources)}] {source.parent.name}/{source.name}"
              f"  -> {row['stage']} ({row['blocker_kind']}) {row['seconds']}s",
              flush=True)

    stages = Counter(r["stage"] for r in rows)
    kinds = Counter(r["blocker_kind"] for r in rows if r["blocker_kind"] not in ("none", ""))
    summary = {
        "sources": len(rows),
        "by_stage": dict(stages.most_common()),
        "by_blocker_kind": dict(kinds.most_common()),
        "transformed": stages.get("transformed", 0),
        "cache_root_name": args.cache_dir.name,
        "cache_root_note": (
            "The cache is outside the repository; set "
            "UMAT_OTI_DISCOVERY_CACHE to point at it. Its absolute path "
            "is a property of the machine that ran the triage, not of "
            "the result, so it is not recorded here."),
        "caveat": (
            "Reaching 'transformed' means the transformer produced Fortran, "
            "not that anything was compiled, executed or compared. These "
            "sources have no material vector and no loading history, so no "
            "count here is verification evidence. The blocker histogram is "
            "the point: it names what the transformer cannot yet do."),
    }
    print(json.dumps(summary, indent=2))

    if args.results_dir:
        args.results_dir.mkdir(parents=True, exist_ok=True)
        path = args.results_dir / "discovery_triage.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(COLUMNS),
                                    lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        (args.results_dir / "discovery_triage.json").write_text(
            json.dumps({"summary": summary, "rows": rows}, indent=2,
                       sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
