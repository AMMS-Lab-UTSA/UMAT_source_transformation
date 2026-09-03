"""Fixed form ignores blanks inside a statement, and the emitter did not.

A source writes `...G12*G23*G3` at the end of one line and `1+G13*...` on the
next. In fixed form that is the single identifier `G31`. An emitter that
rejoins the two with a space writes `G3 1`, and the compiler reads it back as
`G31` -- the original, un-renamed variable, which in the case that raised this
is never assigned and holds whatever was on the stack.

This is the worst failure the transform can produce. It does not crash and it
does not look wrong: it is a nondeterministic answer, so no comparison can be
relied on to catch it. Measured on From-3D-to-3D-Petal, where three such lines
moved the stress disagreement from 8.171e-03 to 2.119e-09 once repaired.

The check cannot repair the emission, and does not pretend to. It refuses to
let it out silently.
"""
from umat_oti.transform.source_transform import _no_identifier_split_by_blanks


def test_the_case_that_raised_this_is_caught():
    """`G3 1` where the source declares G31."""
    emitted = ("      DOUBLE PRECISION G31\n"
               "      X = A/(-G13*G22*G31+G12*G23*G3 1+G13*G32)\n")
    assert not _no_identifier_split_by_blanks(emitted, "fixed")


def test_a_clean_statement_passes():
    assert _no_identifier_split_by_blanks(
        "      DOUBLE PRECISION G31\n      X = G12*G23*G31 + 1.0\n", "fixed")


def test_a_split_that_does_not_re_fuse_into_a_declared_name_passes():
    """`A 1` is only a defect if the source has an `A1` for it to become.

    Otherwise it is ordinary spacing around a literal, which is everywhere.
    """
    assert _no_identifier_split_by_blanks(
        "      X = FOO 1\n      Y = 2\n", "fixed")


def test_ordinary_spacing_around_numbers_is_not_flagged():
    assert _no_identifier_split_by_blanks(
        "      DO I = 1, 10\n      X = Y + 1.0D0\n      CALL F(A, 1)\n", "fixed")


def test_free_form_is_not_checked():
    """Blanks are significant there, so the same text is genuinely two tokens."""
    emitted = ("      DOUBLE PRECISION G31\n"
               "      X = G12*G23*G3 1+G13\n")
    assert _no_identifier_split_by_blanks(emitted, "free")


def test_a_comment_is_not_a_statement():
    assert _no_identifier_split_by_blanks(
        "      DOUBLE PRECISION G31\nC     G3 1 in a comment is not code\n",
        "fixed")


def test_the_label_field_is_not_part_of_the_statement():
    """Columns 1-5 hold a label; a digit there is not part of an identifier."""
    assert _no_identifier_split_by_blanks(
        "      DOUBLE PRECISION G31\n  100 CONTINUE\n", "fixed")


def test_the_real_emitted_output_that_raised_this_is_rejected():
    """Guards the check against being narrowed until it stops firing."""
    emitted = (
        "      DOUBLE PRECISION G31_OTI, G31\n"
        "      A1_OTI = (X)/(-G13_OTI*G22_OTI*G31_OTI+G12_OTI*G23_OTI*G3 1+\n"
        "     1G13_OTI*G32_OTI)\n")
    assert not _no_identifier_split_by_blanks(emitted, "fixed")
