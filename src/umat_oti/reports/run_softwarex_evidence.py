"""Regenerate the SoftwareX evidence artefacts from a clean input state.

This single command produces the reproducible paper-evidence directory
described in the SoftwareX task (§9):

* ``primal_stress_state.csv``   — history-consistent STRESS and STATEV per
  increment for the focused J2 case.
* ``DSIGMA_DP.csv``             — stress sensitivities per parameter.
* ``DSTATEV_DP.csv``            — state-variable sensitivities per parameter.
* ``sensitivity_summary.json``  — the machine-readable run summary.
* ``derivative_manifest.json``  — the schema-versioned manifest emitted by
  ``umat_oti.reports.manifest``.
* ``driver_contract.json``      — the shared UMAT-OTI/Residual-Assembler
  material-driver contract.
* ``j2_stream.jsonl``           — the increment stream consumed by the
  Residual Assembler bridge.
* ``claim_matrix.json``         — the machine-readable claim-to-test matrix
  (see :func:`build_claim_matrix`).
* ``environment.json``          — the environment-detection report from
  :mod:`umat_oti.validation.run_suite`.

Nothing is hand-typed: every value is computed from the reference J2 model
and the current source files.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from umat_oti import __version__ as _umat_oti_version
from umat_oti.core.derivative_request import (
    DerivativeRequest,
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


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_claim_matrix() -> list[dict[str, Any]]:
    """Machine-readable claim-to-test map used by the SoftwareX paper.

    Every entry carries five fields so nothing is fabricated:

    * ``implementation``  — the actual code path that produces the result.
    * ``reference``       — the independent reference used to verify it.
    * ``status``          — one of ``verified``, ``reference_ready``,
                            ``pending_oti_verification``, ``pending``,
                            ``blocked_by_missing_abaqus``,
                            ``blocked_by_missing_otilib``,
                            ``blocked_by_missing_compiler``.
    * ``test``            — the pytest node id or CLI command that exercises it.
    * ``description``     — one-line human-readable summary.

    A claim can only become ``verified`` when the ``implementation`` produced
    a real result AND that result agrees with an independent ``reference``.
    A finite-difference reference on its own is ``reference_ready``, never
    ``verified``.
    """
    return [
        {
            "id": "material_tangent_DDSDDE_generated_from_source",
            "description": "DDSDDE is emitted by the source transformer via OTI GETIM extraction on all 19 benchmark UMATs.",
            "implementation": "src/umat_oti/transform/source_transform.py + oti/module_generator.py",
            "reference": "None (transformation success only; numerical parity requires Abaqus).",
            "test": "tools/run_completed_json_batch.py (transform + write generated .f90/.f); primal parity blocked without Abaqus.",
            "status": "pending_oti_verification",
        },
        {
            "id": "material_tangent_python_reference_consistent_tangent",
            "description": "The Python J2 reference reproduces the closed-form Simo-Hughes consistent tangent at zero plastic strain (elastic) and matches its own centered-FD baseline on the plastic branch.",
            "implementation": "src/umat_oti/validation/j2_reference.py (Python reference).",
            "reference": "Analytical closed-form + centered FD of the same reference.",
            "test": "tests/test_j2_parameter_sensitivity.py::test_consistent_tangent_reduces_to_elastic_stiffness_at_zero_plastic_strain, ::test_consistent_tangent_matches_finite_difference_on_plastic_branch",
            "status": "verified",
            "notes": "This proves the Python reference is self-consistent; it does NOT prove the source transformer emits a correct tangent.",
        },
        {
            "id": "focused_J2_DSIGMA_DP_from_source",
            "description": "OTI-generated Fortran J2 material-point driver emits DSIGMA_DP that matches full-history centered FD.",
            "implementation": "src/umat_oti/fortran_emit/parameter_sensitivity_j2.py (compiled J2 OTI driver).",
            "reference": "Python centered FD (src/umat_oti/validation/parameter_sensitivity.py backend='centered_fd').",
            "test": "tests/test_j2_oti_fortran_driver.py (requires gfortran on PATH).",
            "status": "pending_oti_verification",
        },
        {
            "id": "focused_J2_DSTATEV_DP_from_source",
            "description": "OTI-generated Fortran J2 material-point driver emits DSTATEV_DP that matches full-history centered FD.",
            "implementation": "src/umat_oti/fortran_emit/parameter_sensitivity_j2.py (compiled J2 OTI driver).",
            "reference": "Python centered FD.",
            "test": "tests/test_j2_oti_fortran_driver.py (requires gfortran).",
            "status": "pending_oti_verification",
        },
        {
            "id": "finite_difference_reference_available",
            "description": "Python centered-FD reference for DSIGMA_DP / DSTATEV_DP replays the full loading history for every ± perturbation.",
            "implementation": "src/umat_oti/validation/parameter_sensitivity.py backend='centered_fd'.",
            "reference": "Not applicable (this IS the reference).",
            "test": "tests/test_j2_parameter_sensitivity.py",
            "status": "reference_ready",
            "notes": "Reference values only; these do not implement DSIGMA_DP as an OTI product.",
        },
        {
            "id": "unified_derivative_model_normalization",
            "description": "Every legacy contract shape normalizes into one canonical DerivativeRequest model.",
            "implementation": "src/umat_oti/core/derivative_request.py.",
            "reference": "The 19 completed benchmark contracts + hand-crafted unified example.",
            "test": "tests/test_derivative_request.py",
            "status": "verified",
        },
        {
            "id": "benchmark_batch_transformation_success",
            "description": "All 19 completed benchmark contracts transform without error.",
            "implementation": "src/umat_oti/transform/source_transform.py.",
            "reference": "None (transformation success only).",
            "test": "tools/run_completed_json_batch.py",
            "status": "verified",
            "notes": "Numerical STRESS/STATEV/DDSDDE parity vs. the original UMAT requires Abaqus.",
        },
        {
            "id": "derivative_manifest_schema",
            "description": "Schema-versioned manifest records source hash, PROPS/STATEV maps, direction convention, recovery factors.",
            "implementation": "src/umat_oti/reports/manifest.py.",
            "reference": "None (schema only).",
            "test": "tests/test_manifest_contract_corpus.py::test_manifest_records_all_required_fields",
            "status": "verified",
        },
        {
            "id": "abaqus_validator_honest_env_detection",
            "description": "The unified Abaqus validator never reports a passed run when Abaqus is missing.",
            "implementation": "src/umat_oti/validation/run_suite.py.",
            "reference": "N/A (behaviour claim).",
            "test": "tests/test_run_suite.py::test_run_suite_marks_abaqus_blocked_when_command_missing",
            "status": "verified",
        },
        {
            "id": "corpus_license_dedup_and_offline_safety",
            "description": "Corpus tool classifies SPDX licenses, deduplicates by normalized hash, refuses implicit network.",
            "implementation": "src/umat_oti/corpus/__init__.py.",
            "reference": "N/A (behaviour claim).",
            "test": "tests/test_manifest_contract_corpus.py::test_classify_license, ::test_deduplicate_removes_hash_dupes_preserving_order, ::test_discover_via_github_api_refuses_implicit_network",
            "status": "verified",
        },
        {
            "id": "residual_assembler_driver_contract_and_dRdp_assembly",
            "description": "UMAT-OTI driver contract and JSONL stream load into the Residual Assembler bridge and drive a hand-verified dR/dp assembly on a 1D truss.",
            "implementation": "Residual_Assembler/residual_core/materials/umat_oti_driver.py + core/umat_oti_sensitivity.py.",
            "reference": "Hand-derived analytical truss dR/dp.",
            "test": "Residual_Assembler/tests/framework/test_umat_oti_bridge.py, ::test_umat_oti_end_to_end.py",
            "status": "verified",
            "notes": "The bridge is verified for serialization + assembly logic. A full C3D8 J2 sensitivity vs. 2N+1 Abaqus reruns remains blocked without Abaqus.",
        },
        {
            "id": "higher_order_DDSDDE2_DDSDDE3_DDSDDE4_from_source",
            "description": "Compiled OTI Fortran drivers emit DDSDDE2/3/4 for uniaxial-tension DSTRAN seeding, verified against SymPy derivatives.",
            "implementation": "src/umat_oti/fortran_emit/higher_order_strain.py.",
            "reference": "SymPy analytical derivatives of the same reference model.",
            "test": "tests/test_higher_order_fortran_driver.py (requires gfortran).",
            "status": "pending_oti_verification",
        },
        {
            "id": "abaqus_paired_stress_state_ddsdde_j2",
            "description": "Original vs transformed J2 UMAT paired STRESS/STATEV/DDSDDE comparison inside Abaqus.",
            "implementation": "tools/run_completed_json_batch.py --validate + scripts/run_abaqus_arc.sbatch.",
            "reference": "The original hand-coded UMAT run in Abaqus.",
            "test": "python -m umat_oti.validation.run_suite --abaqus-command abaqus",
            "status": "blocked_by_missing_abaqus",
        },
        {
            "id": "residual_assembler_c3d8_j2_structural_sensitivity",
            "description": "Structural du/dp for a small C3D8 J2 model vs. 2N+1 Abaqus reruns (E, nu, SIGY0, H).",
            "implementation": "Residual_Assembler/residual_core/core/umat_oti_sensitivity.py + compiled OTI J2 driver + C3D8 integration path.",
            "reference": "2N+1 Abaqus centered-FD reruns.",
            "test": "N/A yet (Abaqus required).",
            "status": "blocked_by_missing_abaqus",
        },
        {
            "id": "corpus_regression_round_metrics",
            "description": "Executable web-corpus discovery + staged pipeline + round metrics from live GitHub API.",
            "implementation": "src/umat_oti/corpus/__init__.py + cli.py.",
            "reference": "Real per-round metrics (no hard-coded numbers).",
            "test": "python -m umat_oti.corpus.cli discover --allow-network (needs internet + optional token).",
            "status": "pending",
            "notes": "Discovery, snapshot, dedup, and metrics implemented; live end-to-end run needs outbound network and a token, which are not guaranteed on ARC login nodes.",
        },
    ]


def _run_focused_j2(output_dir: Path) -> dict[str, Any]:
    params = J2Parameters()
    path = build_softwarex_j2_path()
    run = compute_j2_parameter_sensitivities(
        params=params,
        path=path,
        fd_step_relative=1.0e-6,
    )
    csv_files = export_sensitivity_csv(run, output_dir)
    return {"run": run, "csv_files": csv_files}


def _emit_manifest(output_dir: Path, run) -> Path:
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
            id="stress_parameter_sensitivity",
            kind=KIND_PARAMETER_SENSITIVITY,
            target="DSIGMA_DP",
            seed=tuple(name for name, _ in ParameterMap.softwarex_default().entries),
            response="STRESS",
            order=1,
            parameter_map=ParameterMap.softwarex_default().entries,
        ),
        DerivativeRequest(
            id="state_parameter_sensitivity",
            kind=KIND_STATE_SENSITIVITY,
            target="DSTATEV_DP",
            seed=tuple(name for name, _ in ParameterMap.softwarex_default().entries),
            response="STATEV",
            order=1,
            state_map=StateMap.softwarex_default().entries,
        ),
    ]
    manifest = build_manifest(
        source_path=REPO_ROOT / "UMATs" / "elastic_minimal.for",
        entry_routine="UMAT",
        ntens=6,
        nstatv=1,
        nprops=4,
        requests=requests,
        parameters=ParameterMap.softwarex_default().entries,
        state_variables=StateMap.softwarex_default().entries,
        direction_count=len(ParameterMap.softwarex_default().entries),
    )
    return write_manifest(manifest, output_dir / "derivative_manifest.json")


def _emit_bridge(output_dir: Path, run) -> tuple[Path, Path]:
    contract = build_softwarex_j2_contract(stream_path="j2_stream.jsonl")
    records = []
    for inc in run.increments:
        records.append(
            {
                "increment": inc.increment,
                "stress": list(inc.stress),
                "statev": list(inc.statev),
                "dsigma_dp": [list(row) for row in inc.dsigma_dp],
                "dstatev_dp": [list(row) for row in inc.dstatev_dp],
            }
        )
    stream_path = write_j2_stream(records, output_dir / "j2_stream.jsonl")
    contract_path = contract.write(output_dir / "driver_contract.json")
    return contract_path, stream_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m umat_oti.reports.run_softwarex_evidence",
        description="Regenerate the SoftwareX paper-evidence artefacts from source.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "paper_results",
        help="Directory to write the evidence artefacts to (default: paper_results/).",
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    j2 = _run_focused_j2(args.output_dir)
    manifest_path = _emit_manifest(args.output_dir, j2["run"])
    contract_path, stream_path = _emit_bridge(args.output_dir, j2["run"])
    claim_matrix = build_claim_matrix()
    (args.output_dir / "claim_matrix.json").write_text(
        json.dumps(claim_matrix, indent=2, sort_keys=True), encoding="utf-8"
    )
    env = detect_environment(abaqus_command="abaqus")
    (args.output_dir / "environment.json").write_text(
        json.dumps(
            {
                "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                "umat_oti_version": _umat_oti_version,
                "fortran_compiler": env.fortran_compiler,
                "fortran_compiler_version": env.fortran_compiler_version,
                "abaqus_command": env.abaqus_command,
                "abaqus_ok": env.abaqus_ok,
                "abaqus_message": env.abaqus_message,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    summary = {
        "output_dir": str(args.output_dir),
        "artefacts": {name: str(path) for name, path in j2["csv_files"].items()}
        | {
            "derivative_manifest.json": str(manifest_path),
            "driver_contract.json": str(contract_path),
            "j2_stream.jsonl": str(stream_path),
            "claim_matrix.json": str(args.output_dir / "claim_matrix.json"),
            "environment.json": str(args.output_dir / "environment.json"),
        },
        "note": (
            "The DSIGMA_DP_FD / DSTATEV_DP_FD files are the CENTERED-FINITE-"
            "DIFFERENCE REFERENCE, not OTI-generated results. Unsuffixed "
            "paper-facing DSIGMA_DP / DSTATEV_DP files are produced only "
            "after an OTI Fortran run exists and agrees with this reference "
            "(see umat_oti.fortran_emit.parameter_sensitivity_j2)."
        ),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
