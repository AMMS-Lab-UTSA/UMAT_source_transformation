"""The loop body of a local-Jacobian request is read exactly, or the request is refused.

The per-pass reseed clears the extra seed direction in every name the loop
body may carry to the next pass, so the body has to be delimited correctly.
A loop the reader cannot delimit is refused with the reason, not guessed:
a GOTO loop without loop.exit_line, a missing END DO, a labelled DO in the
body, and a named DO construct at the top or in the body (whose
``END DO name`` the plain matcher would pair with the wrong DO).
"""
from __future__ import annotations

import pytest

from umat_oti.transform.source_transform import (
    _jint_carried_names, _jint_loop_body, _jint_loop_problem)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _body(source: str, top: int = 1, exit_line: int = 0):
    contract = {"loop_top_line": top, "loop_exit_line": exit_line}
    lines = source.splitlines()
    return _jint_loop_body(lines, "free", contract), _jint_loop_problem(lines, "free", contract)


@pytest.mark.parametrize("source,body,carried", [
    ("do it=1,10\n x=x+1\nend do\n", (2, 2), {"X"}),
    ("do while (k<3)\n x=1\nend do\n", (2, 2), {"X"}),
    ("do it=1,10\n do i=1,3\n  y=1\n end do\n z=2\nend do\n", (2, 5), {"Y", "Z"}),
    ("do it=1,10\n call step(x, w)\nend do\n", (2, 2), {"X", "W"}),
])
def test_a_plain_loop_is_read(source, body, carried):
    found, problem = _body(source)
    assert found == body and problem == ""
    assert _jint_carried_names(source.splitlines(), "free", found, {"X", "Y", "Z", "W"}) == carried


def test_a_goto_loop_is_read_from_its_exit_line():
    found, problem = _body("10 continue\n x=x+1\n if (x<3) goto 10\n y=1\n", exit_line=4)
    assert found == (2, 3) and problem == ""


@pytest.mark.parametrize("source,reason", [
    ("10 continue\n x=x+1\n if (x<3) goto 10\n", "loop.exit_line"),
    ("do it=1,10\n x=1\n", "no END DO"),
    ("do it=1,10\n do 20 i=1,3\n y=1\n20 continue\nend do\n", "labelled DO"),
    ("do it=1,10\n inner: do i=1,3\n  y=1\n end do inner\n z=2\nend do\n", "named DO construct (line 2)"),
    ("newton: do it=1,10\n x=1\nend do newton\n", "is a named DO construct"),
])
def test_a_loop_the_reader_cannot_delimit_is_refused_with_the_reason(source, reason):
    found, problem = _body(source)
    assert found is None
    assert reason in problem
