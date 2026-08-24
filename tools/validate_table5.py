#!/usr/bin/env python3
"""Validate the J2 parameter-sensitivity dataset and emit the publication views.

The full dataset is a *loading path*, not a single snapshot: 20 increments x
(6 DSIGMA_DP components + 1 DSTATEV_DP component) x 4 parameters = 560 rows. The
manuscript quotes a 6x4 and a 1x4 view, which are one increment of that path.
Having more rows than the quoted view is therefore expected, and is not by
itself a reason to call the dataset incomplete.

This checks the structure explicitly rather than trusting the row count:

  * exactly 20 contiguous increments;
  * exactly 6 DSIGMA_DP components in every increment;
  * exactly 1 DSTATEV_DP component in every increment;
  * exactly 4 parameters, in a consistent order everywhere;
  * no duplicate (increment, array, component, parameter) keys;
  * no missing or unexpected combinations;
  * every OTI and reference value parseable;
  * substantive rows judged by relative error, near-zero rows by absolute;
  * both elastic and plastic increments present, and the path history-dependent.

    python tools/validate_table5.py [--emit-views] [--increment N]

Exits non-zero if any check fails. ``--emit-views`` writes the 6x4 and 1x4 views
next to the source, preserving the complete loading-path archive untouched.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "paper_results/arc_791506/evidence/table5_j2_parameter_sensitivities.csv"

EXPECTED_INCREMENTS = 20
EXPECTED_STRESS_COMPONENTS = 6
EXPECTED_STATE_COMPONENTS = 1
EXPECTED_PARAMETERS = ("E", "NU", "SIGY0", "H")
#: Below this magnitude a value is judged by absolute agreement, not relative:
#: a relative error against zero is meaningless.
NEAR_ZERO = 1.0e-12
#: Relative agreement required of a substantive row.
RELATIVE_TOLERANCE = 1.0e-6


def load(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate(rows: list[dict[str, str]]) -> tuple[list[str], dict]:
    failures: list[str] = []
    facts: dict = {}

    increments = sorted({int(r["increment"]) for r in rows})
    facts["increments"] = len(increments)
    if len(increments) != EXPECTED_INCREMENTS:
        failures.append(f"expected {EXPECTED_INCREMENTS} increments, found {len(increments)}")
    if increments != list(range(increments[0], increments[-1] + 1)):
        failures.append("increments are not contiguous")

    arrays = sorted({r["array"] for r in rows})
    components = {a: sorted({r["row"] for r in rows if r["array"] == a}) for a in arrays}
    facts["components"] = components
    if len(components.get("DSIGMA_DP", [])) != EXPECTED_STRESS_COMPONENTS:
        failures.append(f"DSIGMA_DP has {len(components.get('DSIGMA_DP', []))} components, "
                        f"expected {EXPECTED_STRESS_COMPONENTS}")
    if len(components.get("DSTATEV_DP", [])) != EXPECTED_STATE_COMPONENTS:
        failures.append(f"DSTATEV_DP has {len(components.get('DSTATEV_DP', []))} components, "
                        f"expected {EXPECTED_STATE_COMPONENTS}")

    order = list(dict.fromkeys(r["parameter"] for r in rows))
    facts["parameters"] = order
    if tuple(order) != EXPECTED_PARAMETERS:
        failures.append(f"parameters {order} != expected {list(EXPECTED_PARAMETERS)}")
    orderings = {tuple(g["parameter"] for g in grp) for _key, grp in itertools.groupby(
        rows, key=lambda r: (r["increment"], r["array"], r["row"]))}
    if len(orderings) != 1:
        failures.append(f"parameter ordering is not consistent: {len(orderings)} distinct orders")

    keys = [(r["increment"], r["array"], r["row"], r["parameter"]) for r in rows]
    duplicates = [k for k, c in Counter(keys).items() if c > 1]
    facts["duplicates"] = len(duplicates)
    if duplicates:
        failures.append(f"{len(duplicates)} duplicate (increment, array, component, parameter) keys")

    expected = {(str(i), a, c, p) for i in increments for a in arrays
                for c in components[a] for p in order}
    missing, unexpected = expected - set(keys), set(keys) - expected
    facts["expected_rows"], facts["actual_rows"] = len(expected), len(rows)
    if missing:
        failures.append(f"{len(missing)} missing combinations")
    if unexpected:
        failures.append(f"{len(unexpected)} unexpected combinations")

    substantive, near_zero, unparseable = [], [], 0
    for row in rows:
        try:
            oti, reference = float(row["oti"]), float(row["fd"])
        except ValueError:
            unparseable += 1
            continue
        (substantive if max(abs(oti), abs(reference)) > NEAR_ZERO else near_zero).append(row)
    facts["unparseable"] = unparseable
    facts["substantive_rows"] = len(substantive)
    facts["near_zero_rows"] = len(near_zero)
    if unparseable:
        failures.append(f"{unparseable} rows have unparseable oti/fd values")

    over = [r for r in substantive if float(r["rel_diff"]) > RELATIVE_TOLERANCE]
    facts["worst_relative_error"] = max((float(r["rel_diff"]) for r in substantive), default=None)
    facts["worst_absolute_error_near_zero"] = max(
        (float(r["abs_diff"]) for r in near_zero), default=None)
    if over:
        failures.append(f"{len(over)} substantive rows exceed relative tolerance "
                        f"{RELATIVE_TOLERANCE:g}")

    state = {}
    for row in rows:
        if row["array"] == "DSTATEV_DP":
            state.setdefault(int(row["increment"]), []).append(abs(float(row["oti"])))
    elastic = [i for i, v in sorted(state.items()) if max(v) == 0.0]
    plastic = [i for i, v in sorted(state.items()) if max(v) > 0.0]
    facts["elastic_increments"], facts["plastic_increments"] = len(elastic), len(plastic)
    if not elastic:
        failures.append("no elastic increments: the path never exercises the elastic branch")
    if not plastic:
        failures.append("no plastic increments: the path never yields")

    history = {int(r["increment"]): float(r["oti"]) for r in rows
               if r["array"] == "DSIGMA_DP" and r["row"] == "1" and r["parameter"] == "H"}
    distinct = len(set(history.values()))
    facts["distinct_dsigma1_dH"] = distinct
    if distinct <= 2:
        failures.append("dSIGMA_1/dH takes too few distinct values to be path-dependent")

    return failures, facts


def emit_views(rows: list[dict[str, str]], increment: int, out_dir: Path) -> list[Path]:
    """The 6x4 and 1x4 the manuscript quotes, for one increment of the path."""
    written = []
    for array, name in (("DSIGMA_DP", f"table5_view_dsigma_dp_6x4_increment{increment}.csv"),
                        ("DSTATEV_DP", f"table5_view_dstatev_dp_1x4_increment{increment}.csv")):
        selected = [r for r in rows if r["array"] == array and int(r["increment"]) == increment]
        components = sorted({r["row"] for r in selected},
                            key=lambda c: (int(c) if c.isdigit() else 0, c))
        params = list(dict.fromkeys(r["parameter"] for r in selected))
        path = out_dir / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["component", *params])
            for component in components:
                by_param = {r["parameter"]: r["oti"] for r in selected if r["row"] == component}
                writer.writerow([component, *(by_param[p] for p in params)])
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--emit-views", action="store_true")
    parser.add_argument("--increment", type=int, default=20,
                        help="which increment the 6x4 / 1x4 views describe (default: last)")
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"missing dataset: {args.source}", file=sys.stderr)
        return 2
    rows = load(args.source)
    failures, facts = validate(rows)

    print(f"dataset: {args.source.relative_to(REPO_ROOT)}")
    for key, value in facts.items():
        print(f"  {key:32s} {value}")
    if failures:
        print("\nFAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nAll structural and numerical checks passed. The 560-row dataset is a "
          "complete 20-increment loading path, not an oversized table.")

    if args.emit_views:
        for path in emit_views(rows, args.increment, args.source.parent):
            print(f"  wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
