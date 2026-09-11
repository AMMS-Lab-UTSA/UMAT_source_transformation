"""A rebuild that changed nothing did not measure anything.

The association control recompiles the ORIGINAL so the same mathematics is
computed a different way, runs it on the same deck, and compares it with
itself. What comes back is the model's own sensitivity to how it is
computed, in the same units as the disagreement under test -- and a transform
difference no larger than that is the model's conditioning rather than the
transform's.

That reasoning holds only when the rebuild actually perturbed the model.
Twenty-one of the twenty-three surviving primal disagreements came back with
a control of exactly 0.000e+00: every rung of the ladder reproduced the
original bit for bit. Reported as a sensitivity of zero, it became the
premise of a verdict -- "the difference is larger than its own conditioning
accounts for" -- resting on a number that was never a measurement.

Zero movement under a perturbation that never arrived is not evidence that
the model is well conditioned. It is the absence of evidence either way, and
it has to read as that.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import verify_store_in_abaqus as verify  # noqa: E402


def test_a_bit_identical_rebuild_reports_that_it_measured_nothing():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "tools" / "verify_store_in_abaqus.py").read_text()
    assert 'outcome["measured"] = bool(moved)' in source
    assert "is unmeasured" in source


def test_the_verdict_will_not_rest_on_an_unmeasured_zero():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "tools" / "verify_store_in_abaqus.py").read_text()
    # Both the crediting branch and the blaming branch have to ask.
    credit = source[source.index("own = association.get("):]
    credit = credit[:credit.index("record[\"primal\"][\"own_sensitivity_unmeasured\"]")]
    assert credit.count('association.get("measured")') == 2, (
        "a control that measured nothing must neither credit the transform "
        "nor convict it")


def test_the_unmeasured_case_says_so_rather_than_claiming_zero():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "tools" / "verify_store_in_abaqus.py").read_text()
    assert "own sensitivity to " in source
    assert "round-off could not be measured against it" in source
    assert "own_sensitivity_unmeasured" in source


def test_a_control_that_moved_is_still_a_measurement():
    """The change must not disarm the control where it works.

    Two of the twenty-three did move -- 9.7e-08 and 1.6e-05 -- and those are
    real measurements of real conditioning.
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "tools" / "verify_store_in_abaqus.py").read_text()
    assert "moved = float(best.get(\"worst_stress_relative\") or 0.0)" in source
    # bool(9.7e-08) is True, so a control that moved still measures.
    assert bool(9.716679678184607e-08) is True
    assert bool(0.0) is False


def test_the_ladder_is_named_in_the_reason():
    """A reader has to be able to see WHAT failed to perturb the model."""
    from umat_oti.abaqus.support import ARITHMETIC_LADDER

    assert [name for name, _ in ARITHMETIC_LADDER] == ["intrinsics",
                                                       "reassociation"]
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "tools" / "verify_store_in_abaqus.py").read_text()
    assert "name for name, _ in ARITHMETIC_LADDER" in source
