"""PROPS read through an index expression or a loop is part of the demand (G1b).

``ahartloper__UVC_MatMod``'s multiaxial and plane-stress UMATs read
PROPS(1:7) literally and the backstress pairs through
``props((N_BASIC_PROPS - 1) + 2 * i)`` for i up to (NPROPS - 7) / 2. Only a
bare identifier subscript was seen, so the demand read "PROPS(1:7) by
literal subscript and nothing else" and refused the author's 11-constant
decks as a different parameterisation. Over the 279 pass20 sources 16
demands change (exact -> not exact, no count changes) and no pairing moves
(corpus_campaign/batches/B7/gauss_g1b/demand_ab.out, after_a_expr.json).
"""
import pytest

from umat_oti.abaqus.deck_pairing import demanded

pytestmark = pytest.mark.unit

UVC_LIKE = """\
      n_back = (nprops - 7) / 2
      e  = props(1)
      a  = props(7)
      DO i = 1, n_back
        c_k(i) = props((7 - 1) + 2 * i)
        g_k(i) = props(7 + 2 * i)
      END DO
      statev(1) = ep
"""


def test_an_index_expression_makes_the_demand_open_ended():
    demand = demanded(UVC_LIKE)
    assert demand.nprops == 7 and not demand.props_exact
    assert demand.admits(11, 28)[0]


def test_literal_subscripts_alone_stay_exact():
    demand = demanded("      e = props(1)\n      a = props(7)\n      statev(1) = ep\n")
    assert demand.props_exact and not demand.admits(11, 28)[0]


def test_a_literal_loop_bound_counts_the_constants_it_reads():
    text = ("      e = props(1)\n      DO I = 8, 11\n        X(I) = PROPS(I)\n"
            "      END DO\n")
    assert demanded(text).nprops == 11


def test_extents_slices_and_declarations_are_not_index_expressions():
    text = ("      DIMENSION PROPS(NPROPS), STATEV(NSTATV)\n      REAL*8 PROPS(*)\n"
            "      X = PROPS(1)\n      Y(1:2) = PROPS(1:2)\n")
    assert demanded(text).props_exact
