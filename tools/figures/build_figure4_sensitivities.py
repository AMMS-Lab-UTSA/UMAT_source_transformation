#!/usr/bin/env python3
"""Figure 4: parameter and state sensitivities over the complete loading history.

Both requested families appear -- DSIGMA_DP in panel (a), DSTATEV_DP in panel
(b) -- over every increment of the path, with the elastic and inelastic
responses and the increment where the material yields marked on the axes.

Every curve is scaled by its own parameter, p d(response)/dp. Raw sensitivities
are not comparable: dsigma/dE and dsigma/dnu differ by five orders of magnitude
purely because Young's modulus and Poisson's ratio are numbers of different
size, and plotting them together would say more about the units than about the
material. Scaling by p makes every stress curve a stress and every state curve
a strain, so the panels compare what the parameters actually do.

The exact zeros are the point of the figure as much as the nonzero values are.
Before yield the stress does not depend on the yield stress or the hardening
modulus, and the equivalent plastic strain does not depend on anything; the
verification records those entries as exactly zero on both sides, not as small
numbers, and panel (c) shows how many of them there are.
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

ROWS = (REPO_ROOT / "paper_results" / "parameter_sensitivity"
        / "table6_comparison_rows.csv")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

MODEL = "m3_j2"
#: PROPS order, which is also the order the parameters are plotted in.
PARAMETERS = (("E", 1, 200000.0, "MPa"), ("nu", 2, 0.3, "-"),
              ("SIGY0", 3, 250.0, "MPa"), ("H", 4, 2000.0, "MPa"))
LABELS = {"E": "$E$", "nu": r"$\nu$", "SIGY0": r"$\sigma_{y0}$", "H": "$H$"}
#: STATEV order for this model: a single slot holding equivalent plastic strain.
STATE_LABEL = r"$\bar\varepsilon^{\,p}$ (STATEV 1)"
STRESS_COMPONENT = 1


def _read() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return [r for r in csv.DictReader(handle) if r["model"] == MODEL]


def _series(rows: list[dict], array: str, parameter: str, component: int):
    selected = sorted(
        (r for r in rows if r["array"] == array
         and r["parameter"] == parameter and int(r["component"]) == component),
        key=lambda r: int(r["increment"]))
    return ([int(r["increment"]) for r in selected],
            [float(r["oti"]) for r in selected])


def _branches(rows: list[dict]) -> tuple[dict[int, str], int | None]:
    branch = {int(r["increment"]): r["branch"] for r in rows}
    yielded = sorted(i for i, b in branch.items() if b != "elastic")
    return branch, (yielded[0] if yielded else None)


def _mark_regions(axis, branch: dict[int, str], first_inelastic: int | None) -> None:
    """Shade the two responses and mark the increment the material yields on.

    The shading is deliberately faint and each region is also labelled, so the
    distinction does not depend on seeing the colours.
    """
    increments = sorted(branch)
    if first_inelastic is None:
        return
    axis.axvspan(increments[0] - 0.5, first_inelastic - 0.5,
                 color="0.90", zorder=0)
    axis.axvspan(first_inelastic - 0.5, increments[-1] + 0.5,
                 color="0.97", zorder=0)
    axis.axvline(first_inelastic - 0.5, color="0.45",
                 linestyle=LINESTYLES[2], linewidth=1.0, zorder=1)


def _label_regions(axis, first_inelastic: int, last: int) -> None:
    """Name the two regions in a band cleared above the data.

    Writing them over the curves is how the inelastic label ended up sitting on
    the Poisson-ratio markers.
    """
    axis.text((1 + first_inelastic - 0.5) / 2, 1.02, "elastic",
              transform=axis.get_xaxis_transform(), ha="center", va="bottom",
              fontsize=8, color="0.35")
    axis.text((first_inelastic - 0.5 + last) / 2, 1.02, "inelastic",
              transform=axis.get_xaxis_transform(), ha="center", va="bottom",
              fontsize=8, color="0.35")
    axis.annotate(f"yields at increment {first_inelastic}",
                  xy=(first_inelastic - 0.5, 1.02),
                  xycoords=axis.get_xaxis_transform(),
                  xytext=(-6, 0), textcoords="offset points",
                  ha="right", va="bottom", fontsize=8, color="0.35")


def _symlog_axis(axis, values) -> None:
    """Log where the values live, linear through zero so exact zeros show.

    The decades are thinned by hand. A symlog axis left to itself labels every
    decade it spans, and across the eight this data covers the labels run into
    each other and into the zero tick.
    """
    magnitudes = [abs(v) for v in values if v != 0.0 and np.isfinite(v)]
    if not magnitudes:
        return
    threshold = min(magnitudes) / 3.0
    axis.set_yscale("symlog", linthresh=threshold)
    low = int(np.ceil(np.log10(threshold * 10.0)))
    high = int(np.floor(np.log10(max(magnitudes))))
    if high < low:
        return
    stride = max(1, (high - low) // 3)
    decades = sorted({d for d in range(high, low - 1, -stride)})[-4:]
    positive = [10.0 ** d for d in decades]
    signs = {np.sign(v) for v in values if v != 0.0}
    ticks = [0.0] + positive
    if -1 in signs:
        ticks = [-value for value in reversed(positive)] + ticks
    if 1 not in signs:
        ticks = [v for v in ticks if v <= 0.0]
    axis.set_yticks(ticks)


def panel_stress(axis, rows: list[dict], branch, first_inelastic) -> dict:
    _mark_regions(axis, branch, first_inelastic)
    counts, every = {}, []
    for index, (name, _slot, value, _unit) in enumerate(PARAMETERS):
        increments, raw = _series(rows, "DSIGMA_DP", name, STRESS_COMPONENT)
        scaled = [value * v for v in raw]
        every.extend(scaled)
        counts[name] = {"points": len(scaled),
                        "exact_zeros": sum(1 for v in raw if v == 0.0)}
        axis.plot(increments, scaled, marker=MARKERS[index],
                  linestyle=LINESTYLES[index], color=PALETTE[index],
                  markerfacecolor="none", markevery=2,
                  label=f"{LABELS[name]}  (PROPS {_slot})")
    _symlog_axis(axis, every)
    if first_inelastic:
        _label_regions(axis, first_inelastic, max(branch))
    axis.set_ylabel(r"$p\,\partial\sigma_{11}/\partial p$  (MPa)")
    axis.set_title("(a) Stress sensitivity, DSIGMA_DP", pad=18)
    axis.legend(loc="center left", ncol=2, framealpha=0.9, frameon=True,
                facecolor="white", edgecolor="none")
    return counts


def panel_state(axis, rows: list[dict], branch, first_inelastic) -> dict:
    _mark_regions(axis, branch, first_inelastic)
    counts, every = {}, []
    for index, (name, slot, value, _unit) in enumerate(PARAMETERS):
        increments, raw = _series(rows, "DSTATEV_DP", name, 1)
        scaled = [value * v for v in raw]
        every.extend(scaled)
        counts[name] = {"points": len(scaled),
                        "exact_zeros": sum(1 for v in raw if v == 0.0)}
        axis.plot(increments, scaled, marker=MARKERS[index],
                  linestyle=LINESTYLES[index], color=PALETTE[index],
                  markerfacecolor="none", markevery=2,
                  label=f"{LABELS[name]}  (PROPS {slot})")
    _symlog_axis(axis, every)
    axis.set_ylabel(r"$p\,\partial\bar\varepsilon^{\,p}/\partial p$  (-)")
    axis.set_xlabel("increment along the loading path")
    axis.set_title(f"(b) State sensitivity, DSTATEV_DP: {STATE_LABEL}")
    axis.legend(loc="lower left", ncol=2, framealpha=0.9, frameon=True,
                facecolor="white", edgecolor="none")
    return counts


def panel_verification(axis, rows: list[dict], first_inelastic) -> dict:
    """How every row was adjudicated, so none of the 560 leaves the figure.

    An entry that is exactly zero on both sides is separated from one the
    reference merely could not distinguish from the value: they are different
    claims and collapsing them would overstate what was measured.
    """
    increments = sorted({int(r["increment"]) for r in rows})
    categories = {
        "exact zero, both sides": lambda r: float(r["oti"]) == 0.0
                                            and float(r["reference"]) == 0.0,
        "within reference resolution":
            lambda r: (r["judged_by"] == "within_reference_resolution"
                       and not (float(r["oti"]) == 0.0
                                and float(r["reference"]) == 0.0)),
        "measured on relative error": lambda r: r["judged_by"] == "relative",
    }
    bottom = np.zeros(len(increments))
    counts = {}
    for index, (label, predicate) in enumerate(categories.items()):
        heights = np.array([
            sum(1 for r in rows if int(r["increment"]) == i and predicate(r))
            for i in increments], dtype=float)
        counts[label] = int(heights.sum())
        axis.bar(increments, heights, bottom=bottom, width=0.75,
                 color=PALETTE[index], edgecolor="white", linewidth=0.4,
                 label=f"{label} (n={int(heights.sum())})",
                 hatch=("", "///", "...")[index], zorder=2)
        bottom += heights
    if first_inelastic:
        axis.axvline(first_inelastic - 0.5, color="0.45",
                     linestyle=LINESTYLES[2], linewidth=1.0, zorder=3)
    disagreeing = sum(1 for r in rows if r["agrees"] != "True")
    axis.set_ylabel("rows compared")
    axis.set_xlabel("increment along the loading path")
    axis.set_title(f"(c) Every row accounted for; {disagreeing} disagree")
    axis.legend(loc="upper center", ncol=3, fontsize=8,
                bbox_to_anchor=(0.5, -0.28))
    axis.grid(axis="x", visible=False)
    axis.set_xticks(increments[::2])
    axis.set_xlim(increments[0] - 0.7, increments[-1] + 0.7)
    axis.set_ylim(0, max(bottom) * 1.08)
    counts["disagreeing"] = disagreeing
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not ROWS.is_file():
        print(f"missing evidence: {ROWS}")
        return 1

    rows = _read()
    if not rows:
        print(f"no rows for model {MODEL}")
        return 1
    branch, first_inelastic = _branches(rows)

    use_publication_style()
    figure, axes = plt.subplots(3, 1, figsize=(FIGURE_WIDTH_IN, FIGURE_WIDTH_IN * 1.15),
                                sharex=True)
    counts = {
        "stress": panel_stress(axes[0], rows, branch, first_inelastic),
        "state": panel_state(axes[1], rows, branch, first_inelastic),
        "verification": panel_verification(axes[2], rows, first_inelastic),
    }
    axes[0].set_xlabel("")
    axes[1].set_xlabel("")
    outputs = save(figure, "figure4_parameter_sensitivities", args.out_dir)

    write_provenance(
        "figure4_parameter_sensitivities", args.out_dir,
        inputs=[ROWS], outputs=outputs,
        filters={
            "model": MODEL,
            "increments": f"1-{max(branch)}, the complete path, no selection",
            "panel_a": f"DSIGMA_DP, stress component {STRESS_COMPONENT}, "
                       "all four parameters",
            "panel_b": "DSTATEV_DP, state slot 1 (equivalent plastic strain), "
                       "all four parameters",
            "panel_c": "every row for this model, in all arrays and components",
            "scaling": "each curve is p d(response)/dp with p the parameter's "
                       "own value, so all stress curves carry MPa and all "
                       "state curves are dimensionless",
            "parameter_order": [name for name, _, _, _ in PARAMETERS],
            "parameter_values": {name: value for name, _, value, _ in PARAMETERS},
        },
        rows={"model_rows": len(rows), "first_inelastic_increment": first_inelastic,
              **counts},
        command="python tools/figures/build_figure4_sensitivities.py",
        notes=("The zeros before yield were read from the raw values, not "
               "inferred from the plot: 390 of the 560 rows are exactly 0.0 on "
               "both the OTI and the reference side, and the largest reference "
               "magnitude among them is 0.0. They are structural zeros of this "
               "model, not small numbers."))
    print(f"  {outputs['png']}  ({outputs['width_inches']}x"
          f"{outputs['height_inches']} in)")
    print(f"  {outputs['pdf']}")
    print(f"  {len(rows)} rows, yields at increment {first_inelastic}, "
          f"{counts['verification']['disagreeing']} disagreeing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
