"""End-to-end smoke test for the compact-JSON transform path.

This exercises the real transformation on the bundled minimal elasticity
example. It does not require Abaqus or a Fortran compiler: validation is not
run, only the source transformation and report generation.
"""

from __future__ import annotations

import csv
import json
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
