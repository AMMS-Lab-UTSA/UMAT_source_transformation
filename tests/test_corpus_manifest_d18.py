"""Decision D-18: which routine-level harness run decides each feature, the
guard against the full-feature run, and null build digests on merge."""

from __future__ import annotations

import pytest

from umat_oti.corpus_features.manifest import merge_d18, merge_feature_results

from test_corpus_manifest_vera_probes import SID, _manifest, _ok, _primal, roots  # noqa: F401

LIFTED_NULL = {"kind": "lifted", "fingerprint": None, "sha256": None, "transformer": None}


def _dd(status="verified", **over):
    return _ok(feature="ddsdde", status=status, **over)


def test_primal_and_ddsdde_come_from_the_primal_ddsdde_run(roots):
    m = _manifest(roots)
    prim = [_primal(), _dd()]
    full = [_primal(), _dd("not_attempted", reason="original terminated under "
                           "perturbation (STOP/XIT)"),
            _ok(feature="stress_param_sens_local")]
    merge_d18(m, prim, full)
    f = m["rows"][0]["features"]
    assert f["ddsdde"]["status"] == "verified"
    assert f["stress_param_sens_local"]["status"] == "verified"
    src = m["feature_sources"]
    assert src["decision"] == "D-18" and src["features"]["ddsdde"] == "primal_ddsdde_run"
    assert src["features"]["stress_param_sens_local"] == "full_feature_run"
    assert src["ignored_from_full_feature_run"] == 2


def test_sensitivities_from_the_primal_ddsdde_run_are_ignored(roots):
    m = _manifest(roots)
    merge_d18(m, [_primal(), _ok(feature="stress_param_sens_local")], [])
    assert m["rows"][0]["features"]["stress_param_sens_local"]["status"] == "not_attempted"


@pytest.mark.parametrize("full_rec", [
    _dd("failed", reason="disagrees", evidence="t:fail.jsonl"),
    _dd("not_attempted", reason="hidden state", hidden_state_trips=[{"call": 3}]),
    _ok(feature="stress_param_sens_local", status="not_attempted", reason="hidden",
        hidden_state_trips=[{"call": 1}]),
])
def test_guard_withholds_a_verified_ddsdde_the_full_run_contradicts(roots, full_rec):
    m = _manifest(roots)
    rep = merge_d18(m, [_primal(), _dd()], [full_rec])
    c = m["rows"][0]["features"]["ddsdde"]
    assert c["status"] == "inconclusive" and "D-18 guard" in c["reason"]
    assert c["d18_withheld_verified"]["status"] == "verified"
    assert "ddsdde" in {g["feature"] for g in rep["guarded"]}


def test_null_digests_are_blank_on_cells_that_decide_nothing(roots):
    m = _manifest(roots)
    rep = merge_feature_results(m, [_ok(feature="stress_param_sens_local",
                                        status="unsupported", reason="no lift",
                                        evidence="", build=dict(LIFTED_NULL))])
    assert rep["rejected"] == []
    c = m["rows"][0]["features_other_builds"]["lifted"]["stress_param_sens_local"]
    assert c["build"]["fingerprint"] == "" and c["build"]["sha256"] == ""


def test_a_deciding_cell_without_digests_is_still_rejected(roots):
    m = _manifest(roots)
    rep = merge_feature_results(m, [_ok(feature="stress_param_sens_local",
                                        build=dict(LIFTED_NULL))])
    assert rep["rejected"] and "fingerprint nor a sha256" in \
        "; ".join(rep["rejected"][0]["problems"])
