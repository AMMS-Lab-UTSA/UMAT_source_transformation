"""A hypercomplex value handed to a routine that still takes REALs.

Fortran's implicit interface makes it compile. gfortran emits at most
-Wargument-mismatch and exits 0, so the file is reported as a successful
transformation -- and the callee then reads an ONUMM element, seven doubles,
as a single REAL and computes the whole constitutive response on
reinterpreted memory. One discovered source returned a wrong stress and a NaN
tangent that way with all seventeen semantic checks passing.
"""
from __future__ import annotations

import pytest

from umat_oti.transform.source_transform import (
    oti_arguments_into_untransformed_calls as leaks,
)

SOURCE = (
    "      SUBROUTINE UMAT(STRESS)\n"
    "      CALL CALCDET33(DFGRD1_OTI, DETJ)\n"
    "      CALL KCLEAR(A_OTI, 3, 3)\n"
    "      CALL MYHELPER(STRESS_OTI)\n"
    "C     CALL COMMENTED(X_OTI)\n"
    "      CALL PLAIN(STRESS)\n"
    "      END\n"
    "      SUBROUTINE MYHELPER(S)\n"
    "      END\n")


def _names(source, lifted=None):
    return {callee for callee, _ in leaks(source, "fixed", lifted or set())}


class TestWhatCounts:
    def test_an_external_callee_taking_a_shadow_is_reported(self):
        assert "CALCDET33" in _names(SOURCE)

    def test_the_argument_is_named_too_so_the_message_can_say_which(self):
        assert ("CALCDET33", "DFGRD1_OTI") in leaks(SOURCE, "fixed", set())

    def test_a_routine_defined_in_the_same_file_is_safe(self):
        assert "MYHELPER" not in _names(SOURCE)

    def test_an_inlineable_helper_is_safe(self):
        """No call survives inlining, so there is nothing to mismatch."""
        assert "KCLEAR" not in _names(SOURCE)

    def test_a_call_with_no_shadow_argument_is_not_reported(self):
        assert "PLAIN" not in _names(SOURCE)

    def test_a_commented_call_is_not_a_call(self):
        assert "COMMENTED" not in _names(SOURCE)


class TestWhatIsAlreadySafe:
    """The rewritten call is the safe case, and must not read as the unsafe one."""

    REWRITTEN = ("      SUBROUTINE UMAT(STRESS)\n"
                 "      CALL DETMATRIX_OTI(F_OTI, DETF_OTI)\n"
                 "      END\n")

    def test_a_call_pointed_at_a_lifted_body_is_safe(self):
        assert _names(self.REWRITTEN, {"DETMATRIX"}) == set()

    def test_without_the_suffix_rule_every_lifted_helper_would_be_condemned(self):
        """Guards the fix: the lifted set holds original names, not _OTI ones."""
        assert "DETMATRIX_OTI" not in _names(self.REWRITTEN, {"DETMATRIX"})

    def test_a_suffixed_call_to_something_never_lifted_is_still_reported(self):
        assert "MYSTERY_OTI" in _names(
            "      CALL MYSTERY_OTI(A_OTI)\n", set())


def test_a_lifted_helper_named_directly_is_safe():
    assert _names("      CALL KHELPER(A_OTI)\n", {"KHELPER"}) == set()


def test_every_leak_is_reported_once_per_callee_and_argument():
    source = ("      CALL EXT(A_OTI)\n" * 3) + "      CALL EXT(B_OTI)\n"
    found = leaks(source, "fixed", set())
    assert sorted(found) == [("EXT", "A_OTI"), ("EXT", "B_OTI")]
