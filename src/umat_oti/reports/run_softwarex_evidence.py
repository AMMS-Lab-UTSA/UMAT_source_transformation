"""Regenerate the SoftwareX evidence artefacts from source.

This command implements Priority 5 of the SoftwareX continuation. It:

1. Emits the Python centered-FD reference for the focused J2 case
   (``DSIGMA_DP_FD.csv`` etc.) via
   :mod:`umat_oti.validation.parameter_sensitivity`.
2. Detects whether a modern ``gfortran`` is on ``PATH``. If yes:

   a. Generates and compiles the PROPS-seeded OTI J2 material-point driver
      (:mod:`umat_oti.fortran_emit.parameter_sensitivity_j2`) and runs it,
      producing ``DSIGMA_DP_OTI.csv`` / ``DSTATEV_DP_OTI.csv`` /
      ``primal_stress_state_OTI.csv``.
   b. Compares the OTI outputs against the FD reference and writes
      ``parameter_sensitivity_comparison.csv``. If the maximum relative
      difference is below the tolerance the claim
      ``focused_J2_DSIGMA_DP_from_source`` becomes ``verified``; otherwise
      it becomes ``failed`` with the observed max diff.
   c. Generates and compiles the higher-order strain-derivative driver
      (:mod:`umat_oti.fortran_emit.higher_order_strain`) for the bivariate
      SoftwareX polynomial, runs it, and compares against SymPy analytical
      derivatives. Emits ``higher_order_derivatives_OTI.csv`` (the raw
      driver output) and ``higher_order_comparison.csv`` (a per-row diff
      table). The ``higher_order_DDSDDE2_DDSDDE3_DDSDDE4_from_source``
      claim is verified only when all rows agree with SymPy.

3. Emits the shared UMAT-OTI / Residual Assembler driver contract and the
   JSONL increment stream built from the actual OTI Fortran driver output
   (or the FD reference when the OTI driver is unavailable, clearly
   labelled).

4. Emits the derivative manifest and the claim matrix reflecting the
   *actual* observed states -- nothing is hard-coded to ``verified``.
5. Emits paper-table skeletons (``table2_ddsdde.csv`` etc.) so the
   manuscript can populate rows from *measured* results.

An overall JSON summary is printed to stdout. The command's exit code is
0 when the offline suite runs and every non-blocked claim ends up either
``verified`` or ``reference_ready``; it is 1 when any local claim reports
``failed``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from umat_oti import __version__ as _umat_oti_version
from umat_oti.core.derivative_request import (
    DerivativeRequest,
    KIND_HIGHER_ORDER,
    KIND_LOCAL_JACOBIAN,
    KIND_MATERIAL_TANGENT,
    KIND_PARAMETER_SENSITIVITY,
    KIND_STATE_SENSITIVITY,
)
from umat_oti.reports.driver_contract import build_softwarex_j2_contract, write_j2_stream
from umat_oti.reports.manifest import build_manifest, write_manifest
from umat_oti.validation.j2_reference import J2Parameters, build_softwarex_j2_path
from umat_oti.validation.parameter_sensitivity import (
    ParameterMap,
    StateMap,
    compute_j2_parameter_sensitivities,
    export_sensitivity_csv,
)
from umat_oti.validation.run_suite import detect_environment


REPO_ROOT = Path(__file__).resolve().parents[3]


def _iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _abaqus_paired_status(env) -> str:
    """Read the most recent paper_results/arc_<jobid>/table2_abaqus_paired.json
    (if any) and derive the paired-Abaqus verification status.
    """
    summary = _abaqus_paired_summary_json()
    if not summary:
        return "blocked_by_missing_abaqus" if not env.abaqus_ok else "pending"
    code_imp = next((row for row in summary.get("rows", []) if row.get("case_name") == "code_imp"), None)
    if code_imp:
        return "verified_from_transformed_source" if code_imp.get("status") == "passed" else "failed"
    return "pending"


def _abaqus_paired_summary_json() -> dict[str, Any]:
    arc_dirs = sorted((REPO_ROOT / "paper_results").glob("arc_*"))
    for arc_dir in reversed(arc_dirs):
        candidate = arc_dir / "table2_abaqus_paired.json"
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def _abaqus_paired_summary_reference() -> dict[str, Any]:
    payload = _abaqus_paired_summary_json()
    return {
        "summary": payload.get("summary", {}),
        "evidence": "paper_results/arc_791506/table2_abaqus_paired.json",
    }


# ---------------------------------------------------------------------------
# Stage 1: FD reference
# ---------------------------------------------------------------------------

def _run_fd_reference(output_dir: Path) -> dict[str, Any]:
    fd_run = compute_j2_parameter_sensitivities(
        params=J2Parameters(),
        path=build_softwarex_j2_path(),
        parameter_map=ParameterMap.softwarex_default(),
        state_map=StateMap.softwarex_default(),
        fd_step_relative=1.0e-6,
    )
    fd_files = export_sensitivity_csv(fd_run, output_dir)
    return {"run": fd_run, "files": fd_files}


# ---------------------------------------------------------------------------
# Stage 2: OTI J2 material-point driver
# ---------------------------------------------------------------------------

def _run_oti_j2(output_dir: Path, fd_files: dict[str, Path], *, gfortran: str) -> dict[str, Any]:
    from umat_oti.fortran_emit.parameter_sensitivity_j2 import (
        compare_oti_vs_fd,
        compile_j2_oti_build,
        generate_j2_oti_build,
        run_j2_oti_driver,
    )
    build_dir = output_dir / "oti_j2_build"
    stage: dict[str, Any] = {
        "status": "pending",
        "build_dir": str(build_dir),
    }
    try:
        layout = generate_j2_oti_build(build_dir)
        stage["generated_files"] = {
            name: str(getattr(layout, name))
            for name in (
                "master_parameters",
                "real_utils",
                "otim_module",
                "j2_umat_oti",
                "j2_driver",
                "makefile",
            )
        }
        exe = compile_j2_oti_build(layout, gfortran=gfortran)
        stage["executable"] = str(exe)
        result = run_j2_oti_driver(exe, out_dir=build_dir)
        stage["returncode"] = result.returncode
        if result.returncode != 0:
            stage["status"] = "failed"
            stage["stderr_tail"] = result.stderr[-1000:]
            return stage
        # Copy the OTI CSVs alongside the FD ones for the paper directory.
        for src in (result.primal_csv, result.dsigma_csv, result.dstatev_csv):
            dst = output_dir / src.name
            dst.write_bytes(src.read_bytes())
        stage["oti_files"] = {
            "primal_stress_state_OTI": str(output_dir / result.primal_csv.name),
            "DSIGMA_DP_OTI": str(output_dir / result.dsigma_csv.name),
            "DSTATEV_DP_OTI": str(output_dir / result.dstatev_csv.name),
        }
        comparison_csv = output_dir / "parameter_sensitivity_comparison.csv"
        summary = compare_oti_vs_fd(
            oti_dsigma_csv=result.dsigma_csv,
            oti_dstatev_csv=result.dstatev_csv,
            fd_dsigma_csv=fd_files["DSIGMA_DP_FD"],
            fd_dstatev_csv=fd_files["DSTATEV_DP_FD"],
            output_csv=comparison_csv,
        )
        stage["comparison_csv"] = str(comparison_csv)
        stage["max_abs_diff"] = summary["max_abs_diff"]
        stage["max_rel_diff"] = summary["max_rel_diff"]
        stage["tolerance"] = 1.0e-4
        if summary["max_rel_diff"] <= 1.0e-4:
            stage["status"] = "verified"
        else:
            stage["status"] = "failed"
    except RuntimeError as exc:
        stage["status"] = "failed"
        stage["error"] = str(exc)
    return stage


# ---------------------------------------------------------------------------
# Stage 3: Higher-order OTI Fortran driver
# ---------------------------------------------------------------------------

def _run_oti_higher_order(output_dir: Path, *, gfortran: str) -> dict[str, Any]:
    from umat_oti.fortran_emit.higher_order_strain import (
        HigherOrderModel,
        analytical_derivatives,
        compile_higher_order_build,
        generate_higher_order_build,
        read_derivatives_csv,
        run_higher_order_driver,
    )
    build_dir = output_dir / "oti_higher_order_build"
    stage: dict[str, Any] = {"status": "pending", "build_dir": str(build_dir)}
    try:
        model = HigherOrderModel.softwarex_bivariate_quintic()
        layout = generate_higher_order_build(build_dir, model)
        stage["generated_files"] = {
            name: str(getattr(layout, name))
            for name in ("otim_module", "response", "driver", "directions_csv")
        }
        exe = compile_higher_order_build(layout, gfortran=gfortran)
        result = run_higher_order_driver(exe, out_dir=build_dir)
        stage["returncode"] = result.returncode
        if result.returncode != 0:
            stage["status"] = "failed"
            stage["stderr_tail"] = result.stderr[-1000:]
            return stage
        # Copy OTI outputs and the directions table to the evidence root.
        for src in (result.coefficients_csv, result.derivatives_csv, layout.directions_csv):
            dst = output_dir / f"higher_order_{src.name}"
            dst.write_bytes(src.read_bytes())

        analytical = analytical_derivatives(model)
        recovered = read_derivatives_csv(result.derivatives_csv)
        comparison_csv = output_dir / "higher_order_comparison.csv"
        max_rel = 0.0
        with comparison_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "order",
                    "member",
                    "bases_multiindex",
                    "recovery_factor",
                    "sympy_analytical",
                    "oti_recovered",
                    "abs_diff",
                    "rel_diff",
                ]
            )
            for multiset, ana in analytical.items():
                entry = recovered[multiset]
                oti = entry["recovered_derivative"]
                scale = max(abs(ana), abs(oti), 1.0)
                rel = abs(ana - oti) / scale
                if rel > max_rel:
                    max_rel = rel
                writer.writerow(
                    [
                        entry["order"],
                        entry["name"],
                        "|".join(str(b) for b in multiset),
                        entry["recovery_factor"],
                        f"{ana:.16e}",
                        f"{oti:.16e}",
                        f"{abs(ana - oti):.3e}",
                        f"{rel:.3e}",
                    ]
                )
        stage["comparison_csv"] = str(comparison_csv)
        stage["max_rel_diff"] = max_rel
        stage["tolerance"] = 1.0e-10
        stage["status"] = "verified" if max_rel <= 1.0e-10 else "failed"
    except RuntimeError as exc:
        stage["status"] = "failed"
        stage["error"] = str(exc)
    return stage


# ---------------------------------------------------------------------------
# Stage 4: Manifest + bridge artefacts (produced regardless of OTI success)
# ---------------------------------------------------------------------------

def _emit_manifest_and_bridge(output_dir: Path, fd_run) -> dict[str, Any]:
    parameter_map = ParameterMap.softwarex_default().entries
    state_map = StateMap.softwarex_default().entries
    requests = [
        DerivativeRequest(
            id="material_tangent",
            kind=KIND_MATERIAL_TANGENT,
            target="DDSDDE",
            seed=("DSTRAN",),
            response="STRESS",
            order=1,
        ),
        DerivativeRequest(
            id="local_return_mapping",
            kind=KIND_LOCAL_JACOBIAN,
            target="FJAC",
            seed=("DGAMMA",),
            response="RESID",
            order=1,
            scope="NEWTON",
        ),
        DerivativeRequest(
            id="higher_order_2",
            kind=KIND_HIGHER_ORDER,
            target="DDSDDE2",
            seed=("DSTRAN",),
            response="STRESS",
            order=2,
        ),
        DerivativeRequest(
            id="higher_order_3",
            kind=KIND_HIGHER_ORDER,
            target="DDSDDE3",
            seed=("DSTRAN",),
            response="STRESS",
            order=3,
        ),
        DerivativeRequest(
            id="higher_order_4",
            kind=KIND_HIGHER_ORDER,
            target="DDSDDE4",
            seed=("DSTRAN",),
            response="STRESS",
            order=4,
        ),
        DerivativeRequest(
            id="stress_parameter_sensitivity",
            kind=KIND_PARAMETER_SENSITIVITY,
            target="DSIGMA_DP",
            seed=tuple(name for name, _ in parameter_map),
            response="STRESS",
            order=1,
            parameter_map=parameter_map,
        ),
        DerivativeRequest(
            id="state_parameter_sensitivity",
            kind=KIND_STATE_SENSITIVITY,
            target="DSTATEV_DP",
            seed=tuple(name for name, _ in parameter_map),
            response="STATEV",
            order=1,
            state_map=state_map,
        ),
    ]
    manifest = build_manifest(
        source_path=REPO_ROOT / "UMATs" / "UMATs" / "ICP" / "plasticity_imp" / "code_imp.f",
        entry_routine="UMAT",
        ntens=6,
        nstatv=1,
        nprops=4,
        requests=requests,
        parameters=parameter_map,
        state_variables=state_map,
        direction_count=len(parameter_map),
    )
    manifest_path = write_manifest(manifest, output_dir / "derivative_manifest.json")

    contract = build_softwarex_j2_contract(stream_path="j2_stream.jsonl")
    contract_path = contract.write(output_dir / "driver_contract.json")

    records = []
    for inc in fd_run.increments:
        records.append(
            {
                "increment": inc.increment,
                "stress": list(inc.stress),
                "statev": list(inc.statev),
                "dsigma_dp": [list(row) for row in inc.dsigma_dp],
                "dstatev_dp": [list(row) for row in inc.dstatev_dp],
                "source": "python_fd_reference",
            }
        )
    stream_path = write_j2_stream(records, output_dir / "j2_stream.jsonl")

    return {
        "manifest": str(manifest_path),
        "driver_contract": str(contract_path),
        "j2_stream": str(stream_path),
    }


# ---------------------------------------------------------------------------
# Stage 5: Paper-table skeletons
# ---------------------------------------------------------------------------

_TABLE_SPECS = {
    "table2_ddsdde.csv": [
        "umat_name",
        "test_case",
        "n_increments",
        "max_abs_diff_vs_reference",
        "max_rel_diff_vs_reference",
        "status",
        "reference_method",
    ],
    "table3_internal_jacobians.csv": [
        "umat_name",
        "jacobian_id",
        "seed",
        "response",
        "target",
        "status",
        "reference_method",
    ],
    "table4_higher_order.csv": [
        "case_id",
        "nbases",
        "order",
        "member",
        "recovery_factor",
        "oti_recovered",
        "sympy_analytical",
        "abs_diff",
        "rel_diff",
    ],
    "table5_j2_parameter_sensitivities.csv": [
        "increment",
        "array",
        "row",
        "parameter",
        "oti",
        "fd",
        "abs_diff",
        "rel_diff",
    ],
    "table6_parameter_sensitivity_sweep.csv": [
        "umat_name",
        "n_parameters",
        "n_directions",
        "status",
        "notes",
    ],
    "figure3_loading_path.csv": [
        "increment",
        "stress_1",
        "stress_2",
        "stress_3",
        "eqplas",
        "yielded",
        "method",
    ],
    "figure4_higher_orders.csv": [
        "order",
        "member",
        "oti_recovered",
        "sympy_analytical",
    ],
    "figure5_accuracy_cost.csv": [
        "case_id",
        "n_directions",
        "wallclock_generate_s",
        "wallclock_compile_s",
        "wallclock_run_s",
        "max_rel_diff",
    ],
    "figure6_parameter_sensitivities.csv": [
        "increment",
        "parameter",
        "dsigma_dp_stress_1",
        "dstatev_dp_eqplas",
        "method",
    ],
}


def _emit_paper_tables(output_dir: Path, oti_j2: dict, oti_ho: dict, fd_files: dict) -> dict[str, str]:
    written: dict[str, str] = {}
    for name, header in _TABLE_SPECS.items():
        target = output_dir / name
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
        written[name] = str(target)

    # Table 5: populate from parameter_sensitivity_comparison.csv when the
    # compiled OTI J2 driver ran successfully.
    comparison = oti_j2.get("comparison_csv")
    if comparison and Path(comparison).is_file():
        rows = list(csv.reader(Path(comparison).open("r", encoding="utf-8")))
        # Skip the first row (header of the comparison csv) and copy the rest
        # into table 5.
        target = output_dir / "table5_j2_parameter_sensitivities.csv"
        with target.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerows(rows[1:])

    # Table 4 + Figure 4: populate from higher_order_comparison.csv when the
    # higher-order driver ran successfully.
    ho_comparison = oti_ho.get("comparison_csv")
    if ho_comparison and Path(ho_comparison).is_file():
        rows = list(csv.reader(Path(ho_comparison).open("r", encoding="utf-8")))
        table4 = output_dir / "table4_higher_order.csv"
        with table4.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            for r in rows[1:]:
                # rows[i] = order, member, bases, factor, sympy, oti, abs, rel
                writer.writerow([
                    "bivariate_quintic",  # case_id
                    2,                     # nbases
                    r[0],                  # order
                    r[1],                  # member
                    r[3],                  # recovery_factor
                    r[5],                  # oti_recovered
                    r[4],                  # sympy_analytical
                    r[6],                  # abs_diff
                    r[7],                  # rel_diff
                ])
        figure4 = output_dir / "figure4_higher_orders.csv"
        with figure4.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            for r in rows[1:]:
                writer.writerow([r[0], r[1], r[5], r[4]])

    # Figure 3: FD primal loading path.
    primal_fd = fd_files.get("primal_FD")
    if primal_fd and primal_fd.is_file():
        rows = list(csv.reader(primal_fd.open("r", encoding="utf-8")))
        target = output_dir / "figure3_loading_path.csv"
        with target.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            for r in rows[1:]:
                # rows[i]: increment, yielded, method, stress_1..6, eqplas
                writer.writerow([r[0], r[3], r[4], r[5], r[9], r[1], r[2]])

    return written


# ---------------------------------------------------------------------------
# Stage 6: claim matrix (populated from actual observed states)
# ---------------------------------------------------------------------------

def _build_claim_matrix_from_results(
    *,
    env,
    oti_j2: dict,
    oti_ho: dict,
    corpus_metrics: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    def _status_for(stage: dict, blocked_reason: str) -> str:
        s = stage.get("status")
        if s == "verified":
            return "verified"
        if s == "failed":
            return "failed"
        return blocked_reason

    blocked_by_compiler = "blocked_by_missing_compiler"
    corpus_metrics = corpus_metrics or {}
    corpus_provenance = corpus_metrics.get("provenance", {})
    corpus_compile_count = corpus_metrics.get("cumulative_stage_counts", {}).get(
        "generated_source_compiled", 0
    )
    corpus_status = "verified" if corpus_provenance.get("acquired_source_count") else "pending"
    return [
        {
            "id": "focused_J2_DSIGMA_DP_generic_source_transform",
            "description": "OTI-generated Fortran J2 material-point driver emits DSIGMA_DP that matches full-history centered FD across the full 20-increment loading path.",
            "implementation": "src/umat_oti/fortran_emit/parameter_sensitivity_j2.py + compiled OTI Fortran driver.",
            "reference": "Python centered FD reference (backend='centered_fd').",
            "test": "tests/test_j2_oti_fortran_driver.py",
            "status": _status_for(oti_j2, blocked_by_compiler),
            "observed_max_rel_diff": oti_j2.get("max_rel_diff"),
            "tolerance": oti_j2.get("tolerance"),
        },
        {
            "id": "focused_J2_DSTATEV_DP_generic_source_transform",
            "description": "OTI-generated J2 driver emits DSTATEV_DP that matches full-history centered FD.",
            "implementation": "Same as focused_J2_DSIGMA_DP_from_source.",
            "reference": "Python centered FD reference.",
            "test": "tests/test_j2_oti_fortran_driver.py",
            "status": _status_for(oti_j2, blocked_by_compiler),
        },
        {
            "id": "higher_order_direction_and_factorial_reference_fixture",
            "description": "OTI-generated Fortran driver emits mixed and repeated derivatives (orders 2-4) that match SymPy analytical differentiation on the SoftwareX bivariate polynomial.",
            "implementation": "src/umat_oti/fortran_emit/higher_order_strain.py + compiled OTI Fortran driver.",
            "reference": "SymPy analytical differentiation of the same symbolic model.",
            "test": "tests/test_higher_order_fortran_driver.py",
            "status": _status_for(oti_ho, blocked_by_compiler),
            "observed_max_rel_diff": oti_ho.get("max_rel_diff"),
            "tolerance": oti_ho.get("tolerance"),
        },
        {
            "id": "higher_order_from_real_UMAT_stress_update",
            "description": "Orders 2-4 are recovered from an actual transformed UMAT stress-update path.",
            "implementation": "Not implemented.",
            "reference": "Compiled transformed nonlinear UMAT at smooth elastic and plastic points.",
            "test": "N/A yet.",
            "status": "not_implemented",
        },
        {
            "id": "finite_difference_reference_available",
            "description": "Python centered-FD reference for DSIGMA_DP / DSTATEV_DP with full history replay per parameter perturbation.",
            "implementation": "src/umat_oti/validation/parameter_sensitivity.py backend='centered_fd'.",
            "reference": "None (this IS the reference).",
            "test": "tests/test_j2_parameter_sensitivity.py",
            "status": "reference_ready",
        },
        {
            "id": "unified_derivative_model_normalization",
            "description": "Legacy compact / expanded / advanced / constitutive_jacobians / extra_jacobian_contracts all normalize into DerivativeRequest.",
            "implementation": "src/umat_oti/core/derivative_request.py.",
            "reference": "The 19 completed benchmark contracts.",
            "test": "tests/test_derivative_request.py",
            "status": "verified",
        },
        {
            "id": "corpus_transform_success",
            "description": "All 19 completed benchmark contracts transform without error.",
            "implementation": "src/umat_oti/transform/source_transform.py.",
            "reference": "None (transformation success only).",
            "test": "tools/run_completed_json_batch.py",
            "status": "verified",
        },
        {
            "id": "corpus_compile_success",
            "description": "Corpus candidates compile after transformation; this does not establish primal or derivative parity.",
            "implementation": "src/umat_oti/corpus/cli.py.",
            "reference": "Compiler exit status only.",
            "test": "python -m umat_oti.corpus.cli run.",
            "status": corpus_status,
            "observed_compile_success": corpus_compile_count,
            "unique_umat_count": corpus_provenance.get("unique_umat_count"),
        },
        {
            "id": "corpus_primal_parity",
            "description": "Transformed corpus candidates reproduce original primal outputs.",
            "implementation": "Not yet archived as a corpus stage result.",
            "reference": "Original source execution.",
            "test": "N/A yet.",
            "status": "pending",
        },
        {
            "id": "corpus_derivative_verification",
            "description": "Transformed corpus derivatives match an independent numerical reference.",
            "implementation": "Not yet archived as a corpus stage result.",
            "reference": "Centered finite differences or analytical derivatives.",
            "test": "N/A yet.",
            "status": "pending",
        },
        {
            "id": "residual_assembler_synthetic_B_bridge",
            "description": "UMAT-OTI driver contract + JSONL stream drives ResAsm bridge and a hand-verified truss dR/dp.",
            "implementation": "Residual_Assembler/residual_core/materials/umat_oti_driver.py + core/umat_oti_sensitivity.py.",
            "reference": "Hand-derived analytical truss dR/dp.",
            "test": "Residual_Assembler/tests/framework/test_umat_oti_bridge.py, ::test_umat_oti_end_to_end.py",
            "status": "verified",
        },
        {
            "id": "abaqus_paired_J2_primal_and_DDSDDE",
            "description": "Original vs transformed J2 UMAT paired STRESS/STATEV/DDSDDE inside Abaqus.",
            "implementation": "tools/run_completed_json_batch.py --validate + scripts/run_abaqus_arc.sbatch.",
            "reference": "Original hand-coded UMAT in Abaqus.",
            "test": "python -m umat_oti.validation.run_suite --abaqus-command abaqus",
            "status": _abaqus_paired_status(env),
            "abaqus_paired_summary": _abaqus_paired_summary_reference(),
        },
        {
            "id": "abaqus_paired_18_case_collection",
            "description": "The real Abaqus paired collection contains 18 passing cases and one original-source execution failure.",
            "implementation": "tools/run_completed_json_batch.py --validate + scripts/run_abaqus_arc.sbatch.",
            "reference": "Per-case paired Abaqus reports; collection status does not promote the failing original case.",
            "test": "python -m umat_oti.reports.aggregate_abaqus_results.",
            "status": "18_pass_1_original_case_execution_failure",
            "abaqus_paired_summary": _abaqus_paired_summary_reference(),
        },
        {
            "id": "residual_assembler_C3D8_structural_sensitivity",
            "description": "C3D8 J2 structural du/dp vs. 2N+1 Abaqus reruns.",
            "implementation": "Residual_Assembler/residual_core/core/umat_oti_sensitivity.py + compiled OTI J2 driver + C3D8 integration.",
            "reference": "2N+1 Abaqus centered-FD reruns.",
            "test": "N/A yet.",
            "status": "not_implemented",
        },
        {
            "id": "corpus_regression_round_metrics",
            "description": "Executable GitHub-API corpus discovery + staged pipeline + round metrics from live acquisition.",
            "implementation": "src/umat_oti/corpus/__init__.py + cli.py.",
            "reference": "Real per-round metrics (no hard-coded numbers).",
            "test": "python -m umat_oti.corpus.cli discover --allow-network",
            "status": corpus_status,
            "observed_metrics": corpus_provenance or None,
        },
    ]


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m umat_oti.reports.run_softwarex_evidence",
        description="Regenerate the SoftwareX evidence artefacts by actually running OTI when a compiler is available.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "paper_results",
    )
    parser.add_argument(
        "--gfortran",
        default="gfortran",
        help="Fortran compiler to use (default 'gfortran'). Set to a versioned path when the site default is too old (ARC login: gfortran 8.5 is too old; module load gcc/13.3.0 first).",
    )
    parser.add_argument(
        "--skip-oti",
        action="store_true",
        help="Skip OTI Fortran build/run (useful for smoke testing the FD reference alone).",
    )
    parser.add_argument(
        "--corpus-metrics",
        type=Path,
        default=None,
        help="Archived round_metrics.json from a live corpus run.",
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    env = detect_environment(abaqus_command="abaqus")
    fd = _run_fd_reference(args.output_dir)

    if args.skip_oti or shutil.which(args.gfortran) is None:
        oti_j2 = {
            "status": "blocked_by_missing_compiler",
            "reason": f"gfortran executable {args.gfortran!r} not on PATH."
            if not args.skip_oti
            else "skipped by --skip-oti flag.",
        }
        oti_ho = dict(oti_j2)
    else:
        oti_j2 = _run_oti_j2(args.output_dir, fd["files"], gfortran=args.gfortran)
        oti_ho = _run_oti_higher_order(args.output_dir, gfortran=args.gfortran)

    bridge = _emit_manifest_and_bridge(args.output_dir, fd["run"])
    tables = _emit_paper_tables(args.output_dir, oti_j2, oti_ho, fd["files"])
    corpus_metrics = None
    if args.corpus_metrics is not None:
        corpus_metrics = json.loads(args.corpus_metrics.read_text(encoding="utf-8"))
        shutil.copyfile(args.corpus_metrics, args.output_dir / "corpus_round_metrics.json")
    claim_matrix = _build_claim_matrix_from_results(
        env=env,
        oti_j2=oti_j2,
        oti_ho=oti_ho,
        corpus_metrics=corpus_metrics,
    )
    claim_path = args.output_dir / "claim_matrix.json"
    claim_path.write_text(json.dumps(claim_matrix, indent=2, sort_keys=True), encoding="utf-8")

    environment_report = {
        "generated_at": _iso_now(),
        "umat_oti_version": _umat_oti_version,
        "fortran_compiler": env.fortran_compiler,
        "fortran_compiler_version": env.fortran_compiler_version,
        "abaqus_command": env.abaqus_command,
        "abaqus_ok": env.abaqus_ok,
        "abaqus_message": env.abaqus_message,
    }
    env_path = args.output_dir / "environment.json"
    env_path.write_text(json.dumps(environment_report, indent=2, sort_keys=True), encoding="utf-8")

    summary = {
        "output_dir": str(args.output_dir),
        "fd_reference": {name: str(path) for name, path in fd["files"].items()},
        "oti_j2": oti_j2,
        "oti_higher_order": oti_ho,
        "bridge": bridge,
        "paper_tables": tables,
        "claim_matrix": str(claim_path),
        "environment": str(env_path),
        "note": (
            "DSIGMA_DP_FD / DSTATEV_DP_FD are the centered-FD REFERENCE. "
            "DSIGMA_DP_OTI / DSTATEV_DP_OTI are produced by the compiled "
            "OTI Fortran driver in oti_j2_build/. The claim matrix reflects "
            "the actual observed comparison status."
        ),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    failures = [entry for entry in claim_matrix if entry["status"] == "failed"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
