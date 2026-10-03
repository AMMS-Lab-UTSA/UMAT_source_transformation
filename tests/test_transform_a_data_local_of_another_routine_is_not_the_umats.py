"""A DATA statement local to another routine does not block the UMAT's shadow of that name.

The DATA guard (a promoted name that starts from a DATA value would start its
shadow at zero) read every DATA statement in the file. damin225's
short-crack-propagation umat.f was refused for FACTOR: LimitRatioForDrag gives
its own local FACTOR a DATA value, while InitialGuessStress assigns an
unrelated local of the same name on the stress path. Only DATA statements
that can reach the selected routine's variables are read now -- its own, any
outside every routine, and those of a routine with a COMMON block. A DATA
value in the UMAT itself is still refused.

Behavioural, against the separately compiled original: primal bitwise, DDSDDE
against central differences at three step sizes.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original, transform

SOURCE = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
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
  real(8) :: factor%(umat_data)s
  integer :: i
  factor = props(1)*(1.0d0 + 3.0d0*dstran(1))
  do i = 1, ntens
    stress(i) = stress(i) + factor*dstran(i)
  end do
  statev(1) = statev(1) + stress(1)
  call limits(props(1), statev(2))
end subroutine umat

subroutine limits(e, cap)
  implicit none
  real(8) :: e, cap
  real(8) :: factor
  data factor /1.0d+10/
  cap = factor/e
end subroutine limits
"""

RENAMES = [("subroutine umat(", "subroutine umatorig("),
           ("end subroutine umat\n", "end subroutine umatorig\n"),
           ("limits(", "limitsorig("), ("subroutine limits\n", "subroutine limitsorig\n")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_data_value_local_to_another_routine_does_not_block_the_umat(tmp_path):
    check_against_original(tmp_path, SOURCE % {"umat_data": ""}, ".f90", RENAMES, ["1000.0d0"])


def test_a_data_value_in_the_umat_itself_is_still_refused(tmp_path):
    text = SOURCE % {"umat_data": "\n  data factor /2.0d0/"}
    summary, code = transform(tmp_path, text, ".f90")
    assert code != 0
    assert "FACTOR takes its starting value from a DATA statement" in str(summary)
