"""A control has to change something, or it is a measurement of nothing.

Two of them here, and both had a way of silently doing nothing.

The PRECISION control widens exactly the declarations the transform promoted
and reruns the original. If it widened none, the run would come back identical
and read as "the difference was the declared precision" when nothing was
declared narrow.

The ASSOCIATION control recompiles the same source with reassociation
permitted where Abaqus's own compile line forbids it, so a model can be
compared with ITSELF. The flags were inserted at the front of the compile
line -- and the last ``-fp-model`` on an ifort command line is the one that
wins, so Abaqus's own ``precise`` overrode the ``fast`` that preceded it. The
control returned "this model differs from itself by 0.000e+00", which is what
a control that did not recompile anything returns, and it would have been read
as a model insensitive to operation order.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.precision import survey, widen  # noqa: E402
from umat_oti.abaqus.support import (ASSOCIATION_FLAGS,  # noqa: E402
                                     association_environment)


def test_the_association_flags_land_after_abaqus_own(tmp_path: Path):
    written = association_environment(tmp_path).read_text(encoding="utf-8")
    assert "compile_fortran[:-1]" in written, (
        "before Abaqus's own flags, a later -fp-model overrides these")
    assert "compile_fortran[-1:]" in written, (
        "and before %P, which has to stay last")
    for flag in ASSOCIATION_FLAGS:
        assert repr(flag) in written


def test_the_association_environment_extends_rather_than_replaces(tmp_path: Path):
    """Abaqus's own flags carry the ABI the rest of the link expects."""
    written = association_environment(tmp_path).read_text(encoding="utf-8")
    assert "compile_fortran = compile_fortran" in written
    assert not any(line.strip().startswith("compile_fortran = [")
                   for line in written.splitlines())


def test_an_existing_environment_is_kept(tmp_path: Path):
    """A job directory may already carry a link line for the OTI support."""
    (tmp_path / "abaqus_v6.env").write_text("_objects = ['a.o']\n", encoding="utf-8")
    written = association_environment(tmp_path).read_text(encoding="utf-8")
    assert "_objects = ['a.o']" in written
    assert "fast=2" in written


def test_a_precision_control_that_would_widen_nothing_is_not_run():
    """It is refused before an Abaqus job is spent on it, and the reason says
    the arithmetic was already double rather than that the difference was
    explained."""
    converted = ("      SUBROUTINE UMAT(S)\n"
                 "      TYPE(ONUMM6N1) :: S_OTI(6)\n"
                 "      RETURN\n      END\n")
    already_double = ("      SUBROUTINE UMAT(S)\n"
                      "      REAL*8 S(6)\n"
                      "      RETURN\n      END\n")
    finding = survey(already_double, converted)
    assert not finding.explains_a_difference
    assert "already double" in finding.reason
    assert widen(already_double, finding)[0] == already_double
