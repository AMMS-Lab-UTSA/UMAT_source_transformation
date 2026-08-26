#!/usr/bin/env python3
"""Does the generated consistent tangent match an independent reference?

One panel, one question. Each point is one entry of DDSDDE: its relative
difference from the closed-form elastoplastic consistent tangent, against how
large that entry is. Plotting it against magnitude is what makes the answer
readable -- agreement that holds over five decades of stiffness is a different
claim from agreement that holds only where the numbers are large.

The 66 entries that are exactly zero in both the generated tangent and the
reference are not drawn. A relative difference is not defined there, and
drawing them would fill the panel with points that carry no information; their
count and the fact that the build returned zero for every one of them is stated
in the annotation and in the caption.
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

ROWS = (REPO_ROOT / "paper_results" / "actual_umat_higher_order" / "j2"
        / "table2_ddsdde_illustrative.csv")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"


def _read() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not ROWS.is_file():
        print(f"missing evidence: {ROWS}")
        return 1

    entries = _read()
    measured = [r for r in entries if r["judged_by"] == "relative"]
    zeros = [r for r in entries if r["judged_by"] == "structural_zero"]
    disagreeing = [r for r in entries if r["agrees"] == "False"]
    tolerance = float(entries[0]["relative_tolerance"])

    use_publication_style()
    fig, axis = figure(3.5)

    by_increment: dict[int, list[dict]] = {}
    for row in measured:
        by_increment.setdefault(int(row["increment"]), []).append(row)

    floor = min(float(r["relative_error"]) for r in measured
                if float(r["relative_error"]) > 0) / 3.0
    plotted = {}
    for index, increment in enumerate(sorted(by_increment)):
        rows = by_increment[increment]
        branch = rows[0]["branch"]
        magnitudes = [abs(float(r["analytic_reference"])) for r in rows]
        errors = [max(float(r["relative_error"]), floor) for r in rows]
        plotted[f"increment {increment} ({branch})"] = len(rows)
        axis.scatter(magnitudes, errors, s=34, marker=MARKERS[index],
                     facecolor="none", edgecolor=PALETTE[index], linewidth=1.3,
                     label=f"increment {increment}, {branch}", zorder=3)

    axis.axhline(tolerance, color="0.35", linestyle=(0, (5, 3)), linewidth=1.1,
                 zorder=2)
    axis.annotate(f"agreement required: {tolerance:.0e}",
                  xy=(0.015, tolerance), xycoords=("axes fraction", "data"),
                  xytext=(0, -4), textcoords="offset points",
                  ha="left", va="top", fontsize=ANNOTATION_PT, color="0.3")
    worst_error = max(float(r["relative_error"]) for r in measured)
    decades = np.log10(tolerance / worst_error)
    # Placed in the empty upper right, which is empty because every entry sits
    # far below the line: the gap is the result, so the note explains it there.
    axis.annotate(
        f"every entry agrees to better than {worst_error:.1e},\n"
        f"{decades:.0f} decades inside what was required\n\n"
        f"{len(zeros)} further entries are exactly zero on both\n"
        f"sides, where a relative difference is undefined",
        xy=(0.98, 0.62), xycoords="axes fraction", ha="right", va="top",
        fontsize=ANNOTATION_PT, color="0.3")

    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("magnitude of the reference tangent entry, "
                    r"$|C_{ij}|$  (MPa)")
    axis.set_ylabel("relative difference from\nthe reference  (dimensionless)")
    axis.set_title("Generated consistent tangent against the closed-form "
                   "reference", loc="left")
    axis.legend(loc="upper left", ncol=1, handletextpad=0.4, borderpad=0.3)

    outputs = save(fig, "figure_tangent_verification", args.out_dir)
    worst = max(float(r["relative_error"]) for r in measured)
    spread = max(float(r["reference_spread_relative"]) for r in measured)
    write_provenance(
        "figure_tangent_verification", args.out_dir, inputs=[ROWS],
        outputs=outputs,
        question="Does the generated consistent tangent match an independent "
                 "reference, and does the agreement hold across magnitudes?",
        filters={
            "model": "controlled_j2_actual_umat (the illustrative example)",
            "plotted": "entries with a defined relative difference, that is "
                       "judged_by == 'relative'",
            "not_plotted": f"{len(zeros)} entries with judged_by == "
                           "'structural_zero', where both sides are exactly "
                           "zero and a relative difference is undefined",
            "error_definition": "|generated - reference| / max(|generated|, "
                                "|reference|)",
            "reference_method": "closed-form elastoplastic consistent tangent "
                                "from umat_oti.validation.j2_reference, "
                                "cross-checked against an 80-digit centred "
                                "difference of an independent integrator",
            "axis_scales": "both logarithmic; no zero is placed on either, "
                           "which is why the structural zeros are counted "
                           "rather than plotted",
        },
        rows={"entries": len(entries), "plotted": len(measured),
              "structural_zeros": len(zeros), "disagreeing": len(disagreeing),
              "worst_relative_difference": worst,
              "references_agree_with_each_other_to": spread,
              "by_increment": plotted},
        command="python tools/figures/build_tangent_figure.py")
    print(f"  {outputs['png']}  ({outputs['width_inches']} x "
          f"{outputs['height_inches']} in)")
    print(f"  {len(measured)} plotted, {len(zeros)} structural zeros, "
          f"{len(disagreeing)} disagreeing, worst {worst:.3e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
