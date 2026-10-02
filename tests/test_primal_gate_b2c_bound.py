"""B2c primal-gate bound (Vera B2 item 4).

* the stiffness of the bound comes from the ORIGINAL / the smaller build per
  call: inflating the transformed DDSDDE x1e6 at one call (MinSur1) no longer
  lets a 1e-6 stress error at that call pass;
* the global 64 ulpK is a cap; the row's own floor is measured on the
  ORIGINAL (1-ulp input perturbations): PureGravity's 1e-4 relative stress
  error (bound 2.2e-4 max|sigma| under the old rule) fails;
* bound / max|sigma| is published per row.
"""
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

from umat_oti.abaqus.compare import (NOISE_MIN_ULPS, STIFFNESS_ULPS, compare_calls,
                                     measured_noise_ulps, stiffness_scale)

FIXTURES = Path(__file__).parent / "fixtures" / "primal_gate"
REPO = Path(__file__).resolve().parents[1]
PASS16 = Path("/home/ammslab3/softwarex_work/corpus_run/pass16/work")
PUREGRAVITY = "2f577b2a3413db6b15714a4e"


def case(name):
    with gzip.open(FIXTURES / f"{name}.json.gz", "rt") as handle:
        return json.load(handle)


def _scaled(records, factor, call=None, ddsdde=1.0):
    out = []
    for i, r in enumerate(records):
        r = dict(r, STRESS=list(r["STRESS"]), DDSDDE=list(r["DDSDDE"]))
        if call is None or i == call:
            r["STRESS"] = [v * factor for v in r["STRESS"]]
            r["DDSDDE"] = [v * ddsdde for v in r["DDSDDE"]]
        out.append(r)
    return out


def test_minsur1_inflated_tangent_at_one_call_cannot_widen_its_own_bound():
    c = case("minsur1")
    orig, trans = c["routine_original"], c["routine_transformed"]
    i = max(range(len(orig)), key=lambda k: max(abs(v) for v in orig[k]["STRESS"]))
    bad = _scaled(trans, 1 + 1e-6, call=i, ddsdde=1e6)
    # the old rule (one global stiffness from the build under test) let it
    # through (Vera B2 item 4). Per call the smaller build's tangent is used,
    # so even passing the inflated history's own maximum cannot widen it:
    for stiffness in (stiffness_scale(bad), stiffness_scale(orig)):
        new = compare_calls(orig, bad, stiffness=stiffness, tolerance=1e-10)
        assert not new.agrees, new.reason
    # the clean pair still agrees under the same rule
    assert compare_calls(orig, trans, stiffness=stiffness_scale(orig), tolerance=1e-10).agrees


def test_puregravity_1e4_relative_error_fails_at_the_measured_floor():
    c = case("puregravity")
    orig, trans = c["routine_original"], c["routine_transformed"]
    bad = _scaled(trans, 1 + 1e-4)
    kw = dict(stiffness=stiffness_scale(orig), tolerance=1e-10, excluded={"STATEV": [7]})
    # the global cap alone (old rule) let it through: bound 2.2e-4 max|sigma|
    capped = compare_calls(orig, bad, ulps=STIFFNESS_ULPS, **kw)
    assert capped.agrees and capped.bound_over_max_sigma > 1e-4
    # the floor measured on this row's original (B2c gate_eval: 3.0 ulpK -> 12)
    floored = compare_calls(orig, bad, ulps=12.0, **kw)
    assert not floored.agrees and floored.bound_over_max_sigma < 1e-4
    assert compare_calls(orig, trans, ulps=12.0, **kw).agrees


def test_bound_over_max_sigma_is_recorded():
    c = case("minsur1")
    r = compare_calls(c["routine_original"], c["routine_transformed"],
                      stiffness=stiffness_scale(c["routine_original"]), tolerance=1e-10)
    d = r.as_dict()
    assert 0 < d["bound_over_max_sigma"] < 1e-6
    assert d["worst_stress_over_bound"] < 1.0


def test_measured_floor_rule():
    ref = [{"STRESS": [1.0, 2.0], "DDSDDE": [1e3]}]
    same = measured_noise_ulps(ref, [ref])
    assert same["measured"] == 0.0 and same["ulps"] == NOISE_MIN_ULPS
    eps = 2.220446049250313e-16
    moved = [{"STRESS": [1.0 + 3 * eps * 1e3, 2.0], "DDSDDE": [1e3]}]
    m = measured_noise_ulps(ref, [moved])
    assert abs(m["measured"] - 3.0) < 1e-6 and abs(m["ulps"] - 12.0) < 1e-5
    huge = [{"STRESS": [1.0 + 1e3 * eps * 1e3, 2.0], "DDSDDE": [1e3]}]
    assert measured_noise_ulps(ref, [huge])["ulps"] == STIFFNESS_ULPS
    assert measured_noise_ulps(ref, [])["ulps"] == STIFFNESS_ULPS


@pytest.mark.skipif(not (PASS16 / PUREGRAVITY).is_dir() or shutil.which("ifort") is None,
                    reason="needs the pass16 PureGravity work dir and ifort")
def test_puregravity_end_to_end_floor_and_injection(tmp_path):
    sys.path.insert(0, str(REPO / "tools"))
    import verify_store_in_abaqus as V
    od, td = PASS16 / PUREGRAVITY / "original", PASS16 / PUREGRAVITY / "transformed"
    oh = json.load(open(od / "original_history.json"))
    th = json.load(open(td / "transformed_history.json"))
    out = V.routine_level_primal(od, td, oh, th, tmp_path, ntens=6, tolerance=1e-10,
                                 undefined={"STATEV": [7]})
    assert out["agrees"], out["reason"]
    floor = out["noise_floor"]
    assert floor["draws"] == 3 and floor["ulps"] < 20
    assert out["bound_over_max_sigma"] < 1e-4
