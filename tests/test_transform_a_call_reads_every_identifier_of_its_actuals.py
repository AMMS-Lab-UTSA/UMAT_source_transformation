"""A helper call's dependency edge reads every identifier of each input actual.

regions._inferred_edges_for_call took the first identifier of each actual
(``_base_name``). For ``CALL SCALE(2.0D0*G, ...)`` that is none and for
``CALL SCALE(Q*G/PROPS(1), ...)`` it is Q, so G's edge to the callee's output
was lost: G's own assignment from DSTRAN was left REAL ahead of the seed
block, G_OTI was filled with no derivative, and the transform returned a
bitwise-correct stress beside a wrong tangent (Vera, B8 review R2: 1000
against FD 1040.8 and 1020.4). Every identifier is read now, in the inferred
edges and in the hand-checked helper table alike.

Behavioural, against the separately compiled original: primal bitwise, DDSDDE
against central differences at h = 1e-4, 1e-5, 1e-6.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original
from test_transform_a_value_at_a_hypercomplex_dummy_is_passed_as_one import HEAD, RENAMES


def _two_hop(first: str) -> str:
    return (HEAD.replace("g = props(1)*(1.0d0 + dstran(2))",
                         "t = dstran(2)\n  q = props(1)\n  g = props(1)*(1.0d0 + t)")
            .replace("real(8) :: y(6), g", "real(8) :: y(6), g, t, q") % {"first": first})


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("text", [
    HEAD % {"first": "2.0d0*g"},
    _two_hop("2.0d0*g"),
    _two_hop("q*g/props(1)"),
], ids=["literal_first", "two_hops", "second_identifier"])
def test_a_variable_inside_an_expression_actual_keeps_its_derivative(tmp_path, text):
    check_against_original(tmp_path, text, ".f90", RENAMES, ["1000.0d0"])
