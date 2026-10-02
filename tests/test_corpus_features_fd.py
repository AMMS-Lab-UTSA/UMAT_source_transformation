"""Unit tests: FD ladder, plateau rule (D-4), nonsmooth detection, tolerances.

Synthetic functions with closed-form derivatives; no Fortran.
"""
import math

import numpy as np
import pytest

from umat_oti.corpus_features import fd
from umat_oti.corpus_features.cells import fold
from umat_oti.corpus_features.paths import (
    Increment, LoadingPath, kinematics_for, strain_voigt_to_tensor, tensor_to_strain_voigt)

LADDER = fd.DEFAULT_LADDER


def ladder_of(f, x, scale=None):
    scale = scale or max(abs(x), 1.0)
    steps = [h * scale for h in LADDER]
    plus = [f(x + h) for h in steps]
    minus = [f(x - h) for h in steps]
    return plus, minus, f(x), steps


def smooth(x):
    return np.array([math.sin(x), x ** 3, math.exp(x), 0.0])


def dsmooth(x):
    return np.array([math.cos(x), 3 * x * x, math.exp(x), 0.0])


def test_smooth_function_verified_on_a_plateau_of_at_least_three_steps():
    x = 0.7
    plus, minus, base, steps = ladder_of(smooth, x)
    column = fd.classify_and_reference(plus, minus, base, steps)
    assert column.smooth
    assert column.order == pytest.approx(2.0, abs=0.05)       # central differences
    verdict = fd.judge_column(dsmooth(x), column.estimates, column.usable, LADDER,
                              steps=steps, magnitude=column.magnitude)
    assert verdict.status == "verified"
    assert verdict.min_plateau >= fd.MIN_PLATEAU
    assert verdict.max_rel < 1e-8


def test_wrong_derivative_fails_on_a_converged_plateau():
    x = 0.7
    plus, minus, base, steps = ladder_of(smooth, x)
    column = fd.classify_and_reference(plus, minus, base, steps)
    wrong = dsmooth(x) * np.array([1.0, 1.0 + 1e-4, 1.0, 1.0])
    verdict = fd.judge_column(wrong, column.estimates, column.usable, LADDER,
                              steps=steps, magnitude=column.magnitude)
    assert verdict.status == "failed" and verdict.failed == 1


def test_kink_at_the_state_is_nonsmooth_by_asymmetry():
    f = lambda x: np.array([abs(x), max(x, 0.0) ** 2 + x])   # noqa: E731
    plus, minus, base, steps = ladder_of(f, 0.0, scale=1.0)
    column = fd.classify_and_reference(plus, minus, base, steps)
    assert not column.smooth
    assert "one-sided" in column.reason


def test_branch_change_mask_makes_the_state_nonsmooth():
    plus, minus, base, steps = ladder_of(smooth, 0.3)
    same = [False, False, False, False, True, True]   # only two consistent steps
    column = fd.classify_and_reference(plus, minus, base, steps, same_branch=same)
    assert not column.smooth and "branch change" in column.reason


def test_branch_consistent_small_steps_still_give_a_smooth_reference():
    # The kink sits 1e-3 away: the two largest steps straddle it, the rest do not.
    f = lambda x: np.array([x * x if x < 0.301 else 10 * x])   # noqa: E731
    plus, minus, base, steps = ladder_of(f, 0.3, scale=1.0)
    same = [h < 1e-3 for h in steps]
    column = fd.classify_and_reference(plus, minus, base, steps, same_branch=same)
    assert column.smooth
    verdict = fd.judge_column(np.array([0.6]), column.estimates, column.usable, LADDER,
                              steps=steps, magnitude=column.magnitude)
    assert verdict.status == "verified"


def test_identically_zero_column_is_resolved():
    f = lambda x: np.array([0.0, 5.0])   # noqa: E731
    plus, minus, base, steps = ladder_of(f, 2.0)
    column = fd.classify_and_reference(plus, minus, base, steps)
    verdict = fd.judge_column(np.zeros(2), column.estimates, column.usable, LADDER,
                              steps=steps, magnitude=column.magnitude)
    assert verdict.status == "verified"


def test_primal_scale_has_a_history_floor():
    a = np.array([[300.0, 1.0], [1e-13, 0.0]])
    b = np.array([[300.0, 1.0], [-2e-13, 0.0]])
    assert fd.judge_primal(a, b)["agrees"]
    c = np.array([[300.0, 1.0], [1e-3, 0.0]])
    assert not fd.judge_primal(a, c)["agrees"]


def test_engineering_shear_round_trip_and_finite_kinematics():
    v = [1e-3, -2e-4, 3e-4, 4e-4, -5e-4, 6e-4]
    eps = strain_voigt_to_tensor(v, 3, 3)
    assert eps[0, 1] == pytest.approx(2e-4)                  # gamma/2
    assert tensor_to_strain_voigt(eps, 3, 3) == pytest.approx(v)
    lam = 1.1
    path = LoadingPath("t", "elastic", "finite",
                       [Increment(dfgrd1=((lam, 0, 0), (0, 1, 0), (0, 0, 1)))])
    (dstran, f0, f1, drot), = kinematics_for(path, 3, 3)
    assert dstran[0] == pytest.approx((lam - 1) / (0.5 * (lam + 1)))   # midpoint rate
    assert np.allclose(drot, np.eye(3)) and np.allclose(f0, np.eye(3))


