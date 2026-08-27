#!/usr/bin/env python3
"""How much of the collected UMAT corpus reached numerical verification?

Two figures, because the corpus asks two questions that do not share an answer.

The first is coverage: how many files were found, how many distinct
implementations they turned out to be, and how far those got. It is drawn as a
funnel because that is what it is, but the funnel is honest about the stages
where nothing dropped out: transformation, compilation and primal parity are
equal because no source in the collection failed any of them, and a chart that
hid that by omitting the stages would be claiming attrition that never happened.

The second is route: the corpus was verified two ways, offline and inside
Abaqus, and a source may have taken either, both or neither. That is an overlap
question, not a funnel stage, so it gets its own figure.

The illustrative J2 example is excluded from every count in both.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figure_style import (  # noqa: E402
    ANNOTATION_PT, PALETTE, REPO_ROOT, figure, page_title, save,
    use_publication_style, write_provenance,
)

RESULTS = REPO_ROOT / "paper_results"
MATRIX = RESULTS / "generality" / "generality_matrix.csv"
SUMMARY = RESULTS / "generality" / "generality_summary.json"
IDENTITY = RESULTS / "generality" / "source_identity.csv"
DEFAULT_OUT = RESULTS / "figures"

#: The illustrative example, reported only in the illustrative section.
ILLUSTRATIVE = {"m3_j2", "j2"}


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _collection() -> tuple[list[dict], list[dict]]:
    every = _rows(MATRIX)
    return every, [r for r in every if r["aliases"] not in ILLUSTRATIVE]


def _offline(row: dict) -> bool:
    return row["numerical_verification"] == "succeeded"


def _abaqus(row: dict) -> bool:
    return row["abaqus"].startswith("passed")


def build_funnel(out_dir: Path) -> dict:
    every, rows = _collection()
    registry = json.loads(SUMMARY.read_text(encoding="utf-8"))["identity_registry_counts"]
    discovered = int(registry["raw_discovered_files"])
    deduplicated = int(registry["content_deduplicated_sources"])
    eligible = len(rows)

    stages = [
        ("files discovered", discovered,
         "everything the acquisition returned"),
        ("distinct implementations", deduplicated,
         "after global identity reconciliation"),
        ("in the verification matrix", len(every),
         "property decks carry no entry routine"),
        ("eligible collection sources", eligible,
         "the illustrative example excluded"),
        ("attempted offline", sum(1 for r in rows
                                  if r["transformation"] != "not_attempted"),
         "the rest took the Abaqus route only"),
        ("transformed, compiled and\nprimal-parity checked",
         sum(1 for r in rows if r["primal_parity"] == "succeeded"),
         "no source failed any of these three"),
        ("derivative verified offline", sum(1 for r in rows if _offline(r)),
         "two are withheld by their reference"),
        ("verified in Abaqus", sum(1 for r in rows if _abaqus(r)),
         "a separate route, not a later stage"),
    ]

    use_publication_style()
    fig, axis = figure(4.2)
    positions = np.arange(len(stages))[::-1]
    counts = [count for _, count, _ in stages]
    axis.barh(positions, [discovered] * len(stages), color="#eef0f3",
              height=0.62, zorder=1)
    colours = [PALETTE[5]] * 4 + [PALETTE[0]] * 3 + [PALETTE[2]]
    axis.barh(positions, counts, color=colours, height=0.62, zorder=2)
    # The count and the note each get their own column. Offsetting the note
    # from the end of its bar put it on top of the count whenever the bar was
    # long, which was most of them.
    # The count sits just past its bar. The per-stage notes moved to the
    # caption: at a readable size the longest of them ran past the right edge
    # of the figure and was cut in half.
    for position, (label, count, note) in zip(positions, stages):
        axis.text(count + discovered * 0.015, position, str(count),
                  va="center", ha="left", fontsize=ANNOTATION_PT,
                  fontweight="bold")
    axis.set_yticks(positions)
    axis.set_yticklabels([label for label, _, _ in stages])
    axis.set_xlim(0, discovered * 1.12)
    axis.set_xticks([0, 10, 20, 30, 40, 50])
    axis.set_xlabel(f"UMAT sources, of {discovered} files discovered\n"
                    "(every attempt is kept in the count)")
    page_title(fig, "How far the collected corpus reached")
    axis.grid(axis="y", visible=False)

    outputs = save(fig, "figure_collection_coverage", out_dir)
    write_provenance(
        "figure_collection_coverage", out_dir,
        inputs=[MATRIX, SUMMARY, IDENTITY], outputs=outputs,
        question="How much of the collected UMAT corpus reached numerical "
                 "verification, and where did the rest stop?",
        filters={
            "excluded": sorted(ILLUSTRATIVE),
            "exclusion_reason": "the illustrative example is reported only in "
                                "the illustrative section",
            "denominator": f"{eligible} eligible collection sources; the bars "
                           f"above it count files and implementations, which "
                           f"is why they are larger",
            "two_step_deduction": f"{deduplicated} distinct implementations "
                                  f"minus the property decks that carry no "
                                  f"entry routine gives {len(every)} matrix "
                                  f"rows, minus {len(every) - eligible} "
                                  f"illustrative rows gives {eligible}",
            "equal_stages": "transformation, compilation and primal parity are "
                            "one bar because no source failed any of them; "
                            "drawing three equal bars would imply attrition "
                            "that did not occur",
        },
        rows={label.replace("\n", " "): {"count": count, "note": note}
              for label, count, note in stages},
        command="python tools/figures/build_collection_figures.py")
    return {"stages": {l.replace("\n", " "): c for l, c, _ in stages},
            "outputs": outputs}


def build_routes(out_dir: Path) -> dict:
    _, rows = _collection()
    both = [r for r in rows if _offline(r) and _abaqus(r)]
    offline = [r for r in rows if _offline(r) and not _abaqus(r)]
    abaqus = [r for r in rows if _abaqus(r) and not _offline(r)]
    neither = [r for r in rows if not _offline(r) and not _abaqus(r)]
    groups = [("offline route only", offline), ("both routes", both),
              ("Abaqus route only", abaqus),
              ("neither route", neither)]

    use_publication_style()
    fig, axis = figure(3.1)
    positions = np.arange(len(groups))[::-1]
    counts = [len(entries) for _, entries in groups]
    colours = [PALETTE[0], PALETTE[2], PALETTE[1], PALETTE[6]]
    axis.barh(positions, counts, height=0.6, color=colours, zorder=2)
    total = len(rows)
    for position, count in zip(positions, counts):
        axis.text(count + total * 0.012, position,
                  f"{count}  ({count / total:.0%})", va="center", ha="left",
                  fontsize=ANNOTATION_PT, fontweight="bold")
    axis.set_yticks(positions)
    axis.set_yticklabels([label for label, _ in groups])
    axis.set_xlim(0, total * 0.72)
    axis.set_xlabel(f"unique collection sources (of {total} eligible)")
    page_title(fig, "Which route verified each source")
    axis.grid(axis="y", visible=False)

    outputs = save(fig, "figure_verification_routes", out_dir)
    write_provenance(
        "figure_verification_routes", out_dir, inputs=[MATRIX], outputs=outputs,
        question="Which verification route reached each collection source, and "
                 "how much do the two routes overlap?",
        filters={
            "excluded": sorted(ILLUSTRATIVE),
            "denominator": f"{total} eligible collection sources, the same "
                           "denominator as the coverage figure",
            "offline_route": "numerical_verification == 'succeeded'",
            "abaqus_route": "abaqus starts with 'passed'",
        },
        rows={label: len(entries) for label, entries in groups}
        | {"eligible": total,
           "verified_by_at_least_one": total - len(neither),
           "unverified_with_reasons":
               [r["failure_category_and_blocker"][:120] for r in neither]},
        command="python tools/figures/build_collection_figures.py",
        notes=(f"{total - len(neither)} of {total} sources are verified by at "
               f"least one route. The {len(neither)} that are not keep their "
               "place in the denominator and are shown as their own bar; the "
               "four bars sum to the denominator. This belongs in the caption "
               "rather than on the figure, where at a readable size it "
               "overlapped the first row of bars."))
    return {"groups": {l: len(e) for l, e in groups}, "outputs": outputs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in (MATRIX, SUMMARY):
        if not path.is_file():
            print(f"missing evidence: {path}")
            return 1
    funnel = build_funnel(args.out_dir)
    routes = build_routes(args.out_dir)
    print(f"  {funnel['outputs']['png']}")
    for label, count in funnel["stages"].items():
        print(f"     {label:44s} {count}")
    print(f"  {routes['outputs']['png']}")
    for label, count in routes["groups"].items():
        print(f"     {label:44s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
