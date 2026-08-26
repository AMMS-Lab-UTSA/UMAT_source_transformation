#!/usr/bin/env python3
"""Figure 3: derivative validation for the illustrative example.

Four panels, all from the same J2 run and all from committed evidence:

  (a) the consistent tangent against its two independent references;
  (b) repeated higher-order stress derivatives against theirs;
  (c) mixed higher-order stress derivatives against theirs;
  (d) where the error in every one of those comparisons actually sits.

Panels (a)-(c) plot value against value, so agreement is the diagonal and a
disagreement is visible as a point off it -- a bar chart of errors would hide
which quantity was wrong. Panel (d) is what the eye cannot read off a diagonal:
how far from it every point is.

The illustrative model integrates its return map in closed form and runs no
local Newton iteration, so it has no internal constitutive Jacobian to show
here. Those appear with the models that actually have one, rather than being
borrowed into this figure from a different material.
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

EVIDENCE = REPO_ROOT / "paper_results" / "actual_umat_higher_order" / "j2"
TANGENT = EVIDENCE / "table2_ddsdde_illustrative.csv"
HIGHER = EVIDENCE / "actual_umat_higher_order_comparison.csv"
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

REPEATED = ("1|1", "1|1|1", "1|1|1|1")
MIXED = ("1|2", "1|1|2", "1|1|2|2")
ORDER_LABEL = {2: "order 2", 3: "order 3", 4: "order 4"}


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _diagonal(axis, values) -> None:
    """The line agreement would fall on, drawn from the data's own range."""
    finite = [v for v in values if v and np.isfinite(v)]
    if not finite:
        return
    low, high = min(finite), max(finite)
    axis.plot([low, high], [low, high], color="0.55", linewidth=0.9,
              linestyle=(0, (4, 3)), zorder=0)


#: An entry below this fraction of the largest value in the same panel is a
#: zero of that quantity, not a small number. Taking the axis floor from the
#: smallest nonzero magnitude instead stretches the plot over the ninety
#: decades of rounding dust that sits at those zeros, which is unreadable and
#: says nothing.
PANEL_ZERO_FRACTION = 1.0e-12


def _symlog(axis, values) -> float:
    """A linear window around zero, sized from what is actually plotted.

    Structural zeros are excluded before this is called, so the smallest
    remaining magnitude is a real derivative. Sizing the window from the
    panel's largest value instead would open a twelve-decade gap around zero
    that contains no data and squeezes every point into the corners.
    """
    magnitudes = [abs(v) for v in values
                  if v is not None and np.isfinite(v) and v != 0.0]
    if not magnitudes:
        return 1.0
    scale = max(magnitudes)
    threshold = min(magnitudes) / 3.0
    ticks = _decade_ticks(threshold, scale)
    for setter, locator in ((axis.set_xscale, axis.set_xticks),
                            (axis.set_yscale, axis.set_yticks)):
        setter("symlog", linthresh=threshold)
        locator(ticks)
    return threshold


