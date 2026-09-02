"""What an intrinsic means when its argument is hypercomplex.

Three different answers, and the difference between them is a derivative.

FLOOR, NINT and IDINT answer with a whole number. They are piecewise constant,
so their derivative is zero wherever it is defined and the value is fixed
entirely by the real part -- reading it there is exact.

MOD is not. MOD(a, p) has slope one in a almost everywhere, and wrapping its
argument in REAL would compile and silently return a derivative of zero where
the true one is one. Fortran defines it as ``a - INT(a/p)*p``, and that form is
exact in hypercomplex arithmetic: only the truncation needs the real value.

SUM has nothing to take a real part of. A sum of hypercomplex numbers is
hypercomplex and its derivative is the sum of theirs, so it is written out term
by term -- and only when the extent is a literal, because a loop cannot be
written inside an expression.

These came from four crystal-plasticity UMATs that decode packed option codes
out of PROPS with FLOOR(MOD(VAL,10.D0)) and sum principal stresses with
SUM(PSIG).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.transform.helper_lifting import (  # noqa: E402
    _expand_mod_over_oti, _expand_sum_over_oti,
    _real_argument_to_integer_intrinsics, _wrap_oti_rhs_assigned_to_a_plain_variable,
)
from umat_oti.transform.source_transform import (  # noqa: E402
    _real_argument_to_integer_intrinsics as _shadow_integer_intrinsics,
    _real_sign_selector_in_oti_expression,
)

OTI = {"HARD_PAR", "VAL1", "STAT_VAR", "PSIG", "A"}


class TestIntegerValuedIntrinsicsReadTheRealPart:
    def test_floor(self):
        assert _real_argument_to_integer_intrinsics(
            "X=FLOOR(HARD_PAR)", OTI) == "X=FLOOR(REAL(HARD_PAR))"

    def test_idint_of_an_element(self):
        assert "IDINT(REAL(STAT_VAR(3)))" in _real_argument_to_integer_intrinsics(
            "N=IDINT(STAT_VAR(3))", OTI)

    def test_every_name_in_the_family(self):
        for name in ("FLOOR", "CEILING", "NINT", "IDNINT", "IDINT", "INT", "IFIX"):
            got = _real_argument_to_integer_intrinsics(f"X={name}(HARD_PAR)", OTI)
            assert f"{name}(REAL(HARD_PAR))" == got.split("=", 1)[1], name

    def test_a_plain_argument_is_left_alone(self):
        assert _real_argument_to_integer_intrinsics("X=FLOOR(PLAIN)", OTI) == "X=FLOOR(PLAIN)"

    def test_it_is_not_applied_twice(self):
        once = _real_argument_to_integer_intrinsics("X=FLOOR(HARD_PAR)", OTI)
        assert _real_argument_to_integer_intrinsics(once, OTI) == once

    def test_a_name_merely_ending_in_int_is_not_the_intrinsic(self):
        assert _real_argument_to_integer_intrinsics(
            "X=PRINT(A)", OTI) == "X=PRINT(A)"

    def test_the_shadow_side_does_the_same_by_suffix(self):
        assert _shadow_integer_intrinsics(
            "N=IDINT(STAT_VAR_OTI(3))") == "N=IDINT(REAL(STAT_VAR_OTI(3)))"


class TestModKeepsItsDerivative:
    def test_it_is_written_out_rather_than_wrapped(self):
        got = _expand_mod_over_oti("SSC=MOD(VAL1,10.D0)", OTI)
        assert "REAL(MOD(" not in got, "wrapping would zero a derivative of one"
        assert "(VAL1)" in got and "INT(REAL(VAL1)/(10.D0))" in got

    def test_the_leading_term_carries_the_derivative(self):
        # a - INT(a/p)*p : the bare `a` is what differentiates to one.
        got = _expand_mod_over_oti("SSC=MOD(VAL1,10.D0)", OTI)
        assert got.split("=", 1)[1].strip().startswith("((VAL1)")

    def test_a_plain_argument_keeps_the_intrinsic(self):
        assert _expand_mod_over_oti("X=MOD(I,3)+1", OTI) == "X=MOD(I,3)+1"

    def test_nested_inside_floor_still_reads_the_real_part(self):
        got = _real_argument_to_integer_intrinsics(
            _expand_mod_over_oti("U=FLOOR(MOD(VAL1,10.D0))", OTI), OTI)
        assert got.startswith("U=FLOOR(REAL(")
        assert "MOD(" not in got


class TestSumIsWrittenOut:
    def test_a_literal_extent_is_expanded(self):
        assert _expand_sum_over_oti("V=SUM(PSIG)", OTI, {"PSIG": "3"}) == \
            "V=(PSIG(1) + PSIG(2) + PSIG(3))"

    def test_a_run_time_extent_keeps_the_sum_and_the_compiler_reports_it(self):
        # Refusing is right: a loop cannot be written inside an expression, and
        # a wrong expansion would be a wrong number.
        assert _expand_sum_over_oti("V=SUM(Q)", {"Q"}, {"Q": "NDIM"}) == "V=SUM(Q)"

    def test_a_plain_array_is_left_alone(self):
        assert _expand_sum_over_oti("V=SUM(PLAIN)", OTI, {"PLAIN": "3"}) == "V=SUM(PLAIN)"

    def test_a_section_is_not_a_whole_array_reference(self):
        assert _expand_sum_over_oti("V=SUM(PSIG(1:2))", OTI, {"PSIG": "3"}) == \
            "V=SUM(PSIG(1:2))"

    def test_no_shapes_is_a_no_op(self):
        assert _expand_sum_over_oti("V=SUM(PSIG)", OTI, {}) == "V=SUM(PSIG)"


class TestASignSelectorReadsTheRealPart:
    def test_dsign(self):
        assert _real_sign_selector_in_oti_expression(
            "X_OTI=DSIGN(1.D0,FSLIP_OTI(J))") == "X_OTI=DSIGN(1.D0,REAL(FSLIP_OTI(J)))"

    def test_the_magnitude_argument_is_untouched(self):
        got = _real_sign_selector_in_oti_expression("X_OTI=SIGN(A_OTI,B_OTI)")
        assert got == "X_OTI=SIGN(A_OTI,REAL(B_OTI))"

    def test_a_plain_selector_is_left_alone(self):
        assert _real_sign_selector_in_oti_expression(
            "X_OTI=DSIGN(1.D0,PLAIN)") == "X_OTI=DSIGN(1.D0,PLAIN)"


class TestAnOtiValueAssignedToAPlainVariable:
    def test_it_takes_the_real_part(self):
        assert _wrap_oti_rhs_assigned_to_a_plain_variable(
            "NSS=STAT_VAR(3)", OTI) == "NSS = REAL(STAT_VAR(3))"

    def test_an_oti_target_keeps_the_whole_number(self):
        # A is hypercomplex here; wrapping would throw the derivative away.
        assert _wrap_oti_rhs_assigned_to_a_plain_variable(
            "A=STAT_VAR(1)+1", OTI) == "A=STAT_VAR(1)+1"

    def test_a_plain_right_hand_side_is_left_alone(self):
        assert _wrap_oti_rhs_assigned_to_a_plain_variable("NSS=3", OTI) == "NSS=3"

    def test_it_is_not_applied_twice(self):
        once = _wrap_oti_rhs_assigned_to_a_plain_variable("NSS=STAT_VAR(3)", OTI)
        assert _wrap_oti_rhs_assigned_to_a_plain_variable(once, OTI) == once

    def test_a_condition_is_not_an_assignment(self):
        line = "IF (A.GT.STAT_VAR(1)) THEN"
        assert _wrap_oti_rhs_assigned_to_a_plain_variable(line, OTI) == line
