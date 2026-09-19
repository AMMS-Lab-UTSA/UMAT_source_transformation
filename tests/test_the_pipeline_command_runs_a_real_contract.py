"""``umat-oti-pipeline`` runs a shipped contract from transformation to verification.

The other pipeline tests list the stages, reject bad arguments and stop at
acquisition. This one runs the command's own entry point,
:func:`umat_oti.pipeline.cli.main`, on ``examples/code_imp_actual_higher_order.json``
with ``--compile``: the source is transformed, the generated Fortran is
compiled, the transformed UMAT is executed along the contract's material-point
history, its stress is compared with the original's, and the derivatives are
checked against finite differences. Everything it claims is read back from
``run_manifest.json``.

The three stages that are registered but not yet implemented report
``unsupported``, so a full run exits with 1 -- the documented behaviour
(docs/CLI_GUIDE.md). That, and only that, is what the problem list may hold.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from umat_oti.pipeline.cli import EXIT_PROBLEM, main

pytestmark = [
    pytest.mark.fortran,
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("gfortran") is None,
                       reason="gfortran is not on PATH; --compile builds the generated Fortran"),
]

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "examples" / "code_imp_actual_higher_order.json"

EXECUTED = (
    "source_acquisition", "source_inventory", "license_classification",
    "entry_routine_detection", "dependency_closure", "contract_inference",
    "derivative_request_normalization", "source_transformation",
    "oti_support_generation", "compilation", "material_point_execution",
    "primal_parity", "derivative_verification",
)
NOT_YET_IMPLEMENTED = ("abaqus_validation", "evidence_generation", "distributable_package")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_compiled_run_of_a_shipped_contract_is_recorded_stage_by_stage(tmp_path, capsys):
    work = tmp_path / "run"
    code = main(["--config", str(CONTRACT), "--work-dir", str(work), "--compile", "--json"])
    printed = json.loads(capsys.readouterr().out)

    manifest = json.loads((work / "run_manifest.json").read_text(encoding="utf-8"))
    stages = manifest["stages"]
    assert printed == manifest["summary"]

    # Every implemented stage ran and succeeded; the only problems are the
    # stages that are not implemented yet, and that is why the exit code is 1.
    assert {name: stages[name]["status"] for name in EXECUTED} == \
        {name: "succeeded" for name in EXECUTED}
    assert sorted(p["stage"] for p in manifest["summary"]["problems"]) == \
        sorted(NOT_YET_IMPLEMENTED)
    assert all(p["status"] == "unsupported" for p in manifest["summary"]["problems"])
    assert code == EXIT_PROBLEM
    assert manifest["summary"]["status_counts"] == {
        "succeeded": len(EXECUTED), "unsupported": len(NOT_YET_IMPLEMENTED)}

    # Every artifact the manifest records exists, with the recorded hash.
    recorded = [artifact for record in stages.values() for artifact in record["artifacts"]]
    assert recorded
    for artifact in recorded:
        path = work / artifact["path"]
        assert path.is_file(), artifact["path"]
        assert _sha256(path) == artifact["sha256"], artifact["path"]

    # Transformation wrote the transformed source; compilation built objects
    # for every unit in the compile order, the transformed UMAT among them.
    roles = {a["role"] for a in stages["source_transformation"]["artifacts"]}
    assert {"transformed_source", "manifest"} <= roles
    compilation = stages["compilation"]
    assert compilation["input_digest"]["resolved_inputs"]["compile_requested"] is True
    objects = [Path(a["path"]).name for a in compilation["artifacts"]]
    assert "transformed_umat.o" in objects
    assert compilation["outputs"]["object_count"] == len(objects) == \
        len(stages["oti_support_generation"]["outputs"]["compile_order"])

    # The transformed UMAT was executed along the contract's own history.
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    execution = stages["material_point_execution"]["outputs"]
    assert execution["increments"] == contract["validation"]["increments"]
    assert execution["oti_value_count"] > 0
    assert [b["increment"] for b in execution["branch_history"]] == \
        list(range(1, len(contract["validation"]["increments"]) + 1))

    # Primal parity compared every increment, and any divergence is within
    # what the model's own local Newton tolerance explains.
    parity = stages["primal_parity"]["outputs"]
    assert len(parity["per_increment"]) == len(contract["validation"]["increments"])
    assert parity["unexplained_increments"] == []
    assert parity["model_solver_tolerance"] == contract["validation"]["local_solver_tolerance"]

    # The derivative verification classified every row it produced, and says
    # plainly that executing it is not the same as verifying the model.
    verification = stages["derivative_verification"]["outputs"]
    assert verification["rows"] > 0
    assert sum(verification["classification_counts"].values()) == verification["rows"]
    assert 0 < verification["rows_supporting_verification"] <= verification["rows"]
    assert isinstance(verification["verified"], bool)
    assert verification["parity_failed"] is False
    assert "stage_success_is_not_verification" in verification
    assert {a["role"] for a in stages["derivative_verification"]["artifacts"]} == \
        {"convergence_evidence", "derivative_rows"}
