"""An integer in a GOTO is a label, and a label is not a value.

Eight discovered sources produced Fortran that would not compile because
``Goto 999`` came out as ``Goto 999.0D0``. The promoter's guard read

    prev_char in "+-*/" or next_char in "+-*/"

and for an integer at the end of a line ``next_char`` is ``""`` -- which
Python reports as a member of every string. So every trailing integer was
promoted whatever it meant, and the one place that always ends a statement
with an integer is a branch target.

The end of a line is a real case and it is kept, but for the reason it is
actually true: an integer that ends an assignment is the value being assigned,
and an OTI variable has no overload that takes an integer.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.transform.helper_lifting import (  # noqa: E402
    _promote_bare_integers_for_oti as promote,
)


class TestLabelsAreLeftAlone:
    def test_a_goto_target(self):
        assert promote("      GOTO 100") == "      GOTO 100"

    def test_go_to_written_as_two_words(self):
        assert promote("      GO TO 100") == "      GO TO 100"

    def test_a_goto_after_a_logical_if(self):
        line = "      IF (K.EQ.3) GO TO 20"
        assert promote(line) == line

    def test_a_goto_in_mixed_case(self):
        line = "    If (REAL(fme).Lt.0 .And. REAL(fte).Lt.0 ) Goto 999"
        assert promote(line) == line

    def test_the_three_branches_of_an_arithmetic_if(self):
        line = "      IF (X) 10, 20, 30"
        assert promote(line) == line

    def test_an_assign_target(self):
        assert promote("      ASSIGN 40 TO NEXT") == "      ASSIGN 40 TO NEXT"

    def test_a_do_loop_label(self):
        assert promote("      DO 50 I = 1, N") == "      DO 50 I = 1, N"


class TestValuesAreStillPromoted:
    def test_an_integer_that_ends_an_assignment(self):
        # X_OTI = 5 has no overload; the literal has to become a double.
        assert promote("      X = 5") == "      X = 5.0D0"

    def test_an_integer_before_an_operator(self):
        assert promote("      X = 2 * Y") == "      X = 2.0D0 * Y"

    def test_an_integer_after_an_operator(self):
        assert promote("      X = Y * 2") == "      X = Y * 2.0D0"

    def test_a_subscript_or_argument_is_not_a_value_to_promote(self):
        assert promote("      CALL F(2)") == "      CALL F(2)"

    def test_an_exponent_is_left_intact(self):
        # The minus sign of an exponent reads as an operator and its digits
        # read as a bare integer standing beside one, so ``1.0D-6`` came out
        # as ``1.0D-6.0D0``. The digits after an exponent's sign belong to the
        # literal that opened it.
        assert promote("      X = 1.0D-6 * Y") == "      X = 1.0D-6 * Y"

    def test_a_positive_exponent_too(self):
        assert promote("      X = 1.0E+3 * Y") == "      X = 1.0E+3 * Y"

    def test_an_exponent_with_no_fractional_digits(self):
        assert promote("      TOL = 1.D-12") == "      TOL = 1.D-12"

    def test_a_genuine_subtraction_is_still_promoted(self):
        # The distinction is the D or E before the sign, not the sign itself.
        assert promote("      X = A - 6 * Y") == "      X = A - 6.0D0 * Y"
