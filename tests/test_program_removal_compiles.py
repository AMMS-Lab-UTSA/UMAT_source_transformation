"""The cleaned source must still be Fortran, in whichever form it was.

`C` in column one is a fixed-form comment and a syntax error in free form. A
.f90 cleaned with it fails to compile, which turns one link error ("multiple
definition of `main`") into a different one -- and the row still reports that
the tangent could not be measured.

These compile the cleaned files with gfortran rather than checking strings,
because whether a comment marker is valid is a question for the compiler.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.replay import without_the_authors_program  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None,
                                reason="gfortran is not on PATH")

FIXED = ("      SUBROUTINE UMATX(S)\n      REAL S\n      S = 1.0\n"
         "      RETURN\n      END\n"
         "      PROGRAM DRV\n      REAL X\n      CALL UMATX(X)\n"
         "      END PROGRAM DRV\n")

FREE = ("subroutine umatx(s)\n  real :: s\n  s = 1.0\nend subroutine umatx\n"
        "program drv\n  real :: x\n  call umatx(x)\nend program drv\n")


def _compile(tmp_path, name, text):
    source = tmp_path / name
    source.write_text(text)
    obj = tmp_path / (name + ".o")
    done = subprocess.run(["gfortran", "-c", str(source), "-o", str(obj)],
                          capture_output=True, text=True, cwd=tmp_path)
    return done, obj


def test_a_cleaned_fixed_form_source_compiles(tmp_path):
    cleaned, removed = without_the_authors_program(FIXED)
    assert removed == ("DRV",)
    done, _obj = _compile(tmp_path, "t.f", cleaned)
    assert done.returncode == 0, done.stderr


def test_a_cleaned_free_form_source_compiles(tmp_path):
    """The case a fixed-form marker breaks."""
    cleaned, removed = without_the_authors_program(FREE)
    assert removed == ("drv",)
    done, _obj = _compile(tmp_path, "t.f90", cleaned)
    assert done.returncode == 0, done.stderr


def test_the_marker_follows_the_form():
    fixed_lines = [l for l in without_the_authors_program(FIXED)[0].splitlines()
                   if "OTIS-REMOVED" in l]
    free_lines = [l for l in without_the_authors_program(FREE)[0].splitlines()
                  if "OTIS-REMOVED" in l]
    assert fixed_lines and fixed_lines[0].startswith("C")
    assert free_lines and free_lines[0].startswith("!")


def test_neither_cleaned_object_defines_main(tmp_path):
    """The whole point: two mains in one link is what failed."""
    if shutil.which("nm") is None:
        pytest.skip("nm is not on PATH")
    for name, text in (("t.f", FIXED), ("t.f90", FREE)):
        cleaned, _removed = without_the_authors_program(text)
        done, obj = _compile(tmp_path, name, cleaned)
        assert done.returncode == 0, done.stderr
        symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True)
        assert " T main" not in symbols.stdout


def test_the_subroutine_still_compiles_into_the_object(tmp_path):
    """Removing the program must not remove what the replay needs."""
    cleaned, _removed = without_the_authors_program(FIXED)
    done, obj = _compile(tmp_path, "t.f", cleaned)
    assert done.returncode == 0
    if shutil.which("nm"):
        symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True)
        assert "umatx_" in symbols.stdout.lower()


def test_several_programs_are_all_removed_and_the_rest_survives(tmp_path):
    text = ("      PROGRAM A\n      END\n"
            "      SUBROUTINE UMATX(S)\n      REAL S\n      S=1.0\n      END\n"
            "      PROGRAM B\n      END\n")
    cleaned, removed = without_the_authors_program(text)
    assert removed == ("A", "B")
    done, _obj = _compile(tmp_path, "t.f", cleaned)
    assert done.returncode == 0, done.stderr


def test_a_preprocessor_line_survives_untouched():
    """It is read before the compiler sees the form, so commenting it out
    would change what gets compiled."""
    text = "#include <x.h>\n      PROGRAM P\n      END\n"
    cleaned, _removed = without_the_authors_program(text)
    assert cleaned.splitlines()[0] == "#include <x.h>"


def test_cleaned_copies_cannot_collide():
    """Two helper files in one bundle can share a name, and the second would
    otherwise overwrite the first's cleaned copy."""
    source = (Path(__file__).resolve().parents[1] / "src" / "umat_oti"
              / "abaqus" / "replay.py").read_text(encoding="utf-8")
    assert 'f"noprogram_{index}_{unit.name}"' in source


# ---- the implicit main program, which has no PROGRAM statement ----------
IMPLICIT_MAIN = ("      subroutine umatx(s)\n      real s\n      s = 1.0\n"
                 "      end\n"
                 "c...  a bare END with nothing open closes an implicit main\n"
                 "      end\n")


def test_a_bare_end_with_nothing_open_is_an_implicit_main_program():
    """Fortran lets a main program omit the PROGRAM statement entirely, and
    gfortran still compiles it into `main`.

    Measured on UMAT_Tissue_2d_plane_strain.f: five subprogram headers, six
    ENDs, no PROGRAM statement anywhere -- and the replay link failed with
    "multiple definition of `main` ... first defined here" naming the UMAT's
    own object. Searching for the PROGRAM keyword found nothing, which is why
    the first fix did not touch this case.
    """
    cleaned, removed = without_the_authors_program(IMPLICIT_MAIN)
    assert removed == ("(implicit main program)",)


def test_the_cleaned_implicit_main_defines_no_main(tmp_path):
    if shutil.which("nm") is None:
        pytest.skip("nm is not on PATH")
    cleaned, _removed = without_the_authors_program(IMPLICIT_MAIN)
    done, obj = _compile(tmp_path, "t.f", cleaned)
    assert done.returncode == 0, done.stderr
    symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True)
    assert " T main" not in symbols.stdout


def test_a_subprograms_own_end_is_not_touched(tmp_path):
    """Only an END with nothing open closes an implicit main. An END that
    closes a subroutine must survive, or the file stops being Fortran."""
    text = ("      subroutine umatx(s)\n      real s\n      s=1.0\n      end\n"
            "      subroutine helper(x)\n      real x\n      x=2.0\n      end\n")
    cleaned, removed = without_the_authors_program(text)
    assert removed == ()
    assert cleaned == text
    done, _obj = _compile(tmp_path, "t.f", cleaned)
    assert done.returncode == 0, done.stderr


def test_a_comment_line_does_not_open_or_close_a_unit():
    text = ("c comment\n      subroutine umatx(s)\n      end\n"
            "c another\n      end\n")
    _cleaned, removed = without_the_authors_program(text)
    assert removed == ("(implicit main program)",)
