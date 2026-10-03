"""A FORALL that only rearranges the old tangent is disabled with the old tangent.

matmodlab's umat_neohooke.f90 writes the upper triangle of its analytical
tangent and fills the lower one with

    forall(i=1:ntens,j=1:ntens,j<i) ddsdde(i,j) = ddsdde(j,i)

The output region the classifier found ended a line short, so the FORALL was
refused as an uncovered DDSDDE write (before that it was kept, and overwrote
the lower triangle of the extracted, unsymmetric, tangent). A FORALL or WHERE
write that names nothing but DDSDDE and its own indices, directly after an
output region and with no stress read of DDSDDE after it, is now joined to that
region and disabled with it.

Behavioural, against the author's routine compiled separately: primal
bit-identical; DDSDDE against central differences of the original at three step
sizes. The stress here has an unsymmetric tangent, so a FORALL left live would
fail the comparison. A FORALL that reads anything else is still refused.
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
  integer :: i, j
  real(8) :: e
  e = props(1)
  do i = 1, ntens
    stress(i) = stress(i) + e*dstran(i) + 30.0d0*e*dstran(1)*dstran(i)
  end do
  statev(1) = statev(1) + stress(1)

  ! old tangent, upper triangle
  ddsdde = 0.0d0
  ddsdde(1,1) = e
  ddsdde(1,2) = 0.5d0*e
  ddsdde(2,2) = e
  ddsdde(3,3) = e
  ddsdde(4,4) = e
  ddsdde(5,5) = e
  ddsdde(6,6) = e

  %(symmetrise)s
end subroutine umat
"""

SYMMETRISE = "forall(i=1:ntens,j=1:ntens,j<i) ddsdde(i,j) = ddsdde(j,i)"

RENAMES = [("subroutine umat(", "subroutine umatorig("),
           ("end subroutine umat\n", "end subroutine umatorig\n")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_symmetrising_forall_is_disabled_with_the_old_tangent(tmp_path):
    output = check_against_original(tmp_path, SOURCE % {"symmetrise": SYMMETRISE}, ".f90",
                                    RENAMES, ["1000.0d0"])
    emitted = next(output.glob("*_oti.f90")).read_text()
    assert "! OTIS-SKIP: forall(i=1:ntens,j=1:ntens,j<i)" in emitted


def test_a_forall_that_reads_anything_else_is_still_refused(tmp_path):
    other = "forall(i=1:ntens,j=1:ntens,j<i) ddsdde(i,j) = ddsdde(j,i) + 0.0d0*stress(1)"
    summary, code = transform(tmp_path, SOURCE % {"symmetrise": other}, ".f90")
    assert code != 0
    assert "DDSDDE assignment is not covered by an old tangent replacement region" in str(summary)
