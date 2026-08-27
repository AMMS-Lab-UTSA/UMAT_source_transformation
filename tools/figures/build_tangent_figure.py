#!/usr/bin/env python3
"""The generated consistent tangent, with the closed-form reference over it.

One panel per stress component, one colour per strain direction, the generated
DDSDDE as a line and the independent reference as open markers on top of it.
A reader sees the tangent itself -- its magnitude, its units, the drop at yield
and the recovery on elastic unloading -- and sees the reference sitting on it.
The size of the disagreement is a number, and numbers belong in Table 5, where
it can be read exactly.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figure_style import (  # noqa: E402
    ANNOTATION_PT, REPO_ROOT, save, use_publication_style, write_provenance,
)
from overlay_style import (  # noqa: E402
    draw_overlay, method_legend, series_colour,
)

ROWS = (REPO_ROOT / "paper_results" / "actual_umat_higher_order" / "j2"
        / "table2_ddsdde_illustrative.csv")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

STRESS = {1: r"$\sigma_{11}$", 2: r"$\sigma_{22}$", 3: r"$\sigma_{33}$",
          4: r"$\sigma_{12}$", 5: r"$\sigma_{13}$", 6: r"$\sigma_{23}$"}
STRAIN = {1: r"$\partial/\partial\varepsilon_{11}$",
          2: r"$\partial/\partial\varepsilon_{22}$",
          3: r"$\partial/\partial\varepsilon_{33}$",
          4: r"$\partial/\partial\gamma_{12}$",
          5: r"$\partial/\partial\gamma_{13}$",
          6: r"$\partial/\partial\gamma_{23}$"}


def _read() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
    parser.add_argument("--panels", type=int, default=4,
                        help="how many stress components to give a panel")
    args = parser.parse_args(argv)
    if not ROWS.is_file():
        print(f"missing evidence: {ROWS}")
        return 1

    entries = _read()
    increments = sorted({int(r["increment"]) for r in entries})
    branches = {int(r["increment"]): r["branch"] for r in entries}

    all_rows = sorted({int(r["row"]) for r in entries})
    stress_rows = all_rows[:args.panels]
    # Columns that never move carry no information and cost a legend entry.
    # Judged over the panelled rows only: the two shear directions move solely
    # in the shear rows, so counting them globally would put two flat lines on
    # the axis of every panel drawn here and two dead entries in the legend.
    moving = []
    for column in sorted({int(r["column"]) for r in entries}):
        if any(float(r["oti"]) != 0.0 for r in entries
               if int(r["column"]) == column and int(r["row"]) in stress_rows):
            moving.append(column)
    colours = [series_colour(i) for i in range(len(moving))]

    use_publication_style()
    # Constrained layout is off: the shared legend sits below the axes and its
    # height has to be reserved by hand, which constrained layout will not do.
    plt.rcParams["figure.constrained_layout.use"] = False
    # Two by two rather than a vertical strip. Stacked panels on a 6.2 in page
    # are wide and flat, so a fifteen-increment path is squeezed into an inch
    # and a half of height; two by two makes each panel about three inches
    # square and lets the type grow to match.
    columns = 2
    grid_rows = -(-len(stress_rows) // columns)
    figure, grid = plt.subplots(grid_rows, columns, figsize=(6.2, 6.4),
                                sharex=True)
    axes = list(grid.flat) if hasattr(grid, "flat") else [grid]

    plotted = {}
    for axis, row_index in zip(axes, stress_rows):
        axis.set_title(STRESS.get(row_index, str(row_index)), loc="center",
                       pad=6)
        for style, (colour, column) in enumerate(zip(colours, moving)):
            selected = sorted(
                (r for r in entries
                 if int(r["row"]) == row_index and int(r["column"]) == column),
                key=lambda r: int(r["increment"]))
            if not selected:
                continue
            # MPa in the evidence; GPa reads better for a stiffness.
            generated = [float(r["oti"]) / 1000.0 for r in selected]
            reference = [float(r["analytic_reference"]) / 1000.0
                         for r in selected]
            draw_overlay(axis, increments, generated, reference, colour,
                         marker_every=2, style=style)
            plotted[f"C[{row_index},{column}]"] = len(selected)
        for low, high in _plastic_spans(increments, branches):
            axis.axvspan(low, high, color="#f2f3f5", zorder=0)
        axis.set_xticks([i for i in increments if i % 3 == 0 or i == 1])
        axis.margins(x=0.06)

    for axis in axes[len(stress_rows):]:
        axis.remove()
    # One shared x label. Per-panel labels are wider than a three-inch panel
    # at this type size, so two of them side by side collide in the middle and
    # run off both edges of the page.
    figure.supxlabel("increment along the loading path", y=0.105)

    figure.suptitle("Consistent tangent per increment, "
                    r"$D_{ij}$  (GPa)", x=0.02, ha="left",
                    fontsize=ANNOTATION_PT + 3)
    axes[0].annotate("shaded: the material has yielded",
                     xy=(0.0, 1.16), xycoords="axes fraction", ha="left",
                     va="bottom", fontsize=ANNOTATION_PT, color="0.45")
    # Wrapped: six entries on one line runs off both edges of a 6.2 in page.
    method_legend(figure, axes, [STRAIN.get(c, str(c)) for c in moving],
                  colours, ncol=3, y=0.006)
    figure.subplots_adjust(left=0.135, right=0.975, top=0.855, bottom=0.205,
                           hspace=0.30, wspace=0.30)

    outputs = save(figure, "figure_tangent_verification", args.out_dir)
    measured = [r for r in entries if r["judged_by"] == "relative"]
    zeros = [r for r in entries if r["judged_by"] == "structural_zero"]
    write_provenance(
        "figure_tangent_verification", args.out_dir, inputs=[ROWS],
        outputs=outputs,
        question="Does the generated consistent tangent match an independent "
                 "closed-form reference at every increment of the path?",
        filters={
            "model": "controlled_j2_actual_umat (the illustrative example)",
            "panels": f"stress components {stress_rows} of {all_rows}",
            "panels_omitted": [r for r in all_rows if r not in stress_rows],
            "columns_plotted": moving,
            "columns_omitted_as_identically_zero":
                [c for c in sorted({int(r['column']) for r in entries})
                 if c not in moving],
            "units": "evidence is in MPa; plotted in GPa",
            "generated": "line", "reference": "open markers every second increment",
            "reference_method": "closed-form elastoplastic consistent tangent "
                                "from umat_oti.validation.j2_reference",
        },
        rows={"entries": len(entries), "increments": len(increments),
              "measured": len(measured), "structural_zeros": len(zeros),
              "disagreeing": sum(1 for r in entries if r["agrees"] == "False"),
              "series": plotted},
        command="python tools/figures/build_tangent_figure.py",
        notes=("Agreement is shown by overlay; the worst measured relative "
               "difference and the count of structural zeros are in Table 5. "
               "Components 5 and 6 are the two shear rows, whose only moving "
               "entry is their own diagonal; they are omitted from the panels "
               "and reported in the table."))
    print(f"  {outputs['png']}  ({outputs['width_inches']} x "
          f"{outputs['height_inches']} in)")
    print(f"  {len(stress_rows)} panels, {len(moving)} strain directions, "
          f"{len(increments)} increments, "
          f"{sum(1 for r in entries if r['agrees'] == 'False')} disagreeing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
