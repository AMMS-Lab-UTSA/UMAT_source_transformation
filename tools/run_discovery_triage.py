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
import subprocess
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

sys.path.insert(0, str(REPO_ROOT / "tools"))
from discover_umat_sources import _FORTRAN_SUFFIXES, _has_umat_entry  # noqa: E402


def _looks_like_a_umat(path: Path) -> bool:
    """Cheap check, for reporting only: does this file declare a UMAT?

    Used to separate "cached but not triaged because the form is unknown" from
    "cached because it sat beside one that was" -- a README is not a hole in
    the triage, a UMAT shipped as ``.inc`` is.
    """
    try:
        if path.stat().st_size > 2_000_000:
            return False
        return _has_umat_entry(path.read_text(errors="replace"))
    except OSError:
        return False


COLUMNS = (
    "source", "repository", "bytes", "lines", "form", "kinematics", "ntens", "nstatv_hint",
    "anchor_status",
    "helper_routines", "declared_unsupported",
    "stage", "blocker_kind", "blocker",
    "original_compiles", "compiled", "compile_error", "seconds",
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



def _original_compiles(source: Path, work: Path) -> tuple[bool, str]:
    """Whether the untransformed source compiles here, and why not if it does not.

    The baseline has to be measured, not assumed. mholla/growth's
    umat_neohooke.f closes its own SUBROUTINE statement with two parentheses
    and does not compile as shipped; charging that to the transformer would be
    inventing a defect, and counting the transformed file as a failure without
    saying so would be worse. Sources are held to what they were, not to what
    they would need to be.
    """
    from umat_oti.corpus.cli import _write_aba_param_stub
    baseline = work / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    _write_aba_param_stub(baseline)
    staged = baseline / source.name
    staged.write_text(source.read_text(errors="replace"), encoding="utf-8")
    # The same line-length flag the generated file is compiled with. Without
    # it gfortran truncates fixed-form source at column 72, and twelve sources
    # whose only sin was an 84-column line were recorded as not compiling as
    # shipped -- which excused the transformer from them. A baseline held to
    # stricter flags than the thing it is the baseline for is not a baseline.
    flags = (["-ffree-form", "-ffree-line-length-none"]
             if source.suffix.lower() == ".f90"
             else ["-ffixed-form", "-ffixed-line-length-none"])
    finished = subprocess.run(
        ["gfortran", "-fsyntax-only", *flags, "-I", str(baseline), str(staged)],
        capture_output=True, text=True, cwd=baseline)
    return finished.returncode == 0, finished.stderr[:300]


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
    # Without the stub beside the generated file, a UMAT that includes
    # ABA_PARAM.INC has its compile silently skipped and the result reads
    # "not_requested" -- indistinguishable here from a clean compile unless
    # the status is checked, and a skipped check is not a passed one.
    from umat_oti.corpus.cli import _write_aba_param_stub
    _write_aba_param_stub(work)

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
        # Compiled, because "the transformer produced Fortran" and "the
        # transformer produced Fortran that is Fortran" are different claims
        # and only the second is worth reporting. A fixed-form comment whose
        # sixth character is not a space was being stitched into the statement
        # above it, and the run was reported as successful with
        # ``ReadDetF(NOEL,NPT) = REAL(DETF_OTI e coordinate from STATEV_OTI)``
        # in the emitted file. Nothing here re-read the emitted text, so the
        # only thing that catches that class of defect is a compiler.
        (work / "out").mkdir(parents=True, exist_ok=True)
        _write_aba_param_stub(work / "out")
        report, _code = run_transformation(
            contract_path, work / "out", TransformationOptions(compile_generated=True))
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
        compilation = report.get("compilation") or {}
        # Anything but a clean compile counts as not compiled, "skipped" and
        # "not_requested" included: a check that did not run is not a check
        # that passed.
        compiled = (str(compilation.get("status", "")) == "compiled"
                    and int(compilation.get("returncode", 1) or 0) == 0)
        row["compiled"] = "yes" if compiled else "no"
        if not compiled:
            row["compile_error"] = str(
                compilation.get("stderr") or compilation.get("status") or "")[:300]
        baseline_ok, baseline_error = _original_compiles(source, work)
        row["original_compiles"] = "yes" if baseline_ok else "no"
        if compiled:
            row.update(stage="transformed", blocker_kind="none", blocker="")
        elif not baseline_ok:
            # The source did not compile before the transform touched it.
            row.update(stage="source_does_not_compile",
                       blocker_kind="source_does_not_compile",
                       blocker=f"as shipped: {baseline_error}"[:300])
        else:
            row.update(stage="generated_not_compiled",
                       blocker_kind="compile_failed",
                       blocker=row["compile_error"])
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

    # The same suffix list discovery admits, imported rather than repeated:
    # the two lists drifted, and a source cached under .f03 or .f77 was
    # triaged by nothing and appeared in no count at all.
    sources = sorted(p for p in args.cache_dir.rglob("*")
                     if p.is_file() and p.suffix.lower() in set(_FORTRAN_SUFFIXES))
    # A UMAT shipped as .inc or .txt is a real source that this triage cannot
    # read, because the transform takes its form decision from the suffix.
    # Counted and named, so the hole is a number in the summary rather than an
    # absence: a file nothing triages is otherwise indistinguishable from a
    # file that was never cached.
    skipped = sorted(
        str(p.relative_to(args.cache_dir)) for p in args.cache_dir.rglob("*")
        if p.is_file() and p.suffix.lower() not in set(_FORTRAN_SUFFIXES)
        and p.suffix.lower() != ".inp" and _looks_like_a_umat(p))
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        print(f"no cached sources under {args.cache_dir}")
        return 2
    print(f"  {len(sources)} cached sources to triage"
          + (f"; {len(skipped)} declare a UMAT under a suffix this triage "
             f"cannot assign a source form to" if skipped else ""))

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
        "not_triaged_unknown_source_form": skipped,
        "not_triaged_unknown_source_form_count": len(skipped),
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
            "Reaching 'transformed' means the generated Fortran compiles, "
            "not that it was executed or compared against anything. These "
            "sources have no material vector and no loading history, so no "
            "count here is verification evidence. 'source_does_not_compile' "
            "means the source did not compile as shipped, before the "
            "transform touched it; those are held to what they were. The "
            "blocker histogram is the point: it names what the transformer "
            "cannot yet do."),
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
