"""Abaqus/Standard 2021.HF5 here aborts when a user subroutine prints.

Two decks identical but for one line. A minimal elastic UMAT completes; the
same routine with ``print*,'ELAM',ELAM`` added aborts in the element loop --
three runs out of three, in a clean directory, with nothing else changed. 179
of the corpus's 391 sources carry such a statement, and the ones whose
statement is on the executed path cannot be run here at all:
``ISOTROPIC-ELASTICITY.for`` prints its Lame constant on every call and its
job leaves no .sta, no .msg error count and no increments.

So the copy that is compiled has them commented out. That cannot change what
a routine computes, and this is not an assertion: a Fortran output statement
assigns nothing unless it carries IOSTAT=, ERR=, END=, IOMSG= or SIZE=, and
one that carries any of those is left alone. A labelled statement becomes
CONTINUE, because the label may be a branch target. It is done identically for
every build in a comparison and for the replay the finite difference is taken
from, and the text of every line touched goes into the record.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.probe import silence_console_writes  # noqa: E402

FIXED = """\
      SUBROUTINE UMAT(STRESS,DSTRAN,NTENS)
      INTEGER NTENS, K1
      DOUBLE PRECISION STRESS(NTENS), DSTRAN(NTENS), E
      E = 210000.0D0
      print*,'E',E
      WRITE(6,*) 'stress', STRESS(1)
      WRITE(*,'(A)') 'starting'
      DO K1 = 1, NTENS
        STRESS(K1) = STRESS(K1) + E*DSTRAN(K1)
      END DO
      RETURN
      END
"""


def test_a_print_is_removed():
    out, removed = silence_console_writes(FIXED)
    assert len(removed) == 3
    assert "print*,'E',E" in removed[0]
    assert "OTIS-SILENCED" in out
    assert out.count("OTIS-SILENCED") == 3


def test_the_computation_is_untouched():
    out, _ = silence_console_writes(FIXED)
    assert "STRESS(K1) = STRESS(K1) + E*DSTRAN(K1)" in out
    assert "E = 210000.0D0" in out


def test_a_write_that_can_assign_is_left_alone():
    """IOSTAT= makes an output statement assign something, so removing it
    would change what the routine computes."""
    source = FIXED.replace("      WRITE(6,*) 'stress', STRESS(1)\n",
                           "      WRITE(6,*,IOSTAT=IOS) 'stress', STRESS(1)\n")
    out, removed = silence_console_writes(source)
    assert "IOSTAT=IOS" in out
    assert all("IOSTAT" not in line for line in removed)


def test_a_write_to_another_unit_is_left_alone():
    """Unit 7 is the .dat file, and the probe's own unit is 197. Neither is
    standard output and neither is this function's business."""
    source = FIXED.replace("      WRITE(6,*) 'stress', STRESS(1)\n",
                           "      WRITE(7,*) 'stress', STRESS(1)\n")
    out, removed = silence_console_writes(source)
    assert "WRITE(7,*)" in out
    assert len(removed) == 2


def test_a_labelled_statement_becomes_continue():
    """The label may be a branch target; deleting it would break the jump."""
    source = FIXED.replace("      print*,'E',E\n",
                           "  100 print*,'E',E\n")
    out, _ = silence_console_writes(source)
    assert "100 CONTINUE" in out


def test_a_continued_write_is_removed_whole():
    source = FIXED.replace(
        "      WRITE(6,*) 'stress', STRESS(1)\n",
        "      WRITE(6,*) 'stress', STRESS(1),\n"
        "     1  'and more', STRESS(2)\n")
    out, removed = silence_console_writes(source)
    live = [line for line in out.splitlines() if line[:1] not in "cC*!"]
    assert not any("and more" in line for line in live), (
        "the continuation is part of the statement and goes with it")
    assert out.count("OTIS-SILENCED") == 4
    whole = next(text for text in removed if "and more" in text)
    assert whole.count("\n") == 1, "the record shows the whole statement"


def test_a_comment_after_the_statement_survives():
    """An earlier walk advanced on every comment and swallowed whatever
    followed the statement -- including the next section of the routine."""
    source = FIXED.replace(
        "      print*,'E',E\n",
        "      print*,'E',E\n"
        "C\n"
        "C ELASTIC STIFFNESS\n")
    out, removed = silence_console_writes(source)
    assert len(removed) == 3
    assert "C ELASTIC STIFFNESS" in out
    assert "OTIS-SILENCED: C ELASTIC STIFFNESS" not in out


def test_a_free_form_file_gets_a_free_form_comment_marker():
    """A C in column 1 of a free-form file is a syntax error, and a source
    that will not compile is a job that leaves no .sta -- which is the very
    failure this whole function exists to remove."""
    free = ("subroutine umat(stress)\n"
            "  double precision :: stress(6)\n"
            "  write(*,*) 'hello'\n"
            "  stress(1) = 1.0d0\n"
            "end subroutine\n")
    out, _ = silence_console_writes(free, "free")
    silenced = [line for line in out.splitlines() if "OTIS-SILENCED" in line]
    assert silenced and all(line.lstrip().startswith("!") for line in silenced)
    fixed, _ = silence_console_writes(free, "fixed")
    assert any(line.startswith("C") for line in fixed.splitlines()
               if "OTIS-SILENCED" in line)


def test_free_form_prints_are_removed_too():
    free = ("subroutine umat(stress, dstran, ntens)\n"
            "  implicit none\n"
            "  integer :: ntens, k1\n"
            "  double precision :: stress(ntens), dstran(ntens)\n"
            "  write(*,*) 'hello', &\n"
            "             ntens\n"
            "  do k1 = 1, ntens\n"
            "    stress(k1) = stress(k1) + dstran(k1)\n"
            "  end do\n"
            "end subroutine\n")
    out, removed = silence_console_writes(free)
    assert len(removed) == 1
    assert "stress(k1) = stress(k1) + dstran(k1)" in out


@pytest.mark.fortran
def test_the_result_still_compiles(tmp_path: Path):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran is not on PATH")
    out, _ = silence_console_writes(FIXED)
    unit = tmp_path / "umat.f"
    unit.write_text(out, encoding="utf-8")
    done = subprocess.run(
        ["gfortran", "-c", "-ffixed-line-length-132", "-std=legacy", "-w",
         str(unit), "-o", str(tmp_path / "umat.o")],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.fortran
def test_a_labelled_print_still_compiles_and_keeps_its_label(tmp_path: Path):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran is not on PATH")
    source = ("      SUBROUTINE UMAT(STRESS,NTENS)\n"
              "      INTEGER NTENS\n"
              "      DOUBLE PRECISION STRESS(NTENS)\n"
              "      IF (NTENS .GT. 0) GO TO 100\n"
              "  100 PRINT *, 'here'\n"
              "      STRESS(1) = 1.0D0\n"
              "      RETURN\n"
              "      END\n")
    out, _ = silence_console_writes(source)
    unit = tmp_path / "labelled.f"
    unit.write_text(out, encoding="utf-8")
    done = subprocess.run(
        ["gfortran", "-c", "-ffixed-line-length-132", "-std=legacy", "-w",
         str(unit), "-o", str(tmp_path / "labelled.o")],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
