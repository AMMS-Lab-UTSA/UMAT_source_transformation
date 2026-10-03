"""A DDSDDE write inside a lifted callee lands in DDSDDE_OTI, not in Abaqus's DDSDDE.

Seven corpus sources were refused with "DDSDDE assignment is not covered by an
old tangent replacement region" for assignments that sit in a routine the UMAT
calls: a dispatcher (``CALL UMAT_MAT1(STRESS, STATEV, DDSDDE, ...)``,
bessagroup veni_mix_model.f, JuliaFEM drucker_prager_plasticity.f90) or a
helper that builds an elastic stiffness the stress update then reads
(``CALL STIFFNESS(B, EMOD, DDSDDE)`` / ``STRE = STRE + DDSDDE*DSTRA``,
Duncan-Chang_EB, vishalsubbiah umatcode3.f). Those callees are on the stress
path, so they are lifted and the rewrite hands them DDSDDE_OTI: the old tangent
they build is a hypercomplex working value and the array Abaqus reads is written
by the extraction alone. The check now runs on the emitted text
(``_callee_ddsdde_writes_left_live``) and clears only writes that provably land
in a shadow.

Behavioural, against the author's routine compiled separately: primal
bit-identical; DDSDDE against central differences of the ORIGINAL at three step
sizes (local tangent at fixed incoming STRESS/STATEV, one increment). Both toys
leave a DIFFERENT matrix (a secant at the updated stress) in DDSDDE at the end,
so a write that leaked into the output would fail the tangent comparison.

A write the emitted code could still route into the real DDSDDE -- the
routine not lifted, its original reached after the seed, or the UMAT itself
naming the real array -- keeps the original refusal.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original

UMAT_HEAD = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
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
"""

STIFF = """
subroutine stiff(e, n, ddsdde)
  implicit none
  integer :: n, i
  real(8) :: e, ddsdde(n, n)
  ddsdde = 0.0d0
  do i = 1, n
    ddsdde(i, i) = e
    if (i .le. 3) ddsdde(i, mod(i, 3) + 1) = 0.3d0*e
  end do
end subroutine stiff
"""

# The UMAT reads the stiffness a helper wrote into DDSDDE, then calls the
# helper again with a stress-dependent modulus: the secant left in DDSDDE is
# not the tangent of the stress.
HELPER_STIFFNESS = UMAT_HEAD + """  real(8) :: emod
  integer :: i, j
  emod = props(1)*(1.0d0 + 0.1d0*statev(1))
  call stiff(emod, ntens, ddsdde)
  do i = 1, ntens
    do j = 1, ntens
      stress(i) = stress(i) + ddsdde(i, j)*dstran(j)
    end do
  end do
  stress(1) = stress(1) + 20.0d0*props(1)*dstran(1)**2
  emod = props(1)*(1.0d0 + 0.01d0*stress(1)**2)
  call stiff(emod, ntens, ddsdde)
  statev(1) = statev(1) + 0.1d0*stress(1)
  statev(2) = statev(2) + 0.2d0*stress(2)
end subroutine umat
""" + STIFF

# A dispatcher: the UMAT hands STRESS, STATEV and DDSDDE to a model routine
# that uses DDSDDE as its working stiffness and leaves a secant in it.
DISPATCHER = UMAT_HEAD + """  if (props(1) .gt. 0.0d0) then
    call model(stress, statev, ddsdde, dstran, props, ntens, nstatv)
  else
    call model(stress, statev, ddsdde, dstran, -props, ntens, nstatv)
  end if
end subroutine umat

subroutine model(stress, statev, ddsdde, dstran, props, ntens, nstatv)
  implicit none
  integer :: ntens, nstatv, i, j
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens), dstran(ntens), props(1)
  real(8) :: emod
  emod = props(1)*(1.0d0 + 0.1d0*statev(2))
  call stiff(emod, ntens, ddsdde)
  do i = 1, ntens
    do j = 1, ntens
      stress(i) = stress(i) + ddsdde(i, j)*dstran(j)
    end do
  end do
  stress(2) = stress(2) - 15.0d0*props(1)*dstran(2)*dstran(1)
  statev(2) = statev(2) + 0.05d0*stress(2)
  call stiff(props(1)*(2.0d0 + stress(1)**2), ntens, ddsdde)
end subroutine model
""" + STIFF

RENAMES = [("subroutine umat(", "subroutine umatorig("),
           ("end subroutine umat\n", "end subroutine umatorig\n"),
           ("stiff(", "stifforig("), ("subroutine stiff\n", "subroutine stifforig\n"),
           ("model(", "modelorig("), ("subroutine model\n", "subroutine modelorig\n")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_helper_built_stiffness_read_by_the_stress_update_transforms_and_agrees(tmp_path):
    output = check_against_original(tmp_path, HELPER_STIFFNESS, ".f90", RENAMES, ["1000.0d0"])
    emitted = next(output.glob("*_oti.f90")).read_text().upper()
    assert "CALL STIFF_OTI(EMOD_OTI, NTENS, DDSDDE_OTI)" in emitted
    # The first call reads nothing differentiated and may stay REAL ahead of
    # the seed block, whose copy-in carries its value into DDSDDE_OTI; after
    # the seed, only the lifted copy is called.
    body = emitted.split("END SUBROUTINE UMAT")[0].split("OTIS SEED INITIALIZATION")[1]
    assert "CALL STIFF(" not in body


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_dispatcher_whose_model_writes_ddsdde_transforms_and_agrees(tmp_path):
    output = check_against_original(tmp_path, DISPATCHER, ".f90", RENAMES, ["1000.0d0"])
    emitted = next(output.glob("*_oti.f90")).read_text().upper()
    assert "CALL MODEL_OTI(STRESS_OTI, STATEV_OTI, DDSDDE_OTI" in emitted

