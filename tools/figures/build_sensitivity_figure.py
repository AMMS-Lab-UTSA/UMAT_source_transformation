#!/usr/bin/env python3
"""How does the material point's response depend on its material constants?

Two aligned panels, one physical quantity each: stress in the upper, the state
variable in the lower. Both are shown along the whole loading path, and the
increment where the material yields is marked once.

Every curve is scaled by its own parameter, p*d(response)/dp, taken from the
committed contract that drove the run. That makes each stress curve a stress in
MPa and each state curve a strain, so the four constants are comparable rather
than being ranked by the size of the numbers used to write them down. The
parameter values are read from the contract, never written here: an earlier
version of this figure carried E = 200000 MPa while the run used 210000, and
nothing could notice.

Row-adjudication counts are deliberately absent. They answer a different
question -- how many comparisons the reference could settle -- and they are
reported in the validation table instead of competing with the response curves.
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
    ANNOTATION_PT, LINESTYLES, MARKERS, PALETTE, REPO_ROOT, figure, save,
    use_publication_style, write_provenance,
)

ROWS = (REPO_ROOT / "paper_results" / "parameter_sensitivity"
        / "table6_comparison_rows.csv")
CONTRACT = REPO_ROOT / "parameter_sensitivity" / "contracts" / "m3_j2.json"
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

MODEL = "m3_j2"
STRESS_COMPONENT = 1
STATE_COMPONENT = 1

#: Printed name for each contract parameter, and the unit of p*d(sigma)/dp.
MATHS = {"E": "$E$", "nu": r"$\nu$", "SIGY0": r"$\sigma_{y0}$", "H": "$H$"}

#: A curve whose largest value is below this fraction of the panel's largest is
#: drawn against its own axis on the right. Sharing one linear axis would draw
#: it flat on zero; sharing a logarithmic one would put its exact zeros
#: nowhere at all.
SECOND_AXIS_FRACTION = 0.02


def _read_rows() -> list[dict]:
    with ROWS.open(newline="", encoding="utf-8") as handle:
        return [r for r in csv.DictReader(handle) if r["model"] == MODEL]


def _contract_parameters() -> list[tuple[str, int, float]]:
    """Name, PROPS index and value, in PROPS order, from the committed contract."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    entries = []
    static = (contract.get("material_point_driver") or {}).get("static_props") or []
    for parameter in contract["parameters"]:
        index = int(parameter["props_index"])
        value = parameter.get("value")
        if value is None and index <= len(static):
            value = static[index - 1]
        if value is None:
            raise SystemExit(
                f"the contract gives no value for {parameter['name']!r}; a "
                "scaled curve cannot be drawn without one, and inventing one "
                "would be worse than leaving the parameter out")
        entries.append((str(parameter["name"]), index, float(value)))
    return sorted(entries, key=lambda e: e[1])


def _series(rows: list[dict], array: str, parameter: str, component: int):
    selected = sorted(
        (r for r in rows if r["array"] == array and r["parameter"] == parameter
         and int(r["component"]) == component),
        key=lambda r: int(r["increment"]))
    return ([int(r["increment"]) for r in selected],
            [float(r["oti"]) for r in selected])


def _yield_increment(rows: list[dict]) -> int | None:
    inelastic = sorted({int(r["increment"]) for r in rows
                        if r["branch"] != "elastic"})
    return inelastic[0] if inelastic else None


def _mark_yield(axis, yield_increment: int | None, label: bool) -> None:
    """One thin rule where the material yields, and no background shading."""
    if yield_increment is None:
        return
    axis.axvline(yield_increment - 0.5, color="0.35", linewidth=1.0,
                 linestyle=(0, (4, 3)), zorder=1)
    if label:
        axis.annotate(f"yields at increment {yield_increment}",
                      xy=(yield_increment - 0.5, 0.5),
                      xycoords=axis.get_xaxis_transform(),
                      xytext=(-6, 0), textcoords="offset points",
                      ha="right", va="center", rotation=90,
                      fontsize=ANNOTATION_PT, color="0.3")


def _direct_label(axis, x, y, text, colour, dy=0.0) -> None:
    axis.annotate(text, xy=(x[-1], y[-1]), xytext=(5, dy),
                  textcoords="offset points", ha="left", va="center",
                  fontsize=ANNOTATION_PT, color=colour, fontweight="bold",
                  annotation_clip=False)


def _align_zero(axis, twin, low_value: float, high_value: float) -> None:
    """Put the two axes' zeros at the same height, without squashing the data.

    Two things go wrong if this is left to matplotlib. The right-hand curve's
    zero lands wherever its own data puts it, so a curve that is exactly zero
    until the material yields gets drawn along the top of the panel and reads
    as the largest response rather than the smallest. And sizing the axis from
    the larger of the two extents inflates it: the hardening curve reached 0.4
    on an axis that ran to 9.

    The limits are computed from the data instead: the span is whatever is
    needed to hold both ends once zero is pinned at the required fraction.
    """
    low, high = axis.get_ylim()
    if high <= low:
        return
    fraction = min(max((0.0 - low) / (high - low), 0.02), 0.98)
    above = max(high_value, 0.0) * 1.08
    below = min(low_value, 0.0) * 1.08
    span = max(above / (1.0 - fraction) if above > 0 else 0.0,
               -below / fraction if below < 0 else 0.0)
    if span <= 0:
        return
    twin.set_ylim(-span * fraction, span * (1.0 - fraction))


