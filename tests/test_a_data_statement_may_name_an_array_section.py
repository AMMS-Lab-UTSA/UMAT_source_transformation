"""DATA I_mat(1,:) /1.D0, 0.D0, 0.D0/ initialises the elements the section covers.

prashanthgadwala's ferrite umat.f initialises the identity row by row with
array sections; the lifter turned DATA into assignments for whole arrays and
name/value lists only and refused the source. Rule (B20 RULES.md R6): a section
whose subscripts are ':' or integer literals, on a name with known literal
extents, expands to its elements in array element order (leftmost subscript
fastest). Planted errors: unknown extents, a value count that does not match the
section, and a non-literal subscript are all still refused.
"""
import pytest

from umat_oti.transform.helper_lifting import HelperLiftingError, _data_to_assignments


def test_a_row_section_is_expanded_in_element_order():
    assert _data_to_assignments("I(1,:) /1.D0, 0.D0, 0.D0/", {"I": (3, 3)}) == [
        "I(1,1) = 1.D0", "I(1,2) = 0.D0", "I(1,3) = 0.D0"]


def test_a_column_section_runs_the_first_subscript_fastest():
    assert _data_to_assignments("A(:,2) /1.D0, 2.D0, 3.D0/", {"A": (3, 3)}) == [
        "A(1,2) = 1.D0", "A(2,2) = 2.D0", "A(3,2) = 3.D0"]


def test_several_sections_in_one_statement():
    out = _data_to_assignments("I(1,:) /1.D0, 0.D0/, I(2,:) /0.D0, 1.D0/", {"I": (2, 2)})
    assert out == ["I(1,1) = 1.D0", "I(1,2) = 0.D0", "I(2,1) = 0.D0", "I(2,2) = 1.D0"]


@pytest.mark.parametrize("payload,extents", [
    ("I(1,:) /1.D0, 0.D0, 0.D0/", {}),                    # extents unknown
    ("I(1,:) /1.D0, 0.D0/", {"I": (3, 3)}),               # two values for three elements
    ("I(K,:) /1.D0, 0.D0, 0.D0/", {"I": (3, 3)}),         # a non-literal subscript
])
def test_canary_what_cannot_be_expanded_is_still_refused(payload, extents):
    with pytest.raises(HelperLiftingError):
        _data_to_assignments(payload, extents)
