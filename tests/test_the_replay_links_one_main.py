"""An author's own PROGRAM must not collide with the replay driver's.

Several corpus sources ship a standalone driver beside the UMAT -- a PROGRAM
the author used to exercise it. The replay driver has its own PROGRAM, and two
mains in one link is `multiple definition of 'main'`. The build then fails and
the row reports that the tangent could not be measured, which is true but says
nothing about the transform: it is the harness failing to link a file it could
have linked. Measured on UMAT_Tissue_2d_plane_strain.f and its plane-stress
twin.

The replay drives the UMAT subroutine directly and never calls the author's
driver, so removing it changes nothing the replay computes. It is commented
rather than deleted so the emitted file still lines up with the original.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.replay import without_the_authors_program  # noqa: E402

WITH_PROGRAM = """      SUBROUTINE UMAT(STRESS)
      RETURN
      END
      PROGRAM DRIVER
      CALL UMAT(1.0)
      END PROGRAM DRIVER
"""


def test_the_authors_program_is_removed():
    out, removed = without_the_authors_program(WITH_PROGRAM)
    assert removed == ("DRIVER",)
    assert not any(line.strip().upper().startswith("PROGRAM")
                   for line in out.splitlines())


def test_the_umat_itself_is_untouched():
    out, _removed = without_the_authors_program(WITH_PROGRAM)
    assert "SUBROUTINE UMAT(STRESS)" in out


def test_a_source_with_no_program_is_unchanged():
    text = "      SUBROUTINE UMAT(STRESS)\n      RETURN\n      END\n"
    out, removed = without_the_authors_program(text)
    assert out == text and removed == ()


def test_the_removal_is_visible_in_the_emitted_file():
    """Commented, not deleted: a reader comparing the emitted file with the
    original has to be able to see what happened and why."""
    out, _removed = without_the_authors_program(WITH_PROGRAM)
    assert "OTIS-REMOVED" in out
    assert "the replay supplies its own" in out


def test_a_bare_end_closes_the_program():
    """Fixed-form sources often close a unit with a bare END."""
    text = ("      SUBROUTINE UMAT(S)\n      END\n"
            "      PROGRAM P\n      CALL UMAT(1.0)\n      END\n")
    out, removed = without_the_authors_program(text)
    assert removed == ("P",)
    assert out.count("OTIS-REMOVED") == 3


def test_a_subroutine_after_the_program_survives():
    """The removal must stop at the program's own END, not swallow the rest
    of the file."""
    text = ("      PROGRAM P\n      END PROGRAM P\n"
            "      SUBROUTINE HELPER(X)\n      RETURN\n      END\n")
    out, _removed = without_the_authors_program(text)
    assert "SUBROUTINE HELPER(X)" in out
    assert "OTIS-REMOVED" not in out.split("SUBROUTINE HELPER")[1]


def test_the_replay_build_uses_the_cleaned_copy():
    source = (Path(__file__).resolve().parents[1] / "src" / "umat_oti"
              / "abaqus" / "replay.py").read_text(encoding="utf-8")
    assert "without_the_authors_program(\n            text, detect_source_form(unit, text))" in source, (
        "the build must pass the unit's own form, or a free-form file\n         gets a fixed-form comment marker")
    assert 'f"noprogram_{index}_{unit.name}"' in source, (
        "the original file on disk must not be rewritten")
