"""An array constructor handed to an intrinsic the OTI module overloads.

MATMUL and DOT_PRODUCT are overloaded for (OTI, real) and (real, OTI), but
there is no specific procedure for a default INTEGER operand -- and
``(/1,0,0/)`` is one. The the model UMAT takes its texture tensor along each
global axis that way, and once the tensor is a shadow gfortran answers
"Generic function 'matmul' is not consistent with a specific intrinsic
interface", which names neither the argument nor the reason.

Paired, as the rest of the literal rules are: the constructor that has to be
widened, and the neighbouring one that must be left an integer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _normalize_numeric_literals_in_oti_expression,
    _real_array_constructors_for_oti_intrinsics,
)


def test_an_integer_constructor_over_an_oti_operand_is_widened():
    line = "      C_X_OTI = sqrt(dot_product((/1,0,0/), matmul(I_TEX_OTI,(/1,0,0/))))"
    widened = _real_array_constructors_for_oti_intrinsics(line)
    assert "(/1,0,0/)" not in widened
    assert widened.count("1.0D0") == 2
    assert widened.count("0.0D0") == 4


def test_the_square_bracket_spelling_is_the_same_constructor():
    line = "      Y_OTI = matmul(A_OTI,[1,0,0])"
    assert "1.0D0" in _real_array_constructors_for_oti_intrinsics(line)


def test_a_constructor_with_no_oti_operand_is_left_alone():
    """Plain MATMUL over real or integer arrays is the compiler's own, and
    widening its operands would change the type of an ordinary expression."""
    line = "      X = matmul(A,(/1,0,0/))"
    assert _real_array_constructors_for_oti_intrinsics(line) == line


def test_an_index_vector_stays_an_integer():
    """A constructor is only widened inside MATMUL or DOT_PRODUCT. Elsewhere
    it may be a list of subscripts, which has to stay an integer."""
    line = "      Y_OTI = STATEV_OTI((/1,2,3/))"
    assert _real_array_constructors_for_oti_intrinsics(line) == line


def test_the_widening_runs_as_part_of_the_normal_literal_pass():
    line = "      C_X_OTI = dot_product((/0,1,0/), matmul(I_TEX_OTI,(/0,1,0/)))"
    normalized = _normalize_numeric_literals_in_oti_expression(line)
    assert "(/0,1,0/)" not in normalized
    assert "1.0D0" in normalized


def test_a_call_continued_onto_the_next_line_is_still_widened():
    """One UMAT writes the call across two lines, and the rewrite
    reads one line at a time. The opening line's parentheses do not balance,
    which used to end the scan before it reached the constructor."""
    opening = "      C_X_OTI = sqrt(dot_product((/1,0,0/), &"
    widened = _real_array_constructors_for_oti_intrinsics(opening)
    assert "(/1,0,0/)" not in widened
    assert "1.0D0" in widened


def test_a_continued_call_with_no_oti_in_the_statement_is_left_alone():
    opening = "      X = sqrt(dot_product((/1,0,0/), &"
    assert _real_array_constructors_for_oti_intrinsics(opening) == opening
