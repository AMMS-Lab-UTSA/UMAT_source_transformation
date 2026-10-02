"""An INTERFACE block in the UMAT, and PRESENT() in a lifted helper.

MohrCoulombAbaqus.for (poroMechanicalFoam, concrete/geomaterial) declares
explicit interfaces for the routines its UMAT calls, indented by a TAB, and its
helpers test optional arguments with ``if (present(Dinv))``. Three defects
stood between it and a build:

* the first statement inside the interface body read as the UMAT's first
  executable statement, so the shadow declarations were written INSIDE the
  INTERFACE block ("Unexpected data declaration statement in INTERFACE");
* the interface body's dummies -- ``D(nsigma,nsigma)``, ``Sigma(nsigma)`` --
  were read as this routine's variables, so the UMAT declared
  ``D_OTI(nsigma, nsigma)`` and ``SIGMA_OTI(nsigma)`` with a bound that does
  not exist there;
* under ``IMPLICIT TYPE(ONUMM6N1) (A-H,O-Z)`` the lifter took PRESENT for an
  implicitly hypercomplex name and wrote ``IF (REAL(present(Dinv)))``.

Behavioural: the transformed UMAT is compiled and run beside the author's
routine (own object); primal bit-identical, DDSDDE against central differences
of the original.

A call that OMITS the optional argument is refused: the lifted UPDATE_OTI is an
external subprogram with no explicit interface (the source's INTERFACE block
describes the real UPDATE), and its PRESENT() would read the stack.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original

SOURCE = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, &
                ndi, nshr, ntens, nstatv, props, nprops, coords, drot, pnewdt, &
                celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
\timplicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens), sse, spd, scd, rpl
  real(8) :: ddsddt(ntens), drplde(ntens), drpldt, stran(ntens), dstran(ntens)
  real(8) :: time(2), dtime, temp, dtemp, predef(1), dpred(1), props(nprops)
  real(8) :: coords(3), drot(3, 3), pnewdt, celent, dfgrd0(3, 3), dfgrd1(3, 3)
  real(8) :: d(ntens, ntens), dinv(ntens, ntens), sig(ntens), e
\tinterface
\t\tsubroutine update(sigma, nsigma, e, deps, d, dinv)
\t\t\tinteger, intent(in) :: nsigma
\t\t\treal(8), intent(inout) :: sigma(nsigma)
\t\t\treal(8), intent(in) :: e, deps(nsigma)
\t\t\treal(8), intent(out) :: d(nsigma, nsigma)
\t\t\treal(8), intent(out), optional :: dinv(nsigma, nsigma)
\t\tend subroutine update
\tend interface
  e = props(1)
  sig = stress
  call update(sig, ntens, e, dstran, d, dinv)
%(second_call)s  stress = sig
  statev(1) = statev(1) + dinv(1, 1)*sig(1)
  ddsdde = d
end subroutine umat

subroutine update(sigma, nsigma, e, deps, d, dinv)
  implicit real(8) (a-h, o-z)
  integer, intent(in) :: nsigma
  real(8), intent(inout) :: sigma(nsigma)
  real(8), intent(in) :: e, deps(nsigma)
  real(8), intent(out) :: d(nsigma, nsigma)
  real(8), intent(out), optional :: dinv(nsigma, nsigma)
  integer :: i
  d = 0.0d0
  do i = 1, nsigma
    d(i, i) = e*(1.0d0 + 0.01d0*sigma(i)**2)
    sigma(i) = sigma(i) + d(i, i)*deps(i)*0.5d0
  end do
  if (present(dinv)) then
    dinv = 0.0d0
    do i = 1, nsigma
      dinv(i, i) = 1.0d0/d(i, i)
    end do
  end if
end subroutine update
"""

RENAMES = [("subroutine umat(", "subroutine umatorig("), ("end subroutine umat\n", "end subroutine umatorig\n"),
           ("update", "updateorig")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_umat_with_an_interface_block_and_present_builds_and_agrees(tmp_path):
    output = check_against_original(tmp_path, SOURCE % {"second_call": ""}, ".f90", RENAMES, ["50.0d0"])
    emitted = next(output.glob("*_oti.f90")).read_text().lower()
    block = emitted[emitted.index("interface"):emitted.index("end interface")]
    assert "_oti" not in block  # nothing of the transform was written inside it
    assert "nsigma" not in emitted.split("interface")[0]  # no shadow sized by another routine's dummy
    assert "real(present" not in (output / "umat_oti_helpers.f90").read_text().lower()


def test_a_call_that_omits_an_optional_argument_of_a_lifted_helper_is_refused(tmp_path):
    from _transform_vs_original import transform
    from umat_oti.transform.helper_lifting import HelperLiftingError

    text = SOURCE % {"second_call": "  call update(sig, ntens, e, dstran, d)\n"}
    with pytest.raises(HelperLiftingError) as refusal:
        transform(tmp_path, text, ".f90")
    assert "OPTIONAL" in str(refusal.value) and "UPDATE" in str(refusal.value)
