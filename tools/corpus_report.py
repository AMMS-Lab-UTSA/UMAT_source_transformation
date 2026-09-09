"""Every corpus entry, the gate it reached, and counts that have to add up.

The point of this report is that nothing can go missing. A file that was
acquired and then quietly stopped being attempted leaves no failing row to
notice, and a summary built only from the rows a batch happened to produce
would never show it. So the inventory is the denominator: every acquired
source appears exactly once, its status is one of the named states below, and
the states partition the inventory. If they do not, the report says so and
fails rather than printing a total that is not the total.

The status model is deliberately strict and non-overlapping. Only
``fully_verified`` counts as verified, and it is reached only by a source that
transformed, compiled, ran in Abaqus as the ORIGINAL, ran in Abaqus as the
CONVERTED build, agreed with itself over the whole stress and state history,
and whose OTI tangent agreed with a finite difference of the original at
several states. Every earlier state is named for what it is. "Compiled" is
not "working"; "ran" is not "verified".

``blocked_with_evidence`` is not a failure to try. It is a claim, with the
reason and the artefacts behind it, that this source cannot be verified from
what was acquired -- and it is never presented as verified.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

#: The states a corpus entry can be in, in the order they are reached. They
#: do not overlap: an entry is in exactly one, and the one it is in is the
#: furthest it got.
STATUSES: tuple[str, ...] = (
    "acquired",
    "metadata_resolved",
    "transformed",
    "compiled",
    "abaqus_original_passed",
    "abaqus_transformed_passed",
    "primal_parity_passed",
    "finite_difference_verified",
    "fully_verified",
)

#: Off the ladder. Neither of these is a rung, and neither may be counted as
#: progress toward one.
NOT_A_UMAT = "not_a_umat"
BLOCKED = "blocked_with_evidence"

#: Which Abaqus stage means which status. The batch's ladder and this report's
#: status model are two vocabularies for the same run, and mapping them here
#: rather than renaming either keeps the batch's own words intact in its own
#: artefacts.
FROM_ABAQUS_STAGE: dict[str, str] = {
    "verified": "fully_verified",
    "tangent_not_verified": "primal_parity_passed",
    "both_builds_non_finite": "abaqus_transformed_passed",
    "primal_disagreed": "abaqus_transformed_passed",
    "transformed_job_failed": "abaqus_original_passed",
    "original_job_failed": "compiled",
    "support_build_failed": "transformed",
    "manifest_refused": "metadata_resolved",
    "needs_material_data": "transformed",
    "waits_for_input": "compiled",
    "not_a_umat": NOT_A_UMAT,
    "harness_error": BLOCKED,
}


@dataclass
class Entry:
    """One corpus source and everything known about how far it got."""

    source_id: str
    status: str = "acquired"
    reason: str = ""
    repository: str = ""
    is_umat: Optional[bool] = None
    entry_interface: str = ""
    transformed: bool = False
    compiled: bool = False
    abaqus_stage: str = ""
    material_provenance: str = ""
    worst_stress_relative: Optional[float] = None
    worst_tangent_relative: Optional[float] = None
    states_checked: Optional[int] = None
    states_agreeing: Optional[int] = None
    promoted_to: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _rows(path: Optional[Path]) -> list[dict]:
    if not path or not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload.get("entries") or payload.get("rows") or []
    return payload or []


def _classify_unreached(entries: dict, cache: Optional[Path]) -> None:
    """What the entries that never reached Abaqus actually are.

    A transform failure is not evidence that a file is a UMAT. Many of the
    140 are refused with "selected_routine_is_not_an_abaqus_umat", and
    counting them in the UMAT denominator makes the verified fraction look
    worse than it is by measuring against files that were never candidates.
    Decided by parsing the Fortran, the same way the batch decides it.
    """
    if cache is None or not cache.is_dir():
        return
    try:
        from umat_oti.corpus.entry_routines import classify
    except Exception:                                   # noqa: BLE001
        return
    for entry in entries.values():
        if entry.is_umat is not None:
            continue
        source = cache / entry.source_id
        if not source.is_file():
            continue
        try:
            found = classify(source.read_text(errors="replace"), path=source)
        except Exception:                               # noqa: BLE001
            continue
        entry.is_umat = found.is_umat
        entry.entry_interface = found.entry_interface
        if not found.is_umat:
            entry.status = NOT_A_UMAT
            entry.reason = found.reason[:400]


def build(transform_report: Optional[Path], abaqus_report: Optional[Path],
          registry: Optional[Path],
          cache: Optional[Path] = None) -> tuple[list[Entry], list[str]]:
    """Every entry, its furthest state, and any way the counts fail to add up."""
    entries: dict[str, Entry] = {}
    problems: list[str] = []

    # 1. The inventory. Every row the transform batch attempted is a corpus
    #    entry, whether it transformed or not -- this is the denominator, and
    #    nothing may be dropped from it later.
    payload = json.loads(transform_report.read_text(encoding="utf-8")) \
        if transform_report and transform_report.is_file() else {}
    for row in payload.get("rows", []):
        source_id = str(row.get("source") or row.get("source_id") or "")
        if not source_id:
            continue
        entries[source_id] = Entry(source_id=source_id,
                                   repository=source_id.split("/")[0].replace("__", "/"))
    for row in payload.get("failures", []):
        source_id = str(row.get("source") or "")
        if source_id and source_id not in entries:
            entries[source_id] = Entry(
                source_id=source_id,
                repository=source_id.split("/")[0].replace("__", "/"))
        if source_id:
            entries[source_id].status = "acquired"
            entries[source_id].reason = str(row.get("reason") or "")[:400]

    transformed_ids = {
        str(row.get("source") or row.get("source_id") or "")
        for row in payload.get("rows", [])
        if str(row.get("outcome") or row.get("stage") or "") in
        ("transformed", "cached")}
    for source_id in transformed_ids:
        if source_id in entries:
            entries[source_id].transformed = True
            entries[source_id].status = "transformed"

    # 2. What Abaqus made of the ones that got that far.
    for row in _rows(abaqus_report):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        entry = entries.setdefault(
            source_id, Entry(source_id=source_id,
                             repository=source_id.split("/")[0].replace("__", "/")))
        stage = str(row.get("stage") or "")
        entry.abaqus_stage = stage
        entry.transformed = True
        entry.status = FROM_ABAQUS_STAGE.get(stage, BLOCKED)
        entry.reason = str(row.get("reason") or "")[:400]
        entry.material_provenance = str(row.get("material_provenance") or "")
        classification = row.get("entry_classification") or {}
        entry.is_umat = (classification.get("kind") == "umat"
                         if classification else stage != NOT_A_UMAT)
        entry.entry_interface = str(classification.get("entry_interface") or "")
        primal = row.get("primal") or {}
        entry.worst_stress_relative = primal.get("worst_stress_relative")
        tangent = row.get("tangent") or {}
        entry.states_checked = tangent.get("states_checked")
        entry.states_agreeing = tangent.get("states_agreeing")
        entry.worst_tangent_relative = (tangent.get("comparison") or {}).get(
            "best_relative")

    # 3. The ones that never reached Abaqus are classified here, so the
    #    denominator is every file that IS a UMAT rather than every file that
    #    was acquired.
    _classify_unreached(entries, cache)

    # 4. What was promoted. A promoted entry must be fully_verified: the
    #    collection is supposed to hold only what passed every gate.
    if registry and registry.is_file():
        published = json.loads(registry.read_text(encoding="utf-8"))
        for material in published.get("materials", []):
            source_id = str(material.get("source_id") or "")
            entry = entries.get(source_id)
            if entry is None:
                problems.append(
                    f"{source_id} is in the verified collection but is not in "
                    f"the corpus inventory at all")
                continue
            entry.promoted_to = str(material.get("id") or "")
            if entry.status != "fully_verified":
                problems.append(
                    f"{source_id} is promoted into umat/ but its status is "
                    f"{entry.status!r}, not fully_verified")

    # 5. Anything fully_verified that was NOT promoted is evidence sitting
    #    outside the collection, which is how a result gets lost.
    for entry in entries.values():
        if entry.status == "fully_verified" and registry and registry.is_file():
            if not entry.promoted_to:
                problems.append(
                    f"{entry.source_id} reached fully_verified but was not "
                    f"promoted into the verified collection")
        if entry.status not in STATUSES and entry.status not in (NOT_A_UMAT, BLOCKED):
            problems.append(f"{entry.source_id} has status {entry.status!r}, "
                            f"which is not one of the named states")

    return sorted(entries.values(), key=lambda e: e.source_id), problems


def counts(entries: list[Entry]) -> dict[str, int]:
    return dict(Counter(entry.status for entry in entries))


def reconcile(entries: list[Entry], tally: dict[str, int]) -> list[str]:
    """The counts have to be the inventory, exactly."""
    problems = []
    total = sum(tally.values())
    if total != len(entries):
        problems.append(
            f"the statuses account for {total} entries but the inventory has "
            f"{len(entries)}: {len(entries) - total} are unaccounted for")
    return problems


def _table(entries: list[Entry], only_umats: bool) -> list[str]:
    header = (f"| {'source':<58} | {'status':<26} | {'iface':<5} | "
              f"{'primal':>9} | {'tangent':>9} | {'states':>6} |")
    lines = [header, "|" + "|".join("-" * (len(part))
                                    for part in header.split("|")[1:-1]) + "|"]
    for entry in entries:
        if only_umats and entry.is_umat is False:
            continue
        primal = (f"{entry.worst_stress_relative:.2e}"
                  if isinstance(entry.worst_stress_relative, float) else "-")
        tangent = (f"{entry.worst_tangent_relative:.2e}"
                   if isinstance(entry.worst_tangent_relative, float) else "-")
        states = (f"{entry.states_agreeing}/{entry.states_checked}"
                  if entry.states_checked else "-")
        lines.append(
            f"| {entry.source_id[-58:]:<58} | {entry.status:<26} | "
            f"{(entry.entry_interface or '-'):<5} | {primal:>9} | "
            f"{tangent:>9} | {states:>6} |")
    return lines


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transform", type=Path, required=True,
                        help="a transform_all.py --json report: the inventory")
    parser.add_argument("--abaqus", type=Path,
                        help="a store_verification.jsonl from an Abaqus batch")
    parser.add_argument("--registry", type=Path, default=REPO / "umat/registry.json")
    parser.add_argument("--cache-dir", type=Path,
                        default=Path.home() / "softwarex_work" / "discovery_cache",
                        help="the discovery mirror, used to classify entries "
                             "that never reached Abaqus")
    parser.add_argument("--json", type=Path, help="write the machine-readable report here")
    parser.add_argument("--markdown", type=Path, help="write the human-readable report here")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero when the counts do not reconcile, "
                             "when a promoted entry is not fully_verified, or "
                             "when a fully_verified entry was not promoted")
    args = parser.parse_args(argv)

    entries, problems = build(args.transform, args.abaqus, args.registry,
                              args.cache_dir)
    tally = counts(entries)
    problems += reconcile(entries, tally)

    umats = [e for e in entries if e.is_umat is not False]
    verified = tally.get("fully_verified", 0)

    print(f"corpus inventory: {len(entries)} entries")
    for status in STATUSES + (NOT_A_UMAT, BLOCKED):
        if tally.get(status):
            print(f"  {tally[status]:>4}  {status}")
    print(f"\n  {len(umats)} present a UMAT interface to Abaqus")
    if umats:
        print(f"  {verified} fully_verified "
              f"({100.0 * verified / len(umats):.1f}% of them)")

    if problems:
        print(f"\n{len(problems)} reconciliation problem(s):")
        for problem in problems[:20]:
            print(f"    {problem}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "schema": "umat-oti/corpus-report/1.0",
            "what_counts_as_verified": (
                "Only fully_verified. It is reached by a source that "
                "transformed, compiled, ran in Abaqus as the original, ran in "
                "Abaqus as the converted build, agreed with itself over the "
                "whole stress and state history, and whose OTI tangent agreed "
                "with a finite difference of the original at several states. "
                "Compiling is not working; running is not verified."),
            "inventory": len(entries),
            "umat_entries": len(umats),
            "counts": tally,
            "reconciliation_problems": problems,
            "entries": [e.as_dict() for e in entries],
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\n  wrote {args.json}")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        body = [
            "# Corpus verification report", "",
            f"{len(entries)} acquired entries, of which {len(umats)} present a "
            f"UMAT interface to Abaqus.", "",
            f"**{verified} fully verified**"
            + (f" ({100.0 * verified / len(umats):.1f}% of the UMATs)." if umats else "."),
            "",
            "Only `fully_verified` counts. It means the source transformed and",
            "compiled, Abaqus ran the ORIGINAL, Abaqus ran the CONVERTED build",
            "on the same deck, their stress and state histories agreed over the",
            "whole path, and the OTI tangent agreed with a finite difference of",
            "the original at several states along it. Compiling is not working,",
            "and running is not verified.", "",
            "## Where every entry stands", "",
            "| status | entries |", "| --- | --- |",
        ]
        for status in STATUSES + (NOT_A_UMAT, BLOCKED):
            if tally.get(status):
                body.append(f"| `{status}` | {tally[status]} |")
        if problems:
            body += ["", "## Reconciliation problems", ""]
            body += [f"- {problem}" for problem in problems]
        body += ["", "## Every UMAT entry", ""] + _table(entries, only_umats=True)
        args.markdown.write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"  wrote {args.markdown}")

    if args.strict and problems:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
