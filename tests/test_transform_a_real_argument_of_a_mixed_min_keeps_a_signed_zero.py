"""A REAL argument of a mixed MIN/MAX keeps the sign of a zero.

A MIN or MAX over hypercomplex and REAL arguments gives the REAL ones the OTI
type. That was ``((z) + 0.0D0*(anchor))``, borrowing the first hypercomplex
argument; 0.0*anchor has the sign of the anchor's real part, so MIN(G, Z) with
Z = -0.0 and G > 0 returned +0.0. It is now ``((z) - 0.0D0*OTI_E1)``, exact for
every value.

Behavioural, against the separately compiled original: STRESS and STATEV
bitwise (STATEV(2) holds the signed zero), DDSDDE against central differences
at h = 1e-4, 1e-5, 1e-6.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original

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
  real(8) :: g, z
  integer :: i
  z = -0.0d0
  do i = 1, ntens
    stress(i) = stress(i) + props(1)*dstran(i)*(1.0d0 + dstran(i))
  end do
  g = stress(1)
  statev(1) = statev(1) + stress(1)
  statev(2) = min(g, z)
end subroutine umat
"""

RENAMES = [("subroutine umat(", "subroutine umatorig("),
           ("end subroutine umat\n", "end subroutine umatorig\n")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_negative_zero_in_a_mixed_min_keeps_its_sign(tmp_path):
    output = check_against_original(tmp_path, SOURCE, ".f90", RENAMES, ["1000.0d0"])
    assert "((z) - 0.0D0*OTI_E1)" in next(output.glob("*_oti.f90")).read_text()
