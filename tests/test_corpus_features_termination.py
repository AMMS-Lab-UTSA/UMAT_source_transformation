"""The ORIGINAL terminates (STOP / CALL XIT) under a PERTURBED input only.

pass19 (three RitioL crystal-plasticity sources): the base path completes,
but a +h perturbation makes the routine STOP. The driver runs every
perturbation in one process, so every record after that call is absent; the
harness raised KeyError at several sites. Rule (Gauss, 2026-10-02): a column
whose perturbed run (any build) did not write the records it needs is not
judged, with the reason "original terminated under perturbation (STOP/XIT) at
increment k"; the states it leaves unjudged go through the coverage rule;
never a crash, never a verdict on missing data.

Toy: linear elasticity that STOPs when PROPS(2) exceeds its nominal value
from increment 5 on. The local block of increment 5 stops at the first
PROPS(2)+h call, so increments 1-4 are complete and every later record
(rest of increment 5, all later increments, every total re-run) is missing.
"""
import shutil

import pytest

from test_corpus_features_hidden_state import BODY, END, HEADER, LAME

pytestmark = [pytest.mark.slow, pytest.mark.fortran]

STOPPER = HEADER + LAME + """      IF (PROPS(2) .GT. 0.30000001D0 .AND. KINC .GE. 5) STOP
""" + BODY + END

FEATURES = ("primal_stress_state", "ddsdde", "stress_param_sens_local",
            "stress_param_sens_total", "state_param_sens_local", "state_state_sens_local")
NEEDLE = "original terminated under perturbation (STOP/XIT) at increment 5"


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features.harness import CorpusEntry, run_entry
    from umat_oti.corpus_features.paths import internal_paths
    root = tmp_path_factory.mktemp("terminate")
    store = root / "store"
    store.mkdir()
    source = root / "toy_stop_under_perturbation.f"
    source.write_text(STOPPER)
    shutil.copy(source, store / "umat.f")
    (store / "compile_order.txt").write_text("umat.f\n")
    entry = CorpusEntry(key="toy_stop", source_id="gauss_toy/stop_under_perturbation",
                        original_source=source, ntens=6, nstatv=2, props=[2.0e5, 0.3],
                        store_dir=store)
    return run_entry(entry, root / "work", paths=internal_paths({"ndi": 3, "nshr": 3}),
                     features=FEATURES)


def _by(records):
    return {(r["feature"], r["path"]): r for r in records}


def test_no_trip_and_the_termination_is_recorded(records):
    assert all(not r.get("hidden_state_trips") for r in records), records[0].get("hidden_state_trips")
    r = _by(records)[("ddsdde", "gauss_small_elastic")]
    stop = r["gates"]["terminated_under_perturbation"]
    assert stop["original"]["increment"] == 5 and "props(2) +h" in stop["original"]["call"]
    # the init variants stop at the same call (otherwise the path is blocked)
    assert all(v == stop["original"] for v in stop.values())


def test_states_before_the_stop_are_judged_the_rest_are_not(records):
    by = _by(records)
    # 5-increment path: 4/5 states judged would pass coverage (verified, the
    # 5th disclosed), but the PROPS isolation probes could not be applied (the
    # total re-runs were never written): explicit rule -> not verified
    for f in ("ddsdde", "stress_param_sens_local"):
        r = by[(f, "gauss_small_elastic")]
        assert r["status_before_gate_notes"] == "verified", r.get("reason_before_gate_notes")
        assert NEEDLE in r["reason_before_gate_notes"]
        assert r["coverage"]["n_states_judged"] == 4
        assert r["coverage"]["n_states_terminated_under_perturbation"] == 1
        assert r["status"] == "not_attempted"
        assert r["reason"].startswith("hidden-state gate not applied on this path: isolation probe")
        assert NEEDLE in r["reason"]
    # the primal is not a derivative: unaffected by the rule
    assert by[("primal_stress_state", "gauss_small_elastic")]["status"] == "verified"
    # 12-increment path: 4/12 judged -> coverage rule, reason names the stop
    r = by[("ddsdde", "gauss_small_load_unload")]
    assert r["status"] == "not_attempted"
    assert r["reason"].startswith(NEEDLE), r["reason"]
    assert r["coverage"]["n_states_judged"] == 4


