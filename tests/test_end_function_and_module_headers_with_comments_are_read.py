"""``end function name`` ends a function; ``module name ! comment`` is a module header.

Two reading errors in the closure resolver and the module scanners
(B19 diagnosis findings 4 and 5). An ``END FUNCTION name`` line matched the
definition pattern (its prefix swallows END), so every free-form FUNCTION
appeared twice, with different bodies, and the resolver reported them as
ambiguous. And the module-header patterns ended at ``\\s*$``, so
``module tools   ! from A. Niemunis`` was not a module header and a module the
file defined was reported as 'USEs TOOLS without defining it'.
Rule (B20 RULES.md R11): END FUNCTION closes the open definition; a trailing
comment may follow a module name. Canaries: two genuinely different functions
are still two definitions, and a name that merely starts with MODULE is not a
module header.
"""
import re

from umat_oti.transform import dependency_resolution as dr
from umat_oti.transform.source_modules import _MODULE_OPEN
from umat_oti.transform.source_transform import _used_modules_not_defined_here

FUNCTIONS = """module m
contains
  function inverse(a) result(b)
    real(8) :: a, b
    b = 1.0d0/a
  end function inverse
  function square(a) result(b)
    real(8) :: a, b
    b = a*a
  end function square
end module m
"""


def test_end_function_closes_its_definition_so_each_function_is_defined_once(tmp_path):
    path = tmp_path / "m.f90"
    path.write_text(FUNCTIONS)
    definitions = dr._definitions_in(path)
    assert sorted(d.name for d in definitions) == ["INVERSE", "SQUARE"]
    spans = {d.name: (d.start_line, d.end_line) for d in definitions}
    assert spans["INVERSE"] == (3, 6) and spans["SQUARE"] == (7, 10)


def test_canary_two_functions_stay_two_definitions_with_their_own_bodies(tmp_path):
    path = tmp_path / "m.f90"
    path.write_text(FUNCTIONS)
    first, second = sorted(dr._definitions_in(path), key=lambda d: d.start_line)
    assert first.body_sha256 != second.body_sha256


def test_a_module_header_may_carry_a_trailing_comment():
    assert _MODULE_OPEN.match("module tools   ! from A. Niemunis")
    assert _MODULE_OPEN.match("module tools")
    assert not _MODULE_OPEN.match("module procedure f")


def test_canary_a_used_module_that_is_defined_with_a_comment_is_not_reported_missing():
    text = ("module tools   ! from A. Niemunis\nend module tools\n"
            "subroutine umat()\n  use tools\nend subroutine umat\n")
    assert "TOOLS" not in _used_modules_not_defined_here(text)
    assert "TOOLS" in _used_modules_not_defined_here(text.replace("module tools   ! from A. Niemunis\nend module tools\n", ""))
