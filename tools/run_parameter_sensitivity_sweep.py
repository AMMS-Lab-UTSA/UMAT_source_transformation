#!/usr/bin/env python3
"""Execute the parameter-sensitivity model set and build the real Table 6.

Generates a canonical contract for each model with the tested adapter, runs it
through the pipeline, and records exactly what happened at every stage. No
number in the output comes from anywhere but a run performed here.

The reported counts are deliberately a funnel -- attempted, transformed,
compiled, executed, verified -- because collapsing them into one number is how
"compiled" starts being read as "verified". A model that fails is kept in the
denominator with its reason.

    python tools/run_parameter_sensitivity_sweep.py --list
    python tools/run_parameter_sensitivity_sweep.py --model m1_elastic
    python tools/run_parameter_sensitivity_sweep.py            # all required models
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.services.contract_adapter import (  # noqa: E402
    ContractAdaptationError, adapt_v2_contract,
)
from umat_oti.services.transformation import (  # noqa: E402
    TransformationOptions, run_transformation,
)

MODELS_DIR = REPO_ROOT / "parameter_sensitivity" / "models"
LOADING_PATHS = REPO_ROOT / "parameter_sensitivity" / "loading_paths.json"
CONTRACTS_DIR = REPO_ROOT / "parameter_sensitivity" / "contracts"
RESULTS = REPO_ROOT / "paper_results" / "parameter_sensitivity"

REQUIRED = (
    "m1_elastic", "m2_cubic", "m3_j2", "m5_cpflow", "m6_fcc",
    "sweep_aniso_ortho", "sweep_damage_elastic", "sweep_eco",
    "sweep_j2_bilinear", "sweep_j2_combined", "sweep_j2_kinematic",
    "sweep_lame_elastic", "sweep_maxwell_ve", "sweep_mooney_small",
    "sweep_real_ECL_TEMP", "sweep_real_PCO", "sweep_thermoelastic",
    "sweep_transiso",
)


def loading_path(model: str, ntens: int) -> dict:
    """The declared material-point path for this model.

    Returns the block plus a note recording that the path was chosen by the
    pipeline rather than imported, because the source contracts define no
    loading history at all and that distinction belongs in the evidence.
    """
    spec = json.loads(LOADING_PATHS.read_text(encoding="utf-8"))
    block = dict(spec["overrides"].get(model) or spec["default"])
    dstran = list(block["dstran_per_increment"])
    if len(dstran) < ntens:
        dstran += [0.0] * (ntens - len(dstran))
    return {
        "dstran_per_increment": dstran[:ntens],
        "n_increments": int(block["n_increments"]),
        "_source": ("declared in parameter_sensitivity/loading_paths.json; "
                    + str(block.get("chosen_by", "pipeline default"))),
        "_rationale": block.get("rationale"),
    }


def generate_contract(model: str) -> tuple[Path, dict]:
    """Adapt the v2 contract and write the canonical one next to the models."""
    v2 = json.loads((MODELS_DIR / model / "contract_v2.json").read_text(encoding="utf-8"))
    adapted = adapt_v2_contract(
        v2, model=model, source_path=f"../models/{model}/umat.for")
    driver = loading_path(model, int(adapted.contract["ntens"]))
    nstatev = len(adapted.contract["state_variables"])
    if nstatev:
        driver["nstatv"] = nstatev
    # The full PROPS vector, not only the seeded parameters. A model may declare
    # more properties than it differentiates -- m5_cpflow seeds PROPS(3..8) and
    # leaves E and nu at PROPS(1..2) fixed -- and without these the driver would
    # run with those properties at zero and silently compute nonsense. The
    # transform skips any index that is already a seeded parameter.
    props_values = (v2.get("validation") or {}).get("props_values") or []
    if props_values:
        driver["static_props"] = [float(v) for v in props_values]
    adapted.contract["material_point_driver"] = driver
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CONTRACTS_DIR / f"{model}.json"
    payload = dict(adapted.contract)
    payload["_generated_by"] = (
        "tools/run_parameter_sensitivity_sweep.py via "
        "umat_oti.services.contract_adapter; edit contract_v2.json, not this file")
    payload["_adapter_notes"] = adapted.notes
    payload["_unmapped_v2_keys"] = sorted(adapted.unmapped)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, adapted.contract


def run_model(model: str, work_root: Path) -> dict:
    record: dict = {"model": model, "stages": {}}
    try:
        contract_path, contract = generate_contract(model)
    except ContractAdaptationError as exc:
        record["stages"]["contract"] = {"status": "failed", "reason": str(exc)}
        record["furthest_stage"] = "contract"
        return record
    record["stages"]["contract"] = {"status": "succeeded",
                                    "path": str(contract_path.relative_to(REPO_ROOT))}
    record["parameters"] = [p["name"] for p in contract["parameters"]]
    record["parameter_count"] = len(contract["parameters"])
    record["targets"] = [r["target"] for r in contract["derivatives"]]
    record["furthest_stage"] = "contract"

    out = work_root / model
    if out.exists():
        shutil.rmtree(out)
    started = time.time()
    summary, exit_code = run_transformation(
        contract_path, out, TransformationOptions(compile_generated=True))
    elapsed = round(time.time() - started, 3)

    transformed = bool(summary.get("transform_success"))
    record["stages"]["transform"] = {
        "status": "succeeded" if transformed else "failed",
        "exit_code": exit_code,
        "seconds": elapsed,
        "status_category": summary.get("status_category"),
        "reason": (summary.get("error")
                   or (summary.get("blockers") or [{}])[0].get("message")
                   if not transformed else None),
        "warnings": len(summary.get("warnings") or []),
    }
    if not transformed:
        return record
    record["furthest_stage"] = "transform"

    compilation = summary.get("compilation") or {}
    compiled = compilation.get("status") == "compiled"
    record["stages"]["compile"] = {
        "status": "succeeded" if compiled else "failed",
        "compiler_status": compilation.get("status"),
        "reason": (compilation.get("stderr") or "")[:400] if not compiled else None,
    }
    if compiled:
        record["furthest_stage"] = "compile"

    # Executing and verifying are separate stages and are NOT claimed here.
    record["stages"]["execute"] = {
        "status": "not_implemented",
        "reason": ("a DSIGMA_DP material-point driver for this contract shape is not "
                   "yet generated by the pipeline; compiling is not executing"),
    }
    record["stages"]["verify"] = {
        "status": "not_implemented",
        "reason": ("no independent reference has been computed for these models here; "
                   "compiling is not verifying"),
    }
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--work-dir", type=Path,
                        default=REPO_ROOT / "umat_oti_workspace" / "parameter_sensitivity")
    args = parser.parse_args(argv)

    if args.list:
        for model in REQUIRED:
            print(model)
        return 0

    models = args.models or list(REQUIRED)
    records = [run_model(m, args.work_dir) for m in models]

    def count(stage: str) -> int:
        return sum(1 for r in records
                   if (r["stages"].get(stage) or {}).get("status") == "succeeded")

    funnel = {
        "attempted": len(records),
        "contract_generated": count("contract"),
        "transformed": count("transform"),
        "compiled": count("compile"),
        "executed": 0,
        "numerically_verified": 0,
        "parameter_directions_declared": sum(r.get("parameter_count", 0) for r in records),
        "parameter_directions_verified": 0,
    }
    taxonomy: dict[str, list[str]] = {}
    for record in records:
        stage = record["stages"].get(record["furthest_stage"], {})
        if record["furthest_stage"] != "compile":
            key = f"{record['furthest_stage']}:{stage.get('status_category') or stage.get('status')}"
            taxonomy.setdefault(key, []).append(record["model"])

    payload = {
        "schema": "umat-oti-parameter-sensitivity-round/1",
        "policy": (
            "Counts are a funnel, not a single number. 'compiled' is not 'executed' "
            "and neither is 'verified'. Models that fail stay in the denominator."
        ),
        "funnel": funnel,
        "failure_taxonomy": taxonomy,
        "models": records,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "parameter_sensitivity_round.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Table 6 as measured. Every model stays in the table with the stage it
    # actually reached; a model that got no further than compiling says so.
    import csv as _csv
    table = RESULTS / "table6_parameter_sensitivity.csv"
    with table.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.writer(handle, lineterminator="\n")
        writer.writerow(["model", "parameter_directions", "parameters",
                         "contract_generated", "transformed", "compiled",
                         "executed", "numerically_verified", "furthest_stage",
                         "targets", "failure_reason"])
        for r in records:
            st = r["stages"]
            def ok(name):
                return (st.get(name) or {}).get("status") == "succeeded"
            reason = ""
            for name in ("contract", "transform", "compile"):
                entry = st.get(name) or {}
                if entry.get("status") == "failed":
                    reason = f"{name}: {(entry.get('reason') or '')[:160]}"
                    break
            writer.writerow([
                r["model"], r.get("parameter_count", 0),
                "|".join(r.get("parameters", [])),
                ok("contract"), ok("transform"), ok("compile"),
                False, False, r["furthest_stage"],
                "|".join(r.get("targets", [])), reason,
            ])
    print(f"wrote {table.relative_to(REPO_ROOT)}")

    print(json.dumps(funnel, indent=2))
    if taxonomy:
        print("\nfailure taxonomy:")
        for key, names in sorted(taxonomy.items()):
            print(f"  {key}: {len(names)} -> {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
