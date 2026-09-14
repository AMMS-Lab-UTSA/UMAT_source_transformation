"""A dependency that crosses a CALL, and a type that has to cross it with one.

Two claims, measured over the 391-source corpus and named here so a change to
either is visible:

* the dependency walk follows a value through a routine's dummy arguments, so
  it survives a caller that names its actual arguments differently from the
  callee's dummies;
* every actual argument arriving at a dummy the lifted helper declares
  hypercomplex is itself hypercomplex -- and where the transform cannot make
  that true, the source is refused rather than emitted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.core.model import ParsedFortranSource  # noqa: E402
from umat_oti.fortran.parser import (  # noqa: E402
    logical_lines_from_text, parse_subroutines)
from umat_oti.fortran.regions import (  # noqa: E402
    _assignments, _call_effect_assignments, _dependency_summary,
    _routine_effect_table)
from umat_oti.transform.source_transform import (  # noqa: E402
    _names_declared_with_type, oti_typed_dummies_of_lifted_helpers,
    real_arguments_into_oti_helper_dummies)


def _parse(text: str, form: str = "fixed") -> ParsedFortranSource:
    lines = logical_lines_from_text(text, form)
    return ParsedFortranSource(Path("memory.f"), form, text, lines,
                               parse_subroutines(lines))


#: A UMAT that hands its work to a kernel and renames every argument on the
#: way. Written out rather than taken from the corpus because the rename is
#: the whole point and a corpus source that happens to reuse its names would
#: pass either way.
RENAMING_CALLER = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS,DFGRD1,NTENS)
      DIMENSION STRESS(NTENS),STATEV(2),DDSDDE(NTENS,NTENS)
      DIMENSION DSTRAN(NTENS),PROPS(2),DFGRD1(3,3)
      CALL KERNEL(SIG,SDV,FNEW,PRP)
      DO K1=1,NTENS
        STRESS(K1)=SIG(K1)
      END DO
      RETURN
      END
      SUBROUTINE KERNEL(SOUT,SDV,FIN,PRP)
      DIMENSION SOUT(6),SDV(2),FIN(3,3),PRP(2)
      DETJ=FIN(1,1)*FIN(2,2)-FIN(1,2)*FIN(2,1)
      DO K1=1,6
        SOUT(K1)=PRP(1)*DETJ
      END DO
      RETURN
      END
"""


def test_the_effect_table_reads_which_dummy_a_routine_writes():
    """KERNEL writes argument 0 from arguments 2 and 3, and says so by position.

    Positions and not names: the caller passes SIG, FNEW and PRP where the
    callee declares SOUT, FIN and PRP, and only the position survives that.
    """
    parsed = _parse(RENAMING_CALLER)
    table = _routine_effect_table(parsed)
    assert "KERNEL" in table
    assert table["KERNEL"].get(0) == {2, 3}


def test_a_renamed_argument_keeps_the_deformation_gradient_on_the_stress_path():
    """Before: SIG and FNEW reach no category at all. After: both are on it.

    Without the call effect the walk from STRESS stops at SIG. SIG is named on
    the right of the stress assignment, so it is reached; nothing in the caller
    assigns to it, so the walk has nowhere to go from there -- the value
    arrives through KERNEL. FNEW never appears, and every quantity computed
    from the deformation gradient is then emitted real, inside REAL(), with the
    derivative dropped one statement after the seed.
    """
    parsed = _parse(RENAMING_CALLER)
    flat = _assignments(parsed.logical_lines)
    without = _dependency_summary(parsed, flat + _call_effect_assignments(
        parsed.logical_lines))
    with_effects = _dependency_summary(parsed, flat + _call_effect_assignments(
        parsed.logical_lines, _routine_effect_table(parsed)))
    assert "SIG" in without.upstream_to_stress
    assert "FNEW" not in without.upstream_to_stress
    assert {"SIG", "FNEW"} <= with_effects.upstream_to_stress


def test_an_inferred_call_effect_never_establishes_constancy():
    """The inferred effect is a lower bound, so it cannot prove a negative.

    It sees what a callee does to its dummy arguments and cannot see what it
    takes from a COMMON block, a module variable, a SAVEd local or a callee
    this file does not define. "Constant" is a claim that nothing else
    contributed; a lower bound can support the path walks, which only ask
    whether a dependency exists, and never this.
    """
    parsed = _parse(RENAMING_CALLER)
    summary = _dependency_summary(
        parsed,
        _assignments(parsed.logical_lines)
        + _call_effect_assignments(parsed.logical_lines,
                                   _routine_effect_table(parsed)))
    assert "SIG" not in summary.constant_variables
    assert "FNEW" not in summary.constant_variables
    assert "SIG" not in summary.constant_variables


LIFTED_HELPER_MODULE = """\
subroutine kernel_oti(sout, sdv, fin, prp, ntens)
    use otim6n1
    implicit none
    type(ONUMM6N1) :: SOUT(6), FIN(3,3)
    type(ONUMM6N1) :: PRP(2)
    integer :: NTENS
    real*8 :: SDV(2)
end subroutine kernel_oti
"""


