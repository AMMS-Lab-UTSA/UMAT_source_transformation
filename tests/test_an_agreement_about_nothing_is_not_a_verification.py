"""A repair that removes the behaviour under test has not verified it.

Shortening the clock is the right repair for a failure that moves with the
period. It is also a change to the mechanical problem, and the two are not
the same claim. A growth law whose stretch ramps in the total analysis time
develops less of it in less of it; a creep law creeps less; a relaxation
relaxes less. Making a history finite that way and then reporting
"verified" says the conversion was checked against behaviour the experiment
no longer contained.

Measured on BodyForce-Growth-2Stages.for, whose source writes its own time
normalisation:

    TotalT = 1.0
    G11 = 1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
              + (G11St2-G11St1)*(TIME(2)+DTIME)/TotalT

so a run to total time 0.2 reaches a fifth of the growth its author
designed, and an agreement over it is an agreement near the initial state --
the part every build gets right.

Two questions, both measured on the FROZEN run rather than on a probe: did
the material do anything, and where the source declares a time scale of its
own, did the experiment reach far enough into it.
"""
import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import verify_store_in_abaqus as verify  # noqa: E402
from umat_oti.abaqus.manifest import uniaxial  # noqa: E402
from umat_oti.abaqus.time_scale import (ENOUGH_OF_THE_SCALE,  # noqa: E402
                                        covers, declared_scale)

GROWTH = """\
      SUBROUTINE UMAT(STRESS,STATEV)
      TotalT = 1.0
      G11 = 1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
      RETURN
      END
"""
NO_SCALE = "      SUBROUTINE UMAT(STRESS,STATEV)\n      RETURN\n      END\n"


# ---- the scale is read from the source, not assumed ----------------------
def test_a_source_that_normalises_its_clock_declares_a_scale():
    scale = declared_scale(GROWTH)
    assert scale.declared
    assert scale.name == "TOTALT" and scale.value == 1.0
    assert "TotalT = 1.0" in scale.evidence or "TotalT=1.0" in scale.evidence


def test_a_constant_nothing_divides_by_is_not_a_time_scale():
    assert not declared_scale("      TAU = 3.0\n      X = TAU * 2\n").declared


def test_a_division_by_something_never_fixed_is_not_one_either():
    assert not declared_scale("      Y = TIME(1)/WHATEVER\n").declared


def test_a_source_with_no_scale_says_so_rather_than_inventing_one():
    coverage = covers(NO_SCALE, [uniaxial(0.01, 10)])
    assert coverage.enough is True
    assert "declares no time scale of its own" in coverage.reason


# ---- and the experiment is measured against it ---------------------------
def test_a_run_that_reaches_far_enough_into_the_scale_is_enough():
    segments = [replace(uniaxial(0.01, 10), period=0.5)]
    coverage = covers(GROWTH, segments)
    assert coverage.fraction == 0.5
    assert coverage.enough is True


def test_a_run_that_barely_starts_the_clock_is_not():
    segments = [replace(uniaxial(0.01, 10), period=0.02)]
    coverage = covers(GROWTH, segments)
    assert coverage.fraction == 0.02
    assert coverage.enough is False
    assert "below the" in coverage.reason
    assert "near its initial state" in coverage.reason


def test_the_floor_is_a_floor_on_coverage_not_a_tolerance_on_an_answer():
    assert 0.0 < ENOUGH_OF_THE_SCALE < 1.0
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "umat_oti" / "abaqus" / "time_scale.py").read_text()
    assert "Not a tolerance on an answer" in source


# ---- and a verdict is gated on it ----------------------------------------
def _all_passed(**overrides):
    base = dict(material_found=True, support_ok=True, original_completed=True,
                transformed_completed=True, primal_agrees=True,
                tangent_verified=True)
    base.update(overrides)
    return verify.StageEvidence(**base)


def test_everything_agreeing_about_nothing_is_not_verified():
    assert verify.classify_stage(
        _all_passed(mechanically_informative=False)) == verify.NOT_INFORMATIVE


def test_everything_agreeing_about_something_is():
    assert verify.classify_stage(
        _all_passed(mechanically_informative=True)) == "verified"


def test_an_unmeasured_answer_does_not_withdraw_a_verdict_by_itself():
    """None means not established. The flag blocks on a measured False."""
    assert verify.classify_stage(_all_passed()) == "verified"


def test_the_new_state_is_ours_and_reaches_the_report_and_the_page():
    from umat_oti.abaqus.terminal_states import FROM_STAGE, INTERNAL, kind_of

    assert "experiment_not_informative" in INTERNAL
    assert kind_of(FROM_STAGE["experiment_not_informative"]) == "internal"
    gloss = (pathlib.Path(__file__).resolve().parents[1]
             / "src" / "umat_oti" / "app" / "corpus_tab.py").read_text()
    assert "experiment_not_informative" in gloss
    report = (pathlib.Path(__file__).resolve().parents[1]
              / "tools" / "corpus_report.py").read_text()
    assert "experiment_not_informative" in report


def test_the_measurement_reads_the_frozen_run_not_a_probe():
    tool = (pathlib.Path(__file__).resolve().parents[1]
            / "tools" / "verify_store_in_abaqus.py").read_text()
    block = tool[tool.index("def _is_informative("):]
    block = block[:block.index("\n\ndef ")]
    assert "detect_activation(list(history))" in block
    assert "time_scale.covers(" in block
    assert 'record["activation_on_the_frozen_run"]' in block
