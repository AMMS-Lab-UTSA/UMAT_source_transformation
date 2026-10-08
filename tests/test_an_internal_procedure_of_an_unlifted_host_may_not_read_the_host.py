"""Internal procedures are lifted as external ones; reading the host's variables is refused.

The lifter types and declares each procedure from its own text, so an internal
procedure that reads a host variable by host association would get an
uninitialised local of the same name in its lifted copy. The refusal for that
ran only when the HOST was lifted; the selected UMAT is never lifted, so a
UMAT hosting internal procedures that read its variables was transformed into a
wrong program with nothing to show for it. A second gap: the parser ends a
host at the first END SUBROUTINE, so internal SUBROUTINES after the first were
never seen by the check even for a lifted host.

Rule (B20 RULES.md R11, detector): the host-association check also runs for an
unlifted host, over the host's whole text (its true END, counting nested units).
Canaries: an internal function that reads only its arguments is still lifted;
the true END of a host with internal subroutines is found.
"""
import pytest

from _b20_support import transform_text
from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.fortran.symbols import find_routine
from umat_oti.transform.helper_lifting import HelperLiftingError, _true_last_line

UMAT = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
    stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, ndi, nshr, ntens, nstatv, &
    props, nprops, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  implicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc, i, j
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens,ntens), sse, spd, scd, rpl, ddsddt(ntens)
  real(8) :: drplde(ntens), drpldt, stran(ntens), dstran(ntens), time(2), dtime, temp, dtemp
  real(8) :: predef(1), dpred(1), props(nprops), coords(3), drot(3,3), pnewdt, celent
  real(8) :: dfgrd0(3,3), dfgrd1(3,3)
  real(8) :: emod, d(6)
  emod = props(1)
  d = dstran
  d = twice(d)
  d = scale_by_modulus(d, emod)
  do i = 1, ntens
    stress(i) = stress(i) + d(i)*(1.0d0 + d(1)**2)
  end do
  ddsdde = 0.0d0
  do i = 1, ntens
    ddsdde(i,i) = emod
  end do
contains
  function twice(x) result(y)
    real(8) :: x(6), y(6)
    y = 2.0d0*x
  end function twice
  function scale_by_modulus(x, modulus) result(y)
    real(8) :: x(6), y(6), modulus
    y = x*%(MODULUS)s
  end function scale_by_modulus
end subroutine umat
"""


def test_an_internal_function_that_reads_only_its_arguments_is_lifted(tmp_path):
    report = transform_text(tmp_path, UMAT % {"MODULUS": "modulus"}, ".f90")
    assert report["transform_success"], report.get("blockers")


def test_canary_an_internal_function_that_reads_a_host_variable_is_refused(tmp_path):
    with pytest.raises(HelperLiftingError) as refusal:
        transform_text(tmp_path, UMAT % {"MODULUS": "emod"}, ".f90")
    message = str(refusal.value)
    assert "SCALE_BY_MODULUS" in message and "EMOD" in message and "host" in message


def test_the_true_end_of_a_host_with_internal_subroutines_is_found(tmp_path):
    text = UMAT.replace("function twice(x) result(y)", "subroutine twice(x)").replace(
        "end function twice", "end subroutine twice").replace("real(8) :: x(6), y(6)\n    y = 2.0d0*x",
                                                            "real(8) :: x(6)\n    x = 2.0d0*x") % {"MODULUS": "modulus"}
    path = tmp_path / "m.f90"
    path.write_text(text)
    parsed = parse_fortran_file(path)
    host = find_routine(parsed, "UMAT")
    lines = parsed.text.splitlines()
    last = _true_last_line(lines, parsed.form, host)
    assert lines[last - 1].strip() == "end subroutine umat"
    assert host.lines[-1].line_numbers[-1] < last      # the parser stopped earlier
