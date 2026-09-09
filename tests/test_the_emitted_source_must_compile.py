"""Two ways the transform emitted Fortran that ifort will not accept.

Both were found by the Abaqus batch rather than by inspection: the converted
build simply never ran, and the row sat at transformed_job_failed across three
runs with the reason "transformed.sta was not written".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    OTI_MODULE_GENERICS, _locals_colliding_with_the_oti_modules,
    _wrap_real_assignment_rhs)


# ---- a REAL() wrap that closed inside the statement ----------------------
def test_an_unfinished_statement_is_not_wrapped():
    """The wrap is handed ONE physical line and a statement may run over
    several. Closing the bracket at the end of the first line put it in the
    middle of the expression:

        SHSTRAN(K1) = REAL(max_shrinkage * (CURE_OTI -
       1morphology_threshold) /)
       &                  (1.0 - morphology_threshold)

    which ifort rejects with "Syntax error, found '/)'".
    """
    line = "      SHSTRAN(K1) = max_shrinkage * (CURE_OTI -"
    assert _wrap_real_assignment_rhs(line) == line


def test_an_unfinished_call_argument_is_not_wrapped():
    line = "      TRN1 = (EPRIN_OTI(1)+EPRIN_OTI(2)+ABS(EPRIN_OTI(1)+"
    assert _wrap_real_assignment_rhs(line) == line


def test_a_complete_statement_is_still_wrapped():
    """The wrap exists for a reason and has to keep working."""
    out = _wrap_real_assignment_rhs("      NSS = STAT_OTI(3)")
    assert out.strip() == "NSS = REAL(STAT_OTI(3))"


def test_a_balanced_nested_expression_is_wrapped():
    out = _wrap_real_assignment_rhs("      X = A_OTI*(B+C)")
    assert out.strip() == "X = REAL(A_OTI*(B+C))"


def test_a_parenthesis_inside_a_string_does_not_unbalance_it():
    """Character literals are not code, and counting their brackets would
    refuse a statement that is perfectly complete."""
    out = _wrap_real_assignment_rhs("      X = A_OTI + LEN('a)b')")
    assert "REAL(" in out


# ---- a local name the OTI modules also export ---------------------------
def test_a_local_named_like_a_module_generic_is_refused():
    """mholla/growth's umat_ortho_stretch.f declares `real*8 max(3)`, and
    ifort then reports "The attributes of this name conflict with those made
    accessible by a USE statement"."""
    found = _locals_colliding_with_the_oti_modules(
        "      real*8  lam, tcr, mu, cr(3), max(3), alpha(3)")
    assert found == ["MAX"]


def test_an_ordinary_declaration_is_not_flagged():
    assert _locals_colliding_with_the_oti_modules(
        "      real*8  lam, tcr, mu, stress(6)") == []


def test_a_comment_is_not_a_declaration():
    assert _locals_colliding_with_the_oti_modules("C     real*8 max(3)") == []


def test_the_generics_are_the_ones_the_modules_publish():
    """PUBLIC :: MIN, MAX, SIGN, NINT, INT, ASSIGNMENT(=), MATMUL in
    oti_intrinsics. The operators cannot be shadowed by a variable name; the
    named generics can."""
    assert OTI_MODULE_GENERICS == {"MIN", "MAX", "SIGN", "NINT", "INT", "MATMUL"}


def test_the_refusal_says_what_to_change():
    """A refusal a reader cannot act on is only half a report."""
    import inspect

    from umat_oti.transform.source_transform import _readiness_blockers

    body = inspect.getsource(_readiness_blockers)
    assert "_locals_colliding_with_the_oti_modules(source_text)" in body, (
        "the collision check must be reached from the readiness blockers, or "
        "the source is emitted and fails at compile time instead")
    # The message is built from several f-string fragments, so assert on
    # pieces that are contiguous in the source rather than on the sentence
    # they compose at runtime.
    assert "will not rename an " in body
    assert "Renaming it in" in body
    assert "compiles and computes something else" in body
