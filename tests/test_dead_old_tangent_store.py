"""An old-tangent write that nothing reads before the extraction is dead.

The emitter keeps an old-tangent line when a stress region also covers it,
because dropping a statement the stress needs would break the stress. That is
right for a statement doing two jobs, and wrong for a statement whose left-hand
side is DDSDDE -- that one does a single job, writing the tangent, and the GETIM
extraction rewrites every entry of DDSDDE afterwards.

Three crystal-plasticity UMATs failed the old_ddsdde_assignments_disabled check
on exactly one statement each: DDSDDE(I,J)=DDSDE1(I,J), restoring a scratch copy
of the author's own hand-coded tangent three hundred lines after the last thing
that reads DDSDDE. The check was right to refuse -- the old tangent really was
still being written -- and the emission was what needed fixing.

The rule fails closed. Anything it cannot establish keeps the statement, because
a surviving old tangent that is overwritten is harmless while a dropped
statement the stress needed is not.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.transform.source_transform import _dead_old_tangent_store  # noqa: E402


def _lines(text: str) -> list[str]:
    return text.splitlines()


class TestADeadStoreIsRecognised:
    def test_nothing_reads_it_before_the_extraction(self):
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "      X = 1.0\n"
                       "      CONTINUE\n")
        assert _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")

    def test_a_later_store_to_it_does_not_revive_it(self):
        # Two stores and no read between them: both are overwritten.
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "      DDSDDE(1,1)=0.0\n"
                       "      CONTINUE\n")
        assert _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")


class TestAnythingUnestablishedKeepsTheStatement:
    def test_a_plain_read_keeps_it(self):
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "      Q = DDSDDE(1,1)\n"
                       "      CONTINUE\n")
        assert not _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")

    def test_a_self_referential_update_keeps_it(self):
        # DDSDDE(I,J) = DDSDDE(I,J) - X reads the value it is about to replace.
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "      DDSDDE(I,J)=DDSDDE(I,J)-STRESS(I)\n"
                       "      CONTINUE\n")
        assert not _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")

    def test_a_call_that_is_handed_it_keeps_it(self):
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "      CALL TIDY(DDSDDE)\n"
                       "      CONTINUE\n")
        assert not _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")

    def test_no_extraction_point_keeps_it(self):
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n      CONTINUE\n")
        assert not _dead_old_tangent_store(lines, 1, 0, "DDSDDE", "fixed")

    def test_a_store_after_the_extraction_keeps_it(self):
        # Nothing overwrites it; it is the last word on DDSDDE.
        lines = _lines("      X = 1.0\n      DDSDDE(I,J)=DDSDE1(I,J)\n")
        assert not _dead_old_tangent_store(lines, 2, 1, "DDSDDE", "fixed")

    def test_a_comment_mentioning_it_is_not_a_read(self):
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "C     DDSDDE is the tangent\n"
                       "      CONTINUE\n")
        assert _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")

    def test_a_component_of_another_name_is_not_a_read(self):
        lines = _lines("      DDSDDE(I,J)=DDSDE1(I,J)\n"
                       "      Q = SHV%DDSDDE\n"
                       "      CONTINUE\n")
        assert _dead_old_tangent_store(lines, 1, 3, "DDSDDE", "fixed")

    def test_a_renamed_output_array_is_followed(self):
        lines = _lines("      DTANG(I,J)=SAVED(I,J)\n"
                       "      Q = DTANG(1,1)\n"
                       "      CONTINUE\n")
        assert not _dead_old_tangent_store(lines, 1, 3, "DTANG", "fixed")
