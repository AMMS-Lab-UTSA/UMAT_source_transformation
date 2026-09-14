"""NTENS=3 carries (11, 22, 12). The seed used to read it as (11, 22, 33).

NTENS is NDI+NSHR, and the two are not free: the element type fixes both. 6 is
3-D (3 direct, 3 shear), 4 is plane strain or axisymmetric (3 direct, 1 shear),
and 3 is PLANE STRESS -- two direct components and one shear. One corpus author
says so in the file, beside the component: "I am treating sigma(3) as sigma12".

The finite-strain seed took the direct directions to be the first
``min(ntens, 3)`` whatever NTENS was, so at NTENS=3 direction 3 perturbed E33 --
a through-thickness stretch that a plane-stress element does not carry and holds
no stress along. The Kirchhoff term beside it asked the routine for NDI, got 2,
and treated column 3 as a shear. Two halves of one tangent, disagreeing about
what the third column means, in the same emitted file.

Measured over all 391 triage rows, correcting it moved three outputs -- the
three NTENS=3 finite-strain sources -- and left every NTENS=4 (12 of them) and
NTENS=6 (220) output byte-identical, which is the demonstration that the 4-
and 6-component cases are untouched.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _finite_dfgrd1_seed_lines, _finite_strain_seed_terms,
    direct_component_count_expression, voigt_layout)

pytestmark = pytest.mark.unit


def test_the_layout_each_ntens_implies():
    assert voigt_layout(6) == (3, 3)
    assert voigt_layout(4) == (3, 1)
    assert voigt_layout(3) == (2, 1)
    assert voigt_layout(1) == (1, 0)


def test_direction_three_at_plane_stress_is_the_twelve_shear():
    terms = _finite_strain_seed_terms(3)
    direction_three = {(row, column, coefficient)
                       for row, column, coefficient, direction in terms
                       if direction == 3}
    assert direction_three == {(1, 2, 0.5), (2, 1, 0.5)}
    assert (3, 3, 1.0, 3) not in terms
    # and nothing seeds the out-of-plane axis at all
    assert not [term for term in terms if term[0] == 3 or term[1] == 3]


def test_three_dimensional_and_plane_strain_are_untouched():
    """The two halves of the corpus that were already right stay right."""
    assert _finite_strain_seed_terms(6) == [
        (1, 1, 1.0, 1), (2, 2, 1.0, 2), (3, 3, 1.0, 3),
        (1, 2, 0.5, 4), (2, 1, 0.5, 4),
        (1, 3, 0.5, 5), (3, 1, 0.5, 5),
        (2, 3, 0.5, 6), (3, 2, 0.5, 6),
    ]
    assert _finite_strain_seed_terms(4) == [
        (1, 1, 1.0, 1), (2, 2, 1.0, 2), (3, 3, 1.0, 3),
        (1, 2, 0.5, 4), (2, 1, 0.5, 4),
    ]


def test_the_seed_half_and_the_kirchhoff_half_agree_about_the_direct_count():
    """One function decides it, so the two halves cannot drift apart.

    Where the routine has NDI the expression is NDI, and at NTENS=3 Abaqus
    passes 2 -- which is what ``voigt_layout`` says. Where it does not, the
    fallback used to be MIN(3,NTENS) and said 3.
    """
    for ntens in (1, 3, 4, 6):
        direct, _shear = voigt_layout(ntens)
        assert direct == len([term for term in _finite_strain_seed_terms(ntens)
                              if term[2] == 1.0])
        assert direct_component_count_expression(set(), ntens) == str(direct)
    assert direct_component_count_expression({"NDI", "NTENS"}) == "NDI"
    assert direct_component_count_expression({"NSHR", "NTENS"}) == "NTENS-NSHR"


def test_the_emitted_seed_never_touches_the_out_of_plane_row():
    lines = _finite_dfgrd1_seed_lines("fixed", 3)
    body = "\n".join(lines)
    assert "DFGRD1_OTI(3," not in body.replace(" ", "")
    assert "OTI_E3*DFGRD1(3," not in body.replace(" ", "")
    assert "0.5D0*OTI_E3*DFGRD1(2,1)" in body.replace(" ", "")
