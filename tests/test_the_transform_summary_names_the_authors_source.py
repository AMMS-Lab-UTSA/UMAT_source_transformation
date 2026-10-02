"""A transform's summary names the source the author gave, not the staged copy.

The transform reads a copy staged beside its bundled modules (57eaeff), and
for a while the summary reported that copy as its ``source``. The regression
service keys its rows on that field, so every row stopped matching the source
it was asked about. The staged copy is for transforming only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.services.transformation import TransformationOptions, run_transformation

pytestmark = [pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "parameter_sensitivity" / "contracts" / "m1_elastic.json"
AUTHORS_SOURCE = REPO_ROOT / "parameter_sensitivity" / "models" / "m1_elastic" / "umat.for"


def test_the_summary_source_is_the_authors_file_not_the_staged_copy(tmp_path):
    summary, _ = run_transformation(CONTRACT, tmp_path / "out", TransformationOptions(compile_generated=False))
    assert summary.get("transform_success"), summary
    assert Path(summary["source"]).resolve() == AUTHORS_SOURCE.resolve()
    # the transform itself still worked from the staged copy
    staged = Path(summary["out_dir"]) / "dependencies"
    assert staged.is_dir() and any(staged.rglob("umat.for"))
