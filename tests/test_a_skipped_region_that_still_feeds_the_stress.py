"""A "tangent helper" skip that deletes something the stress path reads.

The transform commutes a region out when its outputs feed only the old DDSDDE
block. When such a region also DEFINES a quantity the stress path reads
afterwards, the reading code is left with whatever the declaration gave it --
zero -- and the converted routine returns a stress that is not the author's,
with no blocker and a clean compile.

MEASURED offline with gfortran on
``thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_1EL.for``, store
key fc2b59d324a69a9e922be039. Its transform_report records region TANGENT-007,
lines 249-338, skipped because "DDEVTAUDEPSE feeds only the old DDSDDE/tangent
block". Those lines are the entire local Newton return map of the Maxwell
branch, and they also define ``Je`` and ``PVBe``. Twenty lines later the stress
path reads them::

    PVTAU_OTI(I) = DEVTAU_OTI(I) + KVIS/TWO*(JE_OTI*JE_OTI-ONE)

At ``F = I`` the original returns STRESS = 0 exactly; the converted build
returns -30.6931 on all three direct components, which is ``-KVIS/2`` for that
deck's ``KVIS = 61.3862`` to six figures -- the ``(Je^2 - 1)`` term at
``Je = 0``. Every semantic check in the report passed and both ``blockers`` and
``warnings`` are empty.

Over pass10's 254 entries the detector fires on 25. None of them is among the
44 verified. Three are ``primal_disagreed``, and each of those three is
recorded as "N compared values are not finite" -- which is what dividing by a
quantity left at zero produces. Three more are ``transformed_job_failed``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.truncation import (  # noqa: E402
    skipped_definitions_read_later,
)


SKIPPED_AND_READ = """\
      SUBROUTINE UMAT(STRESS)
      TYPE(ONUMM6N1) :: JE_OTI, PVTAU_OTI(3)
         JE_OTI = 0.0D0
      DO ITER = 1, 200
C     OTIS-SKIP: Je = (PVBe(1)*PVBe(2)*PVBe(3))**(ONE/TWO)
      END DO
      DO I=1,3
         PVTAU_OTI(I) = DEVTAU_OTI(I) + KVIS/TWO*(JE_OTI*JE_OTI-ONE)
      END DO
      RETURN
      END
"""

SKIPPED_AND_NEVER_READ = """\
      SUBROUTINE UMAT(STRESS)
      DO ITER = 1, 200
C     OTIS-SKIP: DDEVTAUDEPSe(1,1) = MUVIS * ALPHAVIS
      END DO
      STRESS(1) = TAU_OTI(1)
      RETURN
      END
"""

SKIPPED_THEN_REDEFINED = """\
      SUBROUTINE UMAT(STRESS)
C     OTIS-SKIP: Je = (PVBe(1)*PVBe(2)*PVBe(3))**(ONE/TWO)
      JE_OTI = DETF_OTI
      STRESS(1) = JE_OTI
      RETURN
      END
"""


@pytest.mark.unit
def test_a_skipped_definition_the_stress_path_reads_is_reported():
    found = skipped_definitions_read_later(SKIPPED_AND_READ)
    assert [f.name for f in found] == ["JE"]  # the author's name, which the skip deleted
    assert found[0].defined_at == 5
    assert found[0].read_at == 8
    assert "PVTAU_OTI" in found[0].text


@pytest.mark.unit
def test_a_skipped_definition_nothing_reads_is_not_reported():
    """The skip is the point: a tangent helper nobody reads costs nothing."""
    assert skipped_definitions_read_later(SKIPPED_AND_NEVER_READ) == ()


@pytest.mark.unit
def test_a_skipped_definition_live_code_replaces_is_not_reported():
    """Assigned again before any read, so the deleted line changed nothing."""
    assert skipped_definitions_read_later(SKIPPED_THEN_REDEFINED) == ()


@pytest.mark.unit
def test_a_source_with_no_skipped_region_reports_nothing():
    assert skipped_definitions_read_later(
        "      SUBROUTINE UMAT(STRESS)\n      STRESS(1) = 1.0D0\n      END\n") == ()


@pytest.mark.unit
def test_the_shadow_and_the_real_name_are_the_same_variable():
    """``Je`` is skipped and ``JE_OTI`` is read; they are one variable.

    The emitter writes the skipped line as the author wrote it and the live
    line with the promoted name, so a reader matching names literally sees two
    different variables and reports nothing.
    """
    found = skipped_definitions_read_later(SKIPPED_AND_READ)
    assert found, "matching JE_OTI back to the skipped Je is the whole check"
