"""Widening a literal's type must not stop it being a literal.

In Fortran a real literal takes its kind from its own form, not from what it
is assigned to, and Abaqus compiles user subroutines with no default-real
promotion. So `X = 3.14159265359` under IMPLICIT REAL*8 stores the
single-rounded 3.1415927410125732, and appending D0 does not widen that
literal -- it replaces it with a number 2.78e-08 away. The transform widens
to the double that holds the value the author's program uses.

Doing that introduced a regression these tests exist to stop coming back: a
literal carries ONE kind marker, and where there is an exponent that letter
IS the marker. `8.759264164837077e-05D0` is not a number -- ifort reads D0 as
an identifier glued to a default-real literal -- and four converted builds
failed to compile on it.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _as_written_in_double, _normalize_numeric_literals_in_oti_expression)

#: What ifort will accept as a double-precision literal.
WELL_FORMED = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([dD][-+]?\d+)?$")


def test_every_emitted_literal_is_a_well_formed_fortran_literal():
    for text in ("3.14159265359", "0.5", "1.0", "0.0", "0.1", "2.0", "100.0",
                 "0.0000001", "8.759264164837077e-05", "5.634849567881802e-6",
                 "0.00002639771810208913", "1e20", "0.3333333333"):
        emitted = _as_written_in_double(text)
        assert WELL_FORMED.match(emitted), f"{text} -> {emitted}"


def test_an_exponent_literal_never_gains_a_d0_suffix():
    """The exponent letter is the kind marker; a second one is a syntax
    error, and it is the one that broke four builds."""
    for text in ("8.759264164837077e-05", "5.634849567881802e-6", "1.5E-3"):
        emitted = _as_written_in_double(text)
        # No `e` survives: either the exponent letter became the D that marks
        # the kind, or the value came out short enough to write in full.
        assert "e" not in emitted.lower(), f"{text} -> {emitted}"
        assert WELL_FORMED.match(emitted), f"{text} -> {emitted}"
        # And never two kind markers.
        assert emitted.upper().count("D") <= 1, f"{text} -> {emitted}"


def test_the_author_s_value_is_what_survives():
    """3.14159265359 as written is 3.1415927410125732 under Abaqus's own
    compile flags, and that is the number the author's program computes."""
    assert _as_written_in_double("3.14159265359") == "3.1415927410125732D0"
    assert _as_written_in_double("0.1") == "0.10000000149011612D0"


def test_a_value_that_is_exact_in_single_keeps_the_author_s_digits():
    """0.5, 1.0 and 2.0 are the same number either way, so the emitted line
    stays readable and a diff stays small."""
    for text in ("0.5", "1.0", "2.0", "100.0", "0.0"):
        assert _as_written_in_double(text) == text + "D0"


def test_a_literal_already_carrying_a_kind_is_left_alone():
    line = "      X_OTI = 3.14159265359D0*Y_OTI"
    assert _normalize_numeric_literals_in_oti_expression(line) == line


def test_a_line_with_no_oti_name_is_untouched():
    """The author's own arithmetic keeps the author's own kinds."""
    line = "      X = 3.14159265359*Y"
    assert _normalize_numeric_literals_in_oti_expression(line) == line


def test_a_normalised_line_compiles_as_fortran_literals():
    """The end-to-end shape: every literal the rewrite emits on an OTI line
    has to be something a compiler will read as a number."""
    line = ("      A_OTI = 3.14159265359*B_OTI + 0.1*C_OTI - 0.5*D_OTI "
            "+ 0.0000001*E_OTI")
    out = _normalize_numeric_literals_in_oti_expression(line)
    for token in re.findall(r"(?<![A-Za-z0-9_])\d[\d.]*(?:[dD][-+]?\d+)?", out):
        assert WELL_FORMED.match(token), f"{token} in {out}"
    assert "e-" not in out and "e+" not in out
