"""What ``umat-oti check`` shows when the pipeline has finished.

The pipeline writes a summary of every stage (about 50 KB of JSON) and a CSV of
every checked entry whose first value column is called ``oti``. A person wants
a short answer and the derivative values with names on them, so:

* :func:`results_table` writes ``results_table.txt`` and ``results_table.csv``:
  d(stress component)/d(constant) and d(state variable)/d(constant) at the
  last increment, one named column per constant, each value next to the
  finite-difference value it was checked against and what the check said;
* :func:`facts` reads the headline numbers (how many entries agree, the worst
  relative difference, whether the loading left the elastic range);
* :func:`render` puts the one-page verdict from
  :mod:`umat_oti.app.verdict_page` first and those facts under it.

Nothing here decides whether anything is verified: that stays with the verdict
page (green only when all six checks held) and the pipeline's own check.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Optional

from umat_oti.app.verdict_page import render_verdict

STRESS_NAMES = ("11", "22", "33", "12", "13", "23")

#: What the checker's per-entry verdicts mean, in words.
AGREEMENT = {"agrees": "agrees",
             "consistent_with_zero": "zero (the check agrees it is zero)",
             "reference_unresolved": "not checkable (the reference could not resolve it)",
             "disagrees": "DISAGREES"}

_PLAIN_STAGE = {"material_settings": "reading the material", "dependencies": "finding helper routines",
                "parameters": "choosing the parameters", "jacobian": "converting the routine",
                "sensitivities": "checking the derivatives", "abaqus": "the Abaqus run"}


def _load(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verification_paths(out: Path) -> tuple:
    folder = Path(out) / "sensitivities" / "verification"
    return folder / "verification.json", folder / "verification_entries.csv"


def _entries(csv_path: Path) -> list:
    try:
        with open(csv_path, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _name_of(array: str, component: int) -> str:
    if array == "DSIGMA_DP":
        return "stress " + (STRESS_NAMES[component - 1] if component <= len(STRESS_NAMES) else str(component))
    if array == "DSTATEV_DP":
        return f"state variable {component}"
    return f"{array} {component}"


def _tables(rows: list) -> list:
    """One table per derivative array (stress, state) at its last increment."""
    out = []
    for array, title in (("DSIGMA_DP", "stress"), ("DSTATEV_DP", "state variable")):
        mine = [r for r in rows if r["array"] == array]
        if not mine:
            continue
        last = max(int(r["increment"]) for r in mine)
        mine = [r for r in mine if int(r["increment"]) == last]
        columns = list(dict.fromkeys(r["column"] for r in mine))
        components = sorted({int(r["component"]) for r in mine})
        cells = {(int(r["component"]), r["column"]): r for r in mine}
        out.append({"array": array, "title": title, "increment": last, "columns": columns,
                    "components": components, "cells": cells})
    return out


def _number(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return math.nan


def results_table(out: Path) -> Optional[dict]:
    """Write ``results_table.txt`` and ``results_table.csv`` beside the results.

    Returns ``{"text": path, "csv": path}`` or ``None`` when there is no
    verification to tabulate (the pipeline stopped earlier).
    """
    out = Path(out)
    _, csv_path = verification_paths(out)
    rows = _entries(csv_path)
    tables = _tables(rows)
    if not tables:
        return None
    lines, named = [], [["quantity", "component", "constant", "derivative",
                         "finite_difference_reference", "relative_difference",
                         "agreement", "increment"]]
    for table in tables:
        lines.append(f"d({table['title']}) / d(constant), at the last increment "
                     f"({table['increment']}) of the path")
        width = max(15, *(len(c) + 3 for c in table["columns"]))
        lines.append(" " * 20 + "".join(f"{c:>{width}}" for c in table["columns"]))
        for component in table["components"]:
            label = _name_of(table["array"], component)
            cells = [table["cells"].get((component, c)) for c in table["columns"]]
            lines.append(f"{label:<20}" + "".join(
                f"{_number(cell['oti']):>{width}.6g}" if cell else f"{'-':>{width}}" for cell in cells))
            for column, cell in zip(table["columns"], cells):
                if cell:
                    named.append([table["title"], label, column, cell["oti"], cell["reference"],
                                  cell["relative_error"], AGREEMENT.get(cell["verdict"], cell["verdict"]),
                                  table["increment"]])
        counts = []
        for column in table["columns"]:
            mine = [table["cells"][(k, column)] for k in table["components"] if (k, column) in table["cells"]]
            good = sum(1 for r in mine if r["verdict"] in ("agrees", "consistent_with_zero"))
            counts.append(f"{column} {good} of {len(mine)}")
        lines.append("Entries that match the numerical check of your original routine: " + "; ".join(counts))
        lines.append("")
    lines.append("'Local' here is the derivative of the stress update of one increment at the recorded "
                 "state (the checker's DSIGMA_DP / DSTATEV_DP). Every increment, and the derivative "
                 "carried along the whole path, are in sensitivities/verification/verification_entries.csv.")
    text_path, csv_out = out / "results_table.txt", out / "results_table.csv"
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(csv_out, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(named)
    return {"text": text_path, "csv": csv_out}


def _tangent_changed(rows: list) -> Optional[bool]:
    """Did the tangent (DDSDDE, the checker's per-increment copy) change along the path?"""
    series: dict = {}
    for r in rows:
        if r["array"] == "DDSDDE":
            series.setdefault((r["column"], r["component"]), []).append(
                (int(r["increment"]), _number(r["oti"])))
    if not series:
        return None
    scale = max((abs(v) for values in series.values() for _, v in values if math.isfinite(v)), default=0.0)
    if scale == 0.0:
        return None
    span = max((max(v for _, v in values) - min(v for _, v in values)) for values in series.values())
    return span / scale > 1e-6


def facts(out: Path) -> dict:
    """The headline numbers of a finished check (empty where there was no verification)."""
    json_path, csv_path = verification_paths(out)
    verification = _load(json_path)
    if verification is None:
        return {}
    comparisons = verification.get("comparisons") or {}
    arrays = verification.get("arrays") or {}
    worst = max((a.get("worst_relative_error_agreeing") or 0.0 for a in arrays.values()), default=0.0)
    rows = _entries(csv_path)
    growth = verification.get("state_growth")
    changed = _tangent_changed(rows)
    parameters = list(dict.fromkeys(r["column"] for r in rows if r["array"] == "DSIGMA_DP"))
    if (growth or 0.0) > 0.0:
        nonlinear = (True, f"yes: the internal state variables left zero (largest value "
                           f"{growth:.3g} at the end of the path)")
    elif changed:
        nonlinear = (True, "yes: the stiffness changed along the path")
    elif growth is not None and changed is False:
        nonlinear = (False, "NO: neither the internal state nor the stiffness changed, so this path "
                            "only exercised the elastic behaviour; strain it further with --peak")
    else:
        nonlinear = (None, "cannot tell from this run")
    return {"verdict": verification.get("verdict"), "increments": verification.get("increments"),
            "parameters": parameters, "agree": comparisons.get("verified_entries", 0),
            "zero": comparisons.get("consistent_with_zero", 0),
            "unresolved": comparisons.get("reference_unresolved", 0),
            "disagree": comparisons.get("disagreeing", 0), "worst": worst,
            "tolerance": (verification.get("criterion") or {}).get("relative_tolerance"),
            "nonlinear": nonlinear}


def render(summary: dict, out: Path, *, state: str = "", reason: str = "",
           stage: str = "") -> str:
    """The text a person reads at the end: verdict first, then what was found."""
    out = Path(out)
    record = dict(summary)
    if state:
        record["terminal_state"], record["reason"] = state, reason
    lines = [render_verdict(record), ""]
    found = facts(out)
    if stage and stage in _PLAIN_STAGE:
        lines.append(f"The run stopped while {_PLAIN_STAGE[stage]}.")
    if found:
        names = ", ".join(found["parameters"]) or "none"
        lines.append(f"Constants checked ({len(found['parameters'])}): {names}"
                     + (f"; {found['increments']} increments of loading." if found["increments"] else "."))
        lines.append(f"Derivatives: {found['agree']} entries agree with finite differences of your "
                     f"original routine, {found['zero']} are zero in both, {found['disagree']} disagree"
                     + (f", {found['unresolved']} could not be checked" if found["unresolved"] else "")
                     + (f"; worst relative difference {found['worst']:.2g}"
                        + (f" (tolerance {found['tolerance']:g})" if found["tolerance"] else "")
                        if found["agree"] else "") + ".")
        lines.append("Loading reached the nonlinear range: " + found["nonlinear"][1] + ".")
    tables = results_table(out)
    if tables:
        lines.append(f"The derivatives, with names: {tables['text']}  (and {tables['csv'].name})")
    lines.append(f"Everything the run recorded: {out / 'workflow_summary.json'}")
    return "\n".join(lines)
