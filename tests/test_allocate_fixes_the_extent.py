"""A deferred shape is not an unknown shape: the ALLOCATE states it.

``REAL(8), DIMENSION(:,:), ALLOCATABLE :: jac_inv`` carries no extent, and the
shadow this transformer writes needs one -- ``TYPE(ONUMM6N1) :: X_OTI(:,:)``
is not a declaration and ``DO OTI_HI = 1, :`` is not a loop. But the source
says the extent a few lines later, in ``allocate(jac_inv(nstatv, nstatv))``,
and reading it there is the same move this transformer already makes for a
declared DIMENSION.

Two conditions have to hold before the bound may be used, and both are about
whether the declaration would be true rather than merely well-formed. The
extent must be unambiguous, and every name in it must already have a value
when the routine is entered -- a bound computed in the body would be read
before it is assigned and would size the shadow from whatever the memory held.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _shapes_declared_in_selected_routine, allocate_fixed_shape,
)


def _parse(text: str):
    from umat_oti.fortran.parser import (  # noqa: PLC0415
        ParsedFortranSource, logical_lines_from_text, parse_subroutines,
    )
    lines = logical_lines_from_text(text, "free")
    return ParsedFortranSource(Path("u.f90"), "free", text, lines,
                               parse_subroutines(lines))


DUMMY_BOUND = """subroutine umat(stress, statev, nstatv)
  real(8), dimension(:,:), allocatable :: jac_inv
  allocate(jac_inv(nstatv, nstatv))
end subroutine umat
"""

PARAMETER_BOUND = """subroutine umat(stress, statev, nstatv)
  integer, parameter :: numTens = 1
  integer, parameter :: numMaxwell = 3
  real(8), dimension(:,:), allocatable :: tau
  allocate(tau(numMaxwell, numTens))
end subroutine umat
"""

LOCAL_BOUND = """subroutine umat(stress, statev, nstatv)
  integer :: nvar
  real(8), dimension(:,:), allocatable :: jac_inv
  nvar = nstatv + 6
  allocate(jac_inv(nvar, nvar))
end subroutine umat
"""


class TestReadingTheBound:
    def test_a_dummy_argument_bound_is_usable(self):
        assert allocate_fixed_shape(DUMMY_BOUND, "JAC_INV",
                                    _parse(DUMMY_BOUND), "UMAT") == "nstatv, nstatv"

    def test_a_named_constant_bound_is_usable(self):
        assert allocate_fixed_shape(PARAMETER_BOUND, "TAU",
                                    _parse(PARAMETER_BOUND), "UMAT") == "numMaxwell, numTens"

    def test_a_bound_computed_in_the_body_is_refused(self):
        # nvar has no value where declarations are written.
        assert allocate_fixed_shape(LOCAL_BOUND, "JAC_INV",
                                    _parse(LOCAL_BOUND), "UMAT") == ""

    def test_two_different_extents_are_refused(self):
        text = DUMMY_BOUND.replace(
            "  allocate(jac_inv(nstatv, nstatv))",
            "  if (nstatv > 3) then\n    allocate(jac_inv(nstatv, nstatv))\n"
            "  else\n    allocate(jac_inv(3, 3))\n  end if")
        assert allocate_fixed_shape(text, "JAC_INV", _parse(text), "UMAT") == ""

    def test_the_same_extent_written_twice_is_not_ambiguous(self):
        text = DUMMY_BOUND.replace(
            "  allocate(jac_inv(nstatv, nstatv))",
            "  allocate(jac_inv(nstatv, nstatv))\n  allocate(jac_inv(nstatv,nstatv))")
        assert allocate_fixed_shape(text, "JAC_INV", _parse(text), "UMAT") == "nstatv, nstatv"

    def test_a_commented_out_allocate_is_not_an_allocate(self):
        text = DUMMY_BOUND.replace(
            "  allocate(jac_inv(nstatv, nstatv))",
            "  allocate(jac_inv(nstatv, nstatv))  ! ok\n! allocate(jac_inv(9, 9))")
        assert allocate_fixed_shape(text, "JAC_INV", _parse(text), "UMAT") == "nstatv, nstatv"

    def test_no_allocate_at_all_is_refused(self):
        text = DUMMY_BOUND.replace("  allocate(jac_inv(nstatv, nstatv))\n", "")
        assert allocate_fixed_shape(text, "JAC_INV", _parse(text), "UMAT") == ""

    def test_a_deallocate_is_not_an_allocate(self):
        text = DUMMY_BOUND.replace("  allocate(jac_inv(nstatv, nstatv))",
                                   "  deallocate(jac_inv)")
        assert allocate_fixed_shape(text, "JAC_INV", _parse(text), "UMAT") == ""


class TestTheShapeTheEmitterSees:
    def test_the_resolved_extent_replaces_the_deferred_one(self):
        # The readiness check and the emitter must read one answer. Resolving
        # in the check alone left the emitter writing X_OTI(:,:).
        shapes = _shapes_declared_in_selected_routine(
            _parse(DUMMY_BOUND), "UMAT", {})
        assert shapes["JAC_INV"] == "nstatv, nstatv"

    def test_an_unresolvable_one_stays_deferred(self):
        shapes = _shapes_declared_in_selected_routine(
            _parse(LOCAL_BOUND), "UMAT", {})
        assert ":" in shapes["JAC_INV"]

    def test_an_ordinary_declared_shape_is_untouched(self):
        text = "subroutine umat(stress, ntens)\n  real(8) :: work(ntens, 3)\nend subroutine umat\n"
        shapes = _shapes_declared_in_selected_routine(_parse(text), "UMAT", {})
        assert shapes["WORK"] == "ntens, 3"
