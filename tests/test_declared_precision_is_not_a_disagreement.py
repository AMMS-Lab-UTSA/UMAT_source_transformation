"""Seven digits is not a different model.

``irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for`` line 22 reads

    real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)

and its stress update is ``stress = stress + D1.dstran + D2.stran - S`` with
``S`` holding the incoming stress. Fortran's default real is single precision
and an explicit ``REAL`` overrides the ``IMPLICIT REAL*8(A-H,O-Z)`` that
``aba_param.inc`` installs, so ``S`` truncates the previous stress to seven
digits and the subtraction leaves the truncation residue behind. The OTI type
is built over doubles, so the converted build does not truncate, and the two
stress histories differ by 1.106e-07 -- float32 epsilon.

Reported as a primal disagreement that reads as "the conversion computes
something else". Measured in Abaqus: the original with ``S`` alone widened to
``REAL*8`` -- ``S`` alone because ``S`` alone is what the transform promoted --
agrees with the converted build to 0.000e+00 at every component of all thirty
increments.

Widening every REAL in the unit is a different experiment and answers a
different question: ``D1`` is never promoted, so it stays single in the
converted build, and a control that widens it disagrees for a new reason.
Measured too: ``-r8`` over the whole unit left the control 9.786e-08 from the
converted build rather than at zero.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.precision import (narrow_declarations,  # noqa: E402
                                       promoted_names, survey, widen)

VISCOELASTIC = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     1 rpl,ddsddt,drplde,drpldt,
     2 stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     3 ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,
     4 celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv)
      integer k1, k2
      real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)
      S(1:ntens) = stress(1:ntens)
      return
      end
"""

CONVERTED = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     1 rpl,ddsddt,drplde,drpldt)
      include 'aba_param.inc'
      real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)
      TYPE(ONUMM6N1) :: DSTRAN_OTI(ntens)
      TYPE(ONUMM6N1) :: S_OTI(6)
      TYPE(ONUMM6N1) :: STRESS_OTI(ntens)
      return
      end
"""


def test_the_shadows_name_what_the_transform_promoted():
    assert promoted_names(CONVERTED) == ("DSTRAN", "S", "STRESS")


def test_an_array_spec_comma_is_not_a_separator():
    """``D1(6,6)`` is one name, not two."""
    found = narrow_declarations(VISCOELASTIC, ("D1", "D2", "D3"))
    assert len(found) == 1
    assert found[0].names == ("D1", "D2", "D3")
    assert found[0].all_names == ("E", "nu", "lambda", "mu", "S", "D1", "D2", "D3")


def test_only_the_promoted_narrow_names_are_widened():
    """The control answers one question, so it changes one thing."""
    finding = survey(VISCOELASTIC, CONVERTED)
    assert finding.widened == ("S",)
    assert "line(s) 10" in finding.reason
    control, changes = widen(VISCOELASTIC, finding)
    assert "REAL*8 S(6)" in control
    assert "real E, nu, lambda, mu, D1(6,6), D2(6,6), D3(6,6)" in control
    # and nothing else moved
    assert control.count("subroutine umat") == 1
    assert "S(1:ntens) = stress(1:ntens)" in control
    assert len(changes) == 1


def test_the_control_source_stays_fixed_form():
    """A statement that starts before column 7 is a label or a comment."""
    finding = survey(VISCOELASTIC, CONVERTED)
    control, _ = widen(VISCOELASTIC, finding)
    for line in control.splitlines():
        if not line.strip() or line[0] in "cC*!":
            continue
        assert line.startswith("      ") or line[5] not in " 0", line


def test_a_double_declaration_is_not_widened_again():
    """``REAL*8``, ``REAL(8)``, ``REAL(KIND=8)`` and DOUBLE PRECISION are
    already as wide as the OTI type, so none of them is a candidate."""
    source = VISCOELASTIC.replace(
        "      real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)",
        "      real*8 S(6)\n"
        "      real(8) E\n"
        "      real(kind=8) nu\n"
        "      double precision lambda")
    finding = survey(source, CONVERTED)
    assert finding.widened == ()
    assert "already double" in finding.reason


def test_kind_four_spellings_are_candidates():
    source = VISCOELASTIC.replace(
        "      real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)",
        "      real*4 S(6)")
    finding = survey(source, CONVERTED)
    assert finding.widened == ("S",)
    control, _ = widen(source, finding)
    assert "REAL*8 S(6)" in control

    source = VISCOELASTIC.replace(
        "      real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)",
        "      real(kind=4) :: S(6)")
    finding = survey(source, CONVERTED)
    assert finding.widened == ("S",)
    assert "REAL*8" in widen(source, finding)[0]


def test_a_source_with_no_shadow_asks_for_no_control():
    """No promoted name means no precision question to answer, and no Abaqus
    job is spent asking it."""
    finding = survey(VISCOELASTIC, "      subroutine umat()\n      end\n")
    assert not finding.explains_a_difference
    assert "no OTI shadow" in finding.reason


def test_free_form_declarations_are_widened_in_place():
    free = ("subroutine umat(stress)\n"
            "  real :: S(6), keep(3)\n"
            "  S = stress\n"
            "end subroutine\n")
    finding = survey(free, CONVERTED)
    assert finding.widened == ("S",)
    control, _ = widen(free, finding)
    assert "real :: keep(3)" in control
    assert "REAL*8 :: S(6)" in control