def test_total_columns_need_records_that_were_never_written(records):
    for path in ("gauss_small_elastic", "gauss_small_load_unload"):
        r = _by(records)[("stress_param_sens_total", path)]
        assert r["status"] == "not_attempted"
        assert r["reason"].startswith(NEEDLE), r["reason"]
        assert r["coverage"]["n_states_judged"] == 0


def test_nothing_is_verified_on_missing_data(records):
    for r in records:
        cov = r.get("coverage") or {}
        if r["status"] == "verified" and cov:
            assert cov["n_states_judged"] + cov["n_states_terminated_under_perturbation"] \
                <= cov["n_states"]
            assert cov["n_states_judged"] / cov["n_states"] >= cov["minimum"]


def test_first_missing_record_names_the_call():
    import numpy as np
    from umat_oti.corpus_features import drivers as dv
    from umat_oti.corpus_features.harness import first_missing_record
    perts = [dv.Perturbation("local", "props", 1, 1e-3), dv.Perturbation("total", "props", 1, 1e-3)]
    run = dv.RealOutput(initial_statev=np.zeros(1))
    for inc in (1, 2):
        run.base[inc] = {}
        run.replay[inc] = {}
        run.local[(inc, 1, 1)] = run.local[(inc, 1, -1)] = ()
    assert first_missing_record(run, perts, 2) == {
        "increment": 1, "call": "total props(1) +h, h=0.001", "ip": 2, "sign": 1}
    del run.local[(2, 1, -1)]
    assert first_missing_record(run, perts, 2)["call"] == "local props(1) -h, h=0.001"


def _record(feature, path, status, notes, judged=4, states=5):
    return {"source_id": "toy/s", "key": "toy", "feature": feature, "path": path,
            "status": status, "reason": "4/5 states judged" if status == "verified" else "x",
            "coverage": {"n_states": states, "n_states_judged": judged},
            "gates": {"hidden_state_gate_notes": notes}}


def test_a_dstran_probe_not_applied_blocks_verification_despite_coverage():
    """Coverage alone would verify (4/5 per path, 2 paths); the DSTRAN
    isolation probe was not applied on path b: b is not verified, and the
    cell does not count b's states."""
    from umat_oti.corpus_features.cells import fold
    from umat_oti.corpus_features.harness import apply_gate_notes
    note = ("isolation probe DSTRAN(1) not applied: original terminated under perturbation "
            "(STOP/XIT) at increment 3 (original build; ...)")
    recs = [_record("ddsdde", "a", "verified", []), _record("ddsdde", "b", "verified", [note]),
            _record("primal_stress_state", "b", "verified", [note]),
            _record("stress_param_sens_total", "b", "failed", [note])]
    out = apply_gate_notes([dict(r) for r in recs])
    assert out[0]["status"] == "verified"
    assert out[1]["status"] == "not_attempted" and note in out[1]["reason"]
    assert out[1]["status_before_gate_notes"] == "verified"
    assert out[2]["status"] == "verified"          # primal: not a derivative
    assert out[3]["status"] == "failed"            # a failure stands
    assert apply_gate_notes([dict(r) for r in out]) == out   # idempotent
    # the fold applies the rule itself and does not count b's judged states
    cells = {c["feature"]: c for c in fold(recs, evidence="e")}
    cell = cells["ddsdde"]
    assert cell["status"] != "verified", cell["reason"]
    assert cell["coverage"]["states_judged"] == 4 and cell["coverage"]["paths_verified"] == 1
