"""Table 5 is a 20-increment loading path, not an oversized table.

560 rows = 20 increments x (6 DSIGMA_DP + 1 DSTATEV_DP) x 4 parameters. Having
more rows than the 6x4 and 1x4 the manuscript quotes is expected: those are one
increment of the path. These tests pin the structure so the dataset is judged on
what it contains rather than on its row count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.validate_table5 import (
    EXPECTED_PARAMETERS, SOURCE, emit_views, load, validate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset():
    if not SOURCE.exists():
        pytest.skip(f"{SOURCE} not present")
    return load(SOURCE)


def test_the_dataset_passes_every_structural_check(dataset):
    failures, facts = validate(dataset)
    assert not failures, "; ".join(failures)
    assert facts["actual_rows"] == facts["expected_rows"] == 560


def test_the_row_count_decomposes_as_a_loading_path(dataset):
    _failures, facts = validate(dataset)
    assert facts["increments"] == 20
    assert len(facts["components"]["DSIGMA_DP"]) == 6
    assert len(facts["components"]["DSTATEV_DP"]) == 1
    assert facts["parameters"] == list(EXPECTED_PARAMETERS)
    assert 20 * (6 + 1) * 4 == facts["actual_rows"]


def test_both_branches_and_history_are_exercised(dataset):
    _failures, facts = validate(dataset)
    assert facts["elastic_increments"] > 0 and facts["plastic_increments"] > 0
    # a path-dependent sensitivity must keep changing, not sit at two values
    assert facts["distinct_dsigma1_dH"] > 2


def test_substantive_and_near_zero_rows_are_judged_differently(dataset):
    """A relative error against zero is meaningless; those rows use absolute."""
    _failures, facts = validate(dataset)
    assert facts["substantive_rows"] > 0 and facts["near_zero_rows"] > 0
    assert facts["worst_relative_error"] < 1.0e-6
    assert facts["worst_absolute_error_near_zero"] == 0.0


def test_a_missing_combination_is_detected(dataset):
    """The validator must fail on an incomplete path, not just count rows."""
    broken = [r for r in dataset
              if not (r["increment"] == "7" and r["array"] == "DSIGMA_DP"
                      and r["row"] == "3" and r["parameter"] == "NU")]
    failures, _facts = validate(broken)
    assert any("missing combination" in f for f in failures)


def test_a_duplicated_row_is_detected(dataset):
    failures, _facts = validate(dataset + [dataset[0]])
    assert any("duplicate" in f for f in failures)


def test_views_reduce_to_the_quoted_shapes(dataset, tmp_path):
    written = emit_views(dataset, increment=20, out_dir=tmp_path)
    assert len(written) == 2
    stress, state = sorted(written, key=lambda p: p.name)
    stress_rows = stress.read_text(encoding="utf-8").strip().splitlines()
    state_rows = state.read_text(encoding="utf-8").strip().splitlines()
    assert len(stress_rows) == 1 + 6, "the DSIGMA_DP view must be 6 rows plus a header"
    assert len(state_rows) == 1 + 1, "the DSTATEV_DP view must be 1 row plus a header"
    assert stress_rows[0].split(",")[1:] == list(EXPECTED_PARAMETERS)
