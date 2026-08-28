"""What "constant" is allowed to mean, and what it costs when it is loose.

A variable declared constant is a variable the transform will keep real, and a
real variable on the stress path truncates the derivative in the ``REAL(...)``
cast the transform has to write around it. So the claim has to hold for every
assignment to the name, not for a convenient one.
"""

from __future__ import annotations

import json

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.core.roles import role_summary, suggest_variable_roles
from umat_oti.fortran.regions import AssignmentInfo, _constant_variables
from umat_oti.fortran.scanner import analyze_fortran_source
from umat_oti.services.transformation import TransformationOptions, run_transformation


def _assignment(lhs: str, *rhs: str, line: int = 1) -> AssignmentInfo:
    return AssignmentInfo(lhs=lhs, rhs_tokens=set(rhs), line_index=line,
                          line_numbers=(line,), text=f"{lhs} = ...")


def test_a_zeroed_work_array_later_filled_from_the_gradient_is_not_constant():
    """The reset-then-fill idiom must not certify the array as derivative-free.

    ``A1(K1,K2)=0.0`` in a reset loop and ``A1(1,1)=DFGRD1(1,1)/G11`` two
    statements later are both assignments to A1. Reading only the first is how
    a deformation-gradient-driven stress path was declared constant end to end.
    """
    constants = _constant_variables(
        [_assignment("A1"), _assignment("A1", "DFGRD1", "G11", line=2)],
        parameter_variables=set(), written_variables={"A1"},
        declaration_only_variables=set())
    assert "A1" not in constants


def test_constancy_does_not_propagate_through_a_wrongly_constant_array():
    """The cascade is the damage: one loose name takes the whole chain."""
    constants = _constant_variables(
        [_assignment("A1"), _assignment("A1", "DFGRD1", line=2),
         _assignment("BA1", "A1", line=3), _assignment("EG", "BA1", line=4)],
        parameter_variables=set(), written_variables={"A1", "BA1", "EG"},
        declaration_only_variables=set())
    assert not ({"A1", "BA1", "EG"} & constants)


def test_an_accumulator_seeded_from_dstran_is_not_constant():
    """``X = 0`` then ``X = X + DSTRAN(1)`` still reads the seed."""
    constants = _constant_variables(
        [_assignment("X"), _assignment("X", "X", "DSTRAN", line=2)],
        parameter_variables=set(), written_variables={"X"},
        declaration_only_variables=set())
    assert "X" not in constants


def test_a_genuinely_derived_constant_is_still_constant():
    """The other direction: tightening must not demote real setup data.

    Every assignment to EMOD and to C10 reads constants only, so both carry a
    zero derivative and keeping them real is correct and cheaper.
    """
    constants = _constant_variables(
        [_assignment("EMOD", "PROPS"), _assignment("C10", "EMOD", "FOUR", line=2)],
        parameter_variables={"FOUR"}, written_variables={"EMOD", "C10"},
        declaration_only_variables=set())
    assert {"EMOD", "C10"} <= constants


def test_a_value_delivered_by_a_call_and_then_scaled_is_not_constant():
    """The self-referential definition is not evidence about the value's origin.

    ``CALL GETSTRAIN(EPS, DSTRAN)`` followed by ``EPS = EPS * TWO`` leaves EPS
    with exactly one assignment, and everything that assignment reads besides
    EPS itself is constant. Judging it on that right-hand side certifies the
    variable the call had just seeded: subroutine outputs never appear as
    assignments, so there is nothing here to contradict it.
    """
    constants = _constant_variables(
        [_assignment("EPS", "EPS", "TWO")],
        parameter_variables={"TWO"}, written_variables={"EPS"},
        declaration_only_variables=set())
    assert "EPS" not in constants


def test_refusing_self_reference_costs_only_a_zero_derivative_part():
    """A genuinely constant accumulator stays hypercomplex, and that is fine.

    ``KOUNT = KOUNT + ONE`` carries no derivative, and this function still
    declines to say so. The name is promoted and carries a zero imaginary
    part -- arithmetic, not error -- whereas accepting it would have to accept
    the call-seeded case above too.
    """
    constants = _constant_variables(
        [_assignment("KOUNT", "KOUNT", "ONE")],
        parameter_variables={"ONE"}, written_variables={"KOUNT"},
        declaration_only_variables=set())
    assert "KOUNT" not in constants

def _transform(source_text: str, name: str, tmp_path):
    src = tmp_path / f"{name}.for"
    src.write_text(source_text, encoding="utf-8")
    config, finite = _build_contract(name, "auto", "STRESS", "DDSDDE", 6, 1, src)
    config_path = tmp_path / f"{name}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _ = run_transformation(config_path, tmp_path / f"{name}_out",
                                    TransformationOptions(compile_generated=False))
    return config, finite, summary


