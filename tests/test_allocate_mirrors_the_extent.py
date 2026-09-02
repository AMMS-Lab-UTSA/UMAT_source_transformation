"""When the bound cannot be declared, the ALLOCATE can be mirrored.

``allocate_fixed_shape`` reads the extent out of the source's own ALLOCATE and
writes it into the shadow's declaration -- but only when every name in the
bound already has a value where declarations are written. Seven crystal-
plasticity sources fail exactly that condition: ``allocate(jac_inv(nvar,
nvar))`` after ``call checkinput(...)`` sets nvar, ``ALLOCATE(STAT_VAR(NDIM6))``
after the routine has computed NDIM6 into a COMMON block.

The extent is still stated, just not where a declaration could use it. So the
shadow is declared ALLOCATABLE and given the extent where the source gives its
own array one: an ALLOCATE written immediately after the source's, sized from
the array itself rather than from the author's expression re-evaluated
somewhere else, and zeroed there rather than in the seed block, which runs
before there are any elements to zero.

What must NOT happen is a mirror that disagrees with the allocation it
mirrors. An ALLOCATE this reader cannot take apart -- one sharing its line
with another statement, one written with a type-spec -- would leave the shadow
sized by one allocation and the array by another, so every candidate such a
statement mentions is refused instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _declaration_lines, _initialization_lines, _mirrored_allocation_lines,
    deferred_shadow_allocations,
)


def _parse(text: str, form: str = "free"):
    from umat_oti.fortran.parser import (  # noqa: PLC0415
        ParsedFortranSource, logical_lines_from_text, parse_subroutines,
    )
    lines = logical_lines_from_text(text, form)
    suffix = "u.f90" if form == "free" else "u.for"
    return ParsedFortranSource(Path(suffix), form, text, lines,
                               parse_subroutines(lines))


LOCAL_BOUND = """subroutine umat(stress, statev, nstatv)
  integer :: nvar
  real(8), dimension(:,:), allocatable :: jac_inv
  call checkinput(nstatv, nvar)
  allocate(jac_inv(nvar, nvar))
  stress = jac_inv(1,1)
end subroutine umat
"""

MULTI_ITEM = """subroutine umat(stress, statev, nstatv)
  integer :: nvar
  real(8), dimension(:), allocatable :: r0, x0, statevnew
  call checkinput(nstatv, nvar)
  allocate(r0(nvar), statevnew(nstatv), x0(nvar))
end subroutine umat
"""

DUMMY_BOUND = """subroutine umat(stress, statev, nstatv)
  real(8), dimension(:,:), allocatable :: jac_inv
  allocate(jac_inv(nstatv, nstatv))
end subroutine umat
"""


class TestWhichNamesMayBeMirrored:
    def test_a_bound_computed_in_the_body_is_mirrored(self):
        parsed = _parse(LOCAL_BOUND)
        mirrored = deferred_shadow_allocations(LOCAL_BOUND, parsed, "UMAT")
        assert set(mirrored) == {"JAC_INV"}
        assert mirrored["JAC_INV"][0].rank == 2

    def test_every_name_in_a_multi_item_allocate_is_read(self):
        # Reading only the first item said nothing about the other two, and
        # two of the three names stayed blocked with their extent in plain
        # sight one comma to the right.
        parsed = _parse(MULTI_ITEM)
        mirrored = deferred_shadow_allocations(MULTI_ITEM, parsed, "UMAT")
        assert set(mirrored) == {"R0", "X0", "STATEVNEW"}

    def test_a_bound_a_declaration_may_use_is_left_to_the_declaration(self):
        # allocate_fixed_shape already gives this one a fixed-size shadow.
        # Offering both would let the check and the emitter disagree.
        parsed = _parse(DUMMY_BOUND)
        assert deferred_shadow_allocations(DUMMY_BOUND, parsed, "UMAT") == {}

    def test_a_name_never_allocated_is_refused(self):
        text = LOCAL_BOUND.replace("  allocate(jac_inv(nvar, nvar))\n", "")
        assert deferred_shadow_allocations(text, _parse(text), "UMAT") == {}

    def test_an_allocatable_dummy_argument_is_refused(self):
        text = """subroutine umat(stress, statev, work)
  real(8), dimension(:), allocatable :: work
  allocate(work(6))
end subroutine umat
"""
        assert deferred_shadow_allocations(text, _parse(text), "UMAT") == {}

    def test_an_array_allocated_in_another_routine_is_refused(self):
        text = LOCAL_BOUND.replace("  allocate(jac_inv(nvar, nvar))\n", "") + """
subroutine setup(jac_inv, nvar)
  real(8), dimension(:,:), allocatable :: jac_inv
  allocate(jac_inv(nvar, nvar))
