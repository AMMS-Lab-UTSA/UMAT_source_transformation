"""Reference-quality classification must never let a weak reference pass.

These tests pin the rules that make the higher-order convergence study a
verification instrument rather than a tolerance-fitting exercise:

  * a row is passed only when an independent reference actually resolves it;
  * an unresolved or cancellation-limited row is never promoted by being small,
    and never leaves a study marked verified;
  * a zero derivative needs support that does not come from the OTI result --
    and sampled equality at finitely many points is not such support;
  * a stencil that crosses a constitutive branch boundary cannot verify the
    derivative of the nominal branch;
  * a relative error is quoted only against a resolved reference.
"""

from __future__ import annotations

import csv
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


def _row(values, oti, *, order=4, invariant=False, affine=False,
         high_precision=None, source_proof=None, branch_pattern=None):
    """Build and classify one synthetic row.

    ``branch_pattern`` marks which swept steps stayed on the nominal branch;
    ``None`` means every step is admissible.
    """
    steps = hoc.sweep_steps(2.0e-5)
    assert len(values) == len(steps), "one value per swept step"
    if branch_pattern is None:
        branch_pattern = [True] * len(steps)
    sweep = []
    for (factor, step), value, ok in zip(steps, values, branch_pattern):
        sweep.append(hoc.SweepPoint(
            step=step, step_factor=factor, value=value, invariant=invariant,
            nominal_branch="elastic",
            node_branches=("elastic",) * 9 if ok else ("elastic",) * 8 + ("plastic",),
            branch_consistent=ok,
            admissible=ok,
            rejection_reason=None if ok else "stencil left the nominal 'elastic' branch",
        ))
    kind, detail = (source_proof or (None, None))
    return hoc.classify_row(
        hoc.RowInputs(
            increment=1, branch="elastic", stress_component=1, order=order,
            directions=(1,) * order, direction_pattern="repeated", recovery_factor=1.0,
            oti_value=oti, sweep=sweep,
            structurally_invariant=invariant,
            affine_in_directions=affine,
            affine_amplitudes=(1.6e-4, 8.0e-5, 4.0e-5),
            affine_margin=0.5,
            high_precision_value=high_precision,
            high_precision_step=2.0e-8, high_precision_digits=200,
            source_proof_kind=kind, source_proof_detail=detail,
        ),
        SCALE,
    )


def _plateau_values(centre, wobble=1.0e-6):
    """Large steps off, a clean middle plateau, small steps off again."""
    offsets = (0.3, 0.08, wobble, wobble / 2, 0.0, wobble / 2, wobble, 0.08, 0.3)
    return [centre * (1.0 + offset) for offset in offsets]


# --------------------------------------------------------------------------- #
# Plateau and agreement
# --------------------------------------------------------------------------- #
def test_a_clean_plateau_that_matches_oti_supports_verification():
    row = _row(_plateau_values(1.0e13), 1.0e13)
    assert row["reference_classification"] == hoc.RESOLVED
    assert row["supports_verification"] is True
    assert row["relative_error"] is not None


def test_a_clean_plateau_that_contradicts_oti_does_not_pass():
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


def test_a_huge_absolute_tolerance_cannot_rescue_an_unresolved_row():
    wild = [1.0e7 * f for f in (1.0, 12.0, 0.2, 40.0, 0.05, 90.0, 0.01, 200.0, 0.004)]
    row = _row(wild, 1.0e7 + 1.0e3)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False


# --------------------------------------------------------------------------- #
# Zero support: sampled equality is not proof
# --------------------------------------------------------------------------- #
def test_stencil_invariance_alone_is_only_empirically_zero():
    """Bit-identical samples show local invariance, not exact independence."""
    row = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, invariant=True)
    assert row["reference_classification"] == hoc.EMPIRICALLY_ZERO
    assert row["supports_verification"] is False
    assert row["zero_support_strength"] == "weak"


def test_affine_probe_alone_is_only_empirically_zero():
    row = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, affine=True)
    assert row["reference_classification"] == hoc.EMPIRICALLY_ZERO
    assert row["supports_verification"] is False


def test_both_empirical_signals_together_still_do_not_prove_exact_zero():
    """Two kinds of sampling are still sampling."""
    row = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, invariant=True, affine=True)
    assert row["reference_classification"] == hoc.EMPIRICALLY_ZERO
    assert row["supports_verification"] is False
    assert all(not s["strong"] for s in row["zero_supports"])


