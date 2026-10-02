"""Structural-zero window, value-under-test term, Euler term (Vera B2/C).

Synthetic FD ladders as in corpus_campaign/batches/B2/vera/c_atol_inject.py
(truncation c h^2 + round-off at the reference's eps), judged by
fd.judge_column; and Vera's PROPS(3)=0 injection inside the real harness
(c_orig toy: STRESS(1) += PROPS(3)*STATEV(2), PROPS(3)=0; dropping the
derivative w.r.t. PROPS(3) passed as a "structural zero", local and total).
"""
import shutil
from pathlib import Path

import numpy as np
import pytest

from umat_oti.corpus_features import fd

L = fd.DEFAULT_LADDER
TOYS = Path(__file__).parent / "fixtures" / "corpus_features_b2_toys"


def _judge(oti, D, x_scale, F, *, eps=fd.EPS_QUAD, vmag=None, euler=True, seed=0):
    rng = np.random.default_rng(seed)
    D, F = np.asarray(D, float), np.asarray(F, float)
    steps = [r * x_scale for r in L]
    est = [D + rng.standard_normal(D.shape) * eps * F / h for h in steps]
    return fd.judge_column(np.asarray(oti, float), est, list(range(len(L))), L, steps=steps,
                           magnitude=F, eps=eps, value_magnitude=vmag, euler=euler)


@pytest.mark.parametrize("oti, expect", [([500.0], "verified"), ([0.0], "failed"),
                                         ([-500.0], "failed")])
def test_total_value_term_cannot_open_a_window_beyond_the_derivative_scale(oti, expect):
    # Vera case 5: n=50, history max 1e10, p=0 -> uncapped value term 888 > D=500
    v = _judge(oti, [500.0], 1e-6, [1e3], vmag=np.array([50 * 1e10]))
    assert v.status == expect, (v.codes, v.atol)
    assert v.atol[0] <= fd.RESOLUTION * 500.0 * (1 + 1e-9)
    assert fd.ZERO_PASS not in v.codes


@pytest.mark.parametrize("eps", [fd.EPS, fd.EPS_QUAD])
@pytest.mark.parametrize("vmag", [None, 50])
@pytest.mark.parametrize("slot2", [0.0, 1.5e-4, -1e-5])
def test_mixed_unit_statev_block_never_passes_a_wrong_slot(eps, vmag, slot2):
    # Vera cases 1/6: energy-like slot 1e9 (D 1e7), plastic-strain slot 1e-3 (D 1e-5), p=100
    D, F = [1e7, 1e-5], [1e9, 1e-3]
    v = _judge([1e7, slot2], D, 100.0, F, eps=eps, euler="bracket",
               vmag=None if vmag is None else vmag * np.asarray(F))
    assert v.codes[1] in (fd.FAIL,) or v.codes[1].startswith("unresolved"), v.codes
    assert v.status != "verified"


def test_mixed_unit_statev_block_exact_still_verifies():
    v = _judge([1e7, 1e-5], [1e7, 1e-5], 100.0, [1e9, 1e-3], eps=fd.EPS, euler="bracket")
    assert v.status == "verified", (v.codes, v.atol)


def test_a_cancelled_statev_slot_is_unresolved_not_failed():
    # measured (Lemaitre SDV6, fv44 B2c first run): quad reference ~1e-34, OTI
    # round-off 2.8e-17 from the large terms the slot is the difference of;
    # on its own magnitude it "fails", on the Euler term it passes -> unresolved
    D, F = [1e-1, 0.0], [1e2, 1e-20]
    v = _judge([1e-1, 2.8e-17], D, 1.0, F, eps=fd.EPS_QUAD, euler="bracket",
               vmag=np.array([1e2, 1e-20]))
    assert v.codes[1] == fd.UNRESOLVED_EULER, (v.codes, v.atol)
    assert v.codes[0] == fd.PASS and v.status == "unresolved"


def test_harness_uses_euler_only_on_the_stress_block():
    from umat_oti.corpus_features import harness
    import inspect
    src = inspect.getsource(harness.evaluate_path)
    assert 'euler=True if (block.start == 0 and block.stop == nt) else "bracket"' in src
    assert harness.FeatureTally("x", L, 1e-6).euler is True


def test_a_true_derivative_under_the_noise_is_never_a_structural_zero():
    # one entry, true D below the round-off atol: the column's own scale is ~|D|,
    # so atol is not < 1e-3 of it -> unresolved, never zero_pass
    for oti in ([0.0], [3e-3], [-3e-3]):
        v = _judge(oti, [3e-3], 1e-6, [4e2], eps=fd.EPS)
        assert fd.ZERO_PASS not in v.codes and v.status != "verified", (v.codes, v.atol)


def test_structural_zero_still_passes_when_resolved_against_the_column():
    # entry 2 is a true zero next to a resolved 1e3 entry: atol << 1e-3 * 1e3
    v = _judge([1e3, 0.0], [1e3, 0.0], 1.0, [1e3, 1e3], eps=fd.EPS)
    assert v.codes == [fd.PASS, fd.ZERO_PASS], (v.codes, v.atol)


def test_an_exactly_zero_column_passes_as_structural_zero():
    est = [np.zeros(2) for _ in L]
    v = fd.judge_column(np.zeros(2), est, list(range(len(L))), L, steps=list(L),
                        magnitude=np.array([1.0, 1.0]))
    assert v.codes == [fd.ZERO_PASS, fd.ZERO_PASS]


@pytest.fixture(scope="module")
def injected(tmp_path_factory):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features import harness as H, paths as P
    orig_add = H.FeatureTally.add

    def add(self, inc, wrt, column, oti, *args, **kw):
        oti = np.array(oti, float)
        if wrt == "PROPS(3)":
            oti = np.zeros_like(oti)
        return orig_add(self, inc, wrt, column, oti, *args, **kw)

    root = tmp_path_factory.mktemp("zero_prop")
    store = root / "store"
    store.mkdir()
    shutil.copy(TOYS / "c_orig.f", store / "umat.f")
    (store / "compile_order.txt").write_text("umat.f\n")
    entry = H.CorpusEntry(key="c_orig_drop3", source_id="vera_toy/c_orig_drop3",
                          original_source=TOYS / "c_orig.f", ntens=6, nstatv=2,
                          props=[2.0e5, 0.3, 0.0], store_dir=store)
    feats = ["stress_param_sens_local", "stress_param_sens_total"]
    paths = P.internal_paths({"ndi": 3, "nshr": 3})
    out = {"clean": H.run_entry(entry, root / "work_clean", paths=paths, features=feats)}
    H.FeatureTally.add = add
    try:
        out["drop"] = H.run_entry(entry, root / "work", paths=paths, features=feats)
    finally:
        H.FeatureTally.add = orig_add
    return out


@pytest.mark.slow
@pytest.mark.fortran
def test_props3_zero_dropped_derivative_fails_local_and_total(injected):
    clean = {(r["feature"], r["path"]): r for r in injected["clean"]}
    assert all(r["status"] == "verified" for r in clean.values()), \
        {k: (r["status"], r.get("entries")) for k, r in clean.items()}
    by = {(r["feature"], r["path"]): r for r in injected["drop"]}
    for feature in ("stress_param_sens_local", "stress_param_sens_total"):
        for path in ("gauss_small_elastic", "gauss_small_load_unload"):
            r = by[(feature, path)]
            assert r["status"] == "failed", (feature, path, r["status"], r.get("entries"),
                                             r.get("reason"))
