"""A routine cannot prove its own arguments constant.

A dummy argument arrives with a value from the caller, and no assignment
inside the routine accounts for it. The constancy analysis nevertheless
judged arguments on the assignments it could see, and the universal test --
"every assignment to this name reads only constants" -- passes vacuously on
an assignment that reads nothing at all.

A plane-strain UMAT squares up the out-of-plane part of the deformation
gradient it was handed:

    dfgrd1(1,3) = 0
    dfgrd1(2,3) = 0
    dfgrd1(3,1) = 0
    dfgrd1(3,2) = 0
    dfgrd1(3,3) = 1

Five assignments, no variable read by any of them, and DFGRD1 -- the SEED --
was declared constant. Constancy propagates, so the declaration walked the
whole way to the stress. Measured on UMAT_Tissue_2d_plane_strain.f: the
converted source came back with ``detf = REAL(+DFGRD1_OTI(1,1)*...)`` and
twenty-one further truncating assignments, the derivative dying one
statement after the seed. Seven corpus entries, two of them the anisotropic
damage pair, reached derivative_truncated this way.
"""
from umat_oti.fortran.regions import (STANDARD_CONSTANT_INPUTS,
                                      _constant_variables)


class _Assignment:
    def __init__(self, lhs, rhs):
        self.lhs = lhs
        self.rhs_tokens = set(rhs)


def test_squaring_up_an_argument_does_not_make_it_constant():
    squared_up = [_Assignment("DFGRD1", set()) for _ in range(5)]
    detf = _Assignment("DETF", {"DFGRD1"})
    constants = _constant_variables(
        squared_up + [detf], set(), {"DFGRD1", "DETF"}, set(),
        {"DFGRD1", "STRESS", "PROPS"})
    assert "DFGRD1" not in constants, "the seed was declared constant"
    assert "DETF" not in constants, "and constancy propagated from it"


def test_without_the_argument_list_the_old_answer_still_comes_back():
    """The rule is about arguments, so it needs to be told which they are."""
    squared_up = [_Assignment("DFGRD1", set()) for _ in range(5)]
    constants = _constant_variables(squared_up, set(), {"DFGRD1"}, set())
    assert "DFGRD1" in constants


def test_the_constants_the_method_names_are_still_constant():
    """PROPS and STRAN are dummy arguments too.

    They are constant because the method says so -- a UMAT is not
    differentiated with respect to its material constants on this path --
    not because a fixed point inferred it, so the argument rule must not
    take them back.
    """
    work = [_Assignment("E", {"PROPS"}), _Assignment("OLD", {"STRAN"})]
    constants = _constant_variables(
        work, set(), {"E", "OLD"}, set(),
        {"PROPS", "STRAN", "DFGRD1", "STRESS"})
    assert "PROPS" in constants and "STRAN" in constants
    assert "E" in constants and "OLD" in constants
    assert {"PROPS", "STRAN"} <= STANDARD_CONSTANT_INPUTS


def test_a_local_that_only_ever_reads_constants_is_still_constant():
    work = [_Assignment("SCALE", {"PROPS"}), _Assignment("HALF", set())]
    constants = _constant_variables(
        work, set(), {"SCALE", "HALF"}, set(), {"PROPS", "DFGRD1"})
    assert "SCALE" in constants and "HALF" in constants


def test_the_measured_source_puts_the_determinant_on_the_stress_path():
    """The end of the chain, not just the rule at the start of it."""
    import os
    from pathlib import Path

    from umat_oti.fortran.scanner import analyze_fortran_source
    cache = Path(os.environ.get("UMAT_OTI_CACHE", "")
                 or Path.home() / "softwarex_work" / "discovery_cache")
    found = sorted(cache.rglob("UMAT_Tissue_2d_plane_strain.f")) if cache.is_dir() else []
    if not found:
        import pytest
        pytest.skip("the corpus source is not on this machine")
    summary = analyze_fortran_source(found[0])["region_summary"]
    on_path = {str(name).upper() for name in summary["stress_path_variables"]}
    constant = {str(name).upper() for name in summary["constant_variables"]}
    assert "DFGRD1" in on_path and "DFGRD1" not in constant
    assert "DETF" in on_path and "DETF" not in constant
