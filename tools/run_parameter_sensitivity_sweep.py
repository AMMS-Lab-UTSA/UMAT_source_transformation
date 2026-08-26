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

from umat_oti.validation.reference_resolution import (
    converged_value, measure_reference_resolution, select_reference_step,
)
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
    "sweep_aniso_ortho", "sweep_damage_elastic", "sweep_drucker_prager",
    "sweep_eco", "sweep_j2_bilinear", "sweep_j2_combined",
    "sweep_j2_kinematic", "sweep_lame_elastic", "sweep_maxwell_ve",
    "sweep_mooney_small", "sweep_perzyna_linear", "sweep_real_ECL_TEMP",
    "sweep_real_PCO", "sweep_thermoelastic", "sweep_transiso",
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
        "reason": _failure_reason(summary) if not transformed else None,
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



#: Arrays a row can belong to, mapped to the OTI output that carries them.
_ARRAY_CSV = {"DSIGMA_DP": "DSIGMA_DP_OTI.csv", "DSTATEV_DP": "DSTATEV_DP_OTI.csv"}


def _readjudicate_at_converged_step(rows, *, executable, props, path, ntens,
                                    nstatv, parameters, ps_dir, stress_scale,
                                    branches):
    """Re-check disagreeing rows against a converged finite-difference step.

    A fixed reference step is a guess about the model's third derivative. When a
    row disagrees, the first question is whether the reference itself was the
    limitation, and that is answered by making the reference better rather than
    the test weaker: the step is chosen from the method's own convergence and
    the comparison is repeated. Rows that still disagree stay failures.

    Only disagreeing rows are re-examined, so a model whose reference was
    adequate costs nothing.
    """
    failing = [r for r in rows if r.agrees is False]
    if not failing:
        return rows, None

    by_parameter = {p["name"]: p for p in parameters}
    groups = sorted({(r.parameter, r.array) for r in failing})
    evidence: dict = {"groups": [], "policy": (
        "disagreeing rows are re-judged against a centred difference evaluated at "
        "a step chosen by the method's own convergence; the tolerance is unchanged")}
    replacements: dict = {}

    for parameter_name, array in groups:
        parameter = by_parameter.get(parameter_name)
        if parameter is None or array not in _ARRAY_CSV:
            continue
        ladder = measure_reference_resolution(
            executable, props, path, ntens=ntens, nstatv=nstatv,
            props_index=parameter["props_index"], array=array)
        step = select_reference_step(ladder)
        entry = {"parameter": parameter_name, "array": array,
                 "ladder_steps": list(ladder.steps),
                 "group_selected_relative_step": step}
        source_csv = ps_dir / _ARRAY_CSV[array]
        if not source_csv.is_file():
            entry["outcome"] = "the OTI output for this array is missing"
            evidence["groups"].append(entry)
            continue
        oti_table = read_oti_csv(source_csv)

        # One step per entry, not per parameter: different components of the
        # same array reach their turning point at different steps.
        per_entry = {}
        rejudged = 0
        for row in failing:
            if (row.parameter, row.array) != (parameter_name, array):
                continue
            best = converged_value(ladder, row.increment, row.component)
            if best is None:
                continue
            value, chosen, uncertainty = best
            oti_entry = oti_table.get((row.increment, row.component)) or {}
            oti_value = oti_entry.get(parameter_name.upper(),
                                      oti_entry.get(parameter_name))
            if oti_value is None:
                continue
            magnitude = max(abs(oti_value), abs(value))
            absolute = abs(oti_value - value)
            relative = absolute / magnitude if magnitude else 0.0
            if relative <= 1.0e-6:
                agrees = True
            elif absolute <= uncertainty:
                # The reference still moves by more than this between
                # consecutive steps, so it cannot say the value is wrong.
                agrees = None
            else:
                agrees = False
            per_entry[(row.array, row.parameter, row.increment, row.component)] = (
                value, chosen, absolute, relative, agrees, uncertainty)
            rejudged += 1
        entry["outcome"] = "re-judged per entry"
        entry["rows_rejudged"] = rejudged
        entry["steps_used"] = sorted({v[1] for v in per_entry.values()})
        evidence["groups"].append(entry)

        replacements.update(per_entry)

    if not replacements:
        return rows, evidence

    updated = []
    changed = 0
    for row in rows:
        key = (row.array, row.parameter, row.increment, row.component)
        replacement = replacements.get(key)
        if replacement is not None and row.agrees is False:
            value, chosen, absolute, relative, agrees, uncertainty = replacement
            row.reference = value
            row.absolute_error = absolute
            row.relative_error = relative
            row.agrees = agrees
            row.judged_by = (
                f"reference_unresolved_at_converged_step_{chosen:g}"
                if agrees is None else f"relative_at_converged_step_{chosen:g}")
            if agrees is not False:
                changed += 1
        updated.append(row)
    evidence["rows_reclassified"] = changed
    return updated, evidence


