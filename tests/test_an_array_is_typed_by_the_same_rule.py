"""A DIMENSION statement gives a shape, not a type.

Fortran's implicit typing applies to arrays exactly as it does to scalars, so
`DIMENSION ISPDIR(3)` under `IMPLICIT REAL*8(A-H,O-Z)` declares an array of
INTEGER -- I is outside A-H and O-Z. The rule that keeps implicitly-integer
names real used to exempt anything with a shape, which let exactly this array
be promoted.

What that cost, measured rather than imagined: the Huang crystal-plasticity
UMAT holds its slip-plane and slip-direction Miller indices in two such
arrays and hands them to a routine that declares them INTEGER. Promoted, each
index became seven doubles passed to an integer dummy, so the callee read the
high half of the double 1.0 -- 1072693248 -- as a Miller index, computed a
zero modulus from it, divided by that zero, and reached the source's own
`PAUSE 'Singular matrix.'`. In Abaqus that PAUSE waits on a terminal that
isn't there, so the solver held a licence token and neither finished nor
failed.
"""
from umat_oti.core.roles import _is_implicitly_integer, implicit_integer_letters


LETTERS = implicit_integer_letters("      IMPLICIT REAL*8 (A-H,O-Z)\n")


def test_an_undeclared_integer_array_is_still_an_integer():
    variable = {"detected_shape": "(3)"}
    assert _is_implicitly_integer("ISPDIR", "unknown", variable, LETTERS)


def test_an_undeclared_integer_scalar_is_still_an_integer():
    assert _is_implicitly_integer("IDOT", "unknown", {}, LETTERS)


def test_a_declared_type_always_wins():
    """An explicit declaration is not being guessed at here."""
    variable = {"detected_shape": "(3)"}
    assert not _is_implicitly_integer("ISPDIR", "real(8)", variable, LETTERS)


def test_a_letter_outside_the_integer_range_is_not_touched():
    assert not _is_implicitly_integer("SLPDIR", "unknown", {"detected_shape": "(3,50)"},
                                      LETTERS)


def test_implicit_none_leaves_the_rule_with_nothing_to_say():
    letters = implicit_integer_letters("      IMPLICIT NONE\n")
    assert not _is_implicitly_integer("ISPDIR", "unknown", {}, letters)


def test_a_source_that_makes_i_real_is_believed():
    """`IMPLICIT REAL*8 (A-Z)` leaves no integer range at all."""
    letters = implicit_integer_letters("      IMPLICIT REAL*8 (A-Z)\n")
    assert not _is_implicitly_integer("ISPDIR", "unknown", {}, letters)