end subroutine setup
"""
        assert deferred_shadow_allocations(text, _parse(text), "UMAT") == {}

    def test_a_pointer_is_not_an_allocatable(self):
        text = LOCAL_BOUND.replace("allocatable :: jac_inv", "pointer :: jac_inv")
        assert deferred_shadow_allocations(text, _parse(text), "UMAT") == {}

    def test_a_second_allocate_this_reader_cannot_read_refuses_the_name(self):
        # "allocate(tau(nslip)); tau = 0.0" is an allocation too. Mirroring the
        # readable site alone would size the shadow from one allocation and the
        # array from another.
        text = LOCAL_BOUND.replace(
            "  allocate(jac_inv(nvar, nvar))",
            "  allocate(jac_inv(nvar, nvar))\n"
            "  if (nvar > 3) then\n"
            "    deallocate(jac_inv); allocate(jac_inv(3, 3))\n"
            "  end if")
        assert deferred_shadow_allocations(text, _parse(text), "UMAT") == {}

    def test_a_rank_the_declaration_does_not_have_refuses_the_name(self):
        text = LOCAL_BOUND.replace("allocate(jac_inv(nvar, nvar))",
                                   "allocate(jac_inv(nvar))")
        assert deferred_shadow_allocations(text, _parse(text), "UMAT") == {}

    def test_two_sites_with_different_extents_are_both_mirrored(self):
        # Each mirror takes the extent of the allocation it follows, so a
        # source that reallocates to a new size is followed, not refused.
        text = LOCAL_BOUND.replace(
            "  allocate(jac_inv(nvar, nvar))",
            "  allocate(jac_inv(nvar, nvar))\n"
            "  deallocate(jac_inv)\n"
            "  allocate(jac_inv(nvar+1, nvar+1))")
        mirrored = deferred_shadow_allocations(text, _parse(text), "UMAT")
        assert len(mirrored["JAC_INV"]) == 2


class TestWhatIsWrittenBesideTheAllocate:
    def test_the_shadow_is_sized_from_the_array_it_shadows(self):
        parsed = _parse(LOCAL_BOUND)
        site = deferred_shadow_allocations(LOCAL_BOUND, parsed, "UMAT")["JAC_INV"][0]
        emitted = "\n".join(_mirrored_allocation_lines("free", "ONUMM6N1", site))
        assert ("ALLOCATE(JAC_INV_OTI(LBOUND(JAC_INV,1):UBOUND(JAC_INV,1), "
                "LBOUND(JAC_INV,2):UBOUND(JAC_INV,2)))") in emitted
        # The bound expression is never re-evaluated: whatever the source
        # computed, the shadow is exactly as large as the array.
        assert "nvar" not in emitted

    def test_an_allocated_shadow_is_not_allocated_twice(self):
        parsed = _parse(LOCAL_BOUND)
        site = deferred_shadow_allocations(LOCAL_BOUND, parsed, "UMAT")["JAC_INV"][0]
        emitted = _mirrored_allocation_lines("free", "ONUMM6N1", site)
        assert any("IF (ALLOCATED(JAC_INV_OTI)) DEALLOCATE(JAC_INV_OTI)" in line
                   for line in emitted)

    def test_every_element_is_zeroed_where_it_first_exists(self):
        parsed = _parse(LOCAL_BOUND)
        site = deferred_shadow_allocations(LOCAL_BOUND, parsed, "UMAT")["JAC_INV"][0]
        emitted = "\n".join(_mirrored_allocation_lines("free", "ONUMM6N1", site))
        assert "DO OTI_HI = LBOUND(JAC_INV_OTI,1), UBOUND(JAC_INV_OTI,1)" in emitted
        assert "DO OTI_HJ = LBOUND(JAC_INV_OTI,2), UBOUND(JAC_INV_OTI,2)" in emitted
        assert "JAC_INV_OTI(OTI_HI,OTI_HJ) = 0.0D0" in emitted


class TestTheDeclarationAndTheSeedBlock:
    def test_the_shadow_is_declared_allocatable_with_the_same_rank(self):
        lines = _declaration_lines(
            "free", "ONUMM6N1", ["JAC_INV"], {"JAC_INV": ":, :"},
            allocatable_shadow_ranks={"JAC_INV": 2})
        assert any("TYPE(ONUMM6N1), ALLOCATABLE :: JAC_INV_OTI(:, :)" in line
                   for line in lines)

    def test_a_shape_that_is_not_mirrored_is_declared_as_before(self):
        lines = _declaration_lines(
            "free", "ONUMM6N1", ["WORK"], {"WORK": "NTENS, 3"})
        assert any("TYPE(ONUMM6N1) :: WORK_OTI(NTENS, 3)" in line for line in lines)

    def test_the_seed_block_does_not_touch_a_shadow_with_no_elements_yet(self):
        roles = {"seed": set(), "promote": {"JAC_INV"}, "keep_real": set()}
        lines = _initialization_lines(
            "free", {"dstran": "DSTRAN", "stress": "STRESS", "statev": "STATEV"},
            roles, 6, ["JAC_INV"], {"JAC_INV": ":, :"}, set(), set(),
            allocated_shadow_names={"JAC_INV"})
        assert not any("JAC_INV_OTI" in line for line in lines)

    def test_a_shadow_that_is_not_mirrored_is_still_zeroed_in_the_seed_block(self):
        roles = {"seed": set(), "promote": {"WORK"}, "keep_real": set()}
        lines = _initialization_lines(
            "free", {"dstran": "DSTRAN", "stress": "STRESS", "statev": "STATEV"},
            roles, 6, ["WORK"], {"WORK": "6"}, set(), set())
        assert any("WORK_OTI(OTI_HI) = 0.0D0" in line for line in lines)