def test_asymmetry_below_roundoff_of_the_history_is_not_a_kink():
    # The response has cancelled to ~1e-13 (closed cycle) with round-off of
    # the same size: one-sided slopes disagree wildly relative to the tiny
    # column, but by less than eps * |history| / h.
    rng = np.random.default_rng(0)
    steps = list(LADDER)
    base = np.array([1e-13])
    plus = [np.array([1e-13 + 1e-3 * h + 3e-14 * rng.standard_normal()]) for h in steps]
    minus = [np.array([1e-13 - 1e-3 * h + 3e-14 * rng.standard_normal()]) for h in steps]
    floored = fd.classify_and_reference(plus, minus, base, steps, output_scale=300.0)
    assert floored.smooth


def _rec(path, status, states, judged, **kw):
    base = {"source_id": "s", "feature": "ddsdde", "key": "k", "quantity": "q", "wrt": "w",
            "held_fixed": "h", "derivative_kind": "local", "ladder_relative": list(LADDER),
            "tolerance": {"rule": "r"}, "max_error_over_tolerance": 0.1, "build": "store",
            "transformer_fingerprint": "f", "compiled_source_sha256": "x",
            "coverage": {"n_states": states, "n_states_judged": judged}}
    return dict(base, path=path, status=status, **kw)


def test_fold_needs_two_verified_paths_and_half_the_states():
    # Vera B1/D: one verified path plus not_attempted others was folded verified.
    cells = fold([_rec("a", "verified", 10, 10), _rec("b", "not_attempted", 10, 1)], evidence="e")
    assert cells[0]["status"] == "not_attempted"
    assert cells[0]["reason"].startswith("insufficient coverage: 11/20")
    cells = fold([_rec("a", "verified", 10, 10), _rec("b", "verified", 10, 6),
                  _rec("c", "not_attempted", 10, 0)], evidence="e")
    assert cells[0]["status"] == "verified" and cells[0]["coverage"]["states_judged"] == 16
    assert cells[0]["build"]["kind"] == "store" and cells[0]["max_error"] <= cells[0]["tolerance"]
    cells = fold([_rec("a", "verified", 10, 10), _rec("b", "verified", 10, 5),
                  _rec("c", "not_attempted", 20, 0)], evidence="e")
    assert cells[0]["status"] == "not_attempted"          # 15/40 states
    cells = fold([_rec("a", "verified", 4, 3)], evidence="e")       # one path exists
    assert cells[0]["status"] == "verified"
    cells = fold([_rec("a", "verified", 10, 10), _rec("b", "failed", 10, 10)], evidence="e")
    assert cells[0]["status"] == "failed"


def test_fold_lets_a_hidden_state_trip_override_everything():
    trips = ["[p] base trajectory differs: STATEV(2) at increment 2"]
    cells = fold([_rec("a", "not_attempted", 10, 10, hidden_state_trips=trips,
                       reason="hidden state: ..."),
                  _rec("b", "not_attempted", 10, 10, hidden_state_trips=trips,
                       reason="hidden state: ...")], evidence="e")
    assert cells[0]["status"] == "not_attempted" and cells[0]["reason"].startswith("hidden state")


def test_primal_fold_counts_inconclusive_paths_without_failing():
    base = {"source_id": "s", "feature": "primal_stress_state", "key": "k", "build": "store",
            "max_error_over_tolerance": 0.0}
    cells = fold([dict(base, path="a", status="verified"),
                  dict(base, path="b", status="inconclusive", inconclusive=True,
                       reason="zero history")], evidence="e")
    assert cells[0]["status"] == "verified" and "inconclusive (non-informative) on 1" in cells[0]["reason"]
    cells = fold([dict(base, path="b", status="inconclusive", inconclusive=True,
                       reason="zero history")], evidence="e")
    assert cells[0]["status"] == "inconclusive"
    cells = fold([dict(base, path="a", status="failed", max_error_over_tolerance=7.0)], evidence="e")
    assert cells[0]["status"] == "failed" and cells[0]["values_disagree"] is True


def test_locators_use_the_manifest_roots():
    from umat_oti.corpus_features.harness import ROOTS, locator
    from umat_oti.corpus_features.manifest import DEFAULT_ROOTS
    for name, root in ROOTS.items():
        assert DEFAULT_ROOTS[name] == str(root), name
    assert locator(ROOTS["campaign"] / "batches/B2/x.jsonl") == "campaign:batches/B2/x.jsonl"
    assert locator(ROOTS["umat"] / "src/a.py") == "umat:src/a.py"
    assert locator("/elsewhere/file").startswith("abs:")
