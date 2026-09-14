"""A logical IF is a condition AND an effect, and both must land in one domain.

Two passes rewrite a transformed UMAT. The assignment pass moves assignments
into the OTI domain; the branch pass moves branch conditions. A logical IF is
both at once:

    IF (ALPHA_G .LT. 0.0D0) ALPHA_G = 0.0D0

The assignment pass will not touch an assignment above the seed insertion
point, because the shadows have not been initialised there yet. The branch
pass had no such gate: it fired on any line of the selected routine that
mentioned a promoted name, wherever it sat, and rewrote the statement above
into

    IF (REAL(ALPHA_G_OTI) .LT. 0.0D0) ALPHA_G_OTI = 0.0D0

whose condition reads the declaration's uninitialised shadow rather than the
value computed one line up, and whose effect lands where the real ALPHA_G never
looks. The clamp compiles, runs, and does nothing; the real variable keeps the
negative value the author wrote the clamp to remove. No leak check can see it,
because both halves are consistently in the shadow domain.

The second half of the same asymmetry is the old-tangent block. A DDSDDE store
written ``IF (cond) DDSDDE(I,J) = ...`` reached the branch pass before the arm
that comments out disabled lines, so a tangent the transform reports as
replaced was emitted live, in OTI form, and ran.

Both are guards on a hazard rather than repairs of a wrong output: measured
over all 391 corpus sources, installing them changed no emitted byte. They are
the precondition for moving the region boundaries, which is what the
cross-routine call-effect dataflow does.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _branch_carries_an_effect, branch_rewrite_is_domain_consistent)

pytestmark = pytest.mark.unit

CLAMP = "      IF (ALPHA_G .LT. 0.0D0) ALPHA_G = 0.0D0"
BLOCK = "      IF (DELTA_M .GT. RT_OLD .AND. DELTA_M .LT. DELTA_MF) THEN"


def test_nothing_is_promoted_above_the_seed_insertion_point():
    assert not branch_rewrite_is_domain_consistent(
        CLAMP, 40, seed_insert_before_line=55, disabled_lines=set())
    assert not branch_rewrite_is_domain_consistent(
        BLOCK, 40, seed_insert_before_line=55, disabled_lines=set())


def test_the_seed_line_itself_is_inside_the_shadow_domain():
    assert branch_rewrite_is_domain_consistent(
        CLAMP, 55, seed_insert_before_line=55, disabled_lines=set())


def test_a_disabled_store_is_not_resurrected_by_its_own_guard():
    assert not branch_rewrite_is_domain_consistent(
        "      IF (NTENS .EQ. 3) DDSDDE(3,3) = DSEC(3,3)", 163,
        seed_insert_before_line=55, disabled_lines={163})


def test_a_block_opener_inside_a_disabled_region_keeps_its_guard_promoted():
    """It has no effect to disagree about, and its real names are gone.

    ``_comment_old_line`` refuses to comment out a block opener, because that
    would leave the ENDIF unbalanced -- so the opener stays whatever else
    happens. Its body is commented out either way, and the real names an
    untouched guard would read are no longer assigned anywhere in the emitted
    routine. Leaving it promoted reads defined shadows instead of undefined
    reals, and changes nothing that runs.
    """
    assert branch_rewrite_is_domain_consistent(
        BLOCK, 152, seed_insert_before_line=55, disabled_lines={152})


def test_what_counts_as_an_effect():
    assert _branch_carries_an_effect(CLAMP)
    assert _branch_carries_an_effect("      IF (A .GT. B) CALL FOO(C)")
    assert _branch_carries_an_effect("      IF (DMG .GE. 1.) DMG = 1.  ! clamp")
    assert not _branch_carries_an_effect(BLOCK)
    assert not _branch_carries_an_effect("      ELSE IF (X .GT. 0) THEN")
    assert not _branch_carries_an_effect("      IF (NTENS .EQ. 3) THEN ")
