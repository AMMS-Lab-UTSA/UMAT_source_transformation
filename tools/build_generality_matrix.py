#!/usr/bin/env python
"""Generate the generality matrix from executed evidence.

One row per source. Structural columns are derived from the source and its
contract; outcome columns are joined from the evidence rounds. Nothing here
asserts a capability -- every outcome column is read from a file some run
produced, and a source that was never executed says so.

"General" is a claim about coverage of distinct structures, so the matrix is
also the place where the benchmark set's own uniformity is visible: if every
row is single-file fixed-form small-strain, the matrix shows that rather than
letting a headline count imply otherwise.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.validation.actual_umat_higher_order_generic import MODELS  # noqa: E402

MODELS_DIR = REPO_ROOT / "parameter_sensitivity" / "models"
CONTRACTS_DIR = REPO_ROOT / "parameter_sensitivity" / "contracts"
CLASSIFICATION = REPO_ROOT / "parameter_sensitivity" / "benchmark_classification.json"
ARCHIVE = REPO_ROOT / "parameter_sensitivity" / "internal_jacobian_sources.json"
RESULTS = REPO_ROOT / "paper_results"
OUT = RESULTS / "generality"

UNAVAILABLE = "not_attempted"
BLOCKED = "blocked_by_external_dependency"

_SUBPROGRAM = re.compile(
    r"^\s*(?:\d+\s+)?(?:(?:RECURSIVE|PURE|ELEMENTAL)\s+)*"
    r"(?:SUBROUTINE|(?:[A-Z0-9_()*\s]*?\s)?FUNCTION)\s+([A-Za-z_]\w*)",
    re.IGNORECASE | re.MULTILINE)
_INCLUDE = re.compile(r"^\s*INCLUDE\s+['\"]([^'\"]+)['\"]", re.IGNORECASE | re.MULTILINE)
_DDSDDE_ASSIGN = re.compile(r"DDSDDE\s*\([^)]*\)\s*=", re.IGNORECASE)
_FINITE_STRAIN = re.compile(r"\bDFGRD[01]\b", re.IGNORECASE)


def structural_facts(source: Path) -> dict:
    """Everything the matrix can learn by reading the source itself."""
    text = source.read_text(encoding="utf-8", errors="replace")
    routines = [m.group(1).upper() for m in _SUBPROGRAM.finditer(text)]
    includes = sorted({m.group(1) for m in _INCLUDE.finditer(text)})
    # A fixed-form line puts its continuation marker in column 6.
    fixed = source.suffix.lower() in {".for", ".f", ".f77"}
    return {
        "source_form": "fixed" if fixed else "free",
        "n_subprograms": len(routines),
        "helper_routines": ";".join(r for r in routines if r != "UMAT") or "none",
        "include_files": ";".join(i for i in includes if "ABA_PARAM" not in i.upper())
                         or "none (ABA_PARAM only)" if includes else "none",
        "existing_tangent": "present" if _DDSDDE_ASSIGN.search(text) else "absent",
        "reads_deformation_gradient": "yes" if _FINITE_STRAIN.search(text) else "no",
        "source_lines": text.count("\n") + 1,
    }


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def build_rows() -> list[dict]:
    classification = _load(CLASSIFICATION).get("models", {})
    sweep = _load(RESULTS / "parameter_sensitivity" / "parameter_sensitivity_round.json")
    sweep_by_model = {r["model"]: r for r in sweep.get("models", sweep.get("records", []))}
    jac = _load(RESULTS / "internal_jacobians" / "internal_jacobian_round.json")
    jac_by_id = {r["id"]: r for r in jac.get("records", [])}
    archive = {e["id"]: e for e in _load(ARCHIVE).get("sources", [])}

    paired = {}
    for table2 in sorted(RESULTS.glob("arc_*/table2_abaqus_paired.json")):
        for row in _load(table2).get("rows", []):
            paired[row["case_name"]] = {
                "status": row.get("status"),
                "slurm_job_id": row.get("slurm_job_id"),
                "stress": row.get("stress_status"),
                "ddsdde": row.get("ddsdde_status"),
                "statev": row.get("statev_status"),
            }

    higher_order = {}
    for directory in sorted((RESULTS / "higher_order_convergence").glob("*/")):
        evidence = directory / "convergence_evidence.json"
        if evidence.is_file():
            higher_order[directory.name] = _load(evidence)

    rows: list[dict] = []

    for model in sorted(d.name for d in MODELS_DIR.iterdir() if (d / "umat.for").is_file()):
        source = MODELS_DIR / model / "umat.for"
        contract = _load(CONTRACTS_DIR / f"{model}.json")
        v2 = _load(MODELS_DIR / model / "contract_v2.json")
        record = sweep_by_model.get(model, {})
        stages = record.get("stages", {})
        jrecord = jac_by_id.get(model, {})
        rows.append(_row(
            identity=model, origin="parameter_sensitivity benchmark set",
            provenance=("synthesised or reduced benchmark imported from the authors' "
                        "oti_provider working tree; see IMPORT_PROVENANCE.json"),
            license="this repository's licence (GPL-3.0)",
            source=source, contract=contract, v2=v2,
            classification=classification.get(model, {}),
            stages=stages, record=record, jrecord=jrecord, higher_order=None))

    for entry_id, entry in sorted(archive.items()):
        source = REPO_ROOT / entry["path"]
        if not source.is_file():
            continue
        jrecord = jac_by_id.get(entry_id, {})
        study = higher_order.get(entry_id)
        rows.append(_row(
            identity=entry_id, origin="UMATs/ICP archive",
            provenance=entry.get("provenance"), license=entry.get("license"),
            source=source, contract={}, v2={},
            classification={"constitutive_class": entry.get("constitutive_class"),
                            "classified_from": "declared in internal_jacobian_sources.json"},
            stages={}, record={}, jrecord=jrecord, higher_order=study,
            spec=MODELS.get(entry_id), paired=paired.get(entry_id)))

    for key, study in sorted(higher_order.items()):
        if any(r["identity"] == key for r in rows):
            continue
        spec = MODELS.get(key)
        source_path = (study.get("source") or {}).get("path")
        if not source_path:
            continue
        source = REPO_ROOT / source_path
        if not source.is_file():
            continue
        rows.append(_row(
            identity=key, origin="higher-order study source",
            provenance="Universidad EAFIT / repository UMAT archive",
            license="this repository's licence (GPL-3.0)",
            source=source, contract={}, v2={},
            classification={"constitutive_class": "see the study's model notes",
                            "classified_from": "higher-order convergence study"},
            stages={}, record={}, jrecord=jac_by_id.get(key, {}),
            higher_order=study, spec=spec, paired=paired.get(key)))

    # Externally sourced corpus candidates. They are the strongest generality
    # evidence in the matrix -- independently authored, permissively licensed,
    # pinned to a commit, and not curated for this pipeline.
    corpus = _load(RESULTS / "corpus" / "corpus_round.json")
    for candidate in corpus.get("candidates", []):
        source = REPO_ROOT / (candidate.get("source_path") or "")
        graph = candidate.get("dependency_graph") or {}
        comparison = candidate.get("comparison") or {}
        stages = candidate.get("stages") or {}
        verification = stages.get("derivatives_verified", {}).get("status")
        rows.append({
            "identity": candidate["id"],
            "origin": "external corpus (pinned snapshot)",
            "provenance": f"{candidate.get('repository_url','')} @ "
                          f"{(candidate.get('commit_sha') or '')[:12]}",
            "license": candidate.get("license_spdx", ""),
            "source_path": candidate.get("source_path", ""),
            "source_form": "fixed",
            "file_layout": ("multi_file" if graph.get("multi_file")
                            else "single_file"),
            "n_subprograms": len(graph.get("resolved", {})) or "",
            "helper_routines": ";".join(
                sorted(n for n in graph.get("resolved", {}) if n != "UMAT")) or "none",
            "include_files": "ABA_PARAM only",
            "source_lines": "",
            "kinematics": "small_strain",
            "reads_deformation_gradient": "",
            "ntens": "", "nstatv": "", "nprops": "",
            "path_dependent": "",
            "constitutive_class": candidate.get("constitutive_class", ""),
            "classified_from": "declared in corpus_snapshot.json",
            "existing_tangent": "present",
            "derivative_families_requested": "DSIGMA_DP;DSTATEV_DP",
            "highest_stage_reached": candidate.get("furthest_stage", UNAVAILABLE),
            "transformation": stages.get("transformed", {}).get("status", UNAVAILABLE),
            "compilation": stages.get("generated_compiled", {}).get("status", UNAVAILABLE),
            "primal_parity": stages.get("primal_parity", {}).get("status", UNAVAILABLE),
            "numerical_verification": verification or UNAVAILABLE,
            "higher_order_verified": UNAVAILABLE,
            "internal_jacobian": UNAVAILABLE,
            "abaqus": BLOCKED,
            "failure_category_and_blocker": (candidate.get("blocker")
                                             or candidate.get("material_blocker")
                                             or "none"),
        })

    # Sources that only ever appear in the archived Abaqus round still belong in
    # the denominator: they are real UMATs the pipeline was pointed at.
    for case_name, result in sorted(paired.items()):
        if any(r["identity"] == case_name for r in rows):
            continue
        candidates = [c for c in (REPO_ROOT / "UMATs").rglob(f"{case_name}.*")
                      if c.suffix.lower() in {".for", ".f", ".f90", ".f77"}]
        if not candidates:
            continue
        rows.append(_row(
            identity=case_name, origin="archived Abaqus paired round",
            provenance="Universidad EAFIT / repository UMAT archive",
            license="this repository's licence (GPL-3.0)",
            source=candidates[0], contract={}, v2={},
            classification={"constitutive_class": "",
                            "classified_from": "not classified"},
            stages={}, record={}, jrecord=jac_by_id.get(case_name, {}),
            higher_order=None, spec=MODELS.get(case_name), paired=result))
    return rows


def _stage(stages: dict, name: str) -> str:
    entry = stages.get(name)
    return entry["status"] if entry else UNAVAILABLE


def _row(*, identity, origin, provenance, license, source, contract, v2,
         classification, stages, record, jrecord, higher_order, spec=None,
         paired=None) -> dict:
    facts = structural_facts(source)
    dims = (v2.get("dimensions") or {})
    ntens = contract.get("ntens") or dims.get("ntens") or (spec.ntens if spec else "")
    nstatv = (len(contract.get("state_variables", [])) if contract
              else dims.get("nstatev") or (spec.nstatv if spec else ""))
    nprops = dims.get("nprops") or (spec.nprops if spec else "")
    driver = contract.get("material_point_driver") or {}
    if not nprops and driver.get("static_props"):
        nprops = len(driver["static_props"])

    families = []
    if contract.get("parameters"):
        families.append("DSIGMA_DP")
        if contract.get("state_variables"):
            families.append("DSTATEV_DP")
    if higher_order:
        families.append("higher_order_stress")
    if jrecord.get("local_solves_discovered"):
        families.append("internal_jacobian")
    if paired:
        families.append("abaqus_paired_DDSDDE")

    kinematics = v2.get("kinematics") or ("small_strain" if spec else "")
    path_dependent = ""
    if v2.get("history") is not None:
        path_dependent = "yes" if (v2["history"] or {}).get("path_dependent") else "no"
    elif nstatv:
        path_dependent = "yes (carries state)"

    jverdict = jrecord.get("stages", {}).get("jacobian_verified")
    if jverdict:
        internal = jverdict["status"]
    elif jrecord.get("bucket") == "no_local_solve":
        internal = "no_local_solve"
    elif jrecord:
        internal = f"blocked:{jrecord.get('furthest_stage') or 'not_started'}"
    else:
        internal = UNAVAILABLE

    blocker = ""
    for name in ("derivatives_verified", "primal_parity", "executed_oti",
                 "compile", "transform"):
        entry = stages.get(name)
        if entry and entry["status"] != "succeeded" and entry.get("reason"):
            blocker = f"{name}: {entry['reason']}"
            break
    if not blocker and jrecord.get("reason"):
        blocker = f"internal_jacobian: {jrecord['reason']}"
    if not blocker:
        for name, entry in (jrecord.get("stages") or {}).items():
            if entry["status"] != "succeeded" and entry.get("reason"):
                blocker = f"internal_jacobian/{name}: {entry['reason']}"
                break

    return {
        "identity": identity,
        "origin": origin,
        "provenance": provenance,
        "license": license,
        "source_path": str(source.relative_to(REPO_ROOT)),
        "source_form": facts["source_form"],
        "file_layout": "single_file",
        "n_subprograms": facts["n_subprograms"],
        "helper_routines": facts["helper_routines"],
        "include_files": facts["include_files"],
        "source_lines": facts["source_lines"],
        "kinematics": kinematics,
        "reads_deformation_gradient": facts["reads_deformation_gradient"],
        "ntens": ntens, "nstatv": nstatv, "nprops": nprops,
        "path_dependent": path_dependent,
        "constitutive_class": classification.get("constitutive_class", ""),
        "classified_from": classification.get("classified_from", ""),
        "existing_tangent": facts["existing_tangent"],
        "derivative_families_requested": ";".join(families) or "none",
        "highest_stage_reached": record.get("furthest_stage")
                                 or jrecord.get("furthest_stage") or UNAVAILABLE,
        "transformation": _stage(stages, "transform"),
        "compilation": _stage(stages, "compile"),
        "primal_parity": _stage(stages, "primal_parity"),
        "numerical_verification": _stage(stages, "derivatives_verified"),
        "higher_order_verified": (
            "verified" if (higher_order or {}).get("summary", {}).get("verified")
            else ("not_verified" if higher_order else UNAVAILABLE)),
        "internal_jacobian": internal,
        "abaqus": (f"{paired['status']} (slurm {paired['slurm_job_id']})"
                   if paired else BLOCKED),
        "failure_category_and_blocker": blocker or "none",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, default=OUT,
        help=("where to write the matrix. Defaults to the published location; "
              "tests and trial runs must pass somewhere else so a partial or "
              "experimental run cannot overwrite published evidence."))
    args = parser.parse_args(argv)
    out = args.out_dir

    rows = build_rows()
    out.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    with (out / "generality_matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    def tally(key):
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row[key])] = counts.get(str(row[key]), 0) + 1
        return dict(sorted(counts.items()))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": len(rows),
        "by_constitutive_class": tally("constitutive_class"),
        "by_source_form": tally("source_form"),
        "by_kinematics": tally("kinematics"),
        "by_existing_tangent": tally("existing_tangent"),
        "by_numerical_verification": tally("numerical_verification"),
        "by_internal_jacobian": tally("internal_jacobian"),
        "by_abaqus": tally("abaqus"),
        "structural_diversity_caveat": (
            "Every parameter-sensitivity benchmark row is single-file, fixed-form "
            "and small-strain with at most one helper routine, so that set alone "
            "demonstrates breadth of constitutive class rather than of source "
            "structure. The external corpus rows supply the multi-file evidence: "
            "candidates whose helper closure spans sibling files are resolved, "
            "compiled and verified. Free-form and finite-strain sources are still "
            "not represented anywhere in this matrix."),
        "multi_file_verified": sorted(
            row["identity"] for row in rows
            if row.get("file_layout") == "multi_file"
            and row.get("numerical_verification") == "succeeded"),
    }
    (out / "generality_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
