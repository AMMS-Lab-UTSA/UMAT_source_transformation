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
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_parameter_sensitivity_sweep import generate_contract  # noqa: E402

from umat_oti.transform.internal_jacobian import discover_local_solves  # noqa: E402
from umat_oti.validation.actual_umat_higher_order_generic import MODELS  # noqa: E402
from umat_oti.validation.internal_jacobian_validation import (  # noqa: E402
    InternalJacobianCase,
    verify_internal_jacobian,
)

MODELS_DIR = REPO_ROOT / "parameter_sensitivity" / "models"
EXTERNAL = REPO_ROOT / "parameter_sensitivity" / "internal_jacobian_sources.json"
RESULTS = REPO_ROOT / "paper_results" / "internal_jacobians"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_models() -> list[str]:
    return sorted(d.name for d in MODELS_DIR.iterdir()
                  if (d / "contract_v2.json").is_file())


def run_repo_model(model: str, work_root: Path) -> dict:
    source = MODELS_DIR / model / "umat.for"
    record: dict = {
        "id": model,
        "origin": "repository",
        "source": f"parameter_sensitivity/models/{model}/umat.for",
        "source_sha256": _sha256(source),
    }
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
    record.update(verify_internal_jacobian(case, work_root / model))
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


def write_table3(records: list[dict], path: Path) -> None:
    """Table 3 rows. Only executed comparisons appear; nothing is imputed."""
    columns = ["model", "origin", "iterate", "residual", "jacobian_variable",
               "increment", "converged_iterate", "oti", "finite_difference",
               "hand_coded", "oti_vs_fd_relative", "hand_coded_vs_fd_relative",
               "verdict"]
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
                "verdict": record["bucket"],
            })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--work-dir", type=Path,
                        default=REPO_ROOT / "build" / "internal_jacobians")
    args = parser.parse_args(argv)

    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    for model in (args.models or _repo_models()):
        print(f"[repo]     {model}", flush=True)
        records.append(run_repo_model(model, work))

    if not args.models:
        external = json.loads(EXTERNAL.read_text(encoding="utf-8"))
        for entry in external["sources"]:
            print(f"[external] {entry['id']}", flush=True)
            records.append(run_external(entry, work))

    counts: dict[str, int] = {}
    for record in records:
        counts[record["bucket"]] = counts.get(record["bucket"], 0) + 1
    with_solve = [r for r in records if r["bucket"] != "no_local_solve"]

    round_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "funnel": {
            "candidate_sources": len(records),
            "sources_with_a_local_solve": len(with_solve),
            "extracted_and_verified": counts.get("verified", 0),
            "extracted_and_disagreeing": counts.get("failed", 0),
            "blocked": counts.get("blocked", 0),
            "no_local_solve": counts.get("no_local_solve", 0),
        },
        "records": records,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "internal_jacobian_round.json").write_text(
        json.dumps(round_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_table3(records, RESULTS / "table3_internal_jacobians.csv")

    print("\n" + json.dumps(round_payload["funnel"], indent=2))
    return 0 if counts.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
