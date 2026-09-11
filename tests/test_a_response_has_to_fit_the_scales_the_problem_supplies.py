"""An experiment can be finite, complete, active -- and nowhere real.

Measured on BodyForce-Growth-2Stages.for at the amplitude the resolution
ladder settled on. The growth genuinely developed: STATEV(9), which the
source documents as the norm of the growth tensor, ran 0.003125 to 0.40625.
Both builds agreed. The derivative matched a converged difference. And the
peak stress was 1.575e13 against a deck carrying one material constant, 1e8.

A ratio of 157,500 is not a regime this material has, and an agreement
reached there is not a verification of it. No universal physical limit says
so -- the material's own numbers do.
"""
from umat_oti.abaqus.plausibility import (FAR_ABOVE_THE_CONSTANTS,
                                          FAR_ABOVE_THE_PROBE,
                                          against_material_constants,
                                          against_the_smallest_probe,
                                          deformation_gradient_stays_positive,
                                          examine)


def _history(stress, dfgrd=None):
    record = {"step": 1, "increment": 1, "element": 1, "point": 1,
              "STRESS": [stress], "STATEV": [0.0]}
    if dfgrd is not None:
        record["DFGRD1"] = dfgrd
    return [record]


def test_a_stress_far_above_every_material_constant_is_not_accounted_for():
    check = against_material_constants(_history(1.575e13), [1e8])
    assert check.plausible is False
    assert "157500" in check.detail.replace(",", "") or "1.575e+05" in check.detail
    assert "no combination of this material's own numbers" in check.detail


def test_an_ordinary_stress_is_accounted_for():
    """An elastic strain of order one against a modulus gives a stress of
    order that modulus. The bound allows a thousandfold of that."""
    assert against_material_constants(_history(2.0e8), [1e8]).plausible is True
    assert against_material_constants(_history(9.9e10), [1e8]).plausible is True
    assert FAR_ABOVE_THE_CONSTANTS == 1.0e3


def test_no_constants_means_no_check_rather_than_a_pass():
    assert against_material_constants(_history(1e13), []) is None
    assert against_material_constants(_history(1e13), [0.0]) is None


def test_a_response_far_beyond_what_the_smallest_probe_predicts_is_flagged():
    attempts = [{"ran": True, "amplitude": 1e-4, "largest_stress": 1.0}]
    check = against_the_smallest_probe(_history(1e6), 1e-2, attempts)
    assert check.plausible is False
    assert "not more of what the search measured" in check.detail
    assert FAR_ABOVE_THE_PROBE == 1.0e1


def test_a_response_below_proportionality_is_not_the_concern():
    """A material whose stress grows LESS than linearly is not a runaway."""
    attempts = [{"ran": True, "amplitude": 1e-4, "largest_stress": 1.0}]
    assert against_the_smallest_probe(_history(50.0), 1e-2, attempts).plausible


def test_a_determinant_that_is_not_positive_is_not_a_deformation():
    inside_out = _history(1.0, dfgrd=[-1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0])
    check = deformation_gradient_stays_positive(inside_out)
    assert check.plausible is False
    assert "which is not a deformation" in check.detail


def test_an_identity_deformation_gradient_is_fine():
    ok = _history(1.0, dfgrd=[1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0])
    assert deformation_gradient_stays_positive(ok).plausible is True


def test_a_history_with_no_gradient_recorded_asks_no_question_of_it():
    assert deformation_gradient_stays_positive(_history(1.0)) is None


def test_the_report_says_what_it_could_not_check():
    report = examine(_history(1e13), props=[], amplitude=0.0, attempts=())
    assert report.checks == []
    assert "nothing here supplied a scale" in report.reason()


def test_a_concern_refuses_rather_than_warns():
    report = examine(_history(1.575e13), props=[1e8])
    assert report.plausible is False
    assert len(report.concerns) == 1
    assert "not verified on that basis until it is explained" in report.reason()


def test_the_checks_are_read_off_the_frozen_run_and_recorded():
    import pathlib
    tool = (pathlib.Path(__file__).resolve().parents[1]
            / "tools" / "verify_store_in_abaqus.py").read_text()
    assert "plausibility.examine(" in tool
    assert 'record["response_plausibility"]' in tool