def _decade_ticks(threshold: float, scale: float) -> list[float]:
    """At most a handful of labelled decades per side, plus zero.

    A symlog axis left to itself labels every decade it spans and the labels
    overlap into an unreadable band. Decades inside or just outside the linear
    window are dropped as well: on a symlog axis they sit almost on top of
    zero, so their labels collide with it and with each other.
    """
    innermost = threshold * 10.0
    low = int(np.ceil(np.log10(innermost)))
    high = int(np.floor(np.log10(scale)))
    if high < low:
        return [-scale, 0.0, scale]
    stride = max(1, (high - low) // 3)
    decades = sorted({d for d in range(high, low - 1, -stride)})[-3:]
    positive = [10.0 ** d for d in decades]
    return [-value for value in reversed(positive)] + [0.0] + positive


def panel_tangent(axis, rows: list[dict]) -> dict:
    """Every tangent entry: the OTI value against the closed-form reference.

    Split by increment rather than by outcome, because the elastic and the two
    plastic increments carry different tangents and pooling them would hide
    which branch a disagreement came from.
    """
    zeros = [r for r in rows if r["judged_by"] == "structural_zero"]
    measured = [r for r in rows if r["judged_by"] == "relative"]
    every = []
    counts = {}
    by_increment: dict[int, list[dict]] = {}
    for row in measured:
        by_increment.setdefault(int(row["increment"]), []).append(row)

    for index, increment in enumerate(sorted(by_increment)):
        selected = by_increment[increment]
        branch = selected[0]["branch"]
        reference = [float(r["analytic_reference"]) for r in selected]
        oti = [float(r["oti"]) for r in selected]
        every.extend(reference + oti)
        counts[f"increment {increment} ({branch})"] = len(selected)
        axis.scatter(reference, oti, s=28, marker=MARKERS[index],
                     facecolor="none", edgecolor=PALETTE[index], linewidth=1.1,
                     label=f"increment {increment}, {branch} (n={len(selected)})",
                     zorder=3)
    _symlog(axis, every)
    _diagonal(axis, every)
    counts["structural_zeros"] = len(zeros)
    disagreeing = sum(1 for r in zeros if r["agrees"] == "False")
    axis.text(0.97, 0.03,
              f"{len(zeros)} structural zeros,\nall returned as zero"
              if not disagreeing else
              f"{len(zeros)} structural zeros,\n{disagreeing} NOT returned as zero",
              transform=axis.transAxes, fontsize=8, color="0.35",
              ha="right", va="bottom")
    axis.set_xlabel("closed-form consistent tangent (MPa)")
    axis.set_ylabel("DDSDDE from the OTI build (MPa)")
    axis.set_title("(a) Consistent tangent")
    axis.legend(loc="upper left")
    return counts


def panel_higher_order(axis, rows: list[dict], directions, title: str) -> dict:
    """Higher-order stress derivatives, one series per order."""
    counts = {}
    families = []
    for pattern in directions:
        selected = [r for r in rows if r["directions"] == pattern]
        if selected:
            families.append((pattern, selected))
    scale = max((abs(float(r["fd_reference"])) for _, rows_ in families
                 for r in rows_), default=1.0)
    floor = scale * PANEL_ZERO_FRACTION

    every, zeros = [], 0
    for index, (pattern, selected) in enumerate(families):
        order = int(selected[0]["order"])
        # A pair where both sides sit below the panel's zero is a structural
        # zero of that derivative. Plotting it would place the panel's axes on
        # rounding dust; it is counted instead, so nothing leaves the figure
        # silently.
        significant = [r for r in selected
                       if max(abs(float(r["fd_reference"])),
                              abs(float(r["oti_derivative"]))) > floor]
        zeros += len(selected) - len(significant)
        counts[pattern] = {"rows": len(selected), "plotted": len(significant),
                           "structural_zeros": len(selected) - len(significant)}
        if not significant:
            continue
        reference = [float(r["fd_reference"]) for r in significant]
        oti = [float(r["oti_derivative"]) for r in significant]
        every.extend(reference + oti)
        axis.scatter(reference, oti, s=26, marker=MARKERS[index],
                     facecolor="none", edgecolor=PALETTE[index], linewidth=1.1,
                     label=f"{ORDER_LABEL[order]} $\\partial${pattern} "
                           f"(n={len(significant)})", zorder=3)
    _symlog(axis, every)
    _diagonal(axis, every)
    if zeros:
        axis.text(0.97, 0.03, f"{zeros} structural zeros\nnot plotted",
                  transform=axis.transAxes, fontsize=8, color="0.35",
                  ha="right", va="bottom")
    axis.set_xlabel("independent 80-digit reference (MPa)")
    axis.set_ylabel("OTI derivative (MPa)")
    axis.set_title(title)
    axis.legend(loc="upper left")
    return counts


def panel_errors(axis, tangent: list[dict], higher: list[dict]) -> dict:
    """Where the error actually sits, against what each family was asked for.

    Only entries with something to measure appear: at a structural zero both
    sides are zero and a relative error is not defined, so plotting one would
    invent a data point.
    """
    families = []
    measured = [float(r["relative_error"]) for r in tangent
                if r["judged_by"] == "relative"]
    families.append(("DDSDDE", measured, float(tangent[0]["relative_tolerance"])))
    for order in (2, 3, 4):
        selected = [r for r in higher if int(r["order"]) == order
                    and float(r["absolute_error"]) > float(r["absolute_tolerance"])]
        families.append((f"$\\partial^{order}\\sigma$",
                         [float(r["relative_error"]) for r in selected],
                         float(higher[0]["relative_tolerance"])))

    floor = min((v for _, values, _ in families for v in values if v > 0),
                default=1e-18)
    positions = np.arange(len(families))
    empty_columns: list[tuple[int, str]] = []
    for index, (label, values, tolerance) in enumerate(families):
        if not values:
            empty_columns.append((index, label))
            continue
        plotted = [max(v, floor / 3) for v in values]
        axis.scatter([index] * len(plotted), plotted, s=22,
                     marker=MARKERS[index % len(MARKERS)], facecolor="none",
                     edgecolor=PALETTE[index % len(PALETTE)], linewidth=1.0,
                     zorder=3)
        axis.scatter([index], [max(values)], s=70, marker="_",
                     color=PALETTE[index % len(PALETTE)], zorder=4)

    for index, _label in empty_columns:
        axis.text(index, floor / 3, "no entry exceeds\nits absolute tolerance",
                  ha="center", va="bottom", fontsize=8, color="0.35",
                  rotation=90)
    demanded = max(t for _, _, t in families)
    axis.axhline(demanded, color="0.35", linestyle=LINESTYLES[1], linewidth=1.0)
    axis.text(len(families) - 0.5, demanded * 1.6,
              f"agreement demanded: {demanded:.0e}", ha="right", va="bottom",
              fontsize=8, color="0.35")
    axis.set_yscale("log")
    axis.set_xticks(positions)
    axis.set_xticklabels([label for label, _, _ in families])
    axis.set_xlim(-0.6, len(families) - 0.4)
    axis.set_ylabel("relative error (dimensionless)")
    axis.set_xlabel("derivative family")
    axis.set_title("(d) Error against what was demanded")
    return {label: len(values) for label, values, _ in families}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    for path in (TANGENT, HIGHER):
        if not path.is_file():
            print(f"missing evidence: {path}")
            return 1

    tangent = _read(TANGENT)
    higher = _read(HIGHER)

    use_publication_style()
    figure, axes = plt.subplots(2, 2, figsize=(FIGURE_WIDTH_IN, FIGURE_WIDTH_IN * 0.92))
    counts = {
        "tangent_entries": panel_tangent(axes[0][0], tangent),
        "repeated": panel_higher_order(
            axes[0][1], higher, REPEATED, "(b) Repeated directions"),
        "mixed": panel_higher_order(
            axes[1][0], higher, MIXED, "(c) Mixed directions"),
        "measured_errors": panel_errors(axes[1][1], tangent, higher),
    }
    outputs = save(figure, "figure3_illustrative_derivatives", args.out_dir)

    disagreeing = sum(1 for r in tangent if r["agrees"] == "False")
    disagreeing += sum(1 for r in higher if r["passed"] == "False")
    write_provenance(
        "figure3_illustrative_derivatives", args.out_dir,
        inputs=[TANGENT, HIGHER], outputs=outputs,
        filters={
            "model": "controlled_j2_actual_umat (illustrative example only)",
            "panel_a": "every tangent entry, all 3 increments, no selection",
            "panel_b": f"directions {list(REPEATED)}",
            "panel_c": f"directions {list(MIXED)}",
            "panel_d": ("entries with a defined relative error: tangent entries "
                        "judged on relative error, and higher-order rows whose "
                        "absolute error exceeds their absolute tolerance"),
        },
        rows={"tangent_rows": len(tangent), "higher_order_rows": len(higher),
              "disagreeing_rows_in_either_source": disagreeing, **counts},
        command="python tools/figures/build_figure3_illustrative.py",
        notes=("The illustrative model integrates its return map in closed form "
               "and runs no local Newton iteration, so it has no internal "
               "constitutive Jacobian; those are shown with the models that "
               "have one rather than borrowed into this figure."))
    print(f"  {outputs['png']}  ({outputs['width_inches']}x"
          f"{outputs['height_inches']} in)")
    print(f"  {outputs['pdf']}")
    print(f"  tangent rows {len(tangent)}, higher-order rows {len(higher)}, "
          f"disagreeing {disagreeing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