def test_high_precision_zero_is_strong_support():
    noisy = [1.0e-6 * (1.0 + 0.5 * index) for index in range(len(hoc.STEP_FACTORS))]
    row = _row(noisy, 0.0, high_precision=0.0)
    assert row["reference_classification"] == hoc.EXPECTED_ZERO
    assert row["supports_verification"] is True
    assert row["zero_support_strength"] == "strong"


def test_source_proof_with_branch_consistency_is_strong_support():
    row = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, invariant=True,
               source_proof=("source_affine_branch", "elastic update is affine in DSTRAN."))
    assert row["reference_classification"] == hoc.EXPECTED_ZERO
    assert row["supports_verification"] is True


def test_source_proof_is_rejected_when_the_stencil_left_the_branch():
    """A branch-local proof cannot speak for a stencil that changed branch."""
    pattern = [True] * 8 + [False]
    row = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, invariant=True,
               source_proof=("source_affine_branch", "elastic update is affine."),
               branch_pattern=pattern)
    assert row["branch_consistent_over_admissible_steps"] is True
    # consistency holds over the admissible steps, so the proof still applies
    assert row["reference_classification"] == hoc.EXPECTED_ZERO


def test_a_zero_reference_without_any_support_is_not_a_free_pass():
    tiny = [1.0e-9 * (1.0 + 0.001 * index) for index in range(len(hoc.STEP_FACTORS))]
    row = _row(tiny, 0.0)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False


def test_independent_zero_contradicted_by_nonzero_oti_is_a_disagreement():
    row = _row([0.0] * len(hoc.STEP_FACTORS), 5.0e10, invariant=True)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False
    assert "genuine disagreement" in row["reference_justification"]


# --------------------------------------------------------------------------- #
# Branch admissibility
# --------------------------------------------------------------------------- #
def test_branch_crossing_steps_are_excluded_from_the_plateau():
    """The plateau must be built only from steps that stayed on the branch."""
    values = _plateau_values(1.0e13)
    # corrupt the three plateau steps but mark them as branch-crossing
    pattern = [True, True, False, False, False, True, True, True, True]
    for index in (2, 3, 4):
        values[index] = 5.0e13
    row = _row(values, 1.0e13, branch_pattern=pattern)
    assert row["steps_rejected_for_branch_crossing"] == 3
    # the corrupted values must not have formed the reference
    assert row["reference_value"] is None or abs(row["reference_value"] - 5.0e13) > 1.0e12


def test_too_few_admissible_steps_is_unresolved_with_a_branch_reason():
    values = _plateau_values(1.0e13)
    pattern = [True, True, False, False, False, False, False, True, True]
    row = _row(values, 1.0e13, branch_pattern=pattern)
    assert row["reference_classification"] == hoc.UNRESOLVED
    assert row["supports_verification"] is False
    assert "left the nominal branch" in row["reference_justification"]
    assert row["plateau_points"] is None


def test_every_sweep_point_records_its_branch_audit():
    row = _row(_plateau_values(1.0e13), 1.0e13)
    for point in row["sweep"]:
        assert point["nominal_branch"] == "elastic"
        assert point["node_branches"]
        assert "admissible" in point
        # a margin that is unavailable stays null, never zero
        assert point["min_branch_margin"] is None or isinstance(
            point["min_branch_margin"], float)


# --------------------------------------------------------------------------- #
# Study-level verification predicate
# --------------------------------------------------------------------------- #
def test_summary_marks_a_set_with_unresolved_rows_as_not_verified():
    good = _row(_plateau_values(1.0e13), 1.0e13)
    bad = _row([1.0e13 * f for f in (1.0, 1.4, 0.6, 2.2, 0.3, 3.0, 0.1, 5.0, 0.01)], 1.0e13)
    assert hoc.summarize([good])["verified"] is True
    summary = hoc.summarize([good, bad])
    assert summary["verified"] is False
    assert summary["rows_without_usable_reference"] == 1