def _failure_reason(summary: dict) -> str | None:
    """Why the transformation failed, whatever shape the blocker took.

    Blockers are sometimes dicts carrying a message and sometimes plain
    strings. Assuming a dict made the reporter itself raise on the failure
    path, so a run that failed for one reason ended with a traceback about
    something else entirely and the real reason was never printed.
    """
    error = summary.get("error")
    if error:
        return str(error)
    for blocker in summary.get("blockers") or []:
        if isinstance(blocker, dict):
            message = blocker.get("message") or blocker.get("reason")
            if message:
                return str(message)
        elif blocker:
            return str(blocker)
    category = summary.get("status_category")
    return f"transformation failed ({category})" if category else None


def _unresolved_reason(rows, disagreeing, unresolved) -> str | None:
    """Say which of the two reasons a reference could not adjudicate applies.

    They are different findings. A noise-floor row means the difference is
    smaller than the method can measure. A branch-crossing row means the
    stencil straddled a kink and measured a secant across it -- which is a
    statement about where the model yields, not about resolution. Reporting
    both as "sit at the noise floor" put a discontinuity finding under a
    precision heading.
    """
    if not disagreeing and not unresolved:
        return None
    parts = []
    if disagreeing:
        parts.append(f"{len(disagreeing)} of {len(rows)} rows disagree with the "
                     "centred-difference reference")
    crossing = [r for r in unresolved if r.branch_crossing]
    noise = [r for r in unresolved if not r.branch_crossing]
    if noise:
        parts.append(f"{len(noise)} of {len(rows)} rows sit at the "
                     "centred-difference noise floor and cannot be resolved by it")
    if crossing:
        increments = sorted({r.increment for r in crossing})
        where = ", ".join(str(i) for i in increments)
        parts.append(
            f"{len(crossing)} of {len(rows)} rows sit on a branch boundary "
            f"(increment{'s' if len(increments) > 1 else ''} {where}), where the "
            "centred difference straddles the kink and returns a secant rather "
            "than the derivative on the branch the increment took")
    return "; ".join(parts)


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

    rows, converged = _readjudicate_at_converged_step(
        rows, executable=executable, props=props, path=path, ntens=ntens,
        nstatv=nstatv, parameters=parameters, ps_dir=ps_dir,
        stress_scale=max((abs(v) for row in original.stress for v in row), default=1.0),
        branches=branches)
    if converged:
        record["reference_step_convergence"] = converged

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
    # Three outcomes, not two. A model whose every row agreed or could not be
    # adjudicated has produced no evidence of a defect, and calling that
    # "failed" alongside a model that genuinely disagrees loses the distinction
    # the comparison was built to preserve. It is still not verified: an
    # unresolved row withholds its direction.
    if not disagreeing and not unresolved:
        verdict = "succeeded"
    elif disagreeing:
        verdict = "failed"
    else:
        verdict = "unresolved"
    record["stages"]["derivatives_verified"] = {
        "status": verdict,
        "rows": len(rows),
        "rows_agreeing": len(agreeing),
        "rows_disagreeing": len(disagreeing),
        "rows_reference_unresolved": len(unresolved),
        # Split out, because the two reasons a reference cannot adjudicate are
        # different findings: one says the difference is too small to measure,
        # the other says the stencil crossed a kink and measured the wrong
        # thing. Pooling them hides which increments carry a discontinuity.
        "rows_reference_unresolved_at_noise_floor":
            sum(1 for r in unresolved if not r.branch_crossing),
        "rows_reference_unresolved_by_branch_crossing":
            sum(1 for r in unresolved if r.branch_crossing),
        "increments_with_branch_crossing":
            sorted({r.increment for r in rows if r.branch_crossing}),
        "rows_substantive": len(substantive),
        "worst_relative_error": max((r.relative_error for r in substantive
                                     if r.relative_error is not None), default=None),
        "elastic_increments": branches.count("elastic"),
        "inelastic_increments": branches.count("inelastic"),
        "verdict_meaning": {
            "succeeded": "every row resolved and agreed",
            "failed": "at least one row disagrees with a reference that can adjudicate it",
            "unresolved": ("no row disagrees; some cannot be adjudicated by "
                           "centred differences, so those directions are "
                           "withheld rather than claimed"),
        }[verdict],
        "reason": _unresolved_reason(rows, disagreeing, unresolved),
    }
    record["verified_parameter_directions"] = verified_directions
    record["comparison_rows"] = [r.as_dict() for r in rows]
    if not disagreeing and not unresolved:
        record["furthest_stage"] = "derivatives_verified"
    elif not disagreeing:
        # The comparison ran to completion; it simply could not adjudicate every
        # row. Leaving furthest_stage at primal_parity would report this model
        # as having stopped before the comparison, which is not what happened.
        record["furthest_stage"] = "derivatives_unresolved"