def test_the_oti_dummies_are_read_off_the_lifted_text():
    """Which dummy is hypercomplex is the lifter's decision, so it is read back.

    Positional, and None where the lifted body left the dummy alone: SDV stays
    real and NTENS stays an integer, and an actual argument at either of those
    positions is no mismatch at all.
    """
    found = oti_typed_dummies_of_lifted_helpers(LIFTED_HELPER_MODULE)
    assert found["KERNEL_OTI"] == ["sout", None, "fin", "prp", None]


CALLER_WITH_A_REAL_ACTUAL = """\
      SUBROUTINE UMAT(STRESS,NTENS)
      TYPE(ONUMM6N1) :: STRESS_OTI(6), PRP_OTI(2)
      TYPE(ONUMM6N1), ALLOCATABLE :: FNEW_OTI(:,:)
      DIMENSION FPERT(3,3)
      CALL KERNEL_OTI(STRESS_OTI, SDV, FPERT, PRP_OTI, NTENS)
      RETURN
      END
"""


def test_a_real_actual_reaching_a_hypercomplex_dummy_is_reported():
    """The mirror of the leak check, which only ever looked the other way.

    The lifted helpers are external subprograms -- the compile order builds
    umat_oti_helpers.f90 separately and nothing USEs it -- so the implicit
    interface takes a DOUBLE PRECISION array against a TYPE(ONUMM6N1) dummy
    in silence, and the callee reads the first of seven doubles as the whole
    number. Measured on keisuke58/pde-fem-biofilm's umat_biofilm_visco_phase2.f,
    which passed DFGRD_P and STRESS_PERT to BIOFILM_STRESS_CORE_OTI and
    compiled without a diagnostic.
    """
    found = real_arguments_into_oti_helper_dummies(
        CALLER_WITH_A_REAL_ACTUAL, "fixed", LIFTED_HELPER_MODULE, "ONUMM6N1")
    assert found == [("KERNEL_OTI", "FPERT", "FIN")]


def test_an_attributed_or_continued_declaration_still_names_a_shadow():
    """ALLOCATABLE between the type and the ``::`` does not stop being a shadow.

    A pattern that put ``::`` straight after the parenthesis missed
    ``TYPE(ONUMM4N1), ALLOCATABLE :: ALPHA_K_OTI(:, :)`` entirely, and the
    check above then reported a perfectly good shadow as the offender --
    refusing ahartloper/UVC_MatMod's plane-stress model for a defect that was
    not there.
    """
    names = _names_declared_with_type(CALLER_WITH_A_REAL_ACTUAL, "ONUMM6N1")
    assert {"STRESS_OTI", "FNEW_OTI"} <= names


@pytest.mark.parametrize("statement", [
    "      CALL KERNEL_OTI(STRESS_OTI, SDV, FPERT, PRP_OTI, NTENS)",
    "      CONTINUE",
    "      COMMON /BLK/ X",
])
def test_a_logical_line_beginning_with_c_is_not_a_comment(statement):
    """Fixed-form column 1 is a comment marker for a RAW line and nothing else.

    The logical-line reader has already dropped the comments and stitched the
    continuations, so what it yields starts in column 1 -- and a guard that
    calls any line starting with C a comment throws away CALL, CONTINUE and
    COMMON. With that guard in place the check above saw no call at all and
    passed every source it exists to fail.
    """
    lines = logical_lines_from_text(statement + "\n", "fixed")
    assert [line.text for line in lines] == [statement.strip()]


#: The reproduction that kept the effect table out of the default path.
#:
#: Two statements about one variable, in that order, where the first sits in a
#: region the classifier kept real and the second is a one-line IF. The branch
#: pass rewrites any line in the selected routine that mentions a promoted
#: name, wherever it sits; the assignment pass only rewrites lines in a
#: selected region. Where they disagree the guard reads the shadow, which at
#: that point still holds the zero the initialiser wrote.
CLAMP_THAT_LOST_ITS_SUBJECT = """\
      ALPHA_G  = TEMP + DTEMP
      IF (REAL(ALPHA_G_OTI) .LT. 0.0D0) ALPHA_G_OTI = 0.0D0
      ALPHA_G_OTI = ALPHA_G
"""


def test_a_guard_rewritten_without_its_assignment_reads_the_initialiser():
    """The emitted shape that makes a clamp disappear, named so it is findable.

    Measured on keisuke58/pde-fem-biofilm's umat_biofilm_visco_phase2.f, which
    the corpus verification marks verified: with the cross-routine effect table
    wired in, ALPHA_G's region stops being a transformed one, the assignment
    stays real, the one-line IF is still rewritten to the shadow, and the
    growth parameter is no longer clamped at zero.

    This is an assertion about the SHAPE, not about the transform -- the
    transform no longer emits it, because the table is not wired in. It is here
    so that whoever fixes the branch pass has the reproduction rather than the
    story.
    """
    lines = [line.text for line in logical_lines_from_text(
        CLAMP_THAT_LOST_ITS_SUBJECT, "fixed")]
    guard, copy_in = lines[1], lines[2]
    # The guard reads and writes the shadow ...
    assert "ALPHA_G_OTI" in guard
    # ... and the only assignment that gives the shadow a value comes after it.
    assert copy_in.startswith("ALPHA_G_OTI =")
    assert lines.index(guard) < lines.index(copy_in)
    # The real name is what the value was computed into, and nothing copies it
    # into the shadow before the guard runs.
    assert lines[0].startswith("ALPHA_G ")
