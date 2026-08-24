"""End-to-end smoke test for the compact-JSON transform path.

This exercises the real transformation on the bundled minimal elasticity
example. It does not require Abaqus or a Fortran compiler: validation is not
run, only the source transformation and report generation.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from umat_oti.cli_json import run_config_transform


def test_elastic_minimal_transform_succeeds(examples_dir: Path, tmp_path: Path) -> None:
    config = examples_dir / "elastic_minimal.json"
    assert config.is_file(), f"missing bundled example: {config}"

    summary, exit_code = run_config_transform(config, tmp_path / "elastic_out")

    assert exit_code == 0, summary
    assert summary.get("transform_success") is True
    assert not summary.get("blockers")

    transformed = Path(summary["transformed_source"])
    assert transformed.is_file(), "transformed UMAT source was not written"
    assert transformed.stat().st_size > 0

    report = Path(summary["report_path"])
    assert report.is_file(), "transform report was not written"
    manifest = json.loads(Path(summary["manifest"]).read_text(encoding="utf-8"))
    assert manifest["derivatives"][0]["target"] == "DDSDDE"
    assert manifest["source"]["sha256"]
    assert manifest["generated_sources"]
    assert all(record["sha256"] for record in manifest["generated_sources"])
    assert manifest["dimensions"]["ntens_inference"]["source"]
    assert manifest["execution"]["status"] == "generated_not_compiled"


def test_order_four_transform_emits_direction_metadata(examples_dir: Path, tmp_path: Path) -> None:
    source_config = examples_dir / "elastic_minimal.json"
    config = json.loads(source_config.read_text(encoding="utf-8"))
    config["source"] = str((source_config.parent / config["source"]).resolve())
    config["order"] = 4
    config_path = tmp_path / "elastic_order4.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    summary, exit_code = run_config_transform(config_path, tmp_path / "elastic_order4_out")

    assert exit_code == 0, summary
    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert report["oti_module_name"] == "otim4n4"
    directions_path = Path(summary["report_path"]).parent / "higher_order_directions.csv"
    with directions_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 69
    assert rows[0] == {
        "order": "1",
        "member_name": "E1",
        "flat_getim_index": "1",
        "bases_multiindex": "1",
        "recovery_factor": "1",
    }
    assert rows[-1]["bases_multiindex"] == "4|4|4|4"
    assert rows[-1]["recovery_factor"] == "24"


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
def test_literal_schema_compiles_through_canonical_json_cli(examples_dir: Path, tmp_path: Path) -> None:
    source_config = examples_dir / "elastic_minimal.json"
    compact = json.loads(source_config.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.1",
        "name": "literal_compiled",
        "source": str((source_config.parent / compact["source"]).resolve()),
        "entry_routine": "UMAT",
        "ntens": compact["ntens"],
        "derivatives": [
            {"id": "higher_order_four", "target": "DDSDDE4", "seed": "DSTRAN", "response": "STRESS", "order": 4}
        ],
    }
    config_path = tmp_path / "literal.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    out_dir = tmp_path / "compiled"

    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli_json", "--config", str(config_path), "--out", str(out_dir), "--compile"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["order"] == 4
    assert summary["derivative_requests"][0]["kind"] == "higher_order"
    assert summary["compilation"]["status"] == "compiled"
    manifest = json.loads(Path(summary["manifest"]).read_text(encoding="utf-8"))
    assert manifest["execution"]["status"] == "compiled"
    assert manifest["execution"]["returncode"] == 0


def test_evidence_command_consumes_literal_schema(examples_dir: Path, tmp_path: Path) -> None:
    source_config = examples_dir / "elastic_minimal.json"
    compact = json.loads(source_config.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.1",
        "name": "literal_evidence",
        "source": str((source_config.parent / compact["source"]).resolve()),
        "entry_routine": "UMAT",
        "ntens": compact["ntens"],
        "derivatives": [
            {"id": "tangent", "target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}
        ],
    }
    config_path = tmp_path / "literal.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    evidence_dir = tmp_path / "evidence"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "umat_oti.reports.run_softwarex_evidence",
            "--config",
            str(config_path),
            "--output-dir",
            str(evidence_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads((evidence_dir / "canonical_transform_evidence.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "verified_from_generic_transformed_source"
    assert evidence["transform"]["derivative_requests"][0]["target"] == "DDSDDE"
