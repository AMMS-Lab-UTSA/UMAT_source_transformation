"""A LOGICAL target must never be handed REAL().

Two independent slips produced the same broken line, `OK_FLAG = REAL(.FALSE.)`,
which ifort refuses. Five converted builds failed to compile on it.

The first: `.TRUE.` and `.FALSE.` are logical LITERALS whose dotted form makes
them look like the dotted operators `.AND.` and `.NOT.`. They were missing
from the keyword set, so the tokeniser read `FALSE` as an identifier, found it
undeclared and not implicitly integer, and filed it as an implicitly typed
hypercomplex variable.

The second: having decided the right-hand side "mentions an OTI name", the
wrap fired because the target was merely *not* hypercomplex. Not being
hypercomplex does not make a name numeric -- the author declared some of these
LOGICAL, and REAL() of a logical is a type error rather than a conversion.

Either fix alone would have hidden the other, so both are tested.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.helper_lifting import (  # noqa: E402
    _KEYWORDS, _wrap_oti_rhs_assigned_to_a_plain_variable)


def test_the_logical_literals_are_keywords_not_variables():
    assert "TRUE" in _KEYWORDS and "FALSE" in _KEYWORDS


def test_a_logical_target_is_left_alone():
    line = "      OK_FLAG = STAT_VAR_OTI(3)"
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        line, {"STAT_VAR_OTI"}, {"OK_FLAG"}) == line


def test_a_character_target_is_left_alone():
    line = "      LABEL = NAME_OTI"
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        line, {"NAME_OTI"}, {"LABEL"}) == line


def test_a_numeric_target_still_takes_the_real_part():
    """The rewrite exists for a reason and must keep working: the source
    stored a count in a real array and read it back into an integer, and that
    conversion is what it always did."""
    out = _wrap_oti_rhs_assigned_to_a_plain_variable(
        "      NSS = STAT_VAR_OTI(3)", {"STAT_VAR_OTI"}, set())
    assert out.strip() == "NSS = REAL(STAT_VAR_OTI(3))"


def test_a_hypercomplex_target_keeps_the_whole_number():
    line = "      X_OTI = STAT_VAR_OTI(3)"
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        line, {"STAT_VAR_OTI", "X_OTI"}, set()) == line


def test_no_non_numeric_set_behaves_as_before():
    """Callers that pass nothing keep the old behaviour, so the guard cannot
    silently change a caller that has not been updated."""
    out = _wrap_oti_rhs_assigned_to_a_plain_variable(
        "      NSS = STAT_VAR_OTI(3)", {"STAT_VAR_OTI"})
    assert "REAL(" in out
