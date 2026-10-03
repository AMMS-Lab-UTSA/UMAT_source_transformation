"""A value handed to a lifted helper's hypercomplex dummy is passed as a hypercomplex value.

``real_arguments_into_oti_helper_dummies`` skipped every actual that is not a
plain name -- "a literal or an expression opening with one ... the compiler
will say so". It does not: the lifted helpers are external subprograms compiled
from another file, so

    CALL SCALE_OTI(2.0d0*props(1), DSTRAN_OTI(1), Y_OTI)

against ``TYPE(ONUMM6N1) :: A`` compiles and links without a diagnostic. The
callee reads the real part correctly and the six derivative parts from whatever
follows the temporary, so the primal agrees bit for bit and the tangent is
wrong. Measured on the toy below before the fix: DDSDDE(1,2) came out
312.0898 against a finite-difference 312.0000.

A value actual (anything that does not designate a variable) cannot be written
by the callee, so the emitter now passes ``(value) - 0.0D0*OTI_E1``: the same
real part, zero derivative parts. The leak check, which skipped such actuals,
now reads them too, so one the emitter could not rewrite is refused by name.
An expression that names a shadow is hypercomplex already and is left alone.

Behavioural, against the separately compiled original: primal bitwise, DDSDDE
against central differences at three step sizes.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original, transform

HEAD = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, &
                ndi, nshr, ntens, nstatv, props, nprops, coords, drot, pnewdt, &
                celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  implicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens), sse, spd, scd, rpl
  real(8) :: ddsddt(ntens), drplde(ntens), drpldt, stran(ntens), dstran(ntens)
  real(8) :: time(2), dtime, temp, dtemp, predef(1), dpred(1), props(nprops)
  real(8) :: coords(3), drot(3, 3), pnewdt, celent, dfgrd0(3, 3), dfgrd1(3, 3)
  real(8) :: y(6), g
  integer :: i
  g = props(1)*(1.0d0 + dstran(2))
  do i = 1, ntens
    call scale(%(first)s, dstran(i), y(i))
    stress(i) = stress(i) + y(i) + props(1)*dstran(mod(i, 6) + 1)
  end do
  statev(1) = statev(1) + stress(1)
end subroutine umat

subroutine scale(a, x, b)
  implicit none
  real(8) :: a, x, b
  b = a*x*(1.0d0 + x)
end subroutine scale
"""

RENAMES = [("subroutine umat(", "subroutine umatorig("),
           ("end subroutine umat\n", "end subroutine umatorig\n"),
           ("scale(", "scaleorig("), ("subroutine scale\n", "subroutine scaleorig\n")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("actual", ["2.0d0*props(1)", "1.0d3", "-1.0d3"])
def test_a_value_at_a_hypercomplex_dummy_is_passed_as_a_hypercomplex_value(tmp_path, actual):
    output = check_against_original(tmp_path, HEAD % {"first": actual}, ".f90", RENAMES, ["1000.0d0"])
    emitted = next(output.glob("*_oti.f90")).read_text()
    assert f"({actual}) - 0.0D0*OTI_E1" in emitted


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_an_expression_naming_a_shadow_still_transforms_and_agrees(tmp_path):
    check_against_original(tmp_path, HEAD % {"first": "g*2.0d0"}, ".f90", RENAMES, ["1000.0d0"])


def test_the_leak_check_reads_value_actuals():
    from umat_oti.transform.source_transform import real_arguments_into_oti_helper_dummies

    helper = ("subroutine SCALE_OTI(a, x, b)\n  use otim6n1\n"
              "  TYPE(ONUMM6N1) :: a, x, b\n  b = a*x\nend subroutine SCALE_OTI\n")
    umat = ("subroutine umat(x)\n  TYPE(ONUMM6N1) :: X_OTI, B_OTI\n"
            "  call SCALE_OTI(2.0d0*props(1), X_OTI, B_OTI)\nend subroutine umat\n")
    found = real_arguments_into_oti_helper_dummies(umat, "free", helper, "ONUMM6N1")
    assert ("SCALE_OTI", "2.0d0*props(1)", "A") in found


NESTED = HEAD.replace("""subroutine scale(a, x, b)
  implicit none
  real(8) :: a, x, b
  b = a*x*(1.0d0 + x)
end subroutine scale""", """subroutine scale(a, x, b)
  implicit none
  real(8) :: a, x, b
  call inner(a, 1.5d0, x, b)
end subroutine scale

subroutine inner(a, c, x, b)
  implicit none
  real(8) :: a, c, x, b
  b = c*a*x*(1.0d0 + x)
end subroutine inner""")


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_literal_from_one_lifted_helper_to_another_is_passed_as_a_hypercomplex_value(tmp_path):
    """Before: ``call INNER_OTI(a, 1.5d0, x, b)`` -- the tangent came out ~1e-307."""
    renames = RENAMES + [("inner(", "innerorig("), ("subroutine inner\n", "subroutine innerorig\n")]
    output = check_against_original(tmp_path, NESTED % {"first": "g*2.0d0"}, ".f90", renames, ["1000.0d0"])
    assert "(1.5d0) - 0.0D0*E1" in (output / "umat_oti_helpers.f90").read_text()



@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_negative_zero_value_actual_keeps_its_sign(tmp_path):
    """``(-0.0d0) + 0.0D0*E1`` has real part +0.0; the emitted wrap must keep -0.0 (Vera, B8 R1).

    Checked on the emitted wrap itself, compiled against the generated OTI
    module, because the sign of a zero is what changes and no arithmetic
    downstream of a stress update shows it reliably (the OTI SIGN reads
    B < 0, which is false for -0.0).
    """
    import subprocess

    summary, code = transform(tmp_path, HEAD % {"first": "-0.0d0"}, ".f90")
    assert code == 0, summary
    out = tmp_path / "out"
    emitted = next(out.glob("*_oti.f90")).read_text()
    # The first actual of the emitted call, exactly as the emitter wrote it
    # (Vera, B8 re-review: a hard-coded copy would test the test).
    import re

    from umat_oti.fortran.parser import split_top_level

    call = re.search(r"call\s+SCALE_OTI\s*\((.*)\)\s*$", emitted, re.IGNORECASE | re.MULTILINE)
    assert call, emitted
    wrap = split_top_level(call.group(1))[0].strip()
    assert "-0.0d0" in wrap and "OTI_E1" in wrap
    (out / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    subprocess.run(["bash", "compile_hint.sh"], cwd=out, check=True, capture_output=True, text=True)
    (out / "zero.f90").write_text(
        "program zero\n  use otim6n1, OTI_E1 => E1\n  type(ONUMM6N1) :: z\n"
        f"  z = {wrap}\n  print *, sign(1.0d0, z%R), z%E1\nend program zero\n")
    subprocess.run(["gfortran", "-I.", "zero.f90", "otim6n1.o", "master_parameters.o", "real_utils.o",
                    "-o", "zero"], cwd=out, check=True, capture_output=True, text=True)
    sign, derivative = map(float, subprocess.run(["./zero"], cwd=out, check=True, capture_output=True,
                                                 text=True).stdout.split())
    assert sign == -1.0 and derivative == 0.0
