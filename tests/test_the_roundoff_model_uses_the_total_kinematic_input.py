"""fd.judge_column round-off model, Vera B7 A1 and A3 (P0).

PureGravity (Jeff97): a stress K (J - 1) built from the TOTAL deformation
gradient carries the round-off of K |F|, while the Euler term used the
increment (2.7e-8). The off-diagonal DDSDDE(1-3, 5) entries came out of the
double ladder as bitwise zeros (quantisation), were exempted as exact
structural zeros, and failed against the true small OTI values. Now:

* the Euler term is the largest derivative across the block times the total
  kinematic input (|STRAN + DSTRAN| or |DFGRD1|);
* a bitwise-zero ladder is exempt as a structural zero against the QUAD
  reference only;
* a zero in both double and quad against a nonzero value under test fails.
"""
import numpy as np
import pytest

from umat_oti.corpus_features import fd
from umat_oti.corpus_features.harness import _block_derivative, _exact_zero, _kinematic_input

pytestmark = pytest.mark.unit

L = fd.DEFAULT_LADDER
STEPS = [r * 1e-6 for r in L]          # strain step scale: the 1e-6 floor
K, G = 1.0e4, 1.0                      # bulk term >> the column's shear term
OWN = np.array([1e-12, 1e-6])          # the stress components themselves are tiny
OTI = np.array([1e-9, 1.0])            # true: a small coupling and the shear modulus


def _double_ladder():
    # quantised: the coupling is a bitwise zero at every step
    return [np.array([0.0, G]) for _ in L]


def _quad_ladder():
    return [np.array([1e-9, G]) for _ in L]


def test_puregravity_quantisation_failed_on_the_increment_model():
    v = fd.judge_column(OTI, _double_ladder(), list(range(len(L))), L, steps=STEPS,
                        magnitude=OWN)
    assert v.codes[0] == fd.FAIL


def test_puregravity_quantisation_is_unresolved_in_double():
    v = fd.judge_column(OTI, _double_ladder(), list(range(len(L))), L, steps=STEPS,
                        magnitude=OWN, kinematic_input=1.0, block_derivative=K)
    assert v.status == "unresolved" and v.failed == 0
    assert v.codes[0] == fd.UNRESOLVED_ZERO_SCALE


def test_puregravity_is_resolved_by_the_quad_reference():
    v = fd.judge_column(OTI, _quad_ladder(), list(range(len(L))), L, steps=STEPS,
                        magnitude=OWN, eps=fd.EPS_QUAD, kinematic_input=1.0,
                        block_derivative=K)
    assert v.status == "verified", v.codes


def test_the_double_exact_zero_exemption_is_gone():
    # a bitwise-zero double ladder whose atol is not < 1e-3 of the scale
    est = [np.zeros(1) for _ in L]
    v = fd.judge_column(np.zeros(1), est, list(range(len(L))), L, steps=STEPS,
                        magnitude=np.array([1.0]))
    assert v.codes == [fd.UNRESOLVED_ZERO_SCALE]


@pytest.mark.parametrize("oti, code", [(0.0, fd.ZERO_PASS), (1e-30, fd.FAIL), (1e-12, fd.FAIL)])
def test_a_zero_in_both_precisions_against_a_nonzero_value_fails(oti, code):
    est = [np.zeros(1) for _ in L]
    v = fd.judge_column(np.array([oti]), est, list(range(len(L))), L, steps=STEPS,
                        magnitude=np.array([1.0]), eps=fd.EPS_QUAD,
                        double_zero=np.array([True]))
    assert v.codes == [code]


def test_a_quad_zero_without_a_double_zero_keeps_the_round_off_window():
    est = [np.zeros(1) for _ in L]
    v = fd.judge_column(np.array([1e-30]), est, list(range(len(L))), L, steps=STEPS,
                        magnitude=np.array([1.0]), eps=fd.EPS_QUAD,
                        double_zero=np.array([False]))
    assert v.codes == [fd.ZERO_PASS]


def test_the_harness_measures_the_total_input_and_the_block():
    increments = [(np.array([1e-8, 0, 0]), None, np.eye(3) * 1.5, None),
                  (np.array([2e-8, 0, 0]), None, np.eye(3) * 2.0, None)]
    assert _kinematic_input(increments, 2, False) == pytest.approx(3e-8)
    assert _kinematic_input(increments, 2, True) == 2.0
    a = fd.ColumnFD([np.array([1.0, -7.0, 99.0])], [], [], [0], [0], True, "", [])
    b = fd.ColumnFD([np.array([3.0, 0.0, 0.0])], [], [], [0], [0], True, "", [])
    assert _block_derivative([a, b], slice(0, 2)) == 7.0
    z = fd.ColumnFD([np.array([0.0, 1.0]), np.array([0.0, 2.0])], [], [], [0, 1], [0, 1],
                    True, "", [])
    assert _exact_zero(z).tolist() == [True, False]
