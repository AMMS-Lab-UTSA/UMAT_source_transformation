"""Entrywise, resolution-aware tolerance (B2) against Vera's B1 injection cases.

Vera (corpus_campaign/batches/B1/vera/b_c_inject.py) injected known errors
into an exact tangent of a synthetic stiffness-like map with a wide spread of
entry sizes; the B1 column-norm rule passed a -100% error on an entry at 6e-7
of its column, +0.5% at 1.5e-4 and x10 at 9e-8. Under the B2 rule every
injected error beyond the stated tolerance must be caught and the exact
tangent must pass. c_floor.py showed the B1 path floor passing a 100% error on
a state whose column is 1e-9 of the path maximum; that must fail now too.
Pure numerics, no Fortran.
"""
import numpy as np
import pytest

from umat_oti.corpus_features import fd

N = 6
A = np.zeros((N, N))
A[:3, :3] = 1.2e5
A[np.arange(3), np.arange(3)] = 2.8e5
A[3:, 3:] = np.diag([8e4, 8e4, 8e4])
A[0, 3] = A[3, 0] = 50.0        # 1.8e-4 of its column
A[1, 4] = A[4, 1] = 0.2         # 6e-7 of its column
A[1, 5] = A[5, 1] = 0.03        # 9e-8 of its column
A[2, 5] = A[5, 2] = 2.0         # 7e-6 of its column
C = np.array([3e7, -1e7, 2e7, 5e6, 1e6, 4e6])
EPS0 = np.array([2e-3, -6e-4, -6e-4, 1e-3, 4e-4, -2e-4])
SCALE = 1e-3                    # harness strain scale: max |DSTRAN| on the path


def sigma(eps):
    return A @ eps + C * eps ** 3 + 1e3 * np.sin(50 * eps)


def jac(eps):
    return A + np.diag(3 * C * eps ** 2) + np.diag(1e3 * 50 * np.cos(50 * eps))


def _columns():
    cols = []
    for j in range(N):
        plus, minus, steps = [], [], []
        for r in fd.DEFAULT_LADDER:
            h = r * SCALE
            e = np.zeros(N)
            e[j] = h
            plus.append(sigma(EPS0 + e)); minus.append(sigma(EPS0 - e)); steps.append(h)
        column = fd.classify_and_reference(plus, minus, sigma(EPS0), steps)
        # the harness takes the largest STRESS component for every STRESS entry
        magnitude = np.full(N, float(np.max(column.magnitude)))
        cols.append((column, magnitude))
    return cols


COLS = _columns()


def judge(J):
    out = []
    for j, (column, magnitude) in enumerate(COLS):
        out.append(fd.judge_column(J[:, j], column.estimates, column.usable, fd.DEFAULT_LADDER,
                                   steps=column.steps, magnitude=magnitude))
    return out


def cell(verdicts):
    if any(v.failed for v in verdicts):
        return "failed"
    if any(v.unresolved for v in verdicts):
        return "unresolved"
    return "verified"


def _case(name):
    J = jac(EPS0)
    X = J.copy()
    if name == "column 1 scaled by 1+1e-4":
        X[:, 0] *= 1 + 1e-4
    elif name == "column 1 scaled by 1+3e-6":
        X[:, 0] *= 1 + 3e-6
    elif name == "dropped cubic term":
        X -= np.diag(3 * C * EPS0 ** 2)
    elif name == "DDSDDE(4,1) doubled":
        X[3, 0] *= 2.0
    elif name == "DDSDDE(4,1) +0.5%":
        X[3, 0] *= 1.005
    elif name == "DDSDDE(5,2) dropped":
        X[4, 1] = 0.0
    elif name == "DDSDDE(5,2) sign flipped":
        X[4, 1] *= -1
    elif name == "DDSDDE(6,3) dropped":
        X[5, 2] = 0.0
    elif name == "all tiny couplings dropped":
        X[4, 1] = X[1, 4] = X[5, 2] = X[2, 5] = 0.0
    elif name == "DDSDDE(6,2) x10":
        X[5, 1] *= 10.0
    elif name == "DDSDDE(6,2) dropped":
        X[5, 1] = 0.0
    elif name == "structural zero DDSDDE(4,2) set to 1e-3":
        X[3, 1] = 1e-3      # atol (round-off scale) here is ~1e-5
    else:
        raise KeyError(name)
    return X