def _display(path: Path) -> str:
    """Repository-relative when it can be, absolute otherwise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--work-dir", type=Path,
                        default=REPO_ROOT / "umat_oti_workspace" / "parameter_sensitivity")
    parser.add_argument(
        "--results-dir", type=Path, default=None,
        help=("where to write the round and its tables. Defaults to the published "
              "location, which a partial run must not overwrite: a --model "
              "subset writes elsewhere unless this is given explicitly."))
    args = parser.parse_args(argv)

    if args.list:
        for model in REQUIRED:
            print(model)
        return 0

    models = args.models or list(REQUIRED)
    # A subset run produces a round covering only that subset. Writing it to the
    # published location would silently replace the full Table 6 evidence with a
    # partial one that still looks complete, so a subset defaults elsewhere and
    # has to be pointed at the published path deliberately.
    results_dir = args.results_dir
    if results_dir is None:
        results_dir = RESULTS if not args.models else args.work_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    if results_dir != RESULTS:
        scope = ("full round" if len(models) == len(REQUIRED)
                 else f"partial round ({len(models)} of {len(REQUIRED)} models)")
        print(f"{scope}: writing to {results_dir}, leaving the published round "
              "untouched", flush=True)

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
            status = (entry or {}).get("status")
            if status in ("failed", "unresolved"):
                # "unresolved" is a distinct outcome: the stage ran and found no
                # disagreement, but the reference could not adjudicate every
                # row. Folding it into "failed" would claim a defect nobody
                # measured; folding it into the stopped_after branch would
                # claim the stage never ran.
                key = f"{name}:{entry.get('status_category') or status}"
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
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "parameter_sensitivity_round.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Table 6 as measured. Every model stays in the table with the stage it
    # actually reached; a model that got no further than compiling says so.
    import csv as _csv
    table = results_dir / "table6_parameter_sensitivity.csv"
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
    print(f"wrote {_display(table)}")

    raw = results_dir / "table6_comparison_rows.csv"
    with raw.open("w", newline="", encoding="utf-8") as handle:
        writer = _csv.writer(handle, lineterminator="\n")
        writer.writerow(["model", "increment", "array", "component", "parameter",
                         "props_index", "oti_direction", "oti", "reference",
                         "absolute_error", "relative_error", "judged_by",
                         "agrees", "branch", "branch_crossing"])
        for r in records:
            for row in r.get("comparison_rows", []):
                writer.writerow([r["model"], row["increment"], row["array"],
                                 row["component"], row["parameter"], row["props_index"],
                                 row["oti_direction"], row["oti"], row["reference"],
                                 row["absolute_error"], row["relative_error"],
                                 row["judged_by"], row["agrees"], row["branch"],
                                 row.get("branch_crossing", False)])
    print(f"wrote {_display(raw)}")

    # Rows live in the CSV; keep the round JSON readable. Done only *after* the
    # CSV is written -- popping first silently produced an empty raw-row file.
    for record in payload["models"]:
        record.pop("comparison_rows", None)
    (results_dir / "parameter_sensitivity_round.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(funnel, indent=2))
    if taxonomy:
        print("\nfailure taxonomy:")
        for key, names in sorted(taxonomy.items()):
            print(f"  {key}: {len(names)} -> {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
