#!/usr/bin/env python3
"""Figure 5: what the deduplicated UMAT collection actually reached.

The illustrative J2 example is excluded from every count here, so nothing in
this figure is the model the illustrative section reports on.

Sources are counted after global identity reconciliation: a UMAT reachable both
from the in-repository archive and from a pinned upstream snapshot is one
source with two origins, not two sources. Every attempted source stays in the
denominator, including the ones that failed and the ones that no reference
could adjudicate.

There is no single funnel because there is no single route. Some sources were
verified offline -- transformed, compiled twice, checked for primal parity and
then compared against an independently replayed reference -- and some were
verified inside Abaqus in a paired round. Drawing one chain through both would
show sources dropping out at stages they were never put through.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figure_style import (  # noqa: E402
    FIGURE_WIDTH_IN, LINESTYLES, MARKERS, PALETTE, REPO_ROOT, save,
    use_publication_style, write_provenance,
)

MATRIX = REPO_ROOT / "paper_results" / "generality" / "generality_matrix.csv"
JACOBIANS = (REPO_ROOT / "paper_results" / "internal_jacobians"
             / "table3_internal_jacobians.csv")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

#: The illustrative example, which belongs only to the illustrative section.
ILLUSTRATIVE = {"m3_j2", "j2"}


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _collection(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["aliases"] not in ILLUSTRATIVE]


def _verified_offline(row: dict) -> bool:
    return row["numerical_verification"] == "succeeded"


def _verified_abaqus(row: dict) -> bool:
    return row["abaqus"].startswith("passed")


def panel_offline(axis, rows: list[dict]) -> dict:
    """Gate attainment for the offline route, against the whole collection."""
    total = len(rows)
    gates = [
        ("attempted offline", lambda r: r["transformation"] != "not_attempted"),
        ("transformed", lambda r: r["transformation"] == "succeeded"),
        ("both builds compiled", lambda r: r["compilation"] == "succeeded"),
        ("primal parity", lambda r: r["primal_parity"] == "succeeded"),
        ("reference resolved",
         lambda r: r["numerical_verification"] in ("succeeded", "unresolved")),
        ("derivative verified", _verified_offline),
    ]
    labels = [name for name, _ in gates]
    counts = [sum(1 for r in rows if predicate(r)) for _, predicate in gates]
    positions = np.arange(len(gates))[::-1]

    axis.barh(positions, [total] * len(gates), color="0.92", height=0.66,
              zorder=1)
    axis.barh(positions, counts, color=PALETTE[0], height=0.66, zorder=2)
    for position, count in zip(positions, counts):
        axis.text(count + total * 0.015, position, f"{count}/{total}",
                  va="center", ha="left", fontsize=8.5)
    axis.set_yticks(positions)
    axis.set_yticklabels(labels)
    axis.set_xlim(0, total * 1.16)
    axis.set_xlabel(f"unique sources (denominator {total}, every attempt kept)")
    axis.set_title("(a) Offline route: transform, build twice, compare")
    axis.grid(axis="y", visible=False)
    return dict(zip(labels, counts))


def panel_routes(axis, rows: list[dict]) -> dict:
    """How many sources each route verified, and how much they overlap."""
    both = [r for r in rows if _verified_offline(r) and _verified_abaqus(r)]
    offline = [r for r in rows if _verified_offline(r) and not _verified_abaqus(r)]
    abaqus = [r for r in rows if _verified_abaqus(r) and not _verified_offline(r)]
    neither = [r for r in rows if not _verified_offline(r)
               and not _verified_abaqus(r)]
    groups = [("offline only", len(offline)), ("both routes", len(both)),
              ("Abaqus only", len(abaqus)),
              ("neither", len(neither))]

    # Horizontal, so the group names sit on the axis instead of being rotated
    # or overrun by their neighbours.
    positions = np.arange(len(groups))[::-1]
    widths = [count for _, count in groups]
    bars = axis.barh(positions, widths, height=0.62,
                     color=[PALETTE[0], PALETTE[2], PALETTE[1], PALETTE[6]],
                     hatch=["", "//", "..", "xx"], edgecolor="white",
                     linewidth=0.5, zorder=2)
    for bar, count in zip(bars, widths):
        axis.text(count + max(widths) * 0.03,
                  bar.get_y() + bar.get_height() / 2, str(count),
                  va="center", ha="left", fontsize=9)
    axis.set_yticks(positions)
    axis.set_yticklabels([label for label, _ in groups], fontsize=9)
    axis.set_xlim(0, max(widths) * 1.2)
    axis.set_xlabel("unique sources")
    axis.set_title(f"(b) Verified route: {len(rows) - len(neither)} of "
                   f"{len(rows)} by one or both")
    axis.grid(axis="y", visible=False)
    return {label: count for label, count in groups}


def panel_jacobians(axis, rows: list[dict]) -> dict:
    """What the extracted internal Jacobians found about the hand-coded ones.

    One point per source, deduplicated on canonical identity: the same UMAT
    reached from two origins is one implementation, and plotting it twice would
    double a finding.
    """
    seen, points = set(), []
    for row in rows:
        identity = row["canonical_source_id"]
        if identity in seen or row["verdict"] != "verified":
            continue
        seen.add(identity)
        points.append((row["model"], float(row["oti_vs_fd_relative"]),
                       float(row["hand_coded_vs_fd_relative"])))
    points.sort(key=lambda p: p[2])

    positions = np.arange(len(points))
    # Where the two agree the markers coincide, so the outer one has to be
    # large enough for the inner one to sit inside it. Equal sizes hid the OTI
    # marker completely on the four sources whose hand-coded Jacobian is right.
    axis.scatter([p[1] for p in points], positions, s=90, marker=MARKERS[0],
                 facecolor="none", edgecolor=PALETTE[0], linewidth=1.3,
                 label="extracted by OTI", zorder=3)
    axis.scatter([p[2] for p in points], positions, s=26, marker=MARKERS[1],
                 facecolor="none", edgecolor=PALETTE[1], linewidth=1.3,
                 label="hand-coded in the source", zorder=4)
    for position, (_name, oti, hand) in zip(positions, points):
        axis.plot([min(oti, hand), max(oti, hand)], [position, position],
                  color="0.75", linewidth=0.9, zorder=2)

    axis.set_xscale("log")
    axis.set_yticks(positions)
    axis.set_yticklabels([p[0] for p in points], fontsize=8)
    axis.set_xlabel("relative difference from the reference (-)")
    axis.set_title("(c) Internal constitutive Jacobians")
    # Clear a row at the bottom so the legend does not sit on the lowest source.
    axis.set_ylim(-1.9, len(points) - 0.3)
    axis.legend(loc="lower left", fontsize=8, framealpha=0.9, frameon=True,
                facecolor="white", edgecolor="none")
    axis.grid(axis="y", visible=False)

    drifted = [p for p in points if p[2] > 1e-6]
    for position, (_name, _oti, hand) in zip(positions, points):
        if hand > 1e-6:
            axis.annotate(f"{hand * 100:.3g}%", xy=(hand, position),
                          xytext=(0, 7), textcoords="offset points",
                          ha="center", fontsize=8, color=PALETTE[1])
    return {"unique_sources": len(points),
            "hand_coded_beyond_1e-6": [p[0] for p in drifted]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in (MATRIX, JACOBIANS):
        if not path.is_file():
            print(f"missing evidence: {path}")
            return 1

    every = _read(MATRIX)
    rows = _collection(every)
    jacobians = _read(JACOBIANS)

    use_publication_style()
    figure = plt.figure(figsize=(FIGURE_WIDTH_IN, FIGURE_WIDTH_IN * 0.86))
    grid = figure.add_gridspec(2, 2, height_ratios=[0.85, 1.0],
                               width_ratios=[0.88, 1.12])
    counts = {
        "offline_route": panel_offline(figure.add_subplot(grid[0, :]), rows),
        "by_route": panel_routes(figure.add_subplot(grid[1, 0]), rows),
        "internal_jacobians": panel_jacobians(figure.add_subplot(grid[1, 1]),
                                              jacobians),
    }
    outputs = save(figure, "figure5_collection_verification", args.out_dir)

    write_provenance(
        "figure5_collection_verification", args.out_dir,
        inputs=[MATRIX, JACOBIANS], outputs=outputs,
        filters={
            "excluded": sorted(ILLUSTRATIVE),
            "exclusion_reason": ("the illustrative example is reported only in "
                                 "the illustrative section, and appears in no "
                                 "count, table or panel here"),
            "deduplication": ("one row per canonical source identity: "
                              "normalised content for a single file, resolved "
                              "routine closure for a multi-file source"),
            "panel_c": "verdict == verified, deduplicated on canonical_source_id",
        },
        rows={"matrix_rows": len(every), "collection_rows": len(rows),
              "excluded_rows": len(every) - len(rows),
              "jacobian_validation_events": len(jacobians), **counts},
        command="python tools/figures/build_figure5_collection.py",
        notes=("Panel (a) counts against the whole collection, so a source "
               "never put through the offline route shows as not attempted "
               "rather than as a failure. Panel (b) is what stops that from "
               "understating the evidence."))
    print(f"  {outputs['png']}  ({outputs['width_inches']}x"
          f"{outputs['height_inches']} in)")
    print(f"  {outputs['pdf']}")
    print(f"  collection {len(rows)} sources ({len(every) - len(rows)} "
          f"illustrative excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
