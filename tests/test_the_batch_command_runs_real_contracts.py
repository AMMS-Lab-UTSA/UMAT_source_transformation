"""``umat-oti-batch`` transforms real contracts and reports what it did.

The existing batch test replaces the transform with a fake to check dispatch.
This one substitutes nothing: two shipped contracts, the compact
``examples/elastic_minimal.json`` and the unified-schema
``examples/code_imp_actual_higher_order.json``, are copied into a
``--config-dir`` and the command's own module is run on it, as the console
script runs it. The transformed sources, the per-contract transform reports and
the batch reports it writes are then read back.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
CONTRACTS = {
    "elastic_minimal": ("DDSDDE", 1),
    "code_imp_actual_higher_order": ("DDSDDE4", 4),
}


def _copy_contract(name: str, into: Path) -> None:
    """The contract as shipped, with its source path made absolute.

    A contract's source path is relative to the contract, so a copy elsewhere
    has to carry the resolved path or it names a file that is not there.
    """
    contract = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    contract["source"] = str((EXAMPLES / contract["source"]).resolve())
    (into / f"{name}.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")


def test_the_batch_command_transforms_each_contract_and_writes_both_reports(tmp_path):
    config_dir = tmp_path / "contracts"
    config_dir.mkdir()
    for name in CONTRACTS:
        _copy_contract(name, config_dir)
    batch_dir = tmp_path / "batch"

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), *filter(None, [environment.get("PYTHONPATH")])])
    done = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli_batch",
         "--config-dir", str(config_dir), "--batch-dir", str(batch_dir)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr

    report = json.loads((batch_dir / "completed_json_batch_report.json").read_text())
    rows = {row["umat"]: row for row in report["results"]}
    assert set(rows) == set(CONTRACTS)
    assert report["category_counts"] == {"ready_with_json_contract": len(CONTRACTS)}

    for name, (target, order) in CONTRACTS.items():
        row = rows[name]
        assert row["config"] == f"{name}.json"
        assert row["category"] == "ready_with_json_contract", row
        assert row["transform_success"] is True
        assert row["blockers"] == []
        assert row["validation_status"] == "not_run"
        assert row["status"] == "Transformation succeeded; validation not requested."
        assert [(r["target"], r["order"]) for r in row["derivative_requests"]] == [(target, order)]

        # The transform really ran, into the batch directory.
        transformed = Path(row["transformed_source"])
        assert transformed.parent == batch_dir / "oti_transform" / name
        text = transformed.read_text(encoding="utf-8")
        assert "GETIM(" in text and "_OTI" in text
        transform_report = json.loads(Path(row["transform_report"]).read_text())
        assert transform_report["oti_order"] == order
        assert Path(row["source"]).resolve() == Path(
            json.loads((config_dir / f"{name}.json").read_text())["source"])

    markdown = (batch_dir / "completed_json_batch_report.md").read_text(encoding="utf-8")
    assert f"Total configs: {len(CONTRACTS)}" in markdown
    assert f"- ready_with_json_contract: {len(CONTRACTS)}" in markdown
    for name in CONTRACTS:
        assert f"| {name} |" in markdown
        assert f"{name}.json\tready_with_json_contract" in done.stdout
