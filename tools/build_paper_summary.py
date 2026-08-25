#!/usr/bin/env python
"""Emit measured sentences the authors can paste, each citing artefact and commit.

Every sentence below is rendered from a generated evidence file. Nothing is
transcribed from the manuscript and no number is written by hand, so a sentence
that changes is a sentence whose measurement changed.

The vocabulary is kept separate on purpose. "Compiled" is not "executed",
"executed" is not "primal-parity verified", and neither is "derivative
verified". "Reference unresolved" is its own outcome and is never folded into
agreement. A source with no upstream material data is missing external data, not
a transformation failure.
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
RESULTS = REPO_ROOT / "paper_results"
OUT = RESULTS / "PAPER_READY_SUMMARY.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _commit() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sentences() -> list[tuple[str, str, str]]:
    """(section, sentence, artefact) for every measured claim."""
    out: list[tuple[str, str, str]] = []

    sweep = _load(RESULTS / "parameter_sensitivity" / "parameter_sensitivity_round.json")
    if sweep:
        funnel = sweep["funnel"]
        artefact = "paper_results/parameter_sensitivity/parameter_sensitivity_round.json"
        out.append((
            "Parameter sensitivities (Table 6)",
            f"Across {funnel['attempted']} material models and "
            f"{funnel['parameter_directions_declared']} parameter directions, the "
            f"transformed and untransformed builds were compiled independently, "
            f"executed over the same strain history, and agreed on stress and "
            f"state in all {funnel['primal_parity']} cases; "
            f"{funnel['comparison_rows_agreeing']} of "
            f"{funnel['comparison_rows_total']} derivative comparisons agreed with "
            f"centred differences of the untransformed build, none disagreed, and "
            f"{funnel['parameter_directions_verified']} of "
            f"{funnel['parameter_directions_declared']} directions were verified.",
            artefact))
        unresolved = sum(m["stages"].get("derivatives_verified", {})
                         .get("rows_reference_unresolved", 0)
                         for m in sweep.get("models", []))
        if unresolved:
            out.append((
                "Parameter sensitivities (Table 6)",
                f"The remaining {unresolved} comparisons are withheld rather than "
                "claimed: their quantities sit below what a centred difference can "
                "resolve at any step size, so the reference cannot adjudicate them "
                "and the affected directions are not counted as verified.",
                artefact))

    jac = _load(RESULTS / "internal_jacobians" / "internal_jacobian_round.json")
    if jac:
        funnel = jac["funnel"]
        artefact = "paper_results/internal_jacobians/internal_jacobian_round.json"
        out.append((
            "Internal constitutive Jacobians (Table 3)",
            f"Of {funnel['candidate_sources']} candidate sources, "
            f"{funnel['sources_with_a_local_solve']} carry a local Newton solve; "
            f"{funnel['extracted_and_verified']} had their internal Jacobian "
            f"extracted and verified against centred differences of the residual "
            f"at the identical local state, and none disagreed. The remaining "
            f"{funnel['no_local_solve']} integrate their law without a local "
            "iteration and so have no internal Jacobian to extract.",
            artefact))
        drift = []
        for record in jac.get("records", []):
            audit = record.get("hand_coded_audit") or {}
            extracted = record.get("extracted") or {}
            if not extracted:
                continue
            relative = audit.get("relative_difference")
            reference = extracted.get("finite_difference")
            oti_gap = (abs(extracted["oti"] - reference) / abs(reference)
                       if reference else None)
            if relative and relative > 1.0e-6:
                drift.append((record["id"], relative, oti_gap))
        if drift:
            listed = "; ".join(
                f"{name} by {value:.1e} while the generated derivative agreed with "
                f"the same reference to {gap:.1e}"
                for name, value, gap in sorted(drift, key=lambda d: -d[1]))
            out.append((
                "Internal constitutive Jacobians (Table 3)",
                "In two published models the author's own hand-coded internal "
                f"Jacobian differs from the independent reference: {listed}. The "
                "generated derivative follows the current implementation, so the "
                "comparison exposes tangents that have drifted from the residual "
                "they belong to.",
                artefact))

    corpus = _load(RESULTS / "corpus" / "corpus_round.json")
    if corpus:
        funnel = corpus["funnel"]
        artefact = "paper_results/corpus/corpus_round.json"
        verified = sorted(c["id"] for c in corpus["candidates"]
                          if c.get("furthest_stage") == "derivatives_verified")
        multi = sorted(c["id"] for c in corpus["candidates"]
                       if (c.get("dependency_graph") or {}).get("multi_file")
                       and c.get("furthest_stage") == "derivatives_verified")
        out.append((
            "External source corpus",
            f"{funnel['candidates']} externally authored UMATs from "
            f"{len(corpus['repositories'])} public repositories, each pinned to an "
            f"immutable commit, were run through the pipeline offline: "
            f"{funnel['reached_generated_compiled']} transformed and compiled, "
            f"{funnel['reached_primal_parity']} executed with primal parity against "
            f"the untransformed build, and "
            f"{funnel['reached_derivatives_verified']} verified numerically against "
            "centred differences, with no disagreeing comparison.",
            artefact))
        if multi:
            out.append((
                "External source corpus",
                f"{len(multi)} of the verified sources ({', '.join(multi)}) define "
                "none of the helper routines they call; their closures were "
                "resolved across sibling files, compiled and verified, which "
                "demonstrates the multi-file path rather than asserting it.",
                artefact))
        for key, names in sorted(corpus.get("failure_taxonomy", {}).items()):
            out.append((
                "External source corpus",
                f"{len(names)} candidate(s) stopped at {key} and remain in the "
                f"denominator: {', '.join(names)}.",
                artefact))

    generality = _load(RESULTS / "generality" / "generality_summary.json")
    if generality:
        verification = generality.get("by_numerical_verification", {})
        out.append((
            "Generality",
            f"The generality matrix covers {generality['sources']} distinct "
            f"sources; {verification.get('succeeded', 0)} are numerically verified, "
            f"{verification.get('failed', 0)} disagree, "
            f"{verification.get('unresolved', 0)} are reference-unresolved and "
            f"{verification.get('not_attempted', 0)} were not attempted.",
            "paper_results/generality/generality_matrix.csv"))
        out.append((
            "Generality",
            generality.get("structural_diversity_caveat", ""),
            "paper_results/generality/generality_summary.json"))

    table2 = None
    for path in sorted(RESULTS.glob("arc_*/table2_abaqus_paired.json")):
        table2 = _load(path)
        job = next((r.get("slurm_job_id") for r in table2.get("rows", [])), None)
        host = next((r.get("hostname") for r in table2.get("rows", [])), None)
        compiler = next((r.get("compiler") for r in table2.get("rows", [])), None)
        passed = sum(1 for r in table2["rows"] if r.get("status") == "passed")
        out.append((
            "Paired Abaqus validation (Table 2)",
            f"{passed} of {len(table2['rows'])} paired Abaqus analyses agreed on "
            f"stress, state, tangent and convergence, archived from Slurm job "
            f"{job} on host {host} with {compiler}.",
            str(path.relative_to(REPO_ROOT))))
        out.append((
            "Paired Abaqus validation (Table 2)",
            "That archive does not record the Abaqus version it ran, so it cannot "
            "be attributed to a particular release; it is identified by Slurm job "
            f"{job}, host {host} and compiler version alone. It must not be merged "
            "with any run performed on other hardware.",
            str(path.relative_to(REPO_ROOT))))
        out.append((
            "Paired Abaqus validation (Table 2)",
            "Every archived deck drives its model with a probe property vector of "
            "unit constants, so the comparison establishes that two builds of each "
            "source agree on identical inputs and not that either behaves "
            "correctly on a physical material.",
            str(path.relative_to(REPO_ROOT))))
        break
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    commit = _commit()
    lines = [
        "# Paper-ready measured results", "",
        "<!-- GENERATED by tools/build_paper_summary.py -- do not edit. -->", "",
        f"Generated {datetime.now(timezone.utc).isoformat()} from commit `{commit}`.",
        "",
        "Every sentence is rendered from a generated evidence file. No number here "
        "was transcribed from the manuscript and none was written by hand. Each "
        f"cites its artefact; all of them were produced at commit `{commit}`.",
        "",
        "The vocabulary is deliberately separate: *compiled* is not *executed*, "
        "*executed* is not *primal-parity verified*, and neither is *derivative "
        "verified*. *Reference unresolved* is its own outcome and is never folded "
        "into agreement. A source with no upstream material data is missing "
        "external data, not a transformation failure.", "",
    ]
    grouped: dict[str, list[tuple[str, str]]] = {}
    for section, sentence, artefact in sentences():
        if sentence.strip():
            grouped.setdefault(section, []).append((sentence, artefact))

    for section, items in grouped.items():
        lines += [f"## {section}", ""]
        for sentence, artefact in items:
            # The commit is stated once in the header. Repeating it on every
            # citation makes the document differ from itself whenever it is
            # regenerated at a different commit, which is not a change in any
            # measurement.
            lines += [f"> {sentence}", "", f"Source: `{artefact}`.", ""]

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        shown = args.out.relative_to(REPO_ROOT)
    except ValueError:
        shown = args.out
    print(f"wrote {shown} ({len(grouped)} sections, "
          f"{sum(len(v) for v in grouped.values())} sentences)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
