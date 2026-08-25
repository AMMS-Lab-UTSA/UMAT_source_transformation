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
import subprocess
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
from umat_oti.validation.parameter_sensitivity_validation import (  # noqa: E402
    build_original_driver, centered_fd, compare, primal_parity, read_oti_csv, replay,
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

    _execute_and_verify(model, contract, out, record)
    return record


def _execute_and_verify(model: str, contract: dict, out: Path, record: dict) -> None:
    """Build+run the OTI driver, check primal parity, then compare against FD.

    Each of these is its own stage with its own status, so a model that runs but
    disagrees is distinguishable from one that never ran.
    """
    ps_dir = out / "parameter_sensitivity"
    driver = ps_dir / "ps_driver"
    mpd = contract["material_point_driver"]
    ntens = int(contract["ntens"])
    nstatv = len(contract["state_variables"])
    props = [float(v) for v in mpd.get("static_props", [])]
    path = [list(mpd["dstran_per_increment"])] * int(mpd["n_increments"])
    parameters = contract["parameters"]

    # --- build + run the OTI driver -------------------------------------- #
    if not (ps_dir / "Makefile").exists():
        record["stages"]["executed_oti"] = {
            "status": "failed",
            "reason": "the transform produced no parameter-sensitivity driver"}
        return
    build = subprocess.run(["make"], cwd=ps_dir, capture_output=True, text=True)
    if build.returncode != 0 or not driver.exists():
        record["stages"]["executed_oti"] = {
            "status": "failed", "reason": f"OTI driver build failed: {build.stderr[:300]}"}
        return
    run = subprocess.run([str(driver)], cwd=ps_dir, capture_output=True, text=True)
    if run.returncode != 0:
        record["stages"]["executed_oti"] = {
            "status": "failed",
            "reason": f"OTI driver run failed (rc={run.returncode}): {run.stderr[:300]}"}
        return
    record["stages"]["executed_oti"] = {"status": "succeeded"}
    record["furthest_stage"] = "executed_oti"

    # --- build + run the ORIGINAL reference ------------------------------ #
    source = REPO_ROOT / "parameter_sensitivity" / "models" / model / "umat.for"
    reference_dir = out / "original_reference"
    try:
        executable = build_original_driver(
            source, reference_dir, ntens=ntens, nstatv=nstatv, nprops=len(props))
        original = replay(executable, props, path, ntens=ntens, nstatv=nstatv)
    except RuntimeError as exc:
        record["stages"]["executed_original"] = {"status": "failed", "reason": str(exc)[:400]}
        return
    record["stages"]["executed_original"] = {
        "status": "succeeded", "increments": original.increments}
    record["furthest_stage"] = "executed_original"

    # --- primal parity gates everything downstream ----------------------- #
    try:
        parity = primal_parity(original, ps_dir / "primal_stress_state_OTI.csv",
                               ntens=ntens, nstatv=nstatv)
    except (OSError, KeyError, ValueError) as exc:
        record["stages"]["primal_parity"] = {"status": "failed", "reason": str(exc)[:300]}
        return
    worst = max((p["max_relative_difference"] for p in parity["per_increment"]), default=0.0)
    record["stages"]["primal_parity"] = {
        "status": "succeeded" if parity["agrees"] else "failed",
        "worst_relative_difference": worst,
        "reason": None if parity["agrees"] else (
            "the original and transformed builds compute different stress along the "
            "path, so their derivatives are not comparable quantities"),
    }
    if not parity["agrees"]:
        return
    record["furthest_stage"] = "primal_parity"

    # --- independent reference: centred FD of the ORIGINAL UMAT ---------- #
    branches = ["inelastic" if (sv and abs(sv[0]) > 1e-12) else "elastic"
                for sv in original.statev]
    try:
        reference = centered_fd(
            executable, props, path, ntens=ntens, nstatv=nstatv,
            props_indices=[p["props_index"] for p in parameters])
    except RuntimeError as exc:
        record["stages"]["reference_resolved"] = {"status": "failed", "reason": str(exc)[:300]}
        return
    record["stages"]["reference_resolved"] = {"status": "succeeded"}

    rows = []
    for name, csv_name in (("DSIGMA_DP", "DSIGMA_DP_OTI.csv"),
                           ("DSTATEV_DP", "DSTATEV_DP_OTI.csv")):
        source_csv = ps_dir / csv_name
        if not source_csv.exists():
            continue
        if name == "DSTATEV_DP" and nstatv == 0:
            continue
        stress_scale = max((abs(v) for row in original.stress for v in row), default=1.0)
        rows += compare(read_oti_csv(source_csv), reference, array=name,
                        parameters=parameters, branches=branches,
                        response_scale=stress_scale)
    if not rows:
        record["stages"]["derivatives_verified"] = {
            "status": "failed", "reason": "no comparable derivative rows were produced"}
        return

    agreeing = [r for r in rows if r.agrees is True]
    disagreeing = [r for r in rows if r.agrees is False]
    unresolved = [r for r in rows if r.agrees is None]
    substantive = [r for r in rows if r.judged_by == "relative"]
    # A direction counts as verified only if every one of its rows was resolved
    # and agreed. One unresolvable row withholds the direction.
    by_parameter: dict[str, list] = {}
    for row in rows:
        by_parameter.setdefault(row.parameter, []).append(row)
    verified_directions = sorted(
        name for name, group in by_parameter.items()
        if all(r.agrees is True for r in group))
    record["stages"]["derivatives_verified"] = {
        "status": "succeeded" if (not disagreeing and not unresolved) else "failed",
        "rows": len(rows),
        "rows_agreeing": len(agreeing),
        "rows_disagreeing": len(disagreeing),
        "rows_reference_unresolved": len(unresolved),
        "rows_substantive": len(substantive),
        "worst_relative_error": max((r.relative_error for r in substantive
                                     if r.relative_error is not None), default=None),
        "elastic_increments": branches.count("elastic"),
        "inelastic_increments": branches.count("inelastic"),
        "reason": None if (not disagreeing and not unresolved) else
                  (f"{len(disagreeing)} of {len(rows)} rows disagree with the "
                   f"centred-difference reference" if disagreeing else "")
                  + ("; " if disagreeing and unresolved else "")
                  + (f"{len(unresolved)} of {len(rows)} rows sit at the "
                     f"centred-difference noise floor and cannot be resolved by it"
                     if unresolved else ""),
    }
    record["verified_parameter_directions"] = verified_directions
    record["comparison_rows"] = [r.as_dict() for r in rows]
    if not disagreeing and not unresolved:
        record["furthest_stage"] = "derivatives_verified"


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
        "contract_complete": count("contract"),
        "transformed": count("transform"),
        "compiled_oti": count("compile"),
        "executed_oti": count("executed_oti"),
        "executed_original": count("executed_original"),
        "primal_parity": count("primal_parity"),
        "reference_resolved": count("reference_resolved"),
        "derivatives_verified": count("derivatives_verified"),
        "parameter_directions_declared": sum(r.get("parameter_count", 0) for r in records),
        "parameter_directions_verified": sum(
            len(r.get("verified_parameter_directions", [])) for r in records),
        "comparison_rows_total": sum(len(r.get("comparison_rows", [])) for r in records),
        "comparison_rows_agreeing": sum(
            sum(1 for row in r.get("comparison_rows", []) if row["agrees"])
            for r in records),
    }
    # Only actual problems belong in a failure taxonomy. A model that reached the
    # end of the funnel is not a failure mode.
    taxonomy: dict[str, list[str]] = {}
    for record in records:
        if record["furthest_stage"] == "derivatives_verified":
            continue
        for name, entry in record["stages"].items():
            if (entry or {}).get("status") == "failed":
                key = f"{name}:{entry.get('status_category') or 'failed'}"
                taxonomy.setdefault(key, []).append(record["model"])
                break
        else:
            taxonomy.setdefault(f"stopped_after:{record['furthest_stage']}", []).append(
                record["model"])

    payload = {
        "schema": "umat-oti-parameter-sensitivity-round/2",
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
            for name in ("contract", "transform", "compile", "executed_oti",
                         "executed_original", "primal_parity", "reference_resolved",
                         "derivatives_verified"):
                entry = st.get(name) or {}
                if entry.get("status") == "failed":
                    reason = f"{name}: {(entry.get('reason') or '')[:200]}"
                    break
            dv = st.get("derivatives_verified") or {}
            writer.writerow([
                r["model"], r.get("parameter_count", 0),
                "|".join(r.get("parameters", [])),
                ok("contract"), ok("transform"), ok("compile"),
                ok("executed_oti"), ok("executed_original"), ok("primal_parity"),
                ok("reference_resolved"), ok("derivatives_verified"),
                len(r.get("verified_parameter_directions", [])),
                dv.get("rows", 0), dv.get("worst_relative_error", ""),
                dv.get("elastic_increments", ""), dv.get("inelastic_increments", ""),
                r["furthest_stage"], reason,
            ])
    print(f"wrote {table.relative_to(REPO_ROOT)}")

    raw = RESULTS / "table6_comparison_rows.csv"
    with raw.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.writer(handle, lineterminator="\n")
        writer.writerow(["model", "increment", "array", "component", "parameter",
                         "props_index", "oti_direction", "oti", "reference",
                         "absolute_error", "relative_error", "judged_by",
                         "agrees", "branch"])
        for r in records:
            for row in r.get("comparison_rows", []):
                writer.writerow([r["model"], row["increment"], row["array"],
                                 row["component"], row["parameter"], row["props_index"],
                                 row["oti_direction"], row["oti"], row["reference"],
                                 row["absolute_error"], row["relative_error"],
                                 row["judged_by"], row["agrees"], row["branch"]])
    print(f"wrote {raw.relative_to(REPO_ROOT)}")

    # Rows live in the CSV; keep the round JSON readable. Done only *after* the
    # CSV is written -- popping first silently produced an empty raw-row file.
    for record in payload["models"]:
        record.pop("comparison_rows", None)
    (RESULTS / "parameter_sensitivity_round.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(funnel, indent=2))
    if taxonomy:
        print("\nfailure taxonomy:")
        for key, names in sorted(taxonomy.items()):
            print(f"  {key}: {len(names)} -> {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
