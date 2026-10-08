"""A helper's REAL variable passed on to another helper's hypercomplex dummy.

The leak check for lifted helpers examined literal actuals only. luisez1988's
NorSand declares ``doubleprecision :: p,q,eta`` in a lifted helper and passes
them to GETPANDQ_OTI, whose dummies are hypercomplex and which writes
hypercomplex results into them: gfortran only warns (implicit interface). Rule
(B20 RULES.md R11, detector): inside the lifted helper source, a variable the
calling routine declares explicitly REAL or DOUBLE PRECISION, handed to a
dummy the callee types hypercomplex, is reported. Canaries: a hypercomplex
variable, a name typed only by IMPLICIT, and a REAL dummy are not.
"""
from umat_oti.transform.source_transform import (
    oti_typed_dummies_of_lifted_helpers, real_variable_actuals_in_lifted_helpers)

LIFTED = """subroutine caller_oti(x)
  implicit type(onumm6n1) (a-h,o-z)
  type(onumm6n1) :: x
  doubleprecision :: p, q(3)
  type(onumm6n1) :: z
  call callee_oti(p, z, y, q)
  call real_callee_oti(p)
end subroutine caller_oti
subroutine callee_oti(a, b, c, d)
  implicit type(onumm6n1) (a-h,o-z)
  type(onumm6n1) :: a
  type(onumm6n1) :: b
  type(onumm6n1) :: d(3)
end subroutine callee_oti
subroutine real_callee_oti(a)
  implicit type(onumm6n1) (a-h,o-z)
  integer :: a
end subroutine real_callee_oti
"""


def _found(text=LIFTED):
    return real_variable_actuals_in_lifted_helpers(text, oti_typed_dummies_of_lifted_helpers(text))


def test_a_declared_real_actual_against_a_hypercomplex_dummy_is_reported():
    found = _found()
    assert ("CALLEE_OTI", "p", "A") in found
    assert ("CALLEE_OTI", "q", "D") in found


def test_canary_hypercomplex_implicit_and_real_dummy_cases_are_not_reported():
    names = {actual for _, actual, _ in _found()}
    assert "z" not in names          # declared hypercomplex
    assert "y" not in names          # typed by IMPLICIT, hypercomplex in a helper
    assert not any(callee == "REAL_CALLEE_OTI" for callee, _, _ in _found())   # integer dummy


def test_the_scan_is_per_calling_routine():
    other = LIFTED.replace("  doubleprecision :: p, q(3)\n", "  type(onumm6n1) :: p, q(3)\n")
    assert _found(other) == []
