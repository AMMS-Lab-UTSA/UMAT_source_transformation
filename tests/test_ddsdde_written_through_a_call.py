"""A CALL that hands DDSDDE to a routine is a place DDSDDE gets written.

A Fortran dummy argument is writable unless the callee says otherwise, so
``CALL voigt_notation_tangent(CC, NTENS, indices, DDSDDE)`` writes the old
tangent just as surely as ``DDSDDE(I,J) = CC(I,J)`` does -- and the GETIM
extraction has to be placed after it, or the callee's result lands on top of
the OTI tangent and the generated UMAT quietly returns the very thing it was
supposed to replace. That is the failure mode this project keeps meeting: it
compiles, it runs, and the number is wrong.

The assignment itself is in another program unit, where the UMAT's line
ordering says nothing about when it happens. What places it is the call.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.core.transformation_anchors import (  # noqa: E402
    _ddsdde_writing_call_lines,
)
from umat_oti.transform.source_transform import (  # noqa: E402
    _overwritten_through_its_call_sites, _uncovered_ddsdde_blockers,
)

CONFIG = {"source_file": "probe.f"}


def _parse(text: str):
    """A ParsedFortranSource for fixed-form text, without touching the disk."""
    from umat_oti.fortran.parser import (  # noqa: PLC0415
        ParsedFortranSource, logical_lines_from_text, parse_subroutines,
    )
    lines = logical_lines_from_text(text, "fixed")
    return ParsedFortranSource(Path("probe.f"), "fixed", text, lines,
                               parse_subroutines(lines))

FIXED_FORM = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
      DIMENSION STRESS(6),DDSDDE(6,6)
      STRESS(1)=1.0D0
      CALL TANGENT(CC, 6,
     1 DDSDDE)
      RETURN
      END
      SUBROUTINE TANGENT(CC,NTENS,DDSDDE)
      DDSDDE(1,1)=CC
      RETURN
      END
"""


class TestFindingTheCallsThatWriteIt:
    def test_a_call_passing_ddsdde_is_found(self):
        assert _ddsdde_writing_call_lines(CONFIG, FIXED_FORM, (1, 7)) == [5]

    def test_a_continued_call_is_reported_at_its_last_line(self):
        # The argument sits on the continuation line, and the extraction has
        # to go after the whole statement, not after the word CALL.
        assert max(_ddsdde_writing_call_lines(CONFIG, FIXED_FORM, (1, 7))) == 5

    def test_a_call_not_passing_ddsdde_is_not_one(self):
        source = FIXED_FORM.replace("CALL TANGENT(CC, 6,\n     1 DDSDDE)",
                                    "CALL TANGENT(CC, 6,\n     1 SIX)")
        assert _ddsdde_writing_call_lines(CONFIG, source, (1, 7)) == []

    def test_a_name_that_merely_contains_ddsdde_is_not_ddsdde(self):
        source = FIXED_FORM.replace("     1 DDSDDE)", "     1 DDSDDE_OLD)")
        assert _ddsdde_writing_call_lines(CONFIG, source, (1, 7)) == []

    def test_a_call_outside_the_selected_routine_is_not_counted(self):
        # Another UMAT in the same file writes its own DDSDDE. Its calls
        # cannot move this routine's extraction point.
        assert _ddsdde_writing_call_lines(CONFIG, FIXED_FORM, (8, 11)) == []


class TestJudgingTheAssignmentAtItsCallSite:
    def _parsed(self):
        return _parse(FIXED_FORM)

    def test_a_write_before_the_extraction_is_overwritten(self):
        parsed = self._parsed()
        assert _overwritten_through_its_call_sites(
            [9], (1, 7), parsed, "UMAT", extraction_line=5, last_stress_end=3)

    def test_a_write_after_the_extraction_survives_and_blocks(self):
        parsed = self._parsed()
        assert not _overwritten_through_its_call_sites(
            [9], (1, 7), parsed, "UMAT", extraction_line=3, last_stress_end=3)

    def test_an_assignment_in_the_umat_itself_is_judged_where_it_is_written(self):
        # Its own line is when it happens; there is no call to place it at.
        parsed = self._parsed()
        assert not _overwritten_through_its_call_sites(
            [3], (1, 7), parsed, "UMAT", extraction_line=99, last_stress_end=3)

    def test_no_extraction_point_means_refuse(self):
        parsed = self._parsed()
        assert not _overwritten_through_its_call_sites(
            [9], (1, 7), parsed, "UMAT", extraction_line=0, last_stress_end=3)

    def test_no_parse_means_refuse(self):
        assert not _overwritten_through_its_call_sites(
            [9], (1, 7), None, "UMAT", extraction_line=5, last_stress_end=3)

    def test_a_call_inside_the_stress_update_still_blocks(self):
        # The old tangent would land in DDSDDE while the stress is still being
        # built from it, and no derivative survives that REAL array.
        assert not _overwritten_through_its_call_sites(
            [9], (1, 7), _parse(FIXED_FORM), "UMAT",
            extraction_line=6, last_stress_end=6)

    def test_an_uncallable_routine_means_refuse(self):
        # Nothing in the UMAT reaches it, so nothing places its write.
        parsed = self._parsed()
        assert not _overwritten_through_its_call_sites(
            [9], (1, 7), parsed, "TANGENT", extraction_line=99, last_stress_end=3)


class TestTheBlockerItself:
    ANALYSIS = {"assignments_to_ddsdde": [
        {"line_numbers": [9], "text": "DDSDDE(1,1)=CC"}]}
    STRESS = [{"start_line": 3, "end_line": 3}]

    def test_it_blocks_without_the_evidence_to_clear_it(self):
        blockers = _uncovered_ddsdde_blockers(
            self.ANALYSIS, [], self.STRESS, [], None)
        assert len(blockers) == 1

    def test_it_clears_once_the_call_site_places_the_write(self):
        blockers = _uncovered_ddsdde_blockers(
            self.ANALYSIS, [], self.STRESS, [], None, _parse(FIXED_FORM), "UMAT", 5)
        assert blockers == []

    def test_it_still_blocks_when_the_call_comes_after_extraction(self):
        blockers = _uncovered_ddsdde_blockers(
            self.ANALYSIS, [], self.STRESS, [], None, _parse(FIXED_FORM), "UMAT", 4)
        assert len(blockers) == 1
