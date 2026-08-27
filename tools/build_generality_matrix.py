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

from umat_oti.corpus.identity import closure_identity, content_identity  # noqa: E402
from umat_oti.transform.dependency_resolution import (  # noqa: E402
    DependencyResolutionError, resolve_closure,
)
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

    # The locally executed paired round, for sources the archived cluster round
    # never covered. Only rows the round actually passed are joined: a run it
    # declined to adjudicate, or one that failed, leaves the source where it
    # was rather than overwriting a blocked entry with a softer word. An
    # archived result is never overwritten -- it was a different machine and a
    # different Abaqus, and having both is worth more than having the newer.
    local_round = _load(RESULTS / "abaqus_paired" / "abaqus_paired_round.json")
    for row in local_round.get("rows", []) if local_round else []:
        name = row.get("model")
        if not name or name in paired or row.get("status") != "passed":
            continue
        paired[name] = {
            "status": "passed",
            "slurm_job_id": "local",
            "stress": "passed" if row.get("stress_pass") else "",
            "ddsdde": "passed" if row.get("ddsdde_pass") else "",
            "statev": "passed" if row.get("statev_pass") else "",
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
            stages=stages, record=record, jrecord=jrecord, higher_order=None,
            paired=paired.get(model)))

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
        corpus_identity = (
            candidate.get("identity", {}).get("canonical_source_id")
            or (canonical_identity(source).canonical_source_id
                if source.is_file() else candidate["id"]))
        rows.append({
            "canonical_source_id": corpus_identity,
            "identity_kind": candidate.get("identity", {}).get(
                "identity_kind", "single_file"),
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
            "internal_jacobian": _internal_jacobian_status(
                jac_by_id.get(candidate["id"], {})),
            "abaqus": (
                (f"{_corpus_paired['status']} (local paired round)"
                 if _corpus_paired.get("slurm_job_id") == "local"
                 else f"{_corpus_paired['status']} "
                      f"(slurm {_corpus_paired['slurm_job_id']})")
                if (_corpus_paired := paired.get(candidate["id"])) else BLOCKED),
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


def _internal_jacobian_status(record: dict) -> str:
    """One vocabulary for the internal-Jacobian column, wherever the row came from."""
    verdict = (record.get("stages") or {}).get("jacobian_verified")
    if verdict:
        return verdict["status"]
    if record.get("bucket") == "no_local_solve":
        return "no_local_solve"
    if record:
        return f"blocked:{record.get('furthest_stage') or 'not_started'}"
    return UNAVAILABLE


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

    internal = _internal_jacobian_status(jrecord)

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
    if not blocker and paired and not str(paired["status"]).startswith("passed"):
        # A source whose only validation route was the Abaqus paired round, and
        # which failed there, was reporting no blocker at all -- the one row in
        # the collection that looked unexplained.
        blocker = (f"abaqus: the paired round recorded "
                   f"{paired['status']} for this source (slurm "
                   f"{paired['slurm_job_id']}), and it has not been run through "
                   "the offline pipeline")

    canonical = canonical_identity(source, roots=[source.parent])
    return {
        "canonical_source_id": canonical.canonical_source_id,
        "identity_kind": canonical.kind,
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
        "abaqus": (
            (f"{paired['status']} (local paired round)"
             if paired.get("slurm_job_id") == "local"
             else f"{paired['status']} (slurm {paired['slurm_job_id']})")
            if paired else BLOCKED),
        "failure_category_and_blocker": blocker or "none",
    }


def _structural_caveat(rows: list[dict]) -> str:
    """State the coverage the matrix actually has, computed from the rows.

    A caveat written once and left alone becomes wrong the moment coverage
    changes, and a stale caveat understating the evidence is as misleading as
    one overstating it.
    """
    def verified(predicate) -> list[str]:
        return sorted(row["identity"] for row in rows
                      if predicate(row) and row.get("numerical_verification")
                      == "succeeded")

    multi = verified(lambda r: r.get("file_layout") == "multi_file")
    finite = verified(lambda r: "finite" in (r.get("constitutive_class") or "").lower())
    free_form = verified(lambda r: r.get("source_form") == "free")
    parts = [
        "The parameter-sensitivity benchmark set is uniform by construction: "
        "single-file, fixed-form, small-strain, at most one helper routine. On "
        "its own it demonstrates breadth of constitutive class rather than of "
        "source structure.",
    ]
    parts.append(
        f"Multi-file closures are demonstrated by {len(multi)} verified "
        f"sources ({', '.join(multi)})." if multi else
        "No multi-file source has been verified.")
    parts.append(
        f"Finite-strain kinematics are demonstrated by {len(finite)} verified "
        f"sources ({', '.join(finite)}), driven through the deformation "
        "gradient rather than the strain increment." if finite else
        "No finite-strain source has been verified.")
    parts.append(
        f"Free-form sources: {len(free_form)} verified." if free_form else
        "Free-form and module-based sources are still unrepresented; every row "
        "in this matrix is fixed-form.")
    return " ".join(parts)


def canonical_identity(source: Path, roots=()):
    """The implementation's identity, independent of where the copy was found."""
    try:
        graph = resolve_closure(source, entry="UMAT", roots=roots)
    except (DependencyResolutionError, OSError, ValueError):
        return content_identity(source)
    if graph.missing or not graph.is_multi_file:
        return content_identity(source)
    return closure_identity(graph)


def collapse_to_canonical_rows(rows: list[dict]) -> list[dict]:
    """One row per implementation, with every appearance kept as an event.

    Each of the twelve ICP UMATs is normalised-identical to a file in the pinned
    upstream snapshot, so a matrix keyed on where a copy was found reports one
    implementation as several. Rows are merged on canonical identity and the
    origins and validation events they came from are listed on the surviving
    row, so nothing is lost and nothing is counted twice.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        key = row.get("canonical_source_id") or row["identity"]
        if key not in merged:
            row = dict(row)
            row["origins"] = [row["origin"]]
            row["aliases"] = [row["identity"]]
            row["validation_events"] = [
                f"{row['origin']}:{row['highest_stage_reached']}"]
            merged[key] = row
            order.append(key)
            continue
        target = merged[key]
        if row["origin"] not in target["origins"]:
            target["origins"].append(row["origin"])
        if row["identity"] not in target["aliases"]:
            target["aliases"].append(row["identity"])
        target["validation_events"].append(
            f"{row['origin']}:{row['highest_stage_reached']}")
        # Keep the strongest outcome observed. A source verified in one round is
        # verified; a later appearance that merely did not attempt it must not
        # erase that.
        for column in ("numerical_verification", "primal_parity", "compilation",
                       "transformation", "internal_jacobian",
                       "higher_order_verified"):
            if row.get(column) == "succeeded":
                target[column] = "succeeded"
            elif target.get(column) in (UNAVAILABLE, "", None) and row.get(column):
                target[column] = row[column]
        if target.get("abaqus") == BLOCKED and row.get("abaqus") != BLOCKED:
            target["abaqus"] = row["abaqus"]
        if row.get("file_layout") == "multi_file":
            target["file_layout"] = "multi_file"
        if not target.get("constitutive_class") and row.get("constitutive_class"):
            target["constitutive_class"] = row["constitutive_class"]
    out = []
    for key in order:
        row = merged[key]
        row["origin"] = ";".join(row.pop("origins"))
        row["aliases"] = ";".join(row["aliases"])
        row["validation_events"] = ";".join(sorted(set(row["validation_events"])))
        out.append(row)
    return out


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
    rows = collapse_to_canonical_rows(rows)
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

    identity_registry = _load(OUT / "source_identity.json")
    merged = [row for row in rows if ";" in row.get("origin", "")]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": len(rows),
        "counting_policy": (
            "One row per implementation. Rows are merged on canonical source "
            "identity -- normalised content for a single file, resolved routine "
            "closure for a multi-file source -- so a UMAT reachable from both the "
            "in-repository archive and the pinned upstream snapshot is one source "
            "with several origins and several validation events, not several "
            "sources."),
        "rows_merged_from_more_than_one_origin": len(merged),
        "merged_rows": sorted(row["aliases"] for row in merged),
        "identity_registry_counts": identity_registry.get("counts", {}),
        "by_constitutive_class": tally("constitutive_class"),
        "by_source_form": tally("source_form"),
        "by_kinematics": tally("kinematics"),
        "by_existing_tangent": tally("existing_tangent"),
        "by_numerical_verification": tally("numerical_verification"),
        "by_internal_jacobian": tally("internal_jacobian"),
        "by_abaqus": tally("abaqus"),
        "structural_diversity_caveat": _structural_caveat(rows),
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
