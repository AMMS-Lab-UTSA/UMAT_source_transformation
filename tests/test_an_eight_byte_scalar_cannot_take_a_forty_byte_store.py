"""The crystal-plasticity slot was lost to an overrun, not to a compiler bug.

``STATEV(25)`` came back ``-1.6982275886200392e-30`` where the author's build
wrote ``-73.46290748654624``. The value moved when ``-auto`` went, when
``-align array64byte`` went, when ``-fstack-protector-strong`` went, at ``-O1``
and under ``-no-vec``, which reads like a codegen defect and is not one. All
five of those change what the stack frame looks like, and the generated unit
writes off the end of it.

``CALL LUDCMP_OTI(WORKST_OTI, NSLPTL, ND, INDX, DDCMP)`` passes ``DDCMP``. No
declaration in the generated unit mentions ``DDCMP``, so ``ABA_PARAM.INC``'s
``IMPLICIT REAL*8(A-H,O-Z)`` makes it an 8-byte scalar. The callee declares its
dummies with ``implicit type(ONUMM4N1) (a-h,o-z)``, so ``D`` is a 40-byte
derived type, and ``D=1.0D0`` on the first line of ``LUDCMP_OTI`` stores 40
bytes into those 8. Every call overruns the caller's frame by 32 bytes, and
there is no explicit interface anywhere for a compiler to object through.

Confirmed by repair rather than by flag-flipping: adding the one line
``TYPE(ONUMM4N1) :: DDCMP`` to the generated unit, changing nothing else, and
building at the flags the solver's own ``.com`` names -- vectorisation on --
returns ``-73.4629074865463``.

Two hypotheses died here and these tests hold them dead:

* a compiler bug. The author's own source is clean under ``-init=snan,arrays``
  and returns ``-73.46290748654624`` under every build tried.
* the sequence association at ``CALL ITERATION_OTI(STATEV_OTI(NSLPTL+1),
  STATEV_OTI(2*NSLPTL+1), ...)``. Three separate reasons, any one of which is
  enough. The author's original contains the same pair and compiles
  correctly. ``-assume dummy_aliases`` -- the flag that actually turns off the
  no-alias assumption about dummy arguments, which ``-fno-alias`` does not --
  leaves the value unchanged. And the premise is false: the callee declares
  ``GAMMA(NSLPTL)`` and ``TAUSLP(NSLPTL)`` explicitly, so the storage the two
  dummies cover is ``STATEV(NSLPTL+1 : 2*NSLPTL)`` and
  ``STATEV(2*NSLPTL+1 : 3*NSLPTL)``. Those ABUT. They do not overlap, there is
  no aliasing to exploit, and a minimal reproducer of the same shape gives the
  same answer at -O2 with and without vectorisation.
"""
import os
import pathlib

import pytest

from umat_oti.abaqus.primal_signature import (CONFIRMED_FINDINGS,
                                              SINGLE_OUTPUT_SLOT,
                                              mistyped_oti_arguments)


def _generated_unit():
    """The crystal-plasticity generated source a pass9 run left behind."""
    root = pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or pathlib.Path.home() / "softwarex_work" / "corpus_run")
    unit = (root / "pass9" / "work" / "0d97f9db648d23a064062989"
            / "transformed" / "transformed_user.f")
    if not unit.is_file():
        pytest.skip(f"no generated crystal-plasticity unit at {unit}")
    return unit.read_text(errors="replace")


def test_a_bare_real_variable_reaching_a_helper_is_reported():
    """DDCMP is the whole finding: nothing declares it, so it is REAL*8."""
    source = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      INCLUDE 'ABA_PARAM.INC'\n"
        "      CALL LUDCMP_OTI(WORKST_OTI, NSLPTL, ND, INDX, DDCMP)\n"
        "      END\n")
    found = mistyped_oti_arguments(source)
    assert [(f.callee, f.position, f.actual) for f in found] == [
        ("LUDCMP_OTI", 5, "DDCMP")]
    assert found[0].line == 3