def _panel(axis, rows, parameters, array, component, ylabel, title,
           yield_increment, label_yield):
    """One physical quantity, with any far smaller curve on its own axis."""
    scaled: dict[str, tuple[list[int], list[float]]] = {}
    for name, _index, value in parameters:
        increments, raw = _series(rows, array, name, component)
        if increments:
            scaled[name] = (increments, [value * v for v in raw])
    if not scaled:
        return {}

    largest = {name: max(abs(v) for v in values)
               for name, (_, values) in scaled.items()}
    panel_scale = max(largest.values()) or 1.0
    minor = [n for n, m in largest.items() if m < panel_scale * SECOND_AXIS_FRACTION]
    major = [n for n in scaled if n not in minor]

    _mark_yield(axis, yield_increment, label_yield)
    for index, name in enumerate(major):
        increments, values = scaled[name]
        axis.plot(increments, values, color=PALETTE[index],
                  linestyle=LINESTYLES[index], marker=MARKERS[index],
                  markevery=4, markerfacecolor="none")
        _direct_label(axis, increments, values, MATHS.get(name, name),
                      PALETTE[index])

    twin = None
    if minor:
        twin = axis.twinx()
        twin.grid(False)
        twin.spines["top"].set_visible(False)
        for offset, name in enumerate(minor):
            colour = PALETTE[len(major) + offset]
            increments, values = scaled[name]
            twin.plot(increments, values, color=colour,
                      linestyle=LINESTYLES[(len(major) + offset) % len(LINESTYLES)],
                      marker=MARKERS[(len(major) + offset) % len(MARKERS)],
                      markevery=4, markerfacecolor="none")
            _direct_label(twin, increments, values, MATHS.get(name, name),
                          colour, dy=-13)
        twin.set_ylabel(f"{', '.join(MATHS.get(n, n) for n in minor)} only "
                        f"(right axis)", fontsize=ANNOTATION_PT,
                        color=PALETTE[len(major)])
        twin.tick_params(axis="y", labelsize=ANNOTATION_PT,
                         colors=PALETTE[len(major)])
        twin.ticklabel_format(axis="y", style="sci", scilimits=(-2, 3),
                              useMathText=True)
        minor_values = [v for name in minor for v in scaled[name][1]]
        _align_zero(axis, twin, min(minor_values), max(minor_values))

    axis.set_ylabel(ylabel)
    axis.set_title(title, loc="left")
    axis.ticklabel_format(axis="y", style="sci", scilimits=(-2, 3),
                          useMathText=True)
    return {"plotted": {n: len(v[0]) for n, v in scaled.items()},
            "on_second_axis": minor,
            "largest_absolute_value": {n: float(m) for n, m in largest.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in (ROWS, CONTRACT):
        if not path.is_file():
            print(f"missing evidence: {path}")
            return 1

    rows = _read_rows()
    parameters = _contract_parameters()
    yield_increment = _yield_increment(rows)

    use_publication_style()
    fig, axes = plt.subplots(2, 1, figsize=(6.2, 5.6), sharex=True)
    upper = _panel(
        axes[0], rows, parameters, "DSIGMA_DP", STRESS_COMPONENT,
        r"$p\,\partial\sigma_{11}/\partial p$  (MPa)",
        "(a) Stress response to each material constant",
        yield_increment, label_yield=True)
    lower = _panel(
        axes[1], rows, parameters, "DSTATEV_DP", STATE_COMPONENT,
        r"$p\,\partial\bar\varepsilon^{\,p}/\partial p$  (dimensionless)",
        "(b) Equivalent plastic strain response to each material constant",
        yield_increment, label_yield=False)
    axes[1].set_xlabel("increment along the loading path")
    axes[1].set_xticks(range(2, max(int(r["increment"]) for r in rows) + 1, 2))
    for axis in axes:
        # Room at the right for the direct labels, which sit outside the axes.
        axis.margins(x=0.10)

    outputs = save(fig, "figure_sensitivities", args.out_dir)

    values = {name: value for name, _index, value in parameters}
    disagreeing = sum(1 for r in rows if r["agrees"] != "True")
    write_provenance(
        "figure_sensitivities", args.out_dir, inputs=[ROWS, CONTRACT],
        outputs=outputs,
        question="How does the material point's response depend on each "
                 "material constant, along the whole loading path?",
        filters={
            "model": MODEL,
            "stress_component": STRESS_COMPONENT,
            "state_component": STATE_COMPONENT,
            "increments": f"1-{max(int(r['increment']) for r in rows)}, the "
                          "complete path, no selection",
            "curve_definition": "parameter-scaled: p * d(response)/dp, with p "
                                "read from the committed contract",
            "parameter_values_from_contract": values,
            "second_axis": {"panel_a": upper.get("on_second_axis"),
                            "panel_b": lower.get("on_second_axis")},
            "axis_scale": "linear in both panels; no logarithmic axis is used, "
                          "so the exact zeros before yield are plotted where "
                          "they belong",
        },
        rows={"model_rows": len(rows),
              "first_inelastic_increment": yield_increment,
              "disagreeing_rows": disagreeing,
              "panel_a": upper, "panel_b": lower},
        command="python tools/figures/build_sensitivity_figure.py",
        notes=("Row-adjudication counts are reported in the validation table, "
               "not here: they answer how many comparisons the reference could "
               "settle, which is a different question from how the material "
               "responds."))
    print(f"  {outputs['png']}  ({outputs['width_inches']} x "
          f"{outputs['height_inches']} in)")
    print(f"  parameters from contract: {values}")
    print(f"  second axis: (a) {upper.get('on_second_axis')} "
          f"(b) {lower.get('on_second_axis')}")
    print(f"  {len(rows)} rows, yields at {yield_increment}, "
          f"{disagreeing} disagreeing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
