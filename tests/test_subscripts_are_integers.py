"""A Fortran subscript is an INTEGER, so it carries no derivative.

Promoting one emits ``A1_OTI = A1IMP_OTI(TMPELEM_OTI)`` and gfortran refuses
it outright: "Array index at (1) must be of INTEGER type, found DERIVED".

The usual signals miss this case. The name that prompted the rule is TmpElem,
assigned from the element number NOEL: it begins with T, so the implicit rule
makes it REAL rather than INTEGER, and it sits on the stress path, so the
promotion that runs after the classifier picks it up. Being a subscript is the
only thing that says what it is.
"""
from __future__ import annotations

import pytest

from umat_oti.transform.source_transform import (
    _roles_with_stress_path_promotions, subscript_names,
)

ARRAYS = {"A1IMP", "STRESS", "DDSDDE", "DSTRAN"}


class TestFindingSubscripts:
    def test_a_name_used_to_index_a_known_array_is_found(self):
        assert "TMPELEM" in subscript_names("      a1 = a1Imp(TmpElem)\n", ARRAYS)

    def test_every_subscript_of_a_multiply_indexed_array_is_found(self):
        found = subscript_names("      ddsdde(k1,k2) = 0.d0\n", ARRAYS)
        assert {"K1", "K2"} <= found

    def test_an_argument_to_something_that_is_not_an_array_is_not_a_subscript(self):
        """SIN(THETA) indexes nothing; THETA may well carry a derivative."""
        assert "THETA" not in subscript_names("      y = sin(theta)\n", ARRAYS)

    def test_a_commented_line_indexes_nothing(self):
        assert subscript_names("C     a1 = a1Imp(Nope)\n", ARRAYS) == set()

    def test_no_known_arrays_means_no_subscripts(self):
        assert subscript_names("      a1 = a1Imp(TmpElem)\n", set()) == set()

    def test_a_literal_subscript_contributes_no_name(self):
        assert subscript_names("      stress(1) = 0.d0\n", ARRAYS) == set()


def _config(shapes: dict[str, str]) -> dict:
    return {
        "analysis": {"region_summary": {"stress_path_variables": list(shapes) + ["TMPELEM"]},
                     "detected_variables": []},
        "variable_roles": {name: {"detected_shape": shape} for name, shape in shapes.items()},
    }


class TestASubscriptIsNotPromoted:
    SOURCE = ("      TmpElem = NOEL\n"
              "      a1 = a1Imp(TmpElem)\n"
              "      stress(1) = a1*dstran(1)\n")

    def test_a_subscript_already_in_promote_is_removed(self):
        """Skipping the addition is not enough: the contract can carry it in."""
        roles = {"seed": set(), "promote": {"TMPELEM"}, "constant": set(), "keep_real": set()}
        out = _roles_with_stress_path_promotions(
            _config({"A1IMP": "100", "STRESS": "6", "DSTRAN": "6"}), roles, self.SOURCE)
        assert "TMPELEM" not in out["promote"]

    def test_and_it_is_recorded_as_kept_real_rather_than_dropped(self):
        roles = {"seed": set(), "promote": {"TMPELEM"}, "constant": set(), "keep_real": set()}
        out = _roles_with_stress_path_promotions(
            _config({"A1IMP": "100", "STRESS": "6", "DSTRAN": "6"}), roles, self.SOURCE)
        assert "TMPELEM" in out["keep_real"]

    def test_a_value_on_the_stress_path_is_still_promoted(self):
        """The rule must not swallow the variables the promotion exists for."""
        source = "      trace = dstran(1) + dstran(2)\n      stress(1) = trace\n"
        config = _config({"STRESS": "6", "DSTRAN": "6"})
        config["analysis"]["region_summary"]["stress_path_variables"] = ["TRACE"]
        config["variable_roles"]["TRACE"] = {"detected_shape": ""}
        roles = {"seed": set(), "promote": set(), "constant": set(), "keep_real": set()}
        out = _roles_with_stress_path_promotions(config, roles, source)
        assert "TRACE" in out["promote"]
