#!/usr/bin/env python3
"""What the material point's response depends on, with the reference over it.

One row per material constant, one colour per stress component, the generated
derivative as a line and the independently replayed finite difference as open
markers sitting on it. Agreement is then something a reader sees rather than a
number they have to interpret; the numbers themselves are in Table 5 and
Table 8, where they can be read exactly.

Giving each constant its own row is also what makes the scales work. The
hardening modulus moves the stress by a thousandth of what the elastic
constants do, and on a shared axis it is a flat line at zero; on its own row it
is a curve with a shape. No second axis, no rescaling, nothing to explain.

Every curve is scaled by its own constant, p d(response)/dp, with p read from
the committed contract -- so each stress row is a stress in MPa and the four
constants are comparable. An earlier version of this figure carried
E = 200000 MPa while the run used 210000; nothing is written here that the
contract does not say.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figure_style import (  # noqa: E402
    ANNOTATION_PT, REPO_ROOT, save, use_publication_style, write_provenance,
)
from overlay_style import (  # noqa: E402
    draw_overlay, method_legend, row_label, series_colour,
)

ROWS = (REPO_ROOT / "paper_results" / "parameter_sensitivity"
        / "table6_comparison_rows.csv")
CONTRACT = REPO_ROOT / "parameter_sensitivity" / "contracts" / "m3_j2.json"
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

MODEL = "m3_j2"
MATHS = {"E": "$E$", "nu": r"$\nu$", "SIGY0": r"$\sigma_{y0}$", "H": "$H$"}
COMPONENTS = {1: r"$\sigma_{11}$", 2: r"$\sigma_{22}$", 3: r"$\sigma_{33}$",
              4: r"$\sigma_{12}$", 5: r"$\sigma_{13}$", 6: r"$\sigma_{23}$"}
STATE_LABEL = r"$\bar\varepsilon^{\,p}$"


def _read() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return [r for r in csv.DictReader(handle) if r["model"] == MODEL]


def _contract() -> tuple[list[tuple[str, int, float]], list[float]]:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    driver = data.get("material_point_driver") or {}
    static = driver.get("static_props") or []
    entries = []
    for parameter in data["parameters"]:
        index = int(parameter["props_index"])
        value = parameter.get("value")
        if value is None and index <= len(static):
            value = static[index - 1]
        if value is None:
            raise SystemExit(f"the contract gives no value for {parameter['name']!r}")
        entries.append((str(parameter["name"]), index, float(value)))
    return sorted(entries, key=lambda e: e[1]), list(
        driver.get("dstran_per_increment") or [])


def _strain_axis(rows: list[dict], dstran: list[float]) -> tuple[list[float], str]:
    """Applied strain in per cent, which is what the reader is loading with.

    Falls back to the increment index only if the contract records no strain
    increment, and says so on the axis rather than silently relabelling.
    """
    increments = sorted({int(r["increment"]) for r in rows})
    driving = max((abs(v) for v in dstran), default=0.0)
    if driving > 0:
        return [i * driving * 100.0 for i in increments], "applied strain  (%)"
    return [float(i) for i in increments], "increment along the loading path"


def _series(rows, array, parameter, component):
    selected = sorted((r for r in rows if r["array"] == array
                       and r["parameter"] == parameter
                       and int(r["component"]) == component),
                      key=lambda r: int(r["increment"]))
    return ([float(r["oti"]) for r in selected],
            [float(r["reference"]) for r in selected])


def _yield_strain(rows, x, increments):
    inelastic = sorted({int(r["increment"]) for r in rows
                        if r["branch"] != "elastic"})
    if not inelastic:
        return None
    position = increments.index(inelastic[0])
    return (x[position] + x[position - 1]) / 2 if position else x[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in (ROWS, CONTRACT):
        if not path.is_file():
            print(f"missing evidence: {path}")
            return 1

    rows = _read()
    parameters, dstran = _contract()
    increments = sorted({int(r["increment"]) for r in rows})
    x, x_label = _strain_axis(rows, dstran)
    yield_x = _yield_strain(rows, x, increments)

    # Components that never move are dropped and counted. Under uniaxial
    # strain the shear sensitivities are identically zero for every constant,
    # and three more flat lines on the axis carry no information while costing
    # three legend entries.
    all_components = sorted({int(r["component"]) for r in rows
                             if r["array"] == "DSIGMA_DP"})
    stress_components, flat_components = [], []
    for component in all_components:
        moves = any(float(r["oti"]) != 0.0 for r in rows
                    if r["array"] == "DSIGMA_DP"
                    and int(r["component"]) == component)
        (stress_components if moves else flat_components).append(component)
    colours = [series_colour(i) for i in range(len(stress_components))]

    use_publication_style()
    # Constrained layout is turned off here: the shared legend sits below the
    # axes and its height has to be reserved by hand, which constrained layout
    # refuses to combine with.
    plt.rcParams["figure.constrained_layout.use"] = False
    # Two by two rather than a strip. Four panels across a 6.2 in page leaves
    # each one an inch and a half wide, which is why the labels were
    # unreadable; two by two doubles that and lets the type grow with it.
    columns = 2
    rows_needed = -(-len(parameters) // columns)
    figure, grid = plt.subplots(rows_needed, columns, figsize=(6.2, 6.0),
                                sharex=True)
    axes = list(grid.flat)
    counts: dict[str, dict] = {}

    for axis, (name, _index, value) in zip(axes, parameters):
        axis.set_title(MATHS.get(name, name), loc="center", pad=6)
        drawn: list[list[float]] = []
        style_index = 0
        for colour, component in zip(colours, stress_components):
            oti, reference = _series(rows, "DSIGMA_DP", name, component)
            if not oti:
                continue
            scaled = [value * v for v in oti]
            # Two components can coincide exactly -- transverse symmetry makes
            # sigma_22 and sigma_33 equal under uniaxial strain -- and the one
            # drawn second hides the first completely. The earlier curve is
            # widened so both remain visible.
            coincides = any(
                all(abs(a - b) <= 1e-12 * max(abs(a), abs(b), 1.0)
                    for a, b in zip(scaled, previous)) for previous in drawn)
            if coincides:
                axis.plot(x, scaled, color=colour, zorder=2, linewidth=5.5,
                          alpha=0.5)
            else:
                draw_overlay(axis, x, scaled, [value * v for v in reference],
                             colour, style=style_index)
            drawn.append(scaled)
            style_index += 1
        if yield_x is not None:
            axis.axvline(yield_x, color="0.55", linewidth=1.0,
                         linestyle=(0, (4, 3)), zorder=1)
        axis.ticklabel_format(axis="y", style="sci", scilimits=(-3, 4),
                              useMathText=True)
        counts[name] = {"components": len(stress_components),
                        "points": len(x)}

    for axis in axes[len(parameters):]:
        axis.set_visible(False)
    for axis in axes[max(0, len(parameters) - columns):len(parameters)]:
        axis.set_xlabel(x_label)
    axes[0].set_ylabel(r"$p\,\partial\sigma_{ij}/\partial p$  (MPa)")
    if len(axes) > columns:
        axes[columns].set_ylabel(r"$p\,\partial\sigma_{ij}/\partial p$  (MPa)")

    figure.suptitle(r"DSIGMA_DP per increment,  $p\,\partial\sigma/\partial p$"
                    "  (MPa)", fontsize=ANNOTATION_PT + 3.5, y=0.985)
    if yield_x is not None:
        # Inside the first row, in the space the curve vacates after yield.
        axes[0].annotate("yields here", xy=(yield_x, 0.97),
                         xycoords=axes[0].get_xaxis_transform(),
                         xytext=(5, 0), textcoords="offset points",
                         ha="left", va="top", fontsize=ANNOTATION_PT,
                         color="0.4")

    method_legend(figure, axes,
                  [COMPONENTS.get(c, str(c)) for c in stress_components],
                  colours, ncol=3, y=0.006,
                  reference_label="centred finite difference")
    if flat_components:
        omitted = ", ".join(COMPONENTS.get(c, str(c)) for c in flat_components)
        figure.text(0.5, 0.935, f"{omitted} are identically zero for every "
                    "constant and are not drawn", ha="center", va="top",
                    fontsize=ANNOTATION_PT - 1.5, color="0.45")
    figure.subplots_adjust(left=0.135, right=0.975, top=0.865, bottom=0.205,
                           hspace=0.34, wspace=0.30)

    outputs = save(figure, "figure_sensitivities", args.out_dir)
    disagreeing = sum(1 for r in rows if r["agrees"] != "True")
    write_provenance(
        "figure_sensitivities", args.out_dir, inputs=[ROWS, CONTRACT],
        outputs=outputs,
        question="How does the material point's response depend on each "
                 "material constant along the loading path, and does the "
                 "independent reference agree?",
        filters={
            "model": MODEL,
            "rows": "one per material constant for the stress, plus one for "
                    "the state variable",
            "stress_components_plotted": stress_components,
            "stress_components_omitted_as_identically_zero": flat_components,
            "layout": "two by two, one panel per material constant",
            "curve_definition": "parameter-scaled: p d(response)/dp, with p "
                                "read from the committed contract",
            "parameter_values_from_contract": {n: v for n, _i, v in parameters},
            "generated": "line", "reference": "open markers, every second point",
            "reference_method": "centred differences of the independently "
                                "compiled untransformed build",
            "axis_scale": "linear in every row; each row has its own scale, "
                          "which is why no second axis or rescaling is used",
        },
        rows={"model_rows": len(rows), "increments": len(increments),
              "disagreeing_rows": disagreeing, "per_parameter": counts},
        command="python tools/figures/build_sensitivity_figure.py",
        notes=("Agreement is shown by overlay rather than as an error "
               "statistic; the errors are reported exactly in Table 5 and the "
               "row accounting in Table 8."))
    print(f"  {outputs['png']}  ({outputs['width_inches']} x "
          f"{outputs['height_inches']} in)")
    print(f"  {len(parameters)} constant panels, "
          f"{len(stress_components)} stress components plotted "
          f"({len(flat_components)} identically zero, not drawn), "
          f"{len(x)} increments")
    print(f"  parameters from contract: {{{', '.join(f'{n}={v:g}' for n, _i, v in parameters)}}}")
    print(f"  disagreeing rows: {disagreeing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
