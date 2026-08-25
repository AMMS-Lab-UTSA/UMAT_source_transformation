#!/usr/bin/env python
"""Discover, extract and verify internal constitutive Jacobians. Emits Table 3.

Every candidate source lands in exactly one bucket, and all four are reported:

``verified``      a coefficient was extracted and agreed with centred differences
``failed``        a coefficient was extracted and disagreed
``blocked``       a local solve exists but the round could not execute it
``no_local_solve``  the source integrates its law without a local iteration

The last bucket is a structural fact about the model, not a pipeline failure: a
closed-form return-mapping has no internal Jacobian to extract.  It is reported
so the denominator of "models with an internal Jacobian" is visible rather than
implied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_parameter_sensitivity_sweep import generate_contract  # noqa: E402

from umat_oti.transform.dependency_resolution import (  # noqa: E402
    DependencyResolutionError, combined_source, resolve_closure,
)
from umat_oti.corpus.identity import closure_identity, content_identity  # noqa: E402
from umat_oti.transform.internal_jacobian import discover_local_solves  # noqa: E402
from umat_oti.validation.actual_umat_higher_order_generic import MODELS  # noqa: E402
from umat_oti.validation.internal_jacobian_validation import (  # noqa: E402
    InternalJacobianCase,
    verify_internal_jacobian,
)

MODELS_DIR = REPO_ROOT / "parameter_sensitivity" / "models"
CORPUS_SNAPSHOT = REPO_ROOT / "parameter_sensitivity" / "corpus_snapshot.json"
EXTERNAL = REPO_ROOT / "parameter_sensitivity" / "internal_jacobian_sources.json"
RESULTS = REPO_ROOT / "paper_results" / "internal_jacobians"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_models() -> list[str]:
    return sorted(d.name for d in MODELS_DIR.iterdir()
                  if (d / "contract_v2.json").is_file())



def _canonical_identity(source: Path, roots):
    """Identity that does not depend on which round happened to look at the source.

    A multi-file source must hash as its closure everywhere. Computing a
    single-file identity in one branch and a closure identity in another made
    UMAT_PCO, UMAT_VPDCO and UMAT_ECO each register as two "unique
    implementations", which is precisely the double counting this layer exists
    to prevent.
    """
    try:
        graph = resolve_closure(source, entry="UMAT", roots=roots)
    except DependencyResolutionError:
        return content_identity(source), None
    if graph.missing or not graph.is_multi_file:
        return content_identity(source), graph
    return closure_identity(graph), graph


def run_repo_model(model: str, work_root: Path) -> dict:
    source = MODELS_DIR / model / "umat.for"
    record: dict = {
        "id": model,
        "origin": "repository",
        "source": f"parameter_sensitivity/models/{model}/umat.for",
        "source_sha256": _sha256(source),
    }
    # Identity is computed for every candidate, including those that stop
    # immediately: the counts are about distinct implementations, and a source
    # with no local solve is still one of them.
    _identity, _ = _canonical_identity(source, [source.parent])
    record["identity"] = _identity.as_dict()
    record["canonical_source_id"] = _identity.canonical_source_id
    solves = discover_local_solves(source.read_text(errors="replace"))
    record["local_solves_discovered"] = [s.as_dict() for s in solves]
    if not solves:
        record["bucket"] = "no_local_solve"
        record["reason"] = ("this model integrates its constitutive law without a "
                            "local Newton iteration, so it has no internal Jacobian")
        return record

    _path, contract = generate_contract(model)
    driver = contract["material_point_driver"]
    props = [float(v) for v in driver.get("static_props", [])]
    if not props:
        record["bucket"] = "blocked"
        record["reason"] = "the contract declares no property vector to run with"
        return record

    case = InternalJacobianCase(
        model=model,
        source_path=source.resolve(),
        props=tuple(props),
        dstran_per_increment=tuple(driver["dstran_per_increment"]),
        n_increments=int(driver["n_increments"]),
        ntens=int(contract["ntens"]),
        nstatv=len(contract["state_variables"]),
        ndi=int(contract.get("ndi", 3)),
        nshr=int(contract.get("nshr", max(int(contract["ntens"]) - 3, 0))),
        state_names=tuple(s["name"] for s in contract["state_variables"]),
    )
    declared_source = record["source"]
    record.update(verify_internal_jacobian(case, work_root / model))
    record["executed_source"] = record.get("source")
    record["source"] = declared_source
    record["bucket"] = _bucket(record)
    return record


def _bucket(record: dict) -> str:
    verdict = record.get("stages", {}).get("jacobian_verified")
    if verdict is None:
        return "blocked"
    return {"succeeded": "verified", "failed": "failed"}.get(
        verdict["status"], "blocked")


def run_external(entry: dict, work_root: Path) -> dict:
    """Run one source that lives outside the parameter-sensitivity model set."""
    record: dict = {
        "id": entry["id"],
        "origin": "repository_umat_archive",
        "source": entry["path"],
        "provenance": entry.get("provenance"),
        "license": entry.get("license"),
        "constitutive_class": entry.get("constitutive_class"),
    }
    source = REPO_ROOT / entry["path"]
    if not source.is_file():
        record["bucket"] = "blocked"
        record["reason"] = f"declared source {entry['path']} is not present"
        return record
    record["source_sha256"] = _sha256(source)
    _identity, _ = _canonical_identity(source, [source.parent])
    record["identity"] = _identity.as_dict()
    record["canonical_source_id"] = _identity.canonical_source_id
    solves = discover_local_solves(source.read_text(errors="replace"))
    record["local_solves_discovered"] = [s.as_dict() for s in solves]
    if not solves:
        record["bucket"] = "no_local_solve"
        return record

    material = entry.get("material_data", {})
    status = material.get("status")
    if status == "higher_order_registry":
        spec = MODELS[material["key"]]
        record["material_data_source"] = (
            "umat_oti.validation.actual_umat_higher_order_generic.MODELS"
            f"[{material['key']!r}] -- the same property vector and loading path "
            "the higher-order study for this model used")
        case = InternalJacobianCase(
            model=entry["id"], source_path=source.resolve(),
            props=tuple(spec.props),
            dstran_per_increment=tuple(spec.increments[0]),
            n_increments=len(spec.increments),
            ntens=spec.ntens, nstatv=spec.nstatv,
            ndi=3, nshr=max(spec.ntens - 3, 0))
    elif status == "abaqus_validation_probe":
        provenance = material["provenance"]
        record["material_data_source"] = (
            f"the property vector the archived Abaqus paired validation ran this "
            f"model with ({provenance['abaqus_job']}, deck sha256 "
            f"{provenance['deck_sha256'][:16]}...). {provenance['nature']}.")
        record["material_is_physical"] = False
        case = InternalJacobianCase(
            model=entry["id"], source_path=source.resolve(),
            props=tuple(material["props_values"]),
            dstran_per_increment=tuple(material["dstran_per_increment"]),
            n_increments=int(material["n_increments"]),
            ntens=int(entry["ntens"]), nstatv=int(entry["nstatv"]),
            ndi=int(entry["ndi"]), nshr=int(entry["nshr"]))
    else:
        record["bucket"] = "blocked"
        record["blocked_by"] = "material_data_unavailable"
        record["reason"] = material.get(
            "reason", "no property vector is available for this source")
        return record

    record.update(verify_internal_jacobian(case, work_root / entry["id"]))
    record["bucket"] = _bucket(record)
    return record



def run_corpus_candidate(entry: dict, repository: dict, root: Path,
                         work_root: Path) -> dict:
    """A pinned external candidate, resolved across sibling files if need be.

    The corpus and the internal-Jacobian round share the dependency resolver, so
    a helper-heavy source is not a special case here either: UMAT_PCO defines
    none of the seven helpers it calls, and its closure is assembled the same
    way the corpus funnel assembles it.
    """
    base = root / repository["path"]
    source = base / entry["source"]
    record: dict = {
        "id": entry["id"], "origin": "external corpus (pinned snapshot)",
        "source": f"{repository['path']}/{entry['source']}",
        "provenance": f"{repository['url']} @ {repository['commit_sha'][:12]}",
        "license": repository["license_spdx"],
        "constitutive_class": entry.get("constitutive_class"),
    }
    if not source.is_file():
        record["bucket"] = "blocked"
        record["reason"] = "the pinned snapshot is not checked out"
        return record
    record["source_sha256"] = _sha256(source)
    _roots = [base / r for r in entry.get("dependency_roots", [])]
    _identity, _ = _canonical_identity(source, _roots)
    record["identity"] = _identity.as_dict()
    record["canonical_source_id"] = _identity.canonical_source_id
    solves = discover_local_solves(source.read_text(errors="replace"))
    record["local_solves_discovered"] = [s.as_dict() for s in solves]
    if not solves:
        record["bucket"] = "no_local_solve"
        return record
    material = entry.get("material")
    if not material:
        record["bucket"] = "blocked"
        record["blocked_by"] = "material_data_unavailable"
        record["reason"] = entry.get("material_blocker",
                                     "upstream provides no property vector")
        return record
    try:
        graph = resolve_closure(source, entry="UMAT",
                                roots=[base / r for r in entry.get("dependency_roots", [])])
    except DependencyResolutionError as exc:
        record["bucket"] = "blocked"
        record["reason"] = exc.detail
        return record
    if graph.missing or graph.conflicts:
        record["bucket"] = "blocked"
        record["reason"] = ("unresolved closure: "
                            + ", ".join(m.symbol for m in graph.missing)
                            + ", ".join(d.symbol for d in graph.conflicts))
        return record
    work = work_root / entry["id"]
    work.mkdir(parents=True, exist_ok=True)
    resolved = work / f"{entry['id']}_resolved.for"
    resolved.write_text(combined_source(graph), encoding="utf-8")
    record["dependency_closure"] = sorted(graph.resolved)
    record["multi_file"] = graph.is_multi_file
    record["material_data_source"] = material["provenance"]
    record["material_properties"] = list(material["props"])
    record["loading_history"] = {
        "dstran_per_increment": list(material["dstran_per_increment"]),
        "n_increments": int(material["n_increments"]),
    }
    record["entry_source_sha256"] = _sha256(source)
    record["dependency_closure_sha256"] = _identity.content_sha256
    declared_source = record["source"]
    ntens = int(entry["ntens"])
    record.update(verify_internal_jacobian(
        InternalJacobianCase(
            model=entry["id"], source_path=resolved,
            props=tuple(float(v) for v in material["props"]),
            dstran_per_increment=tuple(material["dstran_per_increment"]),
            n_increments=int(material["n_increments"]),
            ntens=ntens, nstatv=int(entry["nstatv"]),
            ndi=int(entry.get("ndi", 3)), nshr=int(entry.get("nshr", 1))),
        work))
    record["executed_source"] = record.get("source")
    record["source"] = declared_source
    record["bucket"] = _bucket(record)
    return record


def write_table3(records: list[dict], path: Path) -> None:
    """Table 3 rows. Only executed comparisons appear; nothing is imputed.

    A row is one *execution*. The canonical source id is carried explicitly
    because the same implementation is reachable from more than one origin --
    every ICP UMAT is normalised-identical to a file in the pinned upstream
    snapshot -- and two executions of one source with different upstream
    material are two validation events, not two models.
    """
    columns = ["canonical_source_id", "model", "origin", "iterate", "residual",
               "jacobian_variable", "increment", "converged_iterate", "oti",
               "finite_difference", "hand_coded", "oti_vs_fd_relative",
               "hand_coded_vs_fd_relative", "material_provenance", "verdict"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            extracted = record.get("extracted")
            if not extracted:
                continue
            solve = record.get("solve", {})
            fd = extracted["finite_difference"]
            denominator = max(abs(fd), 1e-300)
            writer.writerow({
                "canonical_source_id": record.get("canonical_source_id", ""),
                "model": record["id"],
                "origin": record["origin"],
                "iterate": solve.get("iteration_variable"),
                "residual": solve.get("residual_variable"),
                "jacobian_variable": solve.get("hand_coded_jacobian_variable"),
                "increment": record.get("target_increment"),
                "converged_iterate": f"{record.get('converged_iterate'):.17e}",
                "oti": f"{extracted['oti']:.17e}",
                "finite_difference": f"{fd:.17e}",
                "hand_coded": f"{extracted['hand_coded']:.17e}",
                "oti_vs_fd_relative": f"{abs(extracted['oti'] - fd) / denominator:.6e}",
                "hand_coded_vs_fd_relative":
                    f"{abs(extracted['hand_coded'] - fd) / denominator:.6e}",
                "material_provenance": record.get("material_data_source", ""),
                "verdict": record["bucket"],
            })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--work-dir", type=Path,
                        default=REPO_ROOT / "build" / "internal_jacobians")
    parser.add_argument(
        "--results-dir", type=Path, default=None,
        help=("where to write the round and Table 3. Defaults to the published "
              "location for a full round; a --model subset writes beside its "
              "work directory instead, so a partial round cannot replace "
              "published evidence."))
    args = parser.parse_args(argv)

    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    results = args.results_dir
    if results is None:
        results = RESULTS if not args.models else work / "results"
    if results != RESULTS:
        print(f"partial or redirected round: writing to {results}, leaving the "
              "published round untouched", flush=True)
    records: list[dict] = []

    for model in (args.models or _repo_models()):
        print(f"[repo]     {model}", flush=True)
        records.append(run_repo_model(model, work))

    if not args.models:
        external = json.loads(EXTERNAL.read_text(encoding="utf-8"))
        for entry in external["sources"]:
            print(f"[external] {entry['id']}", flush=True)
            records.append(run_external(entry, work))

        if CORPUS_SNAPSHOT.is_file():
            snapshot = json.loads(CORPUS_SNAPSHOT.read_text(encoding="utf-8"))
            repositories = {r["id"]: r for r in snapshot["repositories"]}
            override = os.environ.get(snapshot["snapshot_root_environment_variable"])
            root = (Path(override) if override
                    else (REPO_ROOT / snapshot["default_snapshot_root"]).resolve())
            for entry in snapshot["candidates"]:
                repository = repositories[entry["repository"]]
                if repository.get("metadata_only"):
                    continue
                print(f"[corpus]   {entry['id']}", flush=True)
                records.append(run_corpus_candidate(entry, repository, root, work))

    counts: dict[str, int] = {}
    for record in records:
        counts[record["bucket"]] = counts.get(record["bucket"], 0) + 1
    with_solve = [r for r in records if r["bucket"] != "no_local_solve"]

    round_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "funnel": {
            "candidate_sources": len(records),
            "unique_source_implementations": len(
                {r["canonical_source_id"] for r in records
                 if r.get("canonical_source_id")}),
            "sources_with_a_local_solve": len(with_solve),
            "unique_sources_with_a_local_solve": len(
                {r["canonical_source_id"] for r in with_solve
                 if r.get("canonical_source_id")}),
            "verification_executions": counts.get("verified", 0),
            "unique_sources_verified": len(
                {r["canonical_source_id"] for r in records
                 if r.get("bucket") == "verified" and r.get("canonical_source_id")}),
            "extracted_and_disagreeing": counts.get("failed", 0),
            "blocked": counts.get("blocked", 0),
            "no_local_solve": counts.get("no_local_solve", 0),
            "_note": ("candidate_sources counts appearances; "
                      "unique_source_implementations counts distinct code. The "
                      "same UMAT is reachable from the in-repository archive and "
                      "from the pinned upstream snapshot, and running it from "
                      "both with different upstream material is two validation "
                      "events against one implementation."),
        },
        "records": records,
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "internal_jacobian_round.json").write_text(
        json.dumps(round_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_table3(records, results / "table3_internal_jacobians.csv")

    print("\n" + json.dumps(round_payload["funnel"], indent=2))
    return 0 if counts.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
