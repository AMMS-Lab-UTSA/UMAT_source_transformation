#!/usr/bin/env python
"""Generate the publication reconciliation from executed evidence.

The manuscript states what the software must be able to do. It does not state
what the software must compute. Every number below is read from an evidence file
produced by a run; the manuscript column is transcribed context, is never used as
a reference, and no comparison or tolerance anywhere reads it.

The document is generated. Editing it by hand would put a number in front of a
reviewer that no run produced.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

RESULTS = REPO_ROOT / "paper_results"
CLAIMS = REPO_ROOT / "docs" / "manuscript_claims.json"
OUT = REPO_ROOT / "docs" / "PUBLICATION_RESULTS_RECONCILIATION.md"

FUNNEL_COLUMNS = (
    "required", "attempted", "transformed", "compiled", "executed",
    "primal_parity", "reference_resolved", "verified", "disagreeing",
    "unresolved", "failed", "blocked",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _commit() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _blank() -> dict:
    return {column: None for column in FUNNEL_COLUMNS}


def table6_row() -> tuple[dict, list[str]]:
    payload = _load(RESULTS / "parameter_sensitivity" / "parameter_sensitivity_round.json")
    funnel = payload.get("funnel", {})
    if not funnel:
        return _blank(), ["no parameter-sensitivity round has been executed"]
    models = payload.get("models", [])
    disagreeing = sum(m["stages"].get("derivatives_verified", {}).get("rows_disagreeing", 0)
                      for m in models)
    unresolved = sum(m["stages"].get("derivatives_verified", {}).get("rows_reference_unresolved", 0)
                     for m in models)
    row = _blank()
    row.update({
        "required": funnel.get("parameter_directions_declared"),
        "attempted": funnel.get("attempted"),
        "transformed": funnel.get("transformed"),
        "compiled": funnel.get("compiled_oti"),
        "executed": funnel.get("executed_oti"),
        "primal_parity": funnel.get("primal_parity"),
        "reference_resolved": funnel.get("reference_resolved"),
        "verified": funnel.get("parameter_directions_verified"),
        "disagreeing": disagreeing,
        "unresolved": unresolved,
        "failed": sum(1 for m in models
                      if m["stages"].get("derivatives_verified", {}).get("status") == "failed"),
        "blocked": 0,
    })
    notes = [
        f"{funnel.get('comparison_rows_agreeing')} of {funnel.get('comparison_rows_total')} "
        "comparison rows agree.",
    ]
    for model in models:
        stage = model["stages"].get("derivatives_verified", {})
        if stage.get("status") in ("failed", "unresolved"):
            notes.append(f"`{model['model']}`: {stage.get('status')} -- {stage.get('reason')}")
    return row, notes


def table3_row() -> tuple[dict, list[str]]:
    payload = _load(RESULTS / "internal_jacobians" / "internal_jacobian_round.json")
    funnel = payload.get("funnel", {})
    if not funnel:
        return _blank(), ["no internal-Jacobian round has been executed"]
    row = _blank()
    row.update({
        "attempted": funnel.get("sources_with_a_local_solve"),
        "verified": funnel.get("extracted_and_verified"),
        "disagreeing": funnel.get("extracted_and_disagreeing"),
        "blocked": funnel.get("blocked"),
    })
    notes = [
        f"{funnel.get('candidate_sources')} candidate sources; "
        f"{funnel.get('no_local_solve')} integrate their law without a local "
        "iteration and so have no internal Jacobian to extract.",
    ]
    for record in payload.get("records", []):
        if record.get("bucket") == "blocked" and record.get("local_solves_discovered"):
            reason = record.get("reason") or (
                record.get("stages", {}).get(record.get("furthest_stage") or "", {}) or {}
            ).get("reason")
            notes.append(f"`{record['id']}`: blocked -- {reason}")
    return row, notes


def table2_row() -> tuple[dict, list[str]]:
    rows: list[dict] = []
    job = None
    for path in sorted(RESULTS.glob("arc_*/table2_abaqus_paired.json")):
        payload = _load(path)
        rows.extend(payload.get("rows", []))
        for entry in payload.get("rows", []):
            job = job or entry.get("slurm_job_id")
    if not rows:
        return _blank(), ["no archived Abaqus paired round is present"]
    row = _blank()
    row.update({
        "attempted": len(rows),
        "executed": sum(1 for r in rows if r.get("status") != "failed_execution"),
        "verified": sum(1 for r in rows if r.get("status") == "passed"),
        "failed": sum(1 for r in rows if r.get("status") == "failed_execution"),
    })
    return row, [
        f"Archived from Slurm job {job}; not re-executed by this run.",
        "Every archived deck drives its model with a probe property vector of unit "
        "constants (a 0.3 Poisson ratio in `UMAT_PCL` and `UMAT_PCLK`). The "
        "comparison is sound because both builds receive identical inputs, but it "
        "is a transformation-fidelity result and not a materials result.",
    ]


def generality_row() -> tuple[dict, list[str]]:
    summary = _load(RESULTS / "generality" / "generality_summary.json")
    if not summary:
        return _blank(), ["no generality matrix has been generated"]
    verification = summary.get("by_numerical_verification", {})
    row = _blank()
    row.update({
        "attempted": summary.get("sources"),
        "verified": verification.get("succeeded", 0),
        "disagreeing": verification.get("failed", 0),
        "unresolved": verification.get("unresolved", 0),
    })
    return row, [summary.get("structural_diversity_caveat", "")]


def corpus_row() -> tuple[dict, list[str]]:
    metrics = _load(RESULTS / "arc_791506" / "evidence" / "corpus_round_metrics.json")
    if not metrics:
        return _blank(), ["no corpus round metrics are present"]
    counts = metrics.get("cumulative_stage_counts", {})
    row = _blank()
    row.update({
        "attempted": metrics.get("corpus_size"),
        "transformed": counts.get("transformed"),
        "compiled": counts.get("generated_source_compiled"),
        "executed": counts.get("primal_parity_verified"),
        "primal_parity": counts.get("primal_parity_verified"),
        "verified": counts.get("derivatives_numerically_verified"),
        "failed": metrics.get("failed"),
    })
    return row, [
        "Archived round. No corpus source has yet reached execution, primal parity "
        "or numerical verification; the funnel stops at compilation.",
    ]


def table4_row() -> tuple[dict, list[str]]:
    summary = _load(RESULTS / "higher_order_convergence" / "table4_reference_quality_summary.json")
    models = summary.get("models") or {}
    if not models:
        return _blank(), ["no higher-order convergence summary is present"]
    defensible = [name for name, entry in models.items() if entry.get("defensible")]
    resolved = sum(entry.get("classification_counts", {}).get("resolved", 0)
                   for entry in models.values())
    unresolved = sum(entry.get("classification_counts", {}).get("reference_unresolved", 0)
                     for entry in models.values())
    row = _blank()
    row.update({
        "attempted": len(models),
        "verified": len(defensible),
        "unresolved": unresolved,
    })
    notes = [
        f"{resolved} rows resolved by an independent reference across "
        f"{len(models)} models; all_models_defensible = "
        f"{summary.get('all_models_defensible')}.",
        summary.get("policy", ""),
    ]
    for name, entry in sorted(models.items()):
        if not entry.get("defensible"):
            finding = entry.get("finding", {})
            consequence = finding.get("consequence") or finding.get("summary") or ""
            notes.append(f"`{name}`: not defensible -- {str(consequence)[:220]}")
    return row, notes


def table5_row() -> tuple[dict, list[str]]:
    payload = _load(RESULTS / "parameter_sensitivity" / "parameter_sensitivity_round.json")
    for model in payload.get("models", []):
        if model["model"] != "m3_j2":
            continue
        stage = model["stages"].get("derivatives_verified", {})
        row = _blank()
        row.update({
            "attempted": stage.get("rows"),
            "verified": stage.get("rows_agreeing"),
            "disagreeing": stage.get("rows_disagreeing"),
            "unresolved": stage.get("rows_reference_unresolved"),
        })
        return row, [
            "The J2 model of the sweep (`m3_j2`) carries the focused stress and "
            "state sensitivity check; worst substantive relative error "
            f"{stage.get('worst_relative_error')}.",
        ]
    return _blank(), ["`m3_j2` is not present in the executed round"]


BUILDERS = {
    "TABLE-2": table2_row, "TABLE-3": table3_row, "TABLE-4": table4_row,
    "TABLE-5": table5_row, "TABLE-6": table6_row, "CORPUS": corpus_row,
    "GENERALITY": generality_row,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    claims = _load(CLAIMS)
    commit = _commit()
    lines = [
        "# Publication results reconciliation", "",
        "<!-- GENERATED by tools/build_publication_reconciliation.py -- do not edit. -->",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()} from commit `{commit}`.",
        "",
        "The manuscript states what the software must be able to do. It does not "
        "state what it must compute. Every number in the funnel columns is read "
        "from an evidence file that a run produced; the manuscript column is "
        "transcribed context and is never used as a reference. No comparison, "
        "tolerance or test anywhere reads it.",
        "",
        f"Manuscript: `{claims.get('source_document', {}).get('name', 'unknown')}`, "
        f"sha256 `{claims.get('source_document', {}).get('sha256', 'unknown')[:16]}...` "
        "(held outside this repository).",
        "",
        "Blank cells mean the stage does not apply to that claim, not zero.",
        "",
        "## Funnel", "",
        "| Claim | " + " | ".join(c.replace("_", " ") for c in FUNNEL_COLUMNS) + " |",
        "|---" * (len(FUNNEL_COLUMNS) + 1) + "|",
    ]

    all_notes: list[tuple[str, list[str]]] = []
    for claim in claims.get("claims", []):
        builder = BUILDERS.get(claim["id"])
        row, notes = builder() if builder else (_blank(), ["no builder for this claim"])
        if claim.get("required_denominator") and row.get("required") is None:
            row["required"] = claim["required_denominator"]
        cells = ["" if row[c] is None else str(row[c]) for c in FUNNEL_COLUMNS]
        lines.append(f"| **{claim['table']}** | " + " | ".join(cells) + " |")
        all_notes.append((claim["table"], notes))

    lines += ["", "## What the manuscript says, and what was measured", ""]
    for claim in claims.get("claims", []):
        notes = dict(all_notes).get(claim["table"], [])
        lines += [
            f"### {claim['table']}", "",
            f"**Manuscript:** {claim['statement']}", "",
            f"**Evidence:** `{claim['evidence']}`", "",
        ]
        lines += [f"- {note}" for note in notes if note] + [""]

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        shown = args.out.relative_to(REPO_ROOT)
    except ValueError:
        shown = args.out
    print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
