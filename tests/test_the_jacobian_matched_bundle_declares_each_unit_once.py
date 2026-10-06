"""The Jacobian-matched bundle holds the author's file twice in one
compilation. A module defined in both copies, and a main program in both (a
bare END that closes an implicit one, as in abuganza UMAT_Tissue_*.f), are
conflicting declarations: 'Declaration of module NUMKIND conflicts with a
previous declaration' (NeoHookean_umat) and 'Declaration of routine
_UNNAMED_MAIN$$ conflicts' (abuganza x3). The bundle did not compile and the
row was recorded as a primal disagreement at pass22.
"""
import re

import pytest

from umat_oti.abaqus.replay import drop_shared_modules, jacobian_matched_source

pytestmark = pytest.mark.unit

FREE = """\
module NumKind
  implicit none
  integer, parameter :: dp = kind(1.0d0)
end module NumKind

subroutine umat(stress, statev)
  use NumKind
  real(dp) :: stress(*), statev(*)
  stress(1) = 1.0_dp
end subroutine umat
"""

FREE_T = FREE.replace("stress(1) = 1.0_dp", "stress(1) = 1.0_dp  ! converted")

FIXED = """      SUBROUTINE UMAT(STRESS,STATEV)
      DIMENSION STRESS(*),STATEV(*)
      STRESS(1) = 1.0D0
      RETURN
      END
C...  ------------------------------------------------------------------
      END
"""


def _statements(text, marker):
    return [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(marker)]


def test_a_module_defined_in_both_copies_is_kept_in_the_first_only():
    bundle, note = jacobian_matched_source(FREE, FREE_T, "free")
    assert note["modules_dropped_from_the_transformed_copy"] == ["NUMKIND"]
    live = _statements(bundle, "!")
    assert sum(bool(re.match(r"\s*module\s+numkind\s*$", l, re.I)) for l in live) == 1
    assert "OTIS-REMOVED (module NUMKIND is the original copy's)" in bundle
    # both routines still compile against the one module: the use statements stay
    assert sum(bool(re.match(r"\s*use\s+numkind\s*$", l, re.I)) for l in live) == 2


def test_a_module_that_differs_is_kept_and_named_not_silently_dropped():
    different = FREE_T.replace("kind(1.0d0)", "kind(1.0)")
    text, note = drop_shared_modules(FREE, different, True)
    assert note["modules_that_differ"] == ["NUMKIND"] and not note["modules_dropped_from_the_transformed_copy"]
    assert text.count("module NumKind") == 2


def test_the_comments_and_case_of_a_module_do_not_make_it_a_different_one():
    shouted = FREE.upper().replace("DP", "dp") + "\n"
    shouted = shouted.replace("SUBROUTINE UMAT", "subroutine umat")
    text, note = drop_shared_modules(FREE, "! a comment\n" + FREE.replace("module", "MODULE"), True)
    assert note["modules_dropped_from_the_transformed_copy"] == ["NUMKIND"]


def test_the_bare_end_that_closes_an_implicit_main_is_dropped_from_the_second_copy_only():
    bundle, note = jacobian_matched_source(FIXED, FIXED, "fixed")
    assert note["main_programs_dropped_from_the_transformed_copy"] == ["(implicit main program)"]
    live_ends = [l for l in bundle.splitlines()
                 if re.match(r"\s{6}END\s*$", l, re.I)]
    # UMATO, its implicit main's END, UMATT, the wrapper's UMAT: the transformed copy's stray END is gone
    assert len(live_ends) == 4
    assert "OTIS-REMOVED (a bare END closing an implicit main program)" in bundle
    # one main program remains: the original copy's
    assert bundle.count("a bare END closing an implicit main program") == 1


def test_a_source_with_neither_is_unchanged_in_structure():
    plain = "      SUBROUTINE UMAT(S)\n      S = 1\n      RETURN\n      END\n"
    bundle, note = jacobian_matched_source(plain, plain, "fixed")
    assert not note["modules_dropped_from_the_transformed_copy"] and not note["main_programs_dropped_from_the_transformed_copy"]
    assert "OTIS-REMOVED" not in bundle
