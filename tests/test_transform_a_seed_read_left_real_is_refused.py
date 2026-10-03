"""A REAL statement that reads the seed into a shadowed variable is refused.

``G = PROPS(1)*(1.0D0 + DSTRAN(2))`` reaching the stress only through
``CALL SCALE(2.0D0*G, ...)`` used to be left REAL ahead of the seed block (the
region classifier's call edge took only the first identifier of each actual),
G_OTI was filled from G with no derivative, and the tangent lost dG/dDSTRAN
beside a bitwise-correct stress. The classifier now reads every identifier
(tests/test_transform_a_call_reads_every_identifier_of_its_actuals.py); this
semantic check, ``no_seed_read_into_a_real_copy_of_a_shadowed_name``, stays as
the backstop on the emitted text, and since Vera's B8 review (R2) it follows
the seed transitively through REAL statements and CALLs.

Checked on emitted text written out here, because the transform no longer
produces it.
"""
from umat_oti.transform.source_transform import _real_statements_reading_the_seed

HEADER = """subroutine umat(stress, dstran, props, ntens)
  use otim6n1, OTI_E1 => E1
  integer :: ntens, i
  real(8) :: stress(ntens), dstran(ntens), props(1), g, t, q, y(6)
  TYPE(ONUMM6N1) :: DSTRAN_OTI(ntens), STRESS_OTI(ntens), G_OTI, Y_OTI(6)
"""
TAIL = """! OTIS seed initialization from GUI configuration
  DO OTI_I = 1, ntens
     DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)
  END DO
  G_OTI = G
  DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1
  do i = 1, ntens
    call SCALE_OTI(2.0d0*G_OTI, DSTRAN_OTI(i), Y_OTI(i))
    STRESS_OTI(i) = STRESS_OTI(i) + Y_OTI(i)
  end do
end subroutine umat
"""


def _check(prelude: str):
    return _real_statements_reading_the_seed(HEADER + prelude + TAIL, "free", "UMAT",
                                             {"DSTRAN"}, "ONUMM6N1")


def test_one_hop_is_refused():
    assert _check("  g = props(1)*(1.0d0 + dstran(2))\n")


def test_two_hops_are_refused():
    """Vera's toy: T = DSTRAN(2); G = PROPS(1)*(1+T). Was 1000 against FD 1040.8."""
    found = _check("  t = dstran(2)\n  g = props(1)*(1.0d0 + t)\n")
    assert any("G = PROPS(1)" in text.upper() or "G_OTI = G" in text.upper() for _, text in found)


def test_a_real_call_carries_the_taint():
    assert _check("  call copy(dstran(2), t)\n  g = props(1)*t\n")


def test_a_value_not_reached_by_the_seed_is_not_refused():
    assert not _check("  q = props(1)\n  g = 2.0d0*q\n")
