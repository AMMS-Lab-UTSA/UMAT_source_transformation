#!/usr/bin/env python3
"""Stress derivatives of order two and above, with the 80-digit reference over them.

One panel per derivative order, because the orders are separated by six decades
and cannot share a scale. Inside a panel, colour is the stress component and
line style is the direction pattern; the generated derivative is a line and the
independent reference is drawn as open markers on top of it.

The whole path is plotted, not only the increments where the derivative is
non-zero. On the elastic branch a linear response makes every derivative of
order two and above vanish, and the study establishes those zeros on evidence
independent of the OTI result -- so the flat run before yield is a result, not
missing data, and the reader can see where the derivatives switch on.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figure_style import (  # noqa: E402
    ANNOTATION_PT, REPO_ROOT, save, use_publication_style, write_provenance,
)
from overlay_style import (  # noqa: E402
    DASHES, GENERATED_KW, REFERENCE_KW, draw_overlay, series_colour,
)

ROWS = (REPO_ROOT / "paper_results" / "higher_order_convergence" / "j2"
        / "convergence_rows.csv")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

ORDER_TITLE = {2: r"order 2:  $\partial^{2}\sigma$",
               3: r"order 3:  $\partial^{3}\sigma$",
               4: r"order 4:  $\partial^{4}\sigma$"}
STRESS = {1: r"$\sigma_{11}$", 2: r"$\sigma_{22}$", 3: r"$\sigma_{33}$",
          4: r"$\sigma_{12}$", 5: r"$\sigma_{13}$", 6: r"$\sigma_{23}$"}
SUBSCRIPT = {"1": r"\varepsilon_{11}", "2": r"\varepsilon_{22}",
             "3": r"\varepsilon_{33}", "4": r"\gamma_{12}",
             "5": r"\gamma_{13}", "6": r"\gamma_{23}"}


def _read() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


#: Each order supplies two direction patterns: one that differentiates the
#: same strain component repeatedly, and one that mixes two components. That
#: distinction is the same at every order, so it gets the same line style in
#: every panel -- indexing the raw ``1|1|2|2`` strings instead would give the
#: same idea a different style in each panel and three legends to reconcile.
KINDS = ("repeated", "mixed")
KIND_LABEL = {
    "repeated": r"repeated, $\partial^{n}\!/\partial\varepsilon_{11}^{n}$",
    "mixed": r"mixed, also in $\varepsilon_{22}$",
}


def _kind(directions: str) -> str:
    """Whether a direction pattern repeats one component or mixes two."""
    return "repeated" if len(set(directions.split("|"))) == 1 else "mixed"


def _plastic_spans(increments, branches):
    """Contiguous runs of yielded increments, as half-open x spans."""
    spans, start = [], None
    for increment in increments:
        yielded = branches.get(increment) != "elastic"
        if yielded and start is None:
            start = increment
        elif not yielded and start is not None:
            spans.append((start - 0.5, increment - 0.5))
            start = None
    if start is not None:
        spans.append((start - 0.5, increments[-1] + 0.5))
    return spans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not ROWS.is_file():
        print(f"missing evidence: {ROWS}")
        return 1

    entries = _read()
    # A row is drawable when the study either resolved it against the reference
    # or established independently that it is zero. Anything else would be
    # drawn as a value the evidence does not support, so it is counted instead.
    drawable = [r for r in entries
                if r["reference_classification"] == "resolved"
                or r["reference_classification"].startswith("expected_zero")]
    withheld = [r for r in entries if r not in drawable]

    increments = sorted({int(r["increment"]) for r in entries})
    branches = {int(r["increment"]): r["branch"] for r in entries}
    orders = sorted({int(r["order"]) for r in drawable})
    patterns = sorted({r["directions"] for r in drawable},
                      key=lambda d: (len(d), d))
    kinds = [k for k in KINDS if any(_kind(p) == k for p in patterns)]
    # Components that are zero at every increment of every order carry no
    # information: they would be a flat line on the axis in every panel.
    components = [c for c in sorted({int(r["stress_component"]) for r in drawable})
                  if any(float(r["oti_derivative"]) != 0.0 for r in drawable
                         if int(r["stress_component"]) == c)]
    colours = [series_colour(i) for i in range(len(components))]

    use_publication_style()
    plt.rcParams["figure.constrained_layout.use"] = False
    # Two by two. Three orders fill three cells and the legend takes the
    # fourth, which is what lets every panel be three inches across and the
    # legend be read at the same size as the rest of the figure.
    figure, grid = plt.subplots(2, 2, figsize=(6.2, 6.4), sharex=True)
    axes = list(grid.flat)

    plotted: dict[str, int] = {}
    for axis, order in zip(axes, orders):
        axis.set_title(ORDER_TITLE.get(order, f"order {order}"), pad=6)
        for colour, component in zip(colours, components):
            for style, kind in enumerate(kinds):
                selected = sorted(
                    (r for r in drawable if int(r["order"]) == order
                     and _kind(r["directions"]) == kind
                     and int(r["stress_component"]) == component),
                    key=lambda r: int(r["increment"]))
                if not selected:
                    continue
                x = [int(r["increment"]) for r in selected]
                draw_overlay(
                    axis, x,
                    [float(r["oti_derivative"]) for r in selected],
                    [float(r["reference_value"]) for r in selected],
                    colour, marker_every=2, style=style)
                plotted[f"order {order} {kind} sigma_{component}"] = len(selected)
        for low, high in _plastic_spans(increments, branches):
            axis.axvspan(low, high, color="#f2f3f5", zorder=0)
        axis.set_xticks([i for i in increments if i % 3 == 0 or i == 1])
        axis.margins(x=0.06)
        axis.ticklabel_format(axis="y", style="sci", scilimits=(-2, 3),
                              useMathText=True)
        axis.yaxis.get_offset_text().set_fontsize(ANNOTATION_PT)

    # sharex hides the tick labels of any panel that has another panel below
    # it. The legend takes one cell, so the panel above the legend has nothing
    # below it and would otherwise be printed with no x axis at all.
    for index in range(len(orders)):
        if index + 2 >= len(orders):
            axes[index].tick_params(labelbottom=True)

    # The fourth cell is the legend, at the same type size as the panels.
    legend_axis = axes[len(orders)]
    legend_axis.set_axis_off()
    handles = [Line2D([], [], color=colour, linewidth=3.2, label=STRESS[c])
               for colour, c in zip(colours, components)]
    handles += [Line2D([], [], color="0.35", linewidth=2.6,
                       linestyle=DASHES[i % len(DASHES)],
                       label=KIND_LABEL[kind])
                for i, kind in enumerate(kinds)]
    handles += [
        Line2D([], [], color="0.15", linewidth=GENERATED_KW["linewidth"],
               label="OTI (exact)"),
        Line2D([], [], color="0.15", linestyle="none", marker="o",
               markersize=REFERENCE_KW["markersize"], markerfacecolor="none",
               markeredgewidth=REFERENCE_KW["markeredgewidth"],
               label="80-digit reference"),
    ]
    legend_axis.legend(handles=handles, loc="center", frameon=False,
                       fontsize=ANNOTATION_PT, handlelength=2.4,
                       labelspacing=0.75, handletextpad=0.7, borderpad=0.0)
    for axis in axes[len(orders) + 1:]:
        axis.remove()

    figure.suptitle("Higher-order stress derivatives along the path  (MPa)",
                    x=0.02, ha="left", fontsize=ANNOTATION_PT + 3)
    # Kept inside the width one panel's axes span: a longer line runs off the
    # right edge of the page, where nothing is there to clip it.
    axes[0].annotate("shaded: the material has yielded. Before yield\n"
                     "the response is linear and these vanish exactly.",
                     xy=(0.0, 1.22), xycoords="axes fraction", ha="left",
                     va="bottom", fontsize=ANNOTATION_PT, color="0.45")
    figure.supxlabel("increment along the loading path", y=0.028)
    figure.subplots_adjust(left=0.155, right=0.975, top=0.805, bottom=0.115,
                           hspace=0.34, wspace=0.42)

    outputs = save(figure, "figure_higher_order_verification", args.out_dir)
    resolved = [r for r in drawable if r["reference_classification"] == "resolved"]
    zeros = [r for r in drawable
             if r["reference_classification"].startswith("expected_zero")]
    worst = max((float(r["relative_error"]) for r in resolved
                 if r["relative_error"]), default=None)
    write_provenance(
        "figure_higher_order_verification", args.out_dir, inputs=[ROWS],
        outputs=outputs,
        question="Do the generated stress derivatives of order two and above "
                 "match an independent 80-digit reference at every increment "
                 "of the path?",
        filters={
            "model": "controlled_j2_actual_umat (the illustrative example)",
            "panels": "one per derivative order, each with its own scale "
                      "because the orders are six decades apart",
            "colour": "stress component",
            "line_style": "whether the direction pattern repeats one strain "
                          "component or mixes two",
            "directions_plotted": patterns,
            "components_plotted": components,
            "components_omitted_as_identically_zero":
                [c for c in sorted({int(r["stress_component"]) for r in drawable})
                 if c not in components],
            "plotted": "comparisons the study resolved against the reference, "
                       "and comparisons the study establishes to be zero on "
                       "evidence independent of the OTI result",
            "not_plotted": f"{len(withheld)} comparisons with neither",
            "generated": "line", "reference": "open markers every second increment",
            "reference_method": "independent tensor-product finite differences "
                                "of umat_oti.validation.j2_reference evaluated "
                                "at 80 decimal digits, with the zeros "
                                "reconfirmed at 200 digits",
        },
        rows={"comparisons": len(entries), "resolved": len(resolved),
              "independently_shown_to_be_zero": len(zeros),
              "withheld_as_unsupported": len(withheld),
              "increments": len(increments),
              "disagreeing": sum(1 for r in entries
                                 if r["agrees_with_reference"] == "False"),
              "worst_resolved_relative_error": worst, "series": plotted},
        command="python tools/figures/build_higher_order_figure.py",
        notes="Errors are reported exactly in Table 4.")
    print(f"  {outputs['png']}  ({outputs['width_inches']} x "
          f"{outputs['height_inches']} in)")
    print(f"  {len(orders)} order panels, {len(patterns)} direction patterns "
          f"in {len(kinds)} kinds, "
          f"{len(components)} components, {len(increments)} increments")
    print(f"  {len(resolved)} resolved + {len(zeros)} independent zeros drawn, "
          f"{len(withheld)} withheld, worst relative error {worst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
