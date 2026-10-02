"""A ``!`` inside a character literal does not hide a free-form continuation.

The stress-path check joins a CALL with its continuation lines (a seed passed
on the second line of the call). Free form marks the continuation with a
trailing ``&``, and the comment was split off at the first ``!`` -- also the
one in ``'a!b'``, so ``call hstr2(e, 'a!b', &`` read as complete, the seed on
the next line went unseen, and a correct transform was refused for a zero
tangent (Vera B5 toy b3). Behavioural: transforms; primal bit-identical to the
author's routine, DDSDDE against central differences of it.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original  # noqa: I001

UMAT = """subroutine umat(stress,statev,ddsdde,sse,spd,scd,rpl,ddsddt,drplde,drpldt, &
  stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,ndi,nshr,ntens,nstatv, &
  props,nprops,coords,drot,pnewdt,celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,jstep,kinc)
  implicit none
  character(len=80) :: cmname
  integer :: ndi,nshr,ntens,nstatv,nprops,noel,npt,layer,kspt,jstep(4),kinc
  real(8) :: stress(ntens),statev(nstatv),ddsdde(ntens,ntens),ddsddt(ntens),drplde(ntens), &
    stran(ntens),dstran(ntens),time(2),predef(1),dpred(1),props(nprops),coords(3),drot(3,3), &
    dfgrd0(3,3),dfgrd1(3,3),sse,spd,scd,rpl,drpldt,dtime,temp,dtemp,pnewdt,celent
  real(8) :: e
  e = props(1)
  call hstr2(e, 'a!b', &
     dstran, stress, ddsdde, ntens)
end subroutine umat

subroutine hstr2(e, tag, de, s, d, n)
  implicit none
  integer :: n, i
  character(len=*) :: tag
  real(8) :: e, de(n), s(n), d(n,n)
  do i = 1, n
    s(i) = s(i) + e*(2.d0*de(i) + 0.7d2*de(i)**2)
  end do
  d = 0.d0
  do i = 1, n
    d(i,i) = 2.d0*e
  end do
end subroutine hstr2
"""

RENAMES = [("subroutine umat(", "subroutine umatorig("), ("call hstr2(", "call hstr2orig("),
           ("subroutine hstr2(", "subroutine hstr2orig("), ("end subroutine hstr2", "end subroutine hstr2orig"),
           ("end subroutine umat", "end subroutine umatorig")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_continued_call_with_a_bang_in_a_string_carries_the_seed(tmp_path):
    check_against_original(tmp_path, UMAT, ".f90", RENAMES, ["1000.0d0"])