INJECTED = ["column 1 scaled by 1+1e-4", "column 1 scaled by 1+3e-6", "dropped cubic term",
            "DDSDDE(4,1) doubled", "DDSDDE(4,1) +0.5%", "DDSDDE(5,2) dropped",
            "DDSDDE(5,2) sign flipped", "DDSDDE(6,3) dropped", "all tiny couplings dropped",
            "DDSDDE(6,2) x10", "DDSDDE(6,2) dropped", "structural zero DDSDDE(4,2) set to 1e-3"]


def test_the_exact_tangent_passes_every_entry():
    verdicts = judge(jac(EPS0))
    assert cell(verdicts) == "verified", [v.codes for v in verdicts]
    assert sum(v.passed for v in verdicts) + sum(v.zero_passed for v in verdicts) == N * N
    assert min(v.min_plateau for v in verdicts) >= fd.MIN_PLATEAU


@pytest.mark.parametrize("name", INJECTED)
def test_every_injected_error_beyond_tolerance_is_caught(name):
    verdicts = judge(_case(name))
    assert cell(verdicts) == "failed", (name, [v.codes for v in verdicts])


def test_an_error_at_exactly_rtol_is_inside_the_stated_tolerance():
    # Vera's "column 1 scaled by 1+1e-6" is an error of exactly rtol: by
    # definition inside tau = atol + rtol |D| + 2u. It is caught as soon as
    # rtol is tightened below it -- the rule is not what hides it.
    X = jac(EPS0)
    X[:, 0] *= 1 + 1e-6
    column, magnitude = COLS[0]
    loose = fd.judge_column(X[:, 0], column.estimates, column.usable, fd.DEFAULT_LADDER,
                            steps=column.steps, magnitude=magnitude)
    tight = fd.judge_column(X[:, 0], column.estimates, column.usable, fd.DEFAULT_LADDER,
                            steps=column.steps, magnitude=magnitude, rtol=1e-7)
    assert loose.failed == 0
    assert tight.failed > 0


@pytest.mark.parametrize("ratio", [1e-3, 1e-5, 1e-7, 1e-9])
@pytest.mark.parametrize("error", [1e-4, 1e-2, 1.0])
def test_a_small_column_is_judged_on_its_own_scale_not_a_path_floor(ratio, error):
    # Vera c_floor.py: a state whose whole column is `ratio` of the path
    # maximum (softened / unloaded). B1 passed 100% errors at 1e-9.
    ladder = fd.DEFAULT_LADDER
    x0, scale = 1e-3, 1e-3
    a = 2e5 * ratio
    f = lambda x: np.array([a * np.sin(x / 1e-3), 0.3 * a * x ** 2 / 1e-3])   # noqa: E731
    true = np.array([a * np.cos(x0 / 1e-3) / 1e-3, 0.6 * a * x0 / 1e-3])
    steps = [r * scale for r in ladder]
    col = fd.classify_and_reference([f(x0 + h) for h in steps], [f(x0 - h) for h in steps],
                                    f(x0), steps)
    v = fd.judge_column(true * (1 + error), col.estimates, col.usable, ladder, steps=steps,
                        magnitude=np.full(2, float(np.max(col.magnitude))))
    assert v.status == "failed", (ratio, error, v.codes, v.reference, v.tolerance)
    exact = fd.judge_column(true, col.estimates, col.usable, ladder, steps=steps,
                            magnitude=np.full(2, float(np.max(col.magnitude))))
    assert exact.status == "verified", exact.codes


def test_an_entry_the_fd_cannot_resolve_is_unresolved_never_failed():
    # output 1e6, derivative 1e-3 -> every step whose round-off bound exceeds
    # 1e-3 |D| is inadmissible; what is left is not a 3-step plateau.
    f = lambda x: np.array([1e6 + 1e-3 * x])   # noqa: E731
    x, scale = 1.0, 1.0
    steps = [r * scale for r in fd.DEFAULT_LADDER]
    col = fd.classify_and_reference([f(x + h) for h in steps], [f(x - h) for h in steps], f(x), steps)
    for wrong in (1e-3, 0.0, 1e3):
        v = fd.judge_column(np.array([wrong]), col.estimates, col.usable, fd.DEFAULT_LADDER,
                            steps=steps, magnitude=col.magnitude)
        assert v.failed == 0 and v.unresolved == 1, v.codes


