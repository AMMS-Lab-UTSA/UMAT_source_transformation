"""Reference-quality classification must never let a weak reference pass.

These tests pin the rules that make the higher-order convergence study a
verification instrument rather than a tolerance-fitting exercise:

  * a row is passed only when an independent reference actually resolves it;
  * an unresolved row is never promoted by being small;
  * a zero derivative needs support that does not come from the OTI result;
  * a relative error is quoted only against a resolved reference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.validation import higher_order_convergence as hoc

REPO_ROOT = Path(__file__).resolve().parents[1]
SCALE = hoc.NormalizationScale(
    stress_scale=250.0,
    strain_scale=1.0e-3,
    stress_scale_meaning="test yield stress",
    strain_scale_meaning="test strain scale",
)


def _row(values, oti, *, order=4, invariant=False, high_precision=None):
    steps = hoc.sweep_steps(2.0e-5)
    assert len(values) == len(steps), "one value per swept step"
    sweep = [
        hoc.SweepPoint(step=step, step_factor=factor, value=value, invariant=invariant)
        for (factor, step), value in zip(steps, values)
    ]
    return hoc.classify_row(
        hoc.RowInputs(
            increment=1,
            branch="plastic",
            stress_component=1,
            order=order,
            directions=(1,) * order,
            direction_pattern="repeated",
            recovery_factor=1.0,
            oti_value=oti,
            sweep=sweep,
            structurally_invariant=invariant,
            high_precision_value=high_precision,
            high_precision_step=2.0e-8,
            high_precision_digits=200,
        ),
        SCALE,
    )


def _plateau_values(centre, wobble=1.0e-6):
    """Large steps off, a clean middle plateau, small steps off again."""
    offsets = (0.3, 0.08, wobble, wobble / 2, 0.0, wobble / 2, wobble, 0.08, 0.3)
    return [centre * (1.0 + offset) for offset in offsets]


def test_a_clean_plateau_that_matches_oti_supports_verification():
    row = _row(_plateau_values(1.0e13), 1.0e13)
    assert row["reference_classification"] == hoc.RESOLVED
    assert row["supports_verification"] is True
    assert row["relative_error"] is not None
    assert row["plateau_points"] >= hoc.PLATEAU_MIN_POINTS


def test_a_clean_plateau_that_contradicts_oti_does_not_pass():
    """The reference is good; OTI is wrong. That must fail, not be absorbed."""
    row = _row(_plateau_values(1.0e13), 1.1e13)
    assert row["reference_classification"] == hoc.RESOLVED
    assert row["agrees_with_reference"] is False
    assert row["supports_verification"] is False


def test_pure_noise_is_unresolved_and_quotes_no_relative_error():
    row = _row([1.0e13 * f for f in (1.0, 1.4, 0.6, 2.2, 0.3, 3.0, 0.1, 5.0, 0.01)], 1.0e13)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False
    assert row["relative_error"] is None, "no relative error against an unresolved reference"


def test_partially_stable_reference_is_cancellation_limited_not_passed():
    row = _row(_plateau_values(1.0e13, wobble=2.0e-2), 1.0e13)
    assert row["reference_classification"] == hoc.CANCELLATION_LIMITED
    assert row["supports_verification"] is False
    assert row["relative_error"] is None


def test_structural_invariance_supports_a_zero_derivative():
    row = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, invariant=True)
    assert row["reference_classification"] == hoc.EXPECTED_ZERO
    assert row["supports_verification"] is True
    assert "structural invariance" in row["reference_justification"]


def test_high_precision_supports_a_zero_derivative_without_structural_invariance():
    noisy = [1.0e-6 * (1.0 + 0.5 * index) for index in range(len(hoc.STEP_FACTORS))]
    row = _row(noisy, 0.0, invariant=False, high_precision=0.0)
    assert row["reference_classification"] == hoc.EXPECTED_ZERO
    assert row["supports_verification"] is True
    assert "high-precision" in row["reference_justification"]


def test_a_zero_reference_without_independent_support_is_not_a_free_pass():
    """The sweep collapsing to ~0 proves nothing on its own."""
    tiny = [1.0e-9 * (1.0 + 0.001 * index) for index in range(len(hoc.STEP_FACTORS))]
    row = _row(tiny, 0.0, invariant=False, high_precision=None)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False


def test_independent_zero_contradicted_by_nonzero_oti_is_reported_as_disagreement():
    row = _row([0.0] * len(hoc.STEP_FACTORS), 5.0e10, invariant=True)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False
    assert "genuine disagreement" in row["reference_justification"]


def test_a_huge_absolute_tolerance_cannot_rescue_an_unresolved_row():
    """The failure mode this study exists to prevent.

    An order-4 row whose reference swings by orders of magnitude across steps is
    unresolved no matter how small the discrepancy looks next to a 4e4 tolerance.
    """
    wild = [1.0e7 * f for f in (1.0, 12.0, 0.2, 40.0, 0.05, 90.0, 0.01, 200.0, 0.004)]
    row = _row(wild, 1.0e7 + 1.0e3)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False


def test_normalization_is_scale_aware_across_orders():
    """The same physical smallness maps to the same normalized magnitude."""
    second = SCALE.normalize(1.0e-3 ** -2 * 1.0e-6 * 250.0, 2)
    fourth = SCALE.normalize(1.0e-3 ** -4 * 1.0e-6 * 250.0, 4)
    assert second == pytest.approx(fourth, rel=1.0e-12)


def test_summary_marks_a_set_with_unresolved_rows_as_not_verified():
    good = _row(_plateau_values(1.0e13), 1.0e13)
    bad = _row([1.0e13 * f for f in (1.0, 1.4, 0.6, 2.2, 0.3, 3.0, 0.1, 5.0, 0.01)], 1.0e13)
    assert hoc.summarize([good])["verified"] is True
    summary = hoc.summarize([good, bad])
    assert summary["verified"] is False
    assert summary["rows_without_usable_reference"] == 1


@pytest.mark.parametrize("model,expected_rows", [("j2", 108), ("code_imp", 96)])
def test_archived_convergence_dataset_is_internally_consistent(model, expected_rows):
    """The generated dataset must agree with its own classification policy."""
    path = REPO_ROOT / "paper_results" / "higher_order_convergence" / model / "convergence_evidence.json"
    if not path.exists():
        pytest.skip(
            f"convergence dataset for {model} not generated; run "
            f"python -m umat_oti.validation.higher_order_convergence_study --model {model}"
        )
    dataset = json.loads(path.read_text(encoding="utf-8"))
    summary = dataset["summary"]
    counts = summary["classification_counts"]

    assert summary["rows"] == expected_rows
    assert sum(counts.values()) == expected_rows
    assert set(counts) == set(hoc.CLASSIFICATIONS)
    # verified is exactly "every row supported, none unresolved, none disagreeing"
    assert summary["verified"] == (
        summary["rows_supporting_verification"] == expected_rows
        and summary["rows_with_reference_but_disagreeing"] == 0
        and counts[hoc.UNRESOLVED] == 0
    )
    assert dataset["normalization"]["stress_units"] == "MPa"
    assert dataset["reference"]["published_step"] > 0.0
    assert len(dataset["reference"]["steps"]) == len(hoc.STEP_FACTORS)