def test_a_transformed_argument_and_an_integer_one_are_not_reported():
    """``_OTI`` names carry the derived type; I-N names are INTEGER on both
    sides of the call, by the same first-letter rule."""
    source = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      CALL LUBKSB_OTI(WORKST_OTI, NSLPTL, ND, INDX, DGAMMA_OTI)\n"
        "      END\n")
    assert mistyped_oti_arguments(source) == []


def test_an_expression_of_oti_operands_is_not_reported():
    """An expression has the type of its operands, not of its leading name,
    so reporting one would be a false positive rather than a cautious one."""
    source = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      CALL STRAINRATE_OTI(A_OTI*TERM1_OTI, X_OTI)\n"
        "      END\n")
    assert mistyped_oti_arguments(source) == []


def test_a_continued_call_is_reported_at_the_line_a_traceback_names():
    """Fixed-form continuations are joined, and the line kept is the first --
    which is the one ``-traceback`` prints."""
    source = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      CALL LUBKSB_OTI(WORKST_OTI, NSLPTL, ND, INDX,\n"
        "     1DDGDDE(1,I))\n"
        "      END\n")
    found = mistyped_oti_arguments(source)
    assert len(found) == 1
    assert found[0].line == 2
    assert found[0].actual == "DDGDDE(1,I)"


@pytest.mark.integration
def test_the_generated_crystal_plasticity_unit_carries_three_of_them():
    """Two LUDCMP_OTI calls take DDCMP; one LUBKSB_OTI call takes DDGDDE.

    Only the DDCMP pair causes the STATEV(25) corruption: patching the
    DDGDDE call out alone leaves the slot at -1.6982275886200392e-30, which
    is why the two are recorded as separate defects and not as one.
    """
    found = mistyped_oti_arguments(_generated_unit())
    assert [(f.line, f.callee, f.actual) for f in found] == [
        (943, "LUDCMP_OTI", "DDCMP"),
        (1235, "LUDCMP_OTI", "DDCMP"),
        (1482, "LUBKSB_OTI", "DDGDDE(1,I)"),
    ]


def test_the_confirmation_names_the_construct_and_not_a_flag():
    """A workaround is not a root cause. If this confirmation ever comes back
    saying only that -no-vec removes the corruption, it has regressed: the
    unrepaired unit returns the right answer under -no-vec and the wrong one
    again under ``-no-vec -heap-arrays``, so -no-vec is a coincidence of stack
    layout and the declaration is the repair."""
    slot = [c for c in CONFIRMED_FINDINGS
            if c.hypothesis == SINGLE_OUTPUT_SLOT and c.fortran_index == 25]
    assert len(slot) == 1
    cause = slot[0].root_cause
    assert "DDCMP" in cause
    assert "LUDCMP_OTI" in cause
    assert "TYPE(ONUMM4N1) :: DDCMP" in cause
    assert "-assume dummy_aliases" in cause
    assert slot[0].original == -73.46290748654624
    assert slot[0].transformed == -1.6982275886200392e-30


def test_the_two_statev_sections_abut_and_do_not_overlap():
    """The refutation is arithmetic, not a flag.

    ``ITERATION_OTI`` declares ``GAMMA(NSLPTL)`` and ``TAUSLP(NSLPTL)``
    explicitly, so each dummy covers exactly NSLPTL elements from where its
    actual argument starts. Passing ``STATEV(NSLPTL+1)`` and
    ``STATEV(2*NSLPTL+1)`` therefore hands the callee two runs of storage that
    meet end to end. "Two overlapping sections of the same array" describes a
    construct that is not in this file.
    """
    nslptl = 12
    gamma = range(nslptl + 1, 2 * nslptl + 1)
    tauslp = range(2 * nslptl + 1, 3 * nslptl + 1)
    assert set(gamma).isdisjoint(tauslp)
    assert max(gamma) + 1 == min(tauslp)