def test_exact_zeros_at_small_steps_only_are_not_a_structural_zero():
    # Measured on Jeff97 DDSDDE(1,4): 6.48 at 1e-3, exact zeros on 1e-5..1e-7
    # (a second-order dependence below one ulp of a cancelling sum). The zeros
    # are round-off, not a reference: no zero verdict, no failure of 6.48.
    est = [np.array([v]) for v in (6.5, 6.48, 3.0, 0.0, 0.0, 0.0)]
    steps = [r * 1e-3 for r in fd.DEFAULT_LADDER]
    v = fd.judge_column(np.array([6.48]), est, list(range(6)), fd.DEFAULT_LADDER, steps=steps,
                        magnitude=np.array([1e3]))
    assert v.zero_passed == 0 and v.failed == 0


def test_a_bit_identical_zero_is_a_structural_zero_judged_absolutely():
    est = [np.array([0.0, 2.0]) for _ in fd.DEFAULT_LADDER]
    steps = [r for r in fd.DEFAULT_LADDER]
    ok = fd.judge_column(np.array([0.0, 2.0]), est, list(range(6)), fd.DEFAULT_LADDER,
                         steps=steps, magnitude=np.array([5.0, 5.0]))
    assert ok.zero_passed == 1 and ok.passed == 1 and ok.status == "verified"
    bad = fd.judge_column(np.array([1e-9, 2.0]), est, list(range(6)), fd.DEFAULT_LADDER,
                          steps=steps, magnitude=np.array([5.0, 5.0]))
    assert bad.status == "failed"


def test_the_tolerance_widens_with_the_measured_fd_uncertainty_and_says_so():
    # Output magnitude 1e7 at unit steps 1e-2..: round-off bounds 1.8e-6,
    # 1.8e-5, 1.8e-4 on the three admissible steps, which agree within them;
    # u_e = spread 1.9e-5, atol_e = 1.8e-4 -> tau ~ 2.2e-4, reported.
    est = [np.array([v]) for v in (1 + 1e-6, 1 - 5e-6, 1 + 2e-5, 1 + 5e-3, 0.5, 3.0)]
    steps = list(fd.DEFAULT_LADDER)
    kw = dict(steps=steps, magnitude=np.array([1e7]))
    v = fd.judge_column(np.array([1.0 + 1.5e-4]), est, list(range(6)), fd.DEFAULT_LADDER, **kw)
    assert v.status == "verified", v.codes
    assert 2e-4 < v.max_rel_tolerance < 3e-4
    v = fd.judge_column(np.array([1.0 + 3e-4]), est, list(range(6)), fd.DEFAULT_LADDER, **kw)
    assert v.status == "failed"
    # truncation spread of 2e-5 with no round-off to explain it is not a plateau
    v = fd.judge_column(np.array([1.0]), [np.array([x]) for x in (1.3, 1 + 2e-5, 1.0, 1 - 1e-5, 0.7, 2.0)],
                        list(range(6)), fd.DEFAULT_LADDER, steps=steps, magnitude=np.array([1e-3]))
    assert v.status == "unresolved"
    # an entry within 1000x of the round-off scale is not resolved either
    v = fd.judge_column(np.array([1.0]), [np.array([1.0])] * 6, list(range(6)), fd.DEFAULT_LADDER,
                        steps=steps, magnitude=np.array([1e10]))
    assert v.codes == [fd.UNRESOLVED_ROUNDOFF]


def test_a_two_step_plateau_is_unresolved_not_plausible():
    est = [np.array([v]) for v in (1.1, 1.01, 1.0000000001, 1.0000000002, 1.3, 2.0)]
    for oti in (1.0, 1.5):
        v = fd.judge_column(np.array([oti]), est, list(range(6)), fd.DEFAULT_LADDER,
                            steps=list(fd.DEFAULT_LADDER), magnitude=np.array([1e-6]))
        assert v.status == "unresolved" and v.failed == 0
        assert v.unresolved_reasons == {fd.UNRESOLVED_PLATEAU: 1}
