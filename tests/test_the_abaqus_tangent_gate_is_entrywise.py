"""The Abaqus-side D-4 tangent gate (G10; Curie B7 items 1-3, 6; Vera A1, A3,
A4, A6), on synthetic sweeps of a known function.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from umat_oti.abaqus import tangent_gate as G
from umat_oti.corpus_features import fd

pytestmark = pytest.mark.unit

LADDER = (1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8)
SCALE = 1e-3
C = np.array([[200.0, 80.0, 0.0], [80.0, 200.0, 0.0], [0.0, 0.0, 60.0]])


X0 = np.array([1e-3, 0.0, 0.0])


def sweep_of(stress, x0=X0):
    """A DifferenceSweep of ``stress(x)`` at ``x0`` (exact arithmetic aside)."""
    n = len(x0)
    base = stress(x0)
    matrices, forward, backward = {}, {}, {}
    for r in LADDER:
        h = r * SCALE
        cen, fwd, bwd = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n))
        for j in range(n):
            e = np.zeros(n); e[j] = h
            p, m = stress(x0 + e), stress(x0 - e)
            cen[:, j] = (p - m) / (2 * h)
            fwd[:, j] = (p - base) / h
            bwd[:, j] = (base - m) / h
        matrices[r], forward[r], backward[r] = cen.tolist(), fwd.tolist(), bwd.tolist()
    return SimpleNamespace(matrices=matrices, forward=forward, backward=backward,
                           unperturbed=list(base))


def test_a_right_tangent_is_judged_and_passes():
    s = G.judge_state(C, sweep_of(lambda x: C @ x), LADDER, SCALE)
    assert s.judged and not s.failed and s.smooth


def test_a_wrong_entry_fails_and_the_failure_stands():
    wrong = C.copy(); wrong[0, 1] *= 1.01
    s = G.judge_state(wrong, sweep_of(lambda x: C @ x), LADDER, SCALE)
    assert s.failed and s.failures[0]["entry"] == [1, 2]
    ok, why = G.row_verdict([s, G.judge_state(C, sweep_of(lambda x: C @ x), LADDER, SCALE)],
                            2, coverage_ok=True, coverage_reason="")
    assert not ok and "disagrees" in why


def test_a_kink_in_one_entry_makes_its_column_nonsmooth_and_the_state_unjudged():
    def kinked(x):
        y = C @ x
        y[2] += 50.0 * abs(x[1])          # |x2| kink at x2 = 0, in entry (3,2)
        return y
    s = G.judge_state(C, sweep_of(kinked), LADDER, SCALE)
    assert s.nonsmooth_columns == [2] and [3, 2] in s.nonsmooth_entries
    assert not s.judged and not s.failed


def test_row_needs_two_judged_states_and_half_of_the_chosen():
    good = G.judge_state(C, sweep_of(lambda x: C @ x), LADDER, SCALE)
    assert G.row_verdict([good, good], 2, coverage_ok=True, coverage_reason="c")[0]
    assert not G.row_verdict([good], 1, coverage_ok=True, coverage_reason="c")[0]
    # 2 judged of 5 chosen (three produced no sweep): under 50%
    ok, why = G.row_verdict([good, good, None, None, None], 5, coverage_ok=True,
                            coverage_reason="c")
    assert not ok and "under 50%" in why
    assert not G.row_verdict([good, good], 2, coverage_ok=False, coverage_reason="c")[0]


def test_quad_only_resolves_what_double_left_unresolved():
    d = G.StateJudgement(increment=1, ntens=1,
                         entry_codes={(1, 1): fd.UNRESOLVED_ZERO_SCALE, (1, 2): fd.PASS})
    q = G.StateJudgement(increment=1, ntens=1,
                         entry_codes={(1, 1): fd.PASS, (1, 2): fd.UNRESOLVED_SPREAD})
    m = G.merge_quad(d, q)
    assert m.entry_codes == {(1, 1): fd.PASS, (1, 2): fd.PASS} and m.judged
    q.entry_codes[(1, 2)] = fd.FAIL
    q.failures = [{"entry": [1, 2]}]
    m = G.merge_quad(d, q)
    assert m.failed and m.entry_codes[(1, 2)] == fd.FAIL


def test_a_zero_in_both_precisions_against_a_nonzero_tangent_fails():
    oti = C.copy(); oti[0, 2] = 1e-12        # the true (1,3) entry is exactly zero
    sweep = sweep_of(lambda x: C @ x)
    zeros = G.exact_zero(sweep, LADDER, 3)
    assert zeros[0, 2]
    s = G.judge_state(oti, sweep, LADDER, SCALE, eps=fd.EPS_QUAD, double_zero=zeros)
    assert s.failed and [1, 3] in [f["entry"] for f in s.failures]


def test_a_kink_that_the_ladder_crosses_is_never_cleared():
    """Vera G10 review A6 (her kinktest): a one-entry kink at distance d below
    the state; wherever A6 flags it, the decay rule must keep it flagged."""
    ladder = LADDER
    for jump in (1.5e-3, 1e-2, 0.5):
        for d in list(np.logspace(-9.5, -0.5, 61)) + list(np.linspace(0.8e-8, 1.0e-8, 11)):
            def f(x, d=d, jump=jump):
                return x if x >= -d else (1.0 - jump) * (x + d) - d
            fwd = [np.array([(f(h) - f(0)) / h]) for h in ladder]
            bwd = [np.array([(f(0) - f(-h)) / h]) for h in ladder]
            cen = [np.array([(f(h) - f(-h)) / (2 * h)]) for h in ladder]
            slack = G.DECAY_SLACK
            try:
                G.DECAY_SLACK = 1e-300                     # A6 alone
                a6 = bool(G.entry_smoothness(fwd, bwd, cen, ladder, np.array([1.0]))[0])
            finally:
                G.DECAY_SLACK = slack
            if a6:
                assert G.entry_smoothness(fwd, bwd, cen, ladder, np.array([1.0]))[0], (jump, d)


def test_an_even_smooth_entry_is_not_a_kink():
    """sigma_12 as an even function of eps_22 at eps_22 = 0: centred 0, gap ~ h."""

    s = G.judge_state(C, sweep_of(lambda x: C @ x + np.array([0.0, 0.0, 300.0 * x[1] ** 2])),
                      LADDER, SCALE)
    assert s.smooth and s.judged


def test_a_curvature_gap_that_decays_like_h_is_not_a_kink_against_quad():
    """Quad round-off is tiny, so an even entry's curvature gap (centred 0)
    is above it and above 1e-3 |0| at every step: only the decay test
    keeps it smooth."""
    steps = [r * SCALE for r in LADDER]
    fwd = [np.array([300.0 * h]) for h in steps]
    bwd = [np.array([-300.0 * h]) for h in steps]
    cen = [np.array([0.0]) for _ in steps]
    assert not G.entry_smoothness(fwd, bwd, cen, steps, np.array([1.0]), fd.EPS_QUAD)[0]
