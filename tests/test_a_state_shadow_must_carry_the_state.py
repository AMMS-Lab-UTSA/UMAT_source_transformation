"""A shadow of the state array that is neither filled nor emptied is not memory.

``awhelanUCD/Lemaitre-damage-UMAT-Public/HETVAL_nonLocalLemaitre/
HETVAL_lemaitreDamageNonLocal.f`` transformed, compiled cleanly and produced a
stress and a tangent for 140 recorded increments, every one of them computed
from a state that was identically zero. The emitted routine declares
``TYPE(ONUMM3N1) :: STATEV_OTI(nstatv)``, zeroes it on entry, reads the
author's damage, equivalent plastic strain and stored stress out of it, writes
the updated ones back into it -- and never copies ``STATEV`` into the shadow
nor ``REAL(STATEV_OTI)`` back into ``STATEV``. The material starts every
increment undamaged and unhardened, and Abaqus is handed a tangent of that.

Both halves are gated on the same condition in the emitter,
``statev in roles["promote"]``, and ``copied`` excludes the state array from
the generic copy path whether that condition held or not, so when it does not
hold the shadow is declared and left disconnected at both ends. Its sibling in
the same repository, ``nonLocalLemaitre/lemaitreDamageNonLocal.f``, gets both
loops; 1,191 of the 1,206 store entries get both loops. The defect is narrow
and it is silent, which is the combination that makes it worth a check rather
than a comment.

The check refuses rather than repairs. What the emitter should have decided is
a question about the role assignment upstream of it, and guessing an answer
would put a copy-in on a source whose state array is not the one the shadow
belongs to. A refusal names the defect and returns no file; an emitted file
here returns a number nobody can tell from a right one.
"""
import pytest

from umat_oti.transform.source_transform import (
    _state_shadow_is_connected_to_the_state_array)

_SEEDED_AND_WRITTEN = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV)
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      DO OTI_I = 1, NSTATV
         STATEV_OTI(OTI_I) = STATEV(OTI_I)
      END DO
      STATEV_OTI(1) = STATEV_OTI(1) + DSTRAN_OTI(1)
      DO OTI_I = 1, NSTATV
         STATEV(OTI_I) = REAL(STATEV_OTI(OTI_I))
      END DO
      END
"""

_NEVER_SEEDED = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV)
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      DO OTI_HI = 1, NSTATV
         STATEV_OTI(OTI_HI) = 0.0D0
      END DO
      STATEV_OTI(1) = STATEV_OTI(1) + DSTRAN_OTI(1)
      DO OTI_I = 1, NSTATV
         STATEV(OTI_I) = REAL(STATEV_OTI(OTI_I))
      END DO
      END
"""

_NEVER_WRITTEN_BACK = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV)
      TYPE(ONUMM6N1) :: STATEV_OTI(NSTATV)
      DO OTI_I = 1, NSTATV
         STATEV_OTI(OTI_I) = STATEV(OTI_I)
      END DO
      STATEV_OTI(1) = STATEV_OTI(1) + DSTRAN_OTI(1)
      END
"""

_NO_STATE_SHADOW = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV)
      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)
      DO OTI_I = 1, NTENS
         STRESS_OTI(OTI_I) = STRESS(OTI_I)
      END DO
      END
"""


@pytest.mark.unit
def test_a_state_shadow_filled_and_emptied_passes():
    assert _state_shadow_is_connected_to_the_state_array(
        _SEEDED_AND_WRITTEN, "fixed", "STATEV")


@pytest.mark.unit
def test_a_state_shadow_that_is_never_filled_fails():
    """The routine would compute its whole response from zeroes."""
    assert not _state_shadow_is_connected_to_the_state_array(
        _NEVER_SEEDED, "fixed", "STATEV")


@pytest.mark.unit
def test_a_state_shadow_that_is_never_emptied_fails():
    """Abaqus reads the state back out of STATEV; nothing reached it."""
    assert not _state_shadow_is_connected_to_the_state_array(
        _NEVER_WRITTEN_BACK, "fixed", "STATEV")


@pytest.mark.unit
def test_a_routine_with_no_state_shadow_is_not_asked_the_question():
    """A UMAT that shadows no state array has no disconnected shadow."""
    assert _state_shadow_is_connected_to_the_state_array(
        _NO_STATE_SHADOW, "fixed", "STATEV")


@pytest.mark.unit
def test_the_check_reads_the_configured_state_name():
    """The interface is positional; the author names the argument."""
    renamed = _SEEDED_AND_WRITTEN.replace("STATEV", "SVARS")
    assert _state_shadow_is_connected_to_the_state_array(renamed, "fixed", "SVARS")
    assert not _state_shadow_is_connected_to_the_state_array(
        _NEVER_SEEDED.replace("STATEV", "SVARS"), "fixed", "SVARS")


@pytest.mark.unit
def test_the_check_is_one_of_the_semantic_post_checks():
    """A property nothing evaluates is documentation, not a check."""
    import inspect

    from umat_oti.transform.source_transform import _semantic_checks

    body = inspect.getsource(_semantic_checks)
    assert "state_shadow_carries_the_state" in body
    assert "_state_shadow_is_connected_to_the_state_array(" in body
