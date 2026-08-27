from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from umat_oti.validation.actual_legacy_higher_order import run_code_imp_higher_order_evidence
from umat_oti.validation.actual_umat_higher_order import (
    HIGHER_ORDER_ZERO_FRACTION, J2_INCREMENTS, SELECTED_DIRECTIONS,
    run_actual_j2_higher_order_evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
def test_actual_transformed_j2_orders_two_to_four_match_independent_reference(tmp_path: Path):
    evidence = run_actual_j2_higher_order_evidence(
        REPO_ROOT / "examples" / "j2_actual_higher_order.json",
        tmp_path / "evidence",
    )

    # Counts derived from the path, not pinned: the loading path is a property
    # of the study and lengthening it must not require editing a literal here,
    # because the only way to satisfy a literal is to change it -- which would
    # equally hide a run that had quietly stopped emitting rows.
    expected = len(J2_INCREMENTS) * len(SELECTED_DIRECTIONS) * 6
    assert evidence["status"] == "verified_from_generic_transformed_source"
    assert evidence["comparison"]["rows"] == expected
    assert evidence["comparison"]["passed_rows"] == expected
    assert evidence["comparison"]["failed_rows"] == 0
    assert evidence["comparison"]["max_relative_error_when_absolute_tolerance_exceeded"] < 1.0e-7

    # The path has to keep exercising both branches and the transition between
    # them, in both directions. A path that only ever loaded would verify the
    # elastic predictor and the hardening law and never the return to elastic.
    yielded = [row["yielded"] for row in evidence["branch_history"]]
    assert yielded.count(True) >= 3 and yielded.count(False) >= 3
    assert (False, True) in list(zip(yielded, yielded[1:])), "never enters yield"
    assert (True, False) in list(zip(yielded, yielded[1:])), "never unloads"
    first_plastic = yielded.index(True)
    assert evidence["branch_history"][first_plastic]["eqplas_after"] > 0.0
    later = evidence["branch_history"][first_plastic + 1]
    assert later["eqplas_after"] >= later["eqplas_before"] > 0.0
    assert {tuple(direction) for direction in evidence["directions"]} >= {
        (1, 1),
        (1, 2),
        (1, 1, 1),
        (1, 1, 2),
        (1, 1, 1, 1),
        (1, 1, 2, 2),
    }
    assert all(record["sha256"] for record in evidence["artifacts"])
    manifest = json.loads(Path(evidence["canonical_manifest"]).read_text(encoding="utf-8"))
    assert manifest["execution"]["status"] == "compiled"
    assert manifest["derivatives"][0]["order"] == 4


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
def test_actual_transformed_code_imp_orders_two_to_four_match_original_umat_fd(tmp_path: Path):
    evidence = run_code_imp_higher_order_evidence(
        REPO_ROOT / "examples" / "code_imp_actual_higher_order.json",
        tmp_path / "evidence",
    )

    assert evidence["status"] == "verified_from_generic_transformed_source"
    assert evidence["comparison"]["rows"] == 96
    assert evidence["comparison"]["passed_rows"] == 96
    assert evidence["comparison"]["failed_rows"] == 0
    assert evidence["comparison"]["max_relative_error_when_absolute_tolerance_exceeded"] < 2.0e-5
    assert [row["branch"] for row in evidence["branch_history"]] == [
        "elastic",
        "plastic",
        "plastic",
        "plastic",
    ]
    assert evidence["branch_history"][3]["effective_plastic_strain"] > evidence["branch_history"][1]["effective_plastic_strain"]
    assert {tuple(direction) for direction in evidence["directions"]} >= {
        (1, 1),
        (1, 2),
        (1, 1, 1),
        (1, 1, 2),
        (1, 1, 1, 1),
        (1, 1, 2, 2),
    }
    assert all(record["sha256"] for record in evidence["artifacts"])
    assert "independently compiled original code_imp UMAT" in evidence["reference"]["method"]
    manifest = json.loads(Path(evidence["canonical_manifest"]).read_text(encoding="utf-8"))
    assert manifest["execution"]["status"] == "compiled"
    assert manifest["derivatives"][0]["order"] == 4


def test_the_structural_zero_gap_is_wide_enough_that_the_fraction_does_not_matter():
    """The floor separating a zero from a value must not be a judgement call.

    ``HIGHER_ORDER_ZERO_FRACTION`` decides which comparisons are zeros of
    their derivative family, and a constant chosen to make rows pass would be
    worthless. It is defensible only because the two populations are far
    apart: every derivative is either at the magnitude its order has in this
    problem or is rounding dust many decades below it, with nothing in
    between. This asserts that separation directly, so the constant stops
    being defensible -- loudly -- the moment the gap closes around it.
    """
    import csv

    path = (REPO_ROOT / "paper_results" / "actual_umat_higher_order" / "j2"
            / "actual_umat_higher_order_comparison.csv")
    if not path.exists():
        pytest.skip("run tools/run_tangent_round.py to generate the comparison")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    # The scale each row was actually judged against, as recorded by the run.
    # Recomputing it here would let the test agree with a rule the code no
    # longer applies.
    dust, real = [], []
    for row in rows:
        scale = float(row["family_scale"])
        assert scale > 0.0, "a derivative family must have a positive scale"
        ratio = max(abs(float(row["oti_derivative"])),
                    abs(float(row["fd_reference"]))) / scale
        if ratio == 0.0:
            continue
        (dust if row["judged_by"] == "structural_zero" else real).append(ratio)

    assert dust and real, "both populations must be present to compare them"
    assert max(dust) < HIGHER_ORDER_ZERO_FRACTION < min(real), (
        f"the fraction {HIGHER_ORDER_ZERO_FRACTION:.0e} no longer separates "
        f"the two populations: dust reaches {max(dust):.3e} and the smallest "
        f"real value is {min(real):.3e}")
    decades = math.log10(min(real) / max(dust))
    assert decades >= 4.0, (
        f"only {decades:.1f} decades separate rounding dust ({max(dust):.3e}) "
        f"from the smallest real derivative ({min(real):.3e}); the fraction is "
        "now close enough to the data to be a judgement call, and the "
        "classification needs evidence stronger than a scale ratio")

    # The point of a wide gap is that the answer does not depend on where in
    # it the constant sits. Every fraction across the gap must classify every
    # row the same way, or the constant is doing work it should not be.
    for candidate in (max(dust) * 10.0, HIGHER_ORDER_ZERO_FRACTION,
                      min(real) / 10.0):
        classified = sum(1 for ratio in dust + real if ratio <= candidate)
        assert classified == len(dust), (
            f"fraction {candidate:.3e} classifies {classified} rows as zeros "
            f"where {HIGHER_ORDER_ZERO_FRACTION:.0e} classifies {len(dust)}")


def test_the_two_adjudicators_agree_row_for_row():
    """Two methods, no shared machinery, and they must reach the same verdict.

    The single-step comparison judges each entry against the contract's own
    magnitude scale and a fixed tolerance. The convergence study instead makes
    the reference earn the row: a plateau across consecutive step sizes, steps
    that cross the yield surface thrown away, and a zero admitted only on a
    recomputation at 200 digits that cannot see the OTI result. Neither can
    check itself. Agreeing on every row is what makes either believable, and a
    row where they part is a finding whichever one turns out to be wrong.
    """
    import csv

    single = (REPO_ROOT / "paper_results" / "actual_umat_higher_order" / "j2"
              / "actual_umat_higher_order_comparison.csv")
    study = (REPO_ROOT / "paper_results" / "higher_order_convergence" / "j2"
             / "convergence_rows.csv")
    if not single.exists() or not study.exists():
        pytest.skip("run tools/run_tangent_round.py and the j2 convergence study")

    def read(path):
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def key(row):
        return (int(row["increment"]), int(row["order"]), row["directions"],
                int(row["stress_component"]))

    single_rows, study_rows = read(single), read(study)
    assert len(single_rows) == len(study_rows), (
        "the two adjudicators covered different numbers of comparisons")

    mine = {key(r): r["judged_by"] == "structural_zero" for r in single_rows}
    theirs = {key(r): r["reference_classification"].startswith("expected_zero")
              for r in study_rows}
    assert set(mine) == set(theirs), "the two cover different comparisons"

    disagree = sorted(k for k in mine if mine[k] != theirs[k])
    assert not disagree, (
        f"{len(disagree)} comparisons are a zero to one method and a value to "
        f"the other, e.g. {disagree[:5]}")

    # And neither may report a disagreement it then counts as agreement.
    assert all(r["passed"] == "True" for r in single_rows)
    assert all(r["agrees_with_reference"] != "False" for r in study_rows)