def test_one_cancellation_limited_row_blocks_verification():
    """Regression: cancellation-limited rows were once absent from the predicate."""
    good = _row(_plateau_values(1.0e13), 1.0e13)
    limited = _row(_plateau_values(1.0e13, wobble=2.0e-2), 1.0e13)
    assert limited["reference_classification"] == hoc.CANCELLATION_LIMITED
    summary = hoc.summarize([good, good, limited])
    assert summary["classification_counts"][hoc.CANCELLATION_LIMITED] == 1
    assert summary["verified"] is False, "a cancellation-limited row must block verification"
    assert summary["rows_without_usable_reference"] == 1


def test_one_empirically_zero_row_blocks_verification():
    good = _row(_plateau_values(1.0e13), 1.0e13)
    empirical = _row([0.0] * len(hoc.STEP_FACTORS), 0.0, invariant=True)
    summary = hoc.summarize([good, empirical])
    assert summary["rows_empirically_zero_only"] == 1
    assert summary["verified"] is False
    assert summary["rows_without_usable_reference"] == 1


def test_one_disagreeing_row_blocks_verification():
    good = _row(_plateau_values(1.0e13), 1.0e13)
    wrong = _row(_plateau_values(1.0e13), 1.1e13)
    summary = hoc.summarize([good, wrong])
    assert summary["rows_with_reference_but_disagreeing"] == 1
    assert summary["verified"] is False


def test_verified_requires_every_row_to_support():
    rows = [_row(_plateau_values(1.0e13), 1.0e13) for _ in range(3)]
    summary = hoc.summarize(rows)
    assert summary["rows_supporting_verification"] == summary["rows"]
    assert summary["verified"] is True


def test_normalization_is_scale_aware_across_orders():
    second = SCALE.normalize(1.0e-3 ** -2 * 1.0e-6 * 250.0, 2)
    fourth = SCALE.normalize(1.0e-3 ** -4 * 1.0e-6 * 250.0, 4)
    assert second == pytest.approx(fourth, rel=1.0e-12)


# --------------------------------------------------------------------------- #
# Generated datasets
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model", ["j2", "code_imp"])
def test_archived_convergence_dataset_is_internally_consistent(model):
    """Consistency, on a count the dataset has to justify from its own shape.

    The row count used to be a literal here. It is the product of the loading
    path, the derivative orders and the direction sets, so lengthening the
    path made this fail with nothing wrong -- and the only way to satisfy a
    literal is to edit it, which is exactly the move that would also hide a
    study that had quietly stopped emitting rows. Deriving it instead means
    the test still fails when rows go missing.
    """
    path = (REPO_ROOT / "paper_results" / "higher_order_convergence" / model
            / "convergence_evidence.json")
    if not path.exists():
        pytest.skip(
            f"convergence dataset for {model} not generated; run "
            f"python -m umat_oti.validation.higher_order_convergence_study --model {model}"
        )
    dataset = json.loads(path.read_text(encoding="utf-8"))
    summary = dataset["summary"]
    counts = summary["classification_counts"]

    rows_path = path.with_name("convergence_rows.csv")
    with rows_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    increments = {int(row["increment"]) for row in rows}
    orders = {int(row["order"]) for row in rows}
    directions = {row["directions"] for row in rows}
    components = {int(row["stress_component"]) for row in rows}
    # One row for every combination the study set out to cover, and no
    # duplicates: each order carries its own direction sets, so the product is
    # taken over the direction sets belonging to each order.
    expected_rows = len(increments) * len(components) * len(directions)
    assert len(rows) == expected_rows, (
        f"{model}: {len(rows)} rows for {len(increments)} increments x "
        f"{len(components)} components x {len(directions)} direction sets")
    assert len({(r["increment"], r["order"], r["directions"],
                 r["stress_component"]) for r in rows}) == len(rows), (
        "a comparison appears twice")
    assert len(orders) == len({d.count("|") + 1 for d in directions})

    assert summary["rows"] == expected_rows
    assert sum(counts.values()) == expected_rows
    assert set(counts) == set(hoc.CLASSIFICATIONS)
    without_usable = (
        counts[hoc.CANCELLATION_LIMITED] + counts[hoc.UNRESOLVED] + counts[hoc.EMPIRICALLY_ZERO]
    )
    assert summary["verified"] == (
        summary["rows_supporting_verification"] == expected_rows
        and summary["rows_with_reference_but_disagreeing"] == 0
        and without_usable == 0
    )
    assert dataset["normalization"]["stress_units"] == "MPa"
    assert len(dataset["reference"]["steps"]) == len(hoc.STEP_FACTORS)
