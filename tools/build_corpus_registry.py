#!/usr/bin/env python3
"""One record per downloaded artefact, and a report a person can read.

The registry is the denominator. Every file the acquisition brought back is in
it exactly once, whether it transformed, whether it ran, whether it is even a
UMAT -- because a source that quietly stopped being attempted leaves no failing
row to notice, and a summary built from the rows a batch happened to produce
would never show it.

Each record carries a terminal state and who has to move next. Four of them are
final and external: nobody published the constants, the file is not a UMAT, it
does not compile as published, a module it needs was never published beside it.
One is final and verified. The rest are unfinished and OURS, named as precisely
as the evidence allows so the cluster a failure belongs to is visible -- because
that is what decides which fix is worth making, and because calling any of them
a terminal state would be relabelling our own limitation as somebody else's.

    tools/build_corpus_registry.py \
        --transform <run>/transform_batch.json \
        --abaqus <run>/results/store_verification.jsonl \
        --json paper_results/corpus/corpus_registry.json \
        --csv  paper_results/corpus/corpus_registry.csv \
        --markdown paper_results/corpus/CORPUS_VERIFICATION.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.abaqus.terminal_states import (EXTERNAL, FULLY_VERIFIED,  # noqa: E402
                                             INTERNAL, WAITS_FOR_INPUT,
                                             from_stage, from_transform_failure,
                                             kind_of)

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO.parent / "discovery_cache")


@dataclass
class Record:
    """One acquired artefact, and everything established about it."""

    source_id: str
    repository: str = ""
    sha256: str = ""
    bytes: Optional[int] = None
    source_form: str = ""
    is_umat: Optional[bool] = None
    entry_interface: str = ""
    terminal_state: str = "not_attempted"
    kind: str = "internal"
    reason: str = ""
    stage: str = ""
    transformed: bool = False
    compiled: Optional[bool] = None
    ntens: Optional[int] = None
    ntens_provenance: str = ""
    element_type: str = ""
    formulation: str = ""
    kinematics: str = ""
    deck: str = ""
    material_provenance: str = ""
    props_count: Optional[int] = None
    nstatv: Optional[int] = None
    activated: Optional[bool] = None
    activation_amplitude: Optional[float] = None
    time_dependent: Optional[bool] = None
    response_character: str = ""
    worst_stress_relative: Optional[float] = None
    worst_state_relative: Optional[float] = None
    primal_increments: Optional[int] = None
    precision_control: Optional[bool] = None
    tangent_states_checked: Optional[int] = None
    tangent_states_agreeing: Optional[int] = None
    worst_tangent_relative: Optional[float] = None
    tangent_plateau: str = ""
    missing_companions: str = ""
    compile_defect: str = ""
    key: str = ""
    seconds: Optional[float] = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _rows(path: Optional[Path]) -> list:
    """Every record, one per entry: the last one written.

    The results file is append-only, so a resumed run that re-runs an entry
    appends a second record rather than editing the first. Keeping both would
    put a superseded verdict in the registry beside the one that replaced it.
    """
    if not path or not Path(path).is_file():
        return []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if Path(path).suffix == ".jsonl":
        latest: dict = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            latest[str(record.get("key") or record.get("source") or line)] = record
        return list(latest.values())
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload.get("entries") or payload.get("rows") or []
    return payload or []


def _classify_file(source: Path) -> tuple:
    """Is this a UMAT, and does it compile as published?

    Both questions are asked of the file the author wrote, so a "no" is about
    the corpus and not about this pipeline.
    """
    try:
        from umat_oti.corpus.entry_routines import classify
        found = classify(source.read_text(errors="replace"), path=source)
        return found.is_umat, found.entry_interface, found.reason
    except Exception:                              # noqa: BLE001
        return None, "", ""


def build(transform_report: Optional[Path], abaqus_report: Optional[Path],
          cache: Optional[Path], *, compile_check: bool = False) -> list:
    """Every acquired artefact, its terminal state, and the evidence for it."""
    records: dict[str, Record] = {}

    payload = json.loads(transform_report.read_text(encoding="utf-8")) \
        if transform_report and Path(transform_report).is_file() else {}
    for row in payload.get("rows", []):
        source_id = str(row.get("source") or row.get("source_id") or "")
        if not source_id:
            continue
        record = Record(source_id=source_id,
                        repository=source_id.split("/")[0].replace("__", "/", 1),
                        ntens=row.get("ntens"),
                        ntens_provenance=str(row.get("ntens_provenance") or ""),
                        kinematics=str(row.get("kinematics") or ""),
                        key=str(row.get("key") or ""))
        outcome = str(row.get("outcome") or "")
        record.transformed = outcome in ("transformed", "cached")
        record.compiled = row.get("compiled")
        if not record.transformed:
            record.reason = str(row.get("reason") or "")[:500]
        records[source_id] = record
    for row in payload.get("failures", []):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        record = records.setdefault(
            source_id, Record(source_id=source_id,
                              repository=source_id.split("/")[0].replace("__", "/", 1)))
        record.transformed = False
        record.reason = str(row.get("reason") or "")[:500]

    # What the file itself is, asked of the file rather than of the transform.
    if cache and Path(cache).is_dir():
        from umat_oti.abaqus.companions import repository_files, resolve
        from umat_oti.fortran.normalize import detect_source_form
        from umat_oti.store.transform_store import file_digest

        for record in records.values():
            source = Path(cache) / record.source_id
            if not source.is_file():
                continue
            text = source.read_text(errors="replace")
            record.bytes = len(text.encode())
            record.sha256 = file_digest(source)
            record.source_form = detect_source_form(source, text)
            is_umat, interface, _why = _classify_file(source)
            record.is_umat, record.entry_interface = is_umat, interface
            found = resolve(source, repository_files(source, cache))
            if not found.complete:
                record.missing_companions = "; ".join(
                    [f"module {n}" for n in found.missing_modules]
                    + [f"include {n}" for n in found.missing_includes])[:300]

    # What Abaqus made of the ones that got that far. This overrides the
    # transform's verdict, because it is later and it is about a real run.
    for row in _rows(abaqus_report):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        record = records.setdefault(
            source_id, Record(source_id=source_id,
                              repository=source_id.split("/")[0].replace("__", "/", 1)))
        record.key = str(row.get("key") or record.key)
        record.stage = str(row.get("stage") or "")
        verdict = from_stage(record.stage, str(row.get("reason") or "")[:500])
        record.terminal_state, record.kind = verdict.state, verdict.kind
        record.reason = verdict.reason
        record.transformed = True
        record.element_type = str(row.get("element_type") or "")
        record.ntens = row.get("ntens", record.ntens)
        record.kinematics = str(row.get("kinematics") or record.kinematics)
        record.deck = str(row.get("deck") or "")
        record.material_provenance = str(row.get("material_provenance") or "")
        record.props_count = row.get("props_count")
        record.nstatv = row.get("nstatv")
        formulation = row.get("formulation") or {}
        record.formulation = str(formulation.get("family") or "")
        discovery = row.get("discovery") or {}
        record.activation_amplitude = discovery.get("chosen_amplitude")
        record.activated = (discovery.get("outcome") == "activated"
                            if discovery.get("ran") else None)
        record.time_dependent = (discovery.get("time") or {}).get("time_dependent")
        primal = row.get("primal") or {}
        record.worst_stress_relative = primal.get("worst_stress_relative")
        record.worst_state_relative = primal.get("worst_state_relative")
        record.primal_increments = primal.get("increments")
        record.precision_control = (row.get("precision_control") or {}).get("agrees")
        tangent = row.get("tangent") or {}
        record.tangent_states_checked = tangent.get("states_checked")
        record.tangent_states_agreeing = tangent.get("states_agreeing")
        record.response_character = str(tangent.get("response_character") or "")
        comparison = tangent.get("comparison") or {}
        record.worst_tangent_relative = comparison.get("best_relative")
        stable = comparison.get("stable_range") or []
        record.tangent_plateau = (f"{min(stable):g}..{max(stable):g}"
                                  if len(stable) == 2 else "")
        classification = row.get("entry_classification") or {}
        if classification:
            record.is_umat = classification.get("kind") == "umat"
            record.entry_interface = str(
                classification.get("entry_interface") or record.entry_interface)
        diagnosis = row.get("original_diagnosis") or {}
        if diagnosis:
            record.compile_defect = "; ".join(
                (diagnosis.get("compile") or {}).get("defects") or [])[:300]
        record.seconds = row.get("seconds")

    # Everything Abaqus never saw. Its terminal state comes from what the file
    # is: a transform refusal is ours unless the file is one nobody could have
    # transformed, and the compile check is what tells those apart.
    for record in records.values():
        if record.stage:
            continue
        if record.is_umat is False:
            record.terminal_state, record.kind = "not_a_umat", "external"
            continue
        if record.transformed:
            # It converted and the batch has not reached it. Not a verdict --
            # an absence of one, and an absence that has to stay visible.
            record.terminal_state, record.kind = "not_attempted", "internal"
            continue
        compiles = None
        if compile_check and cache and (Path(cache) / record.source_id).is_file():
            compiles = _compiles(Path(cache) / record.source_id, record)
        verdict = from_transform_failure(
            record.reason, compiles=compiles,
            companions_missing=bool(record.missing_companions),
            is_umat=_is_a_umat(cache, record.source_id))
        record.terminal_state, record.kind = verdict.state, verdict.kind
    return sorted(records.values(), key=lambda r: r.source_id)


def _is_a_umat(cache: Optional[Path], source_id: str) -> Optional[bool]:
    """What this file presents to Abaqus, by parsing rather than by name.

    Asked of sources the transform refused, because a file whose entry point
    is a UEL was never this transformer's to convert and its refusal says
    nothing about the transformer.
    """
    if not cache or not source_id:
        return None
    path = Path(cache) / source_id
    if not path.is_file():
        return None
    try:
        from umat_oti.corpus.entry_routines import classify
        return bool(classify(path.read_text(errors="replace"), path=path).is_umat)
    except Exception:                              # noqa: BLE001 - advisory
        return None


def _compiles(source: Path, record: Record) -> Optional[bool]:
    """Does the author's own file build with Abaqus's compile line?"""
    try:
        from umat_oti.abaqus.companions import repository_files, resolve
        from umat_oti.abaqus.support import compile_one
        import tempfile

        found = resolve(source, repository_files(source, source.parents[-2]))
        with tempfile.TemporaryDirectory() as scratch:
            check = compile_one(source, Path(scratch), form=record.source_form,
                                extra_sources=found.order)
        if check.ok:
            return True
        if check.missing_dependencies:
            record.missing_companions = (record.missing_companions
                                         or "; ".join(check.missing_dependencies))
            return None
        record.compile_defect = "; ".join(check.defects)[:300]
        # False only when the compiler rejected the TEXT. Anything else is a
        # compile that did not settle the question, and None says so.
        return False if check.source_is_malformed else None
    except Exception:                              # noqa: BLE001
        return None


def summarise(records: list) -> dict:
    umats = [r for r in records if r.is_umat is not False]
    verified = [r for r in records if r.terminal_state == FULLY_VERIFIED]
    by_state = Counter(r.terminal_state for r in records)
    by_kind = Counter(r.kind for r in records)
    clusters = defaultdict(list)
    for record in records:
        if record.kind == "internal":
            clusters[record.terminal_state].append(record.source_id)
    return {
        "acquired": len(records),
        "genuine_umats": len(umats),
        "fully_verified": len(verified),
        "by_terminal_state": dict(sorted(by_state.items(), key=lambda kv: -kv[1])),
        "by_kind": dict(by_kind),
        "external_total": sum(by_state[s] for s in EXTERNAL) + by_state[WAITS_FOR_INPUT],
        "internal_total": sum(by_state[s] for s in INTERNAL),
        "internal_clusters": {state: len(names)
                              for state, names in sorted(
                                  clusters.items(), key=lambda kv: -len(kv[1]))},
        "verified_sources": [r.source_id for r in verified],
    }


def markdown(records: list, summary: dict) -> str:
    lines = [
        "# Corpus verification",
        "",
        f"{summary['acquired']} acquired artefacts, of which "
        f"{summary['genuine_umats']} present a UMAT interface to Abaqus.",
        "",
        f"**{summary['fully_verified']} fully verified.**",
        "",
        "`fully_verified` means the source transformed and compiled, Abaqus ran",
        "the ORIGINAL, Abaqus ran the CONVERTED build on the same deck, their",
        "stress and state histories agreed over the whole path, and the OTI",
        "tangent agreed with a finite difference of the original at several",
        "states along it. Compiling is not working and running is not verified.",
        "",
        "## Finished, and unfinished",
        "",
        "| | entries |",
        "| --- | ---: |",
        f"| verified | {summary['by_kind'].get('verified', 0)} |",
        f"| blocked outside this repository | {summary['external_total']} |",
        f"| work remaining here | {summary['internal_total']} |",
        "",
        "## Every terminal state",
        "",
        "| terminal state | whose move | entries |",
        "| --- | --- | ---: |",
    ]
    for state, count in summary["by_terminal_state"].items():
        lines.append(f"| `{state}` | {kind_of(state)} | {count} |")
    lines += ["", "## What is left here, by cluster", "",
              "Each of these is a limitation of this pipeline, not of the "
              "corpus. They are listed largest first because that is the "
              "order they are worth fixing in.", "",
              "| cluster | entries |", "| --- | ---: |"]
    for state, count in summary["internal_clusters"].items():
        lines.append(f"| `{state}` | {count} |")

    lines += ["", "## Every entry", "",
              "| source | terminal state | element | primal | tangent | states |",
              "| --- | --- | --- | ---: | ---: | --- |"]
    for record in records:
        primal = ("" if record.worst_stress_relative is None
                  else f"{record.worst_stress_relative:.2e}")
        tangent = ("" if record.worst_tangent_relative is None
                   else f"{record.worst_tangent_relative:.2e}")
        states = ("" if record.tangent_states_checked is None
                  else f"{record.tangent_states_agreeing}/{record.tangent_states_checked}")
        lines.append(
            f"| {record.source_id[-70:]} | `{record.terminal_state}` | "
            f"{record.element_type} | {primal} | {tangent} | {states} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transform", type=Path, required=True)
    parser.add_argument("--abaqus", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--json", dest="json_path", type=Path,
                        default=REPO / "paper_results/corpus/corpus_registry.json")
    parser.add_argument("--csv", dest="csv_path", type=Path,
                        default=REPO / "paper_results/corpus/corpus_registry.csv")
    parser.add_argument("--markdown", type=Path,
                        default=REPO / "paper_results/corpus/CORPUS_VERIFICATION.md")
    parser.add_argument("--compile-check", action="store_true",
                        help="compile every unreached source with Abaqus's own "
                             "compile line, so a transform refusal on a file "
                             "that does not build is recorded as the file's "
                             "problem rather than as ours")
    args = parser.parse_args(argv)

    records = build(args.transform, args.abaqus, args.cache_dir,
                    compile_check=args.compile_check)
    summary = summarise(records)

    payload = {
        "schema": "umat-oti/corpus-registry/1",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "what_counts_as_verified": (
            "only fully_verified, and it is reached by a source that "
            "transformed, compiled, ran in Abaqus as the original, ran as the "
            "converted build on the same deck, agreed with itself over the "
            "whole stress and state history, and whose OTI tangent agreed with "
            "a finite difference of the original at several smooth states"),
        "terminal_states": {
            "verified": [FULLY_VERIFIED],
            "external": list(EXTERNAL) + [WAITS_FOR_INPUT],
            "internal": list(INTERNAL),
        },
        "summary": summary,
        "records": [r.as_dict() for r in records],
    }
    for path, text in ((args.json_path, json.dumps(payload, indent=1) + "\n"),
                       (args.markdown, markdown(records, summary))):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")
    with open(args.csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].as_dict())
                                if records else ["source_id"])
        writer.writeheader()
        for record in records:
            writer.writerow(record.as_dict())

    print(f"  {summary['acquired']} artefacts, {summary['genuine_umats']} UMATs, "
          f"{summary['fully_verified']} fully verified")
    for state, count in summary["by_terminal_state"].items():
        print(f"    {state:<34} {count:>4}  ({kind_of(state)})")
    print(f"  wrote {args.json_path}")
    print(f"  wrote {args.csv_path}")
    print(f"  wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
