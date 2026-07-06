"""End-to-end smoke test for the compact-JSON transform path.

This exercises the real transformation on the bundled minimal elasticity
example. It does not require Abaqus or a Fortran compiler: validation is not
run, only the source transformation and report generation.
"""

from __future__ import annotations

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
