"""Every number the manuscript states, read from the evidence that produced it.

The point of this module is that no figure in the paper can be typed. A value
that is not derivable from a committed file cannot be cited, and a value that
changes when the evidence changes changes in the manuscript too.

Each entry carries the file it came from, so the manuscript's own provenance
record names an artefact for every number in the text.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "paper_results"

#: The illustrative example, excluded from every collection-level count.
ILLUSTRATIVE = {"m3_j2", "j2"}


@dataclass(frozen=True)
class Value:
    """One number, what it means, and the file it was read from."""

    key: str
    value: Any
    source: str

    def text(self) -> str:
        if isinstance(self.value, float):
            if self.value == 0.0:
                return "0"
            if abs(self.value) < 1e-3 or abs(self.value) >= 1e5:
                mantissa, exponent = f"{self.value:.2e}".split("e")
                return f"{mantissa}×10^{int(exponent)}"
            return f"{self.value:.3g}"
        return str(self.value)


def _csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def collect() -> dict[str, Value]:
    """Read every quantity the manuscript cites."""
    values: dict[str, Value] = {}

    def add(key: str, value: Any, source: Path) -> None:
        values[key] = Value(key, value, _relative(source))

    # --- the illustrative example -------------------------------------- #
    tangent_path = (RESULTS / "actual_umat_higher_order" / "j2"
                    / "table2_ddsdde_illustrative.csv")
    tangent = _csv(tangent_path)
    measured = [r for r in tangent if r["judged_by"] == "relative"]
    add("tangent_entries", len(tangent), tangent_path)
    add("tangent_measured", len(measured), tangent_path)
    add("tangent_structural_zeros",
        sum(1 for r in tangent if r["judged_by"] == "structural_zero"),
        tangent_path)
    add("tangent_disagreeing",
        sum(1 for r in tangent if r["agrees"] == "False"), tangent_path)
    add("tangent_worst_relative",
        max(float(r["relative_error"]) for r in measured), tangent_path)
    add("tangent_reference_spread",
        max(float(r["reference_spread_relative"]) for r in measured),
        tangent_path)

    higher_path = (RESULTS / "actual_umat_higher_order" / "j2"
                   / "table4_higher_order_actual_umat.csv")
    higher = _csv(higher_path)
    add("higher_order_rows", sum(int(r["comparison_rows"]) for r in higher),
        higher_path)
    add("higher_order_failed", sum(int(r["failed_rows"]) for r in higher),
        higher_path)
    add("higher_order_worst_relative",
        max(float(r["max_relative_error_when_absolute_tolerance_exceeded"])
            for r in higher), higher_path)
    add("higher_order_max_order", max(int(r["order"]) for r in higher),
        higher_path)

    # --- the illustrative example's parameter sensitivities ------------- #
    rows_path = RESULTS / "parameter_sensitivity" / "table6_comparison_rows.csv"
    every_row = _csv(rows_path)
    j2_rows = [r for r in every_row if r["model"] == "m3_j2"]
    add("j2_sensitivity_rows", len(j2_rows), rows_path)
    add("j2_sensitivity_disagreeing",
        sum(1 for r in j2_rows if r["agrees"] != "True"), rows_path)
    j2_measured = [r for r in j2_rows if r["judged_by"] == "relative"]
    add("j2_sensitivity_worst_relative",
        max(float(r["relative_error"]) for r in j2_measured), rows_path)
    add("j2_exact_zeros",
        sum(1 for r in j2_rows
            if float(r["oti"]) == 0.0 and float(r["reference"]) == 0.0),
        rows_path)
    yielded = sorted({int(r["increment"]) for r in j2_rows
                      if r["branch"] != "elastic"})
    add("j2_yield_increment", yielded[0] if yielded else "not measured",
        rows_path)
    add("j2_increments", max(int(r["increment"]) for r in j2_rows), rows_path)

    # --- the collection ------------------------------------------------- #
    round_path = (RESULTS / "parameter_sensitivity"
                  / "parameter_sensitivity_round.json")
    sweep = _json(round_path)
    models = [m for m in sweep["models"] if m["model"] not in ILLUSTRATIVE]
    stages = [m["stages"].get("derivatives_verified", {}) for m in models]
    add("collection_models", len(models), round_path)
    add("collection_rows", sum(s.get("rows", 0) for s in stages), round_path)
    add("collection_agreeing", sum(s.get("rows_agreeing", 0) for s in stages),
        round_path)
    add("collection_disagreeing",
        sum(s.get("rows_disagreeing", 0) for s in stages), round_path)
    add("collection_noise_floor",
        sum(s.get("rows_reference_unresolved_at_noise_floor", 0)
            for s in stages), round_path)
    add("collection_branch_crossing",
        sum(s.get("rows_reference_unresolved_by_branch_crossing", 0)
            for s in stages), round_path)
    add("collection_verified_models",
        sum(1 for s in stages if s.get("status") == "succeeded"), round_path)
    worst = [s.get("worst_relative_error") for s in stages
             if s.get("worst_relative_error") is not None]
    add("collection_worst_relative", max(worst), round_path)

    # --- global identity ------------------------------------------------ #
    matrix_path = RESULTS / "generality" / "generality_matrix.csv"
    matrix = [r for r in _csv(matrix_path) if r["aliases"] not in ILLUSTRATIVE]
    verified_offline = [r for r in matrix
                        if r["numerical_verification"] == "succeeded"]
    verified_abaqus = [r for r in matrix if r["abaqus"].startswith("passed")]
    either = {r["canonical_source_id"] for r in verified_offline} | \
        {r["canonical_source_id"] for r in verified_abaqus}
    add("unique_sources", len(matrix), matrix_path)
    add("verified_offline", len(verified_offline), matrix_path)
    add("verified_abaqus", len(verified_abaqus), matrix_path)
    add("verified_either", len(either), matrix_path)
    add("verified_neither", len(matrix) - len(either), matrix_path)
    add("multi_file_sources",
        sum(1 for r in matrix if r["file_layout"] != "single_file"),
        matrix_path)

    summary_path = RESULTS / "generality" / "generality_summary.json"
    registry = _json(summary_path)["identity_registry_counts"]
    add("raw_discovered_files", registry["raw_discovered_files"], summary_path)
    add("deduplicated_sources", registry["content_deduplicated_sources"],
        summary_path)
    add("upstream_repositories", registry["independent_upstream_repositories"],
        summary_path)
    add("constitutive_models", registry["unique_constitutive_models"],
        summary_path)

    # --- internal Jacobians --------------------------------------------- #
    jacobian_path = (RESULTS / "internal_jacobians"
                     / "table3_internal_jacobians.csv")
    jacobians = _csv(jacobian_path)
    unique = {r["canonical_source_id"]: r for r in jacobians}
    add("jacobian_events", len(jacobians), jacobian_path)
    add("jacobian_sources", len(unique), jacobian_path)
    add("jacobian_worst_oti",
        max(float(r["oti_vs_fd_relative"]) for r in unique.values()),
        jacobian_path)
    drifted = sorted((float(r["hand_coded_vs_fd_relative"]), r["model"])
                     for r in unique.values())
    add("jacobian_worst_hand_coded", drifted[-1][0], jacobian_path)
    add("jacobian_worst_hand_coded_model", drifted[-1][1], jacobian_path)
    add("jacobian_second_hand_coded", drifted[-2][0], jacobian_path)
    add("jacobian_second_hand_coded_model", drifted[-2][1], jacobian_path)
    add("jacobian_drifted",
        sum(1 for value, _ in drifted if value > 1e-6), jacobian_path)

    # --- Abaqus --------------------------------------------------------- #
    abaqus_path = RESULTS / "arc_791506" / "table2_abaqus_paired.csv"
    abaqus = _csv(abaqus_path)
    add("abaqus_cases", len(abaqus), abaqus_path)
    add("abaqus_passed", sum(1 for r in abaqus if r["status"] == "passed"),
        abaqus_path)
    add("abaqus_failed", sum(1 for r in abaqus if r["status"] != "passed"),
        abaqus_path)

    # --- corpus --------------------------------------------------------- #
    corpus_path = RESULTS / "corpus" / "corpus_funnel.csv"
    corpus = _csv(corpus_path)
    add("corpus_candidates", len(corpus), corpus_path)
    add("corpus_verified",
        sum(1 for r in corpus if r["furthest_stage"] == "derivatives_verified"),
        corpus_path)
    return values
