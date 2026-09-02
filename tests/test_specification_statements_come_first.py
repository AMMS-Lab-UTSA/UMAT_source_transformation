"""Declarations go before the first executable line, so that line must be right.

The transform inserts its shadow declarations before the first statement that
runs. Every specification statement the classifier fails to recognise is
therefore a place a TYPE declaration can be inserted ahead of a statement that
has to come first -- and USE has to come first.

The F77 keywords were listed and the F90 ones were not, so a free-form source's
``use NumKind`` was classed executable and the generated file opened with a
derived-type declaration followed by the USE it depends on:

    Error: USE statement at (1) cannot follow data declaration statement at (2)

which points at the USE, not at the declaration that displaced it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.fortran.regions import _is_executable_line as executable  # noqa: E402


class TestSpecificationStatementsAreNotExecutable:
    def test_use(self):
        assert not executable("use NumKind")
        assert not executable("USE otim6n1, only: ONUMM6N1")

    def test_import(self):
        assert not executable("import :: foo")

    def test_a_derived_type_declaration(self):
        assert not executable("type(mytype) :: v")
        assert not executable("class(base), pointer :: p")

    def test_a_derived_type_definition(self):
        assert not executable("type :: newtype")
        assert not executable("type, public :: newtype")

    def test_attribute_statements(self):
        for text in ("allocatable :: work(:)", "pointer :: p", "target :: t",
                     "optional :: o", "intent(in) :: x", "volatile :: v"):
            assert not executable(text), text

    def test_an_interface_block(self):
        assert not executable("interface")
        assert not executable("end interface")
        assert not executable("procedure :: p")

    def test_the_f77_keywords_still_are_not(self):
        for text in ("implicit none", "dimension a(3)", "real*8 X",
                     "common /blk/ x", "parameter (N=3)", "data x/1.0/"):
            assert not executable(text), text


class TestExecutableStatementsStillAre:
    def test_an_assignment(self):
        assert executable("X = 1.0")

    def test_a_call(self):
        assert executable("call foo(x)")

    def test_control_flow(self):
        for text in ("if (x.gt.0) then", "do i=1,n", "where (a > 0)"):
            assert executable(text), text

    def test_type_as_an_output_statement(self):
        # TYPE *, X writes to standard output on compilers that accept it.
        # The parenthesis and the double colon are what mark a declaration.
        assert executable("type *, x")

    def test_an_allocate_runs(self):
        # ALLOCATE is executable even though ALLOCATABLE is not.
        assert executable("allocate(work(n,n))")


class TestADimensionStatementCarriesShapeNotType:
    """A name may already be typed by a declaration above the DIMENSION.

        real*8 vector, tensor
        dimension tensor(3,3), vector(NTENS)

    The first line was rewritten to a type declaration, and rewriting the
    second one the same way declared both names twice: "Symbol 'tensor' at (1)
    already has basic type of DERIVED". The shape is emitted as what the
    source said it was.
    """

    def _rewrite(self, payload: str, typed: set[str]):
        from umat_oti.transform.helper_lifting import (  # noqa: PLC0415
            _rewrite_dimension_line,
        )
        return _rewrite_dimension_line(payload, "ONUMM6N1", typed)[0]

    def test_an_untyped_name_is_typed_and_shaped_together(self):
        assert self._rewrite("tensor(3,3), vector(N)", set()) == [
            "    type(ONUMM6N1) :: tensor(3,3), vector(N)"]

    def test_an_already_typed_name_gets_only_its_shape(self):
        assert self._rewrite("tensor(3,3), vector(N)", {"TENSOR", "VECTOR"}) == [
            "    dimension tensor(3,3), vector(N)"]

    def test_a_mix_splits_between_the_two(self):
        lines = self._rewrite("tensor(3,3), vector(N)", {"TENSOR"})
        assert "    type(ONUMM6N1) :: vector(N)" in lines
        assert "    dimension tensor(3,3)" in lines

    def test_no_name_is_declared_twice(self):
        for typed in (set(), {"TENSOR"}, {"TENSOR", "VECTOR"}):
            lines = self._rewrite("tensor(3,3), vector(N)", typed)
            typing_lines = [line for line in lines if "::" in line]
            declared = [name for line in typing_lines
                        for name in line.split("::")[1].split(",")]
            stems = [name.strip().split("(")[0].upper() for name in declared]
            assert len(stems) == len(set(stems)), lines
            assert not (set(stems) & {name.upper() for name in typed}), lines
