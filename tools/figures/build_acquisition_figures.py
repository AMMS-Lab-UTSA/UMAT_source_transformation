#!/usr/bin/env python3
"""Where the corpus came from, and what stopped the sources that stopped.

Two figures. The first follows the corpus from the files that were found to the
sources that were verified, and is explicit that the counts along it are not
the same kind of thing: files, implementations and eligible sources are three
different denominators, and a bar chart that slid between them without saying
so would read as attrition that never happened.

The second says what is actually blocking each source that is not verified,
grouped by cause, because "not verified" is not a finding and "no material
property vector upstream" is.

An earlier exploratory acquisition round is reported separately and labelled as
exploratory. It is not the publication denominator and must never be read as
one.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
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
CORPUS = RESULTS / "corpus" / "corpus_funnel.csv"
DEFAULT_OUT = RESULTS / "figures"

ILLUSTRATIVE = {"m3_j2", "j2"}

#: What each denominator counts. Printed on the figure, because sliding between
#: them silently is the single easiest way to overstate this evidence.
UNITS = {
    "files": "files on disk",
    "implementations": "distinct implementations",
    "sources": "eligible collection sources",
}

#: Blocker causes, in the order they are reported. The patterns match the
#: recorded blocker text; anything unmatched is reported as unclassified rather
#: than folded into a neighbouring cause.
CAUSES: list[tuple[str, str, re.Pattern]] = [
    ("Ambiguous helper dependency", "dependency",
     re.compile(r"differing definitions|ambiguous", re.I)),
    ("No upstream material properties", "material",
     re.compile(r"no material property vector|material.*not available", re.I)),
    ("No loading history", "loading",
     re.compile(r"loading history is available", re.I)),
    # Before the Fortran cause, and the Fortran pattern needs the word
    # boundary: the funnel stage is named "contract_constructed", so a bare
    # "construct" matched it as a substring and filed a source that has no
    # material vector under unsupported syntax.
    ("No established contract", "contract",
     re.compile(r"contract_constructed|declared dimensions", re.I)),
    ("Unsupported Fortran construct", "fortran",
     re.compile(r"unsupported|cannot be transformed|\bconstruct\b", re.I)),
    ("Reference could not be resolved", "reference",
     re.compile(r"reference|noise floor|branch boundary|returned 0 values", re.I)),
    ("Abaqus failed or unavailable", "abaqus",
     re.compile(r"abaqus", re.I)),
]


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _collection() -> tuple[list[dict], list[dict]]:
    every = _rows(MATRIX)
    return every, [r for r in every if r["aliases"] not in ILLUSTRATIVE]


def _classify(text: str) -> str:
    for label, _key, pattern in CAUSES:
        if pattern.search(text or ""):
            return label
    return "Unclassified"


def build_progression(out_dir: Path) -> dict:
    every, rows = _collection()
    registry = json.loads(SUMMARY.read_text(encoding="utf-8"))["identity_registry_counts"]
    offline = [r for r in rows if r["numerical_verification"] == "succeeded"]
    abaqus = [r for r in rows if r["abaqus"].startswith("passed")]
    either = ({r["canonical_source_id"] for r in offline}
              | {r["canonical_source_id"] for r in abaqus})

    stages = [
        ("discovered files", int(registry["raw_discovered_files"]), "files"),
        ("distinct implementations",
         int(registry["content_deduplicated_sources"]), "implementations"),
        ("eligible collection sources", len(rows), "sources"),
        ("verified offline", len(offline), "sources"),
        ("verified in Abaqus", len(abaqus), "sources"),
        ("verified by at least one route", len(either), "sources"),
        ("not verified", len(rows) - len(either), "sources"),
    ]

    use_publication_style()
    fig, axis = figure(3.9)
    positions = np.arange(len(stages))[::-1]
    counts = [count for _, count, _ in stages]
    unit_colour = {"files": PALETTE[5], "implementations": PALETTE[4],
                   "sources": PALETTE[0]}
    colours = [unit_colour[unit] for _, _, unit in stages]
    colours[-1] = PALETTE[6]
    widest = max(counts)
    axis.barh(positions, counts, height=0.62, color=colours, zorder=2)
    for position, (label, count, unit) in zip(positions, stages):
        axis.text(count + widest * 0.015, position, str(count), va="center",
                  ha="left", fontsize=ANNOTATION_PT, fontweight="bold")
    axis.set_yticks(positions)
    axis.set_yticklabels([label for label, _, _ in stages])
    axis.set_xlim(0, widest * 1.18)
    axis.set_xlabel("count (the unit changes down the chart)")
    page_title(fig, "From files acquired to sources verified")

    # Patch handles, not bars. Indexing a BarContainer yields a Rectangle that
    # does not carry the container's label, so the legend read "_nolegend_"
    # three times where the units should have been.
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=unit_colour[unit], label=UNITS[unit])
               for unit in ("files", "implementations", "sources")]
    # On the figure, not the axes. A chart that names its categories on the y
    # axis has its axes box pushed well to the right, so a three-column legend
    # anchored to that box starts a third of the way across the page and runs
    # off the other side. "outside" keeps constrained layout responsible for
    # reserving the room it needs -- below the chart, because the top of the
    # page already belongs to the title and the two were laid on top of each
    # other when both asked for it.
    fig.legend(handles=handles, loc="outside lower left", ncol=2,
               fontsize=ANNOTATION_PT, handlelength=1.2, columnspacing=1.2,
               frameon=False)
    axis.grid(axis="y", visible=False)

    outputs = save(fig, "figure_acquisition_progression", out_dir)
    write_provenance(
        "figure_acquisition_progression", out_dir,
        inputs=[MATRIX, SUMMARY], outputs=outputs,
        question="How does the corpus go from the files that were acquired to "
                 "the sources that were verified, and where does the "
                 "denominator change?",
        filters={
            "excluded": sorted(ILLUSTRATIVE),
            "denominator_changes": {
                "files -> implementations":
                    "content deduplication: a source found at two origins is "
                    "one implementation",
                "implementations -> eligible sources":
                    "property decks carry no entry routine, and the "
                    "illustrative example is reported only in its own section",
                "eligible sources onward":
                    f"all against the same {len(rows)} eligible sources",
            },
            "units": UNITS,
            "not_the_publication_denominator":
                "an earlier exploratory acquisition round is reported "
                "separately and is not this progression",
        },
        rows={label: {"count": count, "unit": unit}
              for label, count, unit in stages},
        command="python tools/figures/build_acquisition_figures.py")
    return {"stages": {l: c for l, c, _ in stages}, "outputs": outputs}


def build_blockers(out_dir: Path) -> dict:
    _, rows = _collection()
    offline = {r["canonical_source_id"] for r in rows
               if r["numerical_verification"] == "succeeded"}
    abaqus = {r["canonical_source_id"] for r in rows
              if r["abaqus"].startswith("passed")}
    unverified = [r for r in rows
                  if r["canonical_source_id"] not in offline | abaqus]

    causes: dict[str, list[str]] = {}
    for row in unverified:
        causes.setdefault(_classify(row["failure_category_and_blocker"]),
                          []).append(row["aliases"])
    ordered = [(label, causes.get(label, [])) for label, _, _ in CAUSES]
    ordered = [(label, names) for label, names in ordered if names]
    if "Unclassified" in causes:
        ordered.append(("Unclassified", causes["Unclassified"]))

    use_publication_style()
    fig, axis = figure(2.6)
    if not ordered:
        axis.text(0.5, 0.5, "every eligible source is verified by at least "
                            "one route", ha="center", va="center",
                  fontsize=ANNOTATION_PT + 1, transform=axis.transAxes)
        axis.axis("off")
    else:
        positions = np.arange(len(ordered))[::-1]
        counts = [len(names) for _, names in ordered]
        axis.barh(positions, counts, height=0.58, color=PALETTE[1], zorder=2)
        for position, (label, names) in zip(positions, ordered):
            axis.text(len(names) + 0.06, position, ", ".join(names),
                      va="center", ha="left", fontsize=ANNOTATION_PT,
                      color="0.35")
        axis.set_yticks(positions)
        axis.set_yticklabels([label for label, _ in ordered])
        axis.set_xlim(0, max(counts) * 3.4)
        axis.set_xticks(range(0, max(counts) + 1))
        axis.set_xlabel(f"eligible sources, of {len(rows)}\n"
                        "not verified by either route")
        axis.grid(axis="y", visible=False)
    page_title(fig, "What is blocking the sources that are not verified")

    outputs = save(fig, "figure_remaining_blockers", out_dir)
    write_provenance(
        "figure_remaining_blockers", out_dir, inputs=[MATRIX], outputs=outputs,
        question="What is actually blocking each eligible source that no route "
                 "has verified?",
        filters={
            "excluded": sorted(ILLUSTRATIVE),
            "denominator": f"{len(rows)} eligible collection sources",
            "classification": "regular expressions over the recorded blocker "
                              "text; anything unmatched is reported as "
                              "unclassified rather than folded into a "
                              "neighbouring cause",
            "causes": [label for label, _, _ in CAUSES],
        },
        rows={label: names for label, names in ordered}
        | {"unverified_total": len(unverified)},
        command="python tools/figures/build_acquisition_figures.py")
    return {"causes": {l: n for l, n in ordered}, "outputs": outputs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in (MATRIX, SUMMARY):
        if not path.is_file():
            print(f"missing evidence: {path}")
            return 1
    progression = build_progression(args.out_dir)
    blockers = build_blockers(args.out_dir)
    print(f"  {progression['outputs']['png']}")
    for label, count in progression["stages"].items():
        print(f"     {label:34s} {count}")
    print(f"  {blockers['outputs']['png']}")
    for label, names in blockers["causes"].items():
        print(f"     {label:34s} {len(names)}  {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
