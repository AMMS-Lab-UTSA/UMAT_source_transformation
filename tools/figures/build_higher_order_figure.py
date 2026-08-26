#!/usr/bin/env python3
"""Does the agreement hold as the derivative order rises?

One panel, one question. Each point is one resolved comparison of a stress
derivative against an independent 80-digit reference, grouped by derivative
order and by whether the differentiation directions are repeated or mixed.
Those are the two things that could plausibly degrade with order, so they are
the two things the grouping separates.

Only comparisons the reference can adjudicate are drawn. A row whose absolute
difference sits below its absolute tolerance has no meaningful relative error
-- both sides are at the rounding floor -- and drawing one would suggest a
measurement where there is none. Those rows are counted in the annotation.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figure_style import (  # noqa: E402
    ANNOTATION_PT, MARKERS, PALETTE, REPO_ROOT, figure, save,
    use_publication_style, write_provenance,
)

# The adjudicated study, not the fixed-step comparison. The fixed-step file
# calls a row informative only when its absolute error exceeds an absolute
# tolerance, which drops comparisons that are plainly informative: a derivative
# of 2.8e7 agreeing to 6.7e-14 was excluded because 1.9e-6 is a small number.
# This file carries the classification the published higher-order outcome is
# built from, and it separates repeated from mixed directions already.
ROWS = (REPO_ROOT / "paper_results" / "higher_order_convergence" / "j2"
        / "convergence_rows.csv")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

#: The two direction classes, as the evidence itself labels them. A repeated
#: direction exercises a different path in the algebra from a mixed one, so
#: they are kept apart rather than pooled.
CLASSES = ("repeated", "mixed")


def _read() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _class(row: dict) -> str:
    return row["direction_pattern"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not ROWS.is_file():
        print(f"missing evidence: {ROWS}")
        return 1

    rows = _read()
    # The study's own classification. A "resolved" row is one the reference can
    # adjudicate; an "expected zero" row is one the reference independently
    # shows to be zero, where a relative error is not a measurement.
    resolved = [r for r in rows if r["reference_classification"] == "resolved"]
    expected_zero = [r for r in rows
                     if r["reference_classification"].startswith("expected_zero")]
    unresolved = [r for r in rows
                  if r["reference_classification"] == "reference_unresolved"]
    failed = [r for r in rows if r["agrees_with_reference"] == "False"]
    # The comparator on a relative-error axis is how well the reference pins
    # the value down, not a tolerance: "agreement_tolerance" in this file is
    # absolute, in the derivative's own units, so a single horizontal line
    # drawn from it landed at 1e+08 on a dimensionless axis.
    resolution = max(float(r["plateau_relative_uncertainty"]) for r in resolved
                     if r["plateau_relative_uncertainty"])

    orders = sorted({int(r["order"]) for r in rows})
    classes = list(CLASSES)
    groups: dict[tuple[int, str], list[float]] = {}
    counts: dict[str, dict] = {}
    for order in orders:
        for kind in classes:
            selected = [r for r in resolved
                        if int(r["order"]) == order and _class(r) == kind]
            groups[(order, kind)] = [float(r["relative_error"]) for r in selected
                                     if r["relative_error"]]
            everything = [r for r in rows
                          if int(r["order"]) == order and _class(r) == kind]
            counts[f"order {order}, {kind}"] = {
                "comparisons": len(everything), "resolved": len(selected),
                "independently_shown_to_be_zero":
                    sum(1 for r in everything
                        if r["reference_classification"].startswith("expected_zero"))}

    use_publication_style()
    fig, axis = figure(3.4)

    # The legend entry goes on the first group of each class that actually has
    # points. Attaching it to the first order instead left the legend empty
    # whenever that order had nothing the reference could resolve.
    labelled: set[str] = set()
    empty_orders: set[int] = set()
    positions, labels = [], []
    for index, order in enumerate(orders):
        for offset, kind in enumerate(classes):
            position = index + (offset - 0.5) * 0.32
            values = groups[(order, kind)]
            positions.append(position)
            labels.append(kind)
            if not values:
                empty_orders.add(order)
                continue
            jitter = np.linspace(-0.06, 0.06, len(values))
            axis.scatter(position + jitter, values, s=30,
                         marker=MARKERS[offset], facecolor="none",
                         edgecolor=PALETTE[offset], linewidth=1.2, zorder=3,
                         label=(None if kind in labelled
                                else f"{kind} directions"))
            labelled.add(kind)
            axis.plot([position - 0.13, position + 0.13],
                      [max(values)] * 2, color=PALETTE[offset], linewidth=1.6,
                      zorder=4)

    axis.set_yscale("log")
    everything = [v for values in groups.values() for v in values]
    bottom = min(everything) / 4.0
    axis.set_ylim(bottom, resolution * 12.0)
    # No shading: every point lies below the line, so a band drawn under it
    # covers the whole panel and stops meaning anything. The line and its
    # sentence carry it.
    axis.axhline(resolution, color="0.4", linestyle=(0, (5, 3)), linewidth=1.1,
                 zorder=1)
    axis.annotate(f"the reference resolves these values only to {resolution:.0e};\n"
                  "everything below this line is indistinguishable from it",
                  xy=(0.985, resolution), xycoords=("axes fraction", "data"),
                  xytext=(0, -6), textcoords="offset points", ha="right",
                  va="top", fontsize=ANNOTATION_PT, color="0.3")
    # One note per empty order, centred on it, rather than one per empty class:
    # two identical labels a third of a tick apart ran into each other.
    for order in sorted(empty_orders):
        axis.annotate(
            f"no comparison at order {order}\nexceeds its absolute tolerance",
            xy=(orders.index(order), 0.30), xycoords=("data", "axes fraction"),
            ha="center", va="center", fontsize=ANNOTATION_PT, color="0.45")
    axis.set_xticks(range(len(orders)))
    axis.set_xticklabels([f"order {o}" for o in orders])
    axis.set_xlim(-0.55, len(orders) - 0.45)
    axis.set_xlabel("derivative order of the stress with respect to the "
                    "strain increment")
    axis.set_ylabel("relative difference from the\n80-digit reference "
                    "(dimensionless)")
    axis.set_title("Higher-order stress derivatives against an independent "
                   "reference", loc="left")
    # Below the resolution line, which spans the full width at the top.
    axis.legend(loc="upper left", bbox_to_anchor=(0.01, 0.80),
                handletextpad=0.4, borderpad=0.3)
    axis.grid(axis="x", visible=False)

    outputs = save(fig, "figure_higher_order_verification", args.out_dir)
    worst = max((float(r["relative_error"]) for r in resolved
                 if r["relative_error"]), default=None)
    write_provenance(
        "figure_higher_order_verification", args.out_dir, inputs=[ROWS],
        outputs=outputs,
        question="Does the agreement with an independent reference hold as the "
                 "derivative order rises, and does it depend on whether the "
                 "differentiation directions repeat?",
        filters={
            "model": "controlled_j2_actual_umat (the illustrative example)",
            "plotted": "comparisons whose absolute difference exceeds their "
                       "absolute tolerance, so a relative error is meaningful",
            "not_plotted": f"{len(expected_zero)} comparisons the reference "
                           "independently shows to be zero, and "
                           f"{len(unresolved)} the reference cannot resolve",
            "direction_classes": "as labelled by the study's own "
                                 "direction_pattern column",
            "reference_method": "independent tensor-product finite differences "
                                "of umat_oti.validation.j2_reference evaluated "
                                "at 80 decimal digits",
            "error_definition": "|generated - reference| / "
                                "max(|generated|, |reference|)",
            "shaded_band": "the reference's own relative resolution, the "
                           "widest plateau_relative_uncertainty over the "
                           "resolved rows; below it the reference cannot "
                           "distinguish the two values",
            "axis_scale": "logarithmic in the error; no zero is placed on it",
        },
        rows={"comparisons": len(rows), "resolved": len(resolved),
              "independently_shown_to_be_zero": len(expected_zero),
              "reference_unresolved": len(unresolved), "disagreeing": len(failed),
              "worst_resolved_relative_error": worst,
              "reference_relative_resolution": resolution, "by_group": counts},
        command="python tools/figures/build_higher_order_figure.py")
    print(f"  {outputs['png']}  ({outputs['width_inches']} x "
          f"{outputs['height_inches']} in)")
    print(f"  {len(rows)} comparisons, {len(resolved)} resolved, "
          f"{len(expected_zero)} independently zero, {len(unresolved)} "
          f"unresolved, {len(failed)} disagreeing, worst {worst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
