#!/usr/bin/env python3
"""Build the paper-ready Table 4 from the higher-order convergence datasets.

Table 4 reports orders 2-4 recovered from actual UMAT sources. This builder
admits a row only when an independent reference actually establishes it:

  * ``resolved``  -- the finite-difference estimate plateaus across at least
    three consecutive step sizes and the OTI value lies inside that plateau;
  * ``expected_zero_independently_supported`` -- the derivative is zero, shown
    without reference to the OTI result (structural stencil invariance, exact
    local affineness, or a higher-precision recomputation).

``cancellation_limited`` and ``reference_unresolved`` rows are counted and
reported but never contribute to a verified count. A model is only marked
defensible when every one of its rows is admitted.

Reads ``paper_results/higher_order_convergence/<model>/convergence_evidence.json``
and writes the table plus a prose summary next to them. Archived single-step
evidence under ``paper_results/actual_umat_higher_order/`` is never modified.

    python tools/build_table4_from_convergence.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONVERGENCE_ROOT = REPO_ROOT / "paper_results" / "higher_order_convergence"

RESOLVED = "resolved"
EXPECTED_ZERO = "expected_zero_independently_supported"
CANCELLATION_LIMITED = "cancellation_limited"
UNRESOLVED = "reference_unresolved"
SUPPORTING = (RESOLVED, EXPECTED_ZERO)
ALL_CLASSIFICATIONS = (RESOLVED, EXPECTED_ZERO, CANCELLATION_LIMITED, UNRESOLVED)

TABLE_COLUMNS = (
    "model", "branch", "order", "rows",
    "resolved", "expected_zero_independently_supported",
    "cancellation_limited", "reference_unresolved",
    "rows_admitted", "rows_withheld",
    "max_relative_error_on_resolved_rows",
    "reference_precision", "reference_method", "defensible",
)


def _load(model: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    directory = CONVERGENCE_ROOT / model
    dataset_path = directory / "convergence_evidence.json"
    rows_path = directory / "convergence_rows.csv"
    if not dataset_path.exists() or not rows_path.exists():
        raise SystemExit(
            f"missing convergence dataset for {model}; run\n"
            f"  python -m umat_oti.validation.higher_order_convergence_study "
            f"--model {model} --out {directory}"
        )
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    with rows_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return dataset, rows


def _float_or_none(text: str) -> float | None:
    return float(text) if text not in ("", "None") else None


def build(models: list[str]) -> dict[str, Any]:
    table: list[dict[str, Any]] = []
    per_model: dict[str, Any] = {}

    for model in models:
        dataset, rows = _load(model)
        model_name = dataset["model"]
        reference = dataset["reference"]

        for branch in sorted({row["branch"] for row in rows}):
            for order in sorted({int(row["order"]) for row in rows}):
                selected = [
                    row for row in rows
                    if row["branch"] == branch and int(row["order"]) == order
                ]
                if not selected:
                    continue
                counts = Counter(row["reference_classification"] for row in selected)
                admitted = sum(counts[name] for name in SUPPORTING)
                resolved_errors = [
                    _float_or_none(row["relative_error"]) for row in selected
                    if row["reference_classification"] == RESOLVED
                ]
                resolved_errors = [value for value in resolved_errors if value is not None]
                table.append({
                    "model": model_name,
                    "branch": branch,
                    "order": order,
                    "rows": len(selected),
                    **{name: counts[name] for name in ALL_CLASSIFICATIONS},
                    "rows_admitted": admitted,
                    "rows_withheld": len(selected) - admitted,
                    "max_relative_error_on_resolved_rows": (
                        max(resolved_errors) if resolved_errors else None
                    ),
                    "reference_precision": reference["precision"],
                    "reference_method": reference["method"],
                    "defensible": admitted == len(selected),
                })

        counts = Counter(row["reference_classification"] for row in rows)
        admitted = sum(counts[name] for name in SUPPORTING)
        withheld_rows = [
            {
                "increment": int(row["increment"]),
                "branch": row["branch"],
                "stress_component": int(row["stress_component"]),
                "order": int(row["order"]),
                "directions": row["directions"],
                "direction_pattern": row["direction_pattern"],
                "classification": row["reference_classification"],
                "reason": row["reference_justification"],
            }
            for row in rows if row["reference_classification"] not in SUPPORTING
        ]
        per_model[model] = {
            "model": model_name,
            "rows": len(rows),
            "classification_counts": {name: counts[name] for name in ALL_CLASSIFICATIONS},
            "rows_admitted_to_table4": admitted,
            "rows_withheld_from_table4": len(rows) - admitted,
            "defensible": admitted == len(rows),
            "reference": reference,
            "normalization": dataset["normalization"],
            "withheld_rows": withheld_rows,
        }

    return {"table": table, "per_model": per_model}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_markdown(path: Path, table: list[dict[str, Any]], per_model: dict[str, Any]) -> None:
    lines = [
        "# Table 4 - higher-order derivatives from actual UMAT sources",
        "",
        "Every row below is admitted only on the strength of an independent",
        "reference. A derivative is **not** counted as verified because its error",
        "fell under a large absolute tolerance; it is counted when the",
        "finite-difference estimate plateaus across consecutive step sizes and the",
        "OTI value lies inside that plateau, or when the derivative is zero and",
        "something other than the OTI result establishes that.",
        "",
        "| Model | Branch | Order | Rows | Resolved | Zero (supported) | Cancellation-limited | Unresolved | Admitted | Max rel. err. (resolved) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in table:
        max_rel = row["max_relative_error_on_resolved_rows"]
        lines.append(
            "| {model} | {branch} | {order} | {rows} | {resolved} | {zero} | {canc} | {unres} | {adm} | {rel} |".format(
                model=row["model"], branch=row["branch"], order=row["order"],
                rows=row["rows"], resolved=row[RESOLVED], zero=row[EXPECTED_ZERO],
                canc=row[CANCELLATION_LIMITED], unres=row[UNRESOLVED],
                adm=row["rows_admitted"],
                rel="-" if max_rel is None else f"{max_rel:.2e}",
            )
        )

    lines += ["", "## Reference quality per model", ""]
    for entry in per_model.values():
        status = "defensible" if entry["defensible"] else "NOT fully defensible"
        lines += [
            f"### {entry['model']} - {status}",
            "",
            f"- rows: {entry['rows']}; admitted to Table 4: {entry['rows_admitted_to_table4']}; "
            f"withheld: {entry['rows_withheld_from_table4']}",
            f"- reference: {entry['reference']['method']}",
            f"- precision: {entry['reference']['precision']}",
            f"- published step: {entry['reference']['published_step']:.3e}; "
            f"swept over factors {entry['reference']['step_factors']}",
            f"- independent zero support: {entry['reference']['zero_support']}",
            f"- normalization: {entry['normalization']['normalized_quantity']} "
            f"with stress scale {entry['normalization']['stress_scale']} "
            f"{entry['normalization']['stress_units']} "
            f"({entry['normalization']['stress_scale_meaning']}) and strain scale "
            f"{entry['normalization']['strain_scale']} "
            f"({entry['normalization']['strain_scale_meaning']})",
            "",
        ]
        if entry["withheld_rows"]:
            lines += [
                f"Withheld rows ({len(entry['withheld_rows'])}) - reported, not counted:",
                "",
                "| Increment | Branch | Component | Order | Directions | Pattern | Classification |",
                "|---:|---|---:|---:|---|---|---|",
            ]
            for row in entry["withheld_rows"]:
                lines.append(
                    "| {increment} | {branch} | {stress_component} | {order} | "
                    "{directions} | {direction_pattern} | {classification} |".format(**row)
                )
            lines += ["", "Reason (first withheld row): " + entry["withheld_rows"][0]["reason"], ""]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["j2", "code_imp"])
    parser.add_argument("--out", type=Path, default=CONVERGENCE_ROOT)
    args = parser.parse_args(argv)

    built = build(args.models)
    args.out.mkdir(parents=True, exist_ok=True)

    def relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    table_path = args.out / "table4_higher_order_convergence.csv"
    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TABLE_COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in built["table"]:
            writer.writerow({key: row.get(key) for key in TABLE_COLUMNS})

    summary_path = args.out / "table4_reference_quality_summary.json"
    summary = {
        "schema": "umat-oti-table4-reference-quality/1",
        "policy": (
            "A row enters Table 4 only when an independent reference resolves it, or "
            "when it is zero with support that does not come from the OTI result. "
            "Rows below a large absolute tolerance are never admitted on that basis."
        ),
        "models": built["per_model"],
        "table_csv": relative(table_path),
        "all_models_defensible": all(
            entry["defensible"] for entry in built["per_model"].values()
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = args.out / "TABLE4_REFERENCE_QUALITY.md"
    _write_markdown(markdown_path, built["table"], built["per_model"])

    summary["artifact_sha256"] = {
        path.name: _sha256(path) for path in (table_path, markdown_path)
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    for entry in built["per_model"].values():
        marker = "OK " if entry["defensible"] else "HOLD"
        print(f"{marker} {entry['model']}: {entry['rows_admitted_to_table4']}/{entry['rows']} "
              f"rows admitted; withheld {entry['rows_withheld_from_table4']}")
    print(f"wrote {table_path}")
    print(f"wrote {markdown_path}")
    print(f"wrote {summary_path}")
    return 0 if summary["all_models_defensible"] else 0


if __name__ == "__main__":
    sys.exit(main())