#: A finite-strain UMAT in the shape the discovered growth sources take: work
#: arrays zeroed in a reset loop, then filled from DFGRD1, then reduced to
#: STRESS. Nothing here is a model claim -- the arithmetic exists only to make
#: the dependency chain DFGRD1 -> A1 -> BA1 -> STRESS real.
RESET_THEN_FILL_UMAT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION A1(3,3), BA1(6)
      PARAMETER(ZERO=0.D0, ONE=1.D0, TWO=2.D0)
      EMOD=PROPS(1)
      DO K1=1, 3
        DO K2=1, 3
          A1(K1, K2)=0.0
        END DO
      END DO
      DO K1=1, 6
        BA1(K1)=0.0
      END DO
      A1(1, 1)=DFGRD1(1, 1)
      A1(2, 2)=DFGRD1(2, 2)
      A1(3, 3)=DFGRD1(3, 3)
      A1(1, 2)=DFGRD1(1, 2)
      A1(2, 1)=DFGRD1(2, 1)
      BA1(1)=A1(1, 1)*A1(1, 1)+A1(1, 2)*A1(1, 2)
      BA1(2)=A1(2, 1)*A1(2, 1)+A1(2, 2)*A1(2, 2)
      BA1(3)=A1(3, 3)*A1(3, 3)
      BA1(4)=A1(1, 1)*A1(2, 1)+A1(1, 2)*A1(2, 2)
      BA1(5)=ZERO
      BA1(6)=ZERO
      DO K1=1, NTENS
        STRESS(K1)=EMOD*(BA1(K1)-ONE)/TWO
      END DO
      DDSDDE(1, 1)=EMOD
      RETURN
      END
"""

#: The same interface and the same finite-strain kinematics -- the gradient is
#: still read, so the DFGRD1 seed is still emitted -- but the only statement
#: that reads it is the old tangent block the transform replaces. Nothing live
#: on the stress path consumes the seed, so every derivative really would be
#: structurally zero. This is the case the check exists for.
GRADIENT_ONLY_IN_OLD_TANGENT_UMAT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      PARAMETER(ZERO=0.D0, ONE=1.D0, TWO=2.D0)
      EMOD=PROPS(1)
      DO K1=1, NTENS
        STRESS(K1)=EMOD*ONE
      END DO
      DDSDDE(1, 1)=EMOD*DFGRD1(1, 1)
      RETURN
      END
"""


def _transform(source_text: str, name: str, tmp_path):
    src = tmp_path / f"{name}.for"
    src.write_text(source_text, encoding="utf-8")
    config, finite = _build_contract(name, "auto", "STRESS", "DDSDDE", 6, 1, src)
    config_path = tmp_path / f"{name}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _ = run_transformation(config_path, tmp_path / f"{name}_out",
                                    TransformationOptions(compile_generated=False))
    return config, finite, summary


def test_the_reset_idiom_leaves_the_gradient_on_the_promoted_path(tmp_path):
    src = tmp_path / "probe.for"
    src.write_text(RESET_THEN_FILL_UMAT, encoding="utf-8")
    analysis = analyze_fortran_source(src)
    summary = role_summary(suggest_variable_roles(analysis, RESET_THEN_FILL_UMAT))
    for name in ("A1", "BA1"):
        assert name in summary["promoted_variables"], summary
        assert name not in summary["constant_variables"], summary
    # EMOD reads PROPS and nothing else, and must stay real.
    assert "EMOD" in summary["constant_variables"], summary


def test_a_gradient_driven_stress_path_consumes_the_seed(tmp_path):
    config, finite, summary = _transform(RESET_THEN_FILL_UMAT, "consumes", tmp_path)
    assert finite is True
    assert config["transformation_settings"]["seed_dfgrd1"] is True
    assert summary["semantic_checks"]["stress_path_consumes_the_seed"] is True, summary["warnings"]
    assert summary["transform_success"] is True, summary["blockers"] + summary["warnings"]
    transformed = (tmp_path / "consumes_out").rglob("*_oti.for")
    text = "\n".join(path.read_text(encoding="utf-8") for path in transformed)
    # The failure this replaces: the gradient reached the work array only
    # through a cast that discarded every derivative it carried.
    assert "REAL(DFGRD1_OTI" not in text.replace(" ", "")
    assert "A1_OTI(1, 1)=DFGRD1_OTI(1, 1)" in text


def test_a_stress_path_that_never_reads_the_gradient_still_fails_the_check(tmp_path):
    """The check is not weakened: it still names a structurally zero transform."""
    _config, finite, summary = _transform(GRADIENT_ONLY_IN_OLD_TANGENT_UMAT, "ignores", tmp_path)
    assert finite is True
    assert summary["semantic_checks"]["stress_path_consumes_the_seed"] is False
    assert any("stress_path_consumes_the_seed" in warning
               for warning in summary["warnings"]), summary["warnings"]
    assert summary["transform_success"] is False
