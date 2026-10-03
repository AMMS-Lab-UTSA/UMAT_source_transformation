"""A shadow is sized by the selected routine's own declaration, not by a helper's.

The scanner keeps one row per NAME for the whole file, so a UMAT that declares
``eij(ntens)`` beside a helper that takes a scalar dummy ``eij`` had the scalar
in its table, and the transform refused with "Promoted variable EIJ is indexed
in a stress region but has no confirmed shape" (marioruiarruda's Hashin_2D and
Tsai-Wu_2D UMATs, both refused for EIJ and SIJE). The selected routine's
declaration now decides the extent of its shadows.

Behavioural, against the author's routine compiled separately: primal
bit-identical; DDSDDE against central differences of the original at three step
sizes (local tangent, fixed incoming STRESS/STATEV, one increment).
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
  real(8) :: eij(ntens), sij(ntens)
  integer :: i
  do i = 1, ntens
    eij(i) = stran(i) + dstran(i)
  end do
  do i = 1, ntens
    call act(props(1), eij(i), eij(mod(i, 6) + 1), sij(i))
    stress(i) = stress(i) + sij(i)
  end do
  statev(1) = statev(1) + sij(1)
end subroutine umat

subroutine act(e, eij, ekl, sij)
  implicit none
  real(8), intent(in) :: e, eij, ekl
  real(8), intent(out) :: sij
  sij = e*(eij + 0.3d0*ekl + 5.0d0*eij*ekl)
end subroutine act
"""

RENAMES = [("subroutine umat(", "subroutine umatorig("),
           ("end subroutine umat\n", "end subroutine umatorig\n"),
           ("act(", "actorig("), ("subroutine act\n", "subroutine actorig\n")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_an_array_a_helper_takes_as_a_scalar_dummy_keeps_the_umats_extent(tmp_path):
    output = check_against_original(tmp_path, SOURCE, ".f90", RENAMES, ["1000.0d0"])
    emitted = next(output.glob("*_oti.f90")).read_text().upper()
    assert "EIJ_OTI(NTENS)" in emitted and "SIJ_OTI(NTENS)" in emitted
