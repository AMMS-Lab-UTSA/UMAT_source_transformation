"""A CALL whose argument list runs onto a continuation line.

Lifting emits the rewritten body as ``NAME_OTI`` and leaves the original
``NAME`` in the file with its REAL dummies, so the call has to be renamed or
it reaches the wrong one. The rename only ever matched a CALL complete on one
line; one viscoplastic UMAT writes its central call over eight:

    CALL INNER_UPDATE(STRESS_OTI, STATEV_OTI,&
       DDSDDE_OTI, SSE_OTI, SPD_OTI, SCD_OTI,  &
       ...

Both compilers accept it -- an external routine has no explicit interface to
check against -- so the first sign of trouble is a derived type read as a real
at run time, which is what the Abaqus run showed as a garbled material frame.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _rewrite_lifted_helper_call,
    oti_arguments_into_untransformed_calls,
)

LIFTED = {"INNER_UPDATE"}


def test_a_continued_call_is_pointed_at_the_lifted_body():
    opening = "            CALL INNER_UPDATE(STRESS_OTI,STATEV_OTI,&"
    assert _rewrite_lifted_helper_call(opening, LIFTED, {}) == (
        "            CALL INNER_UPDATE_OTI(STRESS_OTI,STATEV_OTI,&")


def test_a_call_complete_on_one_line_still_works():
    assert _rewrite_lifted_helper_call(
        "      CALL INNER_UPDATE(A, B)", LIFTED, {}
    ) == "      CALL INNER_UPDATE_OTI(A, B)"


def test_a_continuation_line_of_arguments_is_not_a_call():
    """The paired case: only the line carrying the CALL keyword is rewritten."""
    line = "               DDSDDE_ALPHA_OTI,SSE_ALPHA_OTI,  &"
    assert _rewrite_lifted_helper_call(line, LIFTED, {}) == line


def test_a_continued_call_to_a_routine_that_was_not_lifted_is_left_alone():
    line = "      CALL SOMETHING_ELSE(A,&"
    assert _rewrite_lifted_helper_call(line, LIFTED, {}) == line


def test_a_continued_call_that_also_surfaces_outputs_is_refused():
    """Appending the surfaced arguments needs the closing parenthesis, which is
    on a line this rewrite cannot see. Renaming without them would call the
    lifted routine with too few arguments, so it is refused rather than done
    wrong."""
    with pytest.raises(ValueError, match="continuation"):
        _rewrite_lifted_helper_call(
            "      CALL INNER_UPDATE(A,&", LIFTED,
            {"INNER_UPDATE": [{"caller_variable": "DDSDDE"}]})


def test_the_check_reports_a_bare_call_to_a_lifted_routine():
    """Being in the lifted set is not on its own safe: the lifted body is
    NAME_OTI, so a call that still says NAME reaches the original."""
    source = """      SUBROUTINE UMAT(STRESS_OTI)
      CALL INNER_UPDATE(STRESS_OTI, DDSDDE_OTI)
      END
"""
    leaked = oti_arguments_into_untransformed_calls(source, "fixed", LIFTED)
    assert ("INNER_UPDATE", "STRESS_OTI") in leaked


def test_the_check_passes_a_call_that_was_redirected():
    source = """      SUBROUTINE UMAT(STRESS_OTI)
      CALL INNER_UPDATE_OTI(STRESS_OTI, DDSDDE_OTI)
      END
"""
    assert oti_arguments_into_untransformed_calls(source, "fixed", LIFTED) == []
