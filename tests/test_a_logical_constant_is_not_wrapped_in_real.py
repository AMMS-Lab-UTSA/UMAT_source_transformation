"""REAL(.TRUE.) is not Fortran.

umatCP.for writes ``IF (X_OTI.GT.0.D0) FULL = .TRUE.``. The line mentions a
shadow (in its condition), so the transform wrapped the right-hand side in
REAL(...), which for a logical or character constant is a compile error. Rule
(B20 RULES.md R7): a logical or character literal on the right-hand side is not
a number and is left as written. Canaries: a numeric right-hand side that
mentions a shadow is still wrapped, as is one inside an inline IF.
"""
import pytest

from umat_oti.transform.source_transform import _wrap_real_assignment_rhs as wrap


@pytest.mark.parametrize("line", [
    "      IF (X_OTI.GT.0.D0) FULL = .TRUE.",
    "      IF (X_OTI.GT.0.D0) FULL = .FALSE.",
    "      IF (X_OTI.GT.0.D0) NAME = 'plastic'",
    "      FLAG = .TRUE._LK",
])
def test_a_logical_or_character_literal_is_left_alone(line):
    assert wrap(line) == line


@pytest.mark.parametrize("line,expected", [
    ("      X = Y_OTI*2.D0", "      X = REAL(Y_OTI*2.D0)"),
    ("      IF (A_OTI.GT.0.D0) X = Y_OTI", "      IF (A_OTI.GT.0.D0)  X = REAL(Y_OTI)"),
])
def test_canary_a_numeric_right_hand_side_is_still_wrapped(line, expected):
    assert wrap(line) == expected
