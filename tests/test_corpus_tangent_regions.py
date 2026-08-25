"""Locating a DDSDDE block is a hypothesis, not a transformability verdict.

Ported from the legacy corpus bundle, where it moved `no_ddsdde_region` from 66
to 17 across a 207-UMAT corpus. These tests pin the behaviour that made it worth
porting -- expanding an assignment outward to its enclosing loops -- and the
boundary that keeps it honest: finding nothing is a real answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.corpus.tangent_regions import (
    describe, find_tangent_ranges, is_code_line,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ICP = REPO_ROOT / "UMATs" / "UMATs" / "ICP"

LOOP_TANGENT = """      SUBROUTINE UMAT
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = ZERO
        END DO
      END DO
      END
"""


def test_an_assignment_expands_to_its_enclosing_loops():
    """The whole point: the classifier misses the loop, this finds it."""
    ranges = find_tangent_ranges(LOOP_TANGENT)
    assert len(ranges) == 1
    assert ranges[0].start == 2 and ranges[0].end == 6
    assert ranges[0].as_spec() == "2-6"


def test_a_bare_assignment_is_its_own_range():
    ranges = find_tangent_ranges("      SUBROUTINE UMAT\n      DDSDDE = ZERO\n      END\n")
    assert [r.as_spec() for r in ranges] == ["2-2"]


def test_adjacent_assignments_merge_into_one_region():
    source = "      DDSDDE(1,1) = A\n      DDSDDE(2,2) = B\n"
    ranges = find_tangent_ranges(source)
    assert len(ranges) == 1 and ranges[0].assignments == 2


def test_separated_regions_stay_separate():
    source = "      DDSDDE(1,1) = A\n" + "      X = 1\n" * 6 + "      DDSDDE(2,2) = B\n"
    assert len(find_tangent_ranges(source)) == 2


def test_commented_assignments_are_ignored():
    """A commented-out tangent is not a tangent."""
    for prefix in ("C", "c", "*", "!"):
        assert find_tangent_ranges(f"{prefix}     DDSDDE(1,1) = A\n") == []
    assert is_code_line("      DDSDDE = 1") is True
    assert is_code_line("C     DDSDDE = 1") is False
    assert is_code_line("      ! trailing") is True


def test_a_source_with_no_tangent_says_so():
    result = describe("      SUBROUTINE UMAT\n      END\n", name="flat.for")
    assert result["found"] is False
    assert result["tangent_ranges"] == []
    # an honest negative, and explicitly not a verdict on transformability
    assert "not a transformability" in result["reason"]


def test_the_result_records_where_the_algorithm_came_from():
    result = describe(LOOP_TANGENT)
    assert "corpus_batch.py::_fallback_ranges" in result["provenance"]


@pytest.mark.skipif(not ICP.is_dir(), reason="ICP sources not present")
def test_every_icp_source_yields_a_locatable_region():
    """Twelve real UMATs, including the three with no scalar Newton solve."""
    for path in sorted(ICP.glob("*.for")):
        result = describe(path.read_text(errors="replace"), name=path.name)
        assert result["found"] is True, f"{path.name} has no locatable DDSDDE region"
        for spec in result["tangent_ranges"]:
            start, end = (int(v) for v in spec.split("-"))
            assert 0 < start <= end
