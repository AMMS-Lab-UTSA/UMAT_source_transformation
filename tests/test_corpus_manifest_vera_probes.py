"""Every case of Vera's B1 merge probe (batches/B1/vera/g_merge_probe.py), and
the rest of her review section G/E, as tests of the manifest merge contract.

Pure Python on a two-row synthetic manifest whose evidence root is a temporary
directory; the last tests read the real B1 evidence when it is present.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from umat_oti.corpus_features.manifest import (
    FEATURES,
    STAGES,
    merge_feature_results,
    ra_records_to_cells,
    summarise,
    to_locator,
    validate_cell,
    write_outputs,
)

pytestmark = pytest.mark.unit

CAMPAIGN = Path("/home/ammslab3/softwarex_work/corpus_campaign")


@pytest.fixture
def roots(tmp_path: Path) -> dict:
    for name in ("ev.jsonl", "fail.jsonl", "primal.jsonl"):
        (tmp_path / name).write_text("{}\n")
    return {"t": str(tmp_path)}


def _manifest(roots) -> dict:
    def row(sid):
        return {"row_kind": "acquired", "source_id": sid,
                "license": {"redistribution": "unknown", "spdx": "", "spdx_metadata": "",
                            "license_class": "none", "attribution_required": None,
                            "copyleft": None, "licence_file": None},
                "model": {"family": {"family": "elasticity", "review": "keyword_only",
                                     "human_reviewed": False}},
                "pipeline": {s: {"status": "verified" if s in ("discovered", "eligible")
                                 else "not_attempted", "reason": "r",
                                 "evidence": "t:ev.jsonl",
                                 **({"layouts": {}} if s == "compiled" else {})}
                             for s in STAGES},
                "features": {f: {"status": "not_attempted", "reason": "none yet",
                                 "evidence": "", "reference": None, "max_error": None,
                                 "tolerance": None, "history": []} for f in FEATURES},
                "features_other_builds": {"lifted": {}, "provider": {}},
                "ddsdde_legacy_gate": {"gate": "passed", "counts_as_verified": False,
                                       "rule": "legacy"}}
    m = {"roots": dict(roots), "rows": [row("s/1.f"), row("s/2.f")]}
    m["summary"] = summarise(m)
    return m


SID = "s/1.f"


def _ok(**over) -> dict:
    rec = dict(source_id=SID, feature="stress_param_sens_local", status="verified",
               reason="x", evidence="t:ev.jsonl#k", reference="fd", max_error=0.4,
               tolerance=1.0, tolerance_rule_id="entrywise/1", rtol=1e-6, atol=1e-12,
               fd_steps=[1e-3, 3e-4, 1e-4, 3e-5, 1e-5], min_plateau_observed=3,
               plateau_basis="fd_only", quantity="d STRESS_{n+1}/d PROPS",
               wrt="PROPS(1..2)", held_fixed="incoming STRESS/STATEV, DSTRAN",
               scope="local", build={"kind": "store", "fingerprint": "dbe9f928191e1d43"})
    rec.update(over)
    return rec


def _primal(status="verified", **over) -> dict:
    rec = dict(source_id=SID, feature="primal_stress_state", status=status,
               reason="primal", evidence="t:primal.jsonl", reference="original",
               max_error=0.1, tolerance=1.0, tolerance_rule_id="primal_row_scaled/1",
               rtol=1e-10, quantity="STRESS, STATEV", scope="history")
    rec.update(over)
    return rec


def _failed(feature="ddsdde", **over) -> dict:
    rec = dict(source_id=SID, feature=feature, status="failed", reason="disagrees",
               evidence="t:fail.jsonl", build={"kind": "store", "fingerprint": "abc"})
    rec.update(over)
    return rec


def _merge(m, recs):
    return merge_feature_results(m, [dict(r) for r in recs])


# ---- the probe cases, one test each ---------------------------------------

PROBES = {
    # Vera: 'nonexistent evidence, tol=1e300, held_fixed="-"' merged=1 in B1
    "nonexistent evidence, tol=1e300, held_fixed='-'": dict(
        evidence="nowhere:does/not/exist.json", tolerance=1e300, held_fixed="-"),
    "no evidence": dict(evidence=""),
    "only 2 fd steps": dict(fd_steps=[1e-3, 1e-4]),
    "fd_steps 3 but min_plateau 2 recorded": dict(fd_steps=[1, 2, 3],
                                                  min_plateau_observed=2),
    "no min_plateau recorded (ladder length is not a plateau)": dict(
        min_plateau_observed=None),
    "no held_fixed": dict(held_fixed=None),
    "reference 'oti'": dict(reference="oti"),
    "status plausible": dict(status="plausible"),
    "max_error NaN": dict(max_error=float("nan")),
    "quantity/wrt placeholders": dict(quantity="q", wrt="w"),
    "no build": dict(build=None),
    "column-norm tolerance rule": dict(tolerance_rule_id="legacy_column_norm"),
    "OTI-vs-FD plateau": dict(plateau_basis="oti_vs_fd"),
    "mixed tolerance semantics (raw tolerance 1e-6)": dict(tolerance=1e-6,
                                                           max_error=1e-9),
}


@pytest.mark.parametrize("name", sorted(PROBES))
def test_vera_probe_record_is_rejected_and_changes_nothing(roots, name):
    m = _manifest(roots)
    before = json.dumps(m["rows"], sort_keys=True)
    rep = _merge(m, [_ok(**PROBES[name])])
    assert rep["merged"] == 0 and len(rep["rejected"]) == 1, rep
    assert json.dumps(m["rows"], sort_keys=True) == before


def test_vera_probe_primal_without_tolerance_semantics_is_rejected(roots):
    m = _manifest(roots)
    rep = _merge(m, [dict(source_id=SID, feature="primal_stress_state",
                          status="verified", reason="", evidence="x:y",
                          reference="original", max_error=0.5, tolerance=1.0)])
    problems = rep["rejected"][0]["problems"]
    assert any("not one of" in p or "locator" in p for p in problems)
    assert any("tolerance_rule_id" in p for p in problems)


def test_the_probe_baseline_is_accepted(roots):
    m = _manifest(roots)
    rep = _merge(m, [_primal(), _ok()])
    assert rep["merged"] == 2 and rep["rejected"] == []
    assert m["rows"][0]["features"]["stress_param_sens_local"]["status"] == "verified"


def test_vera_probe_failed_is_not_overwritten_by_a_later_verified(roots):
    m = _manifest(roots)
    _merge(m, [_primal(), _failed()])
    _merge(m, [_ok(feature="ddsdde")])
    cell = m["rows"][0]["features"]["ddsdde"]
    assert cell["status"] == "conflict"
    assert {c["status"] for c in cell["conflicting"]} == {"verified", "failed"}
    assert "failed by" in cell["reason"] and "verified by" in cell["reason"]


@pytest.mark.parametrize("order", list(itertools.permutations("vfv")))
def test_vera_probe_verified_failed_verified_is_order_independent(roots, order):
    recs = {"v": _ok(feature="ddsdde"), "f": _failed()}
    m = _manifest(roots)
    _merge(m, [_primal()] + [recs[o] for o in order])
    assert m["rows"][0]["features"]["ddsdde"]["status"] == "conflict"
    m2 = _manifest(roots)                       # one record per merge call
    _merge(m2, [_primal()])
    for o in order:
        _merge(m2, [recs[o]])
    assert m2["rows"][0]["features"]["ddsdde"]["status"] == "conflict"


def test_a_conflict_cannot_be_claimed_by_a_record(roots):
    m = _manifest(roots)
    rep = _merge(m, [_failed(status="conflict", conflicting=[{"status": "failed"}])])
    assert rep["merged"] == 0


def test_two_verified_records_keep_the_worse_error(roots):
    m = _manifest(roots)
    _merge(m, [_primal(), _ok(max_error=0.2), _ok(max_error=0.7, evidence="t:fail.jsonl")])
    cell = m["rows"][0]["features"]["stress_param_sens_local"]
    assert cell["status"] == "verified" and cell["max_error"] == 0.7
    assert any(h.get("max_error") == 0.2 for h in cell["history"])


def test_a_non_decisive_record_does_not_replace_a_decision(roots):
    m = _manifest(roots)
    _merge(m, [_primal(), _failed()])
    _merge(m, [dict(source_id=SID, feature="ddsdde", status="not_attempted",
                    reason="later run skipped it")])
    assert m["rows"][0]["features"]["ddsdde"]["status"] == "failed"


# ---- primal: failed only when values disagree --------------------------------

def test_primal_failed_without_a_disagreement_is_refused(roots):
    m = _manifest(roots)
    rep = _merge(m, [_primal("failed", max_error=0.3)])
    assert rep["merged"] == 0
    assert "inconclusive" in rep["rejected"][0]["problems"][0]
    rep = _merge(m, [_primal("inconclusive", reason="not mechanically informative")])
    assert rep["merged"] == 1
    rep = _merge(_manifest(roots), [_primal("failed", max_error=3.0)])
    assert rep["merged"] == 1


# ---- ddsdde: D-4 evidence AND primal agreement ---------------------------------

def test_ddsdde_verified_needs_the_primal_to_agree(roots):
    m = _manifest(roots)
    _merge(m, [_ok(feature="ddsdde")])
    cell = m["rows"][0]["features"]["ddsdde"]
    assert cell["status"] == "inconclusive" and cell["withheld_verified"]
    assert m["summary"]["features"]["D1_acquired"]["ddsdde"]["verified"] == 0
    _merge(m, [_primal()])                       # the primal now agrees
    assert m["rows"][0]["features"]["ddsdde"]["status"] == "verified"
    assert m["summary"]["features"]["D1_acquired"]["ddsdde"]["verified"] == 1


def test_ddsdde_verified_is_withheld_when_the_primal_fails(roots):
    m = _manifest(roots)
    _merge(m, [_primal("failed", max_error=5.0), _ok(feature="ddsdde")])
    assert m["rows"][0]["features"]["ddsdde"]["status"] == "inconclusive"


def test_the_legacy_gate_is_never_counted(roots):
    m = _manifest(roots)
    assert m["summary"]["features"]["D1_acquired"]["ddsdde"]["verified"] == 0
    assert m["summary"]["ddsdde_legacy_gate"]["D1_acquired"]["passed"] == 2


# ---- builds: lifted / provider never pooled -------------------------------------

def test_lifted_and_provider_cells_are_counted_apart(roots):
    m = _manifest(roots)
    rep = _merge(m, [
        _primal(),
        _ok(build={"kind": "lifted", "sha256": "f" * 64}),
        _ok(feature="stress_param_sens_total", scope="total",
            build={"kind": "provider", "sha256": "e" * 64}),
    ])
    assert rep["merged"] == 3
    row = m["rows"][0]
    assert row["features"]["stress_param_sens_local"]["status"] == "not_attempted"
    assert row["features_other_builds"]["lifted"]["stress_param_sens_local"][
        "status"] == "verified"
    s = m["summary"]
    assert s["features"]["D1_acquired"]["stress_param_sens_local"]["verified"] == 0
    assert s["features_other_builds"]["D1_acquired"]["lifted"][
        "stress_param_sens_local"]["verified"] == 1
    assert s["features_other_builds"]["D1_acquired"]["provider"][
        "stress_param_sens_total"]["rows_with_cell"] == 1


def test_a_lifted_derivative_is_gated_on_the_lifted_primal(roots):
    m = _manifest(roots)
    lifted = {"kind": "lifted", "sha256": "f" * 64}
    _merge(m, [_primal(), _primal("failed", max_error=9.0, build=lifted),
               _ok(build=lifted)])
    cells = m["rows"][0]["features_other_builds"]["lifted"]
    assert cells["stress_param_sens_local"]["status"] == "inconclusive"


# ---- locators ----------------------------------------------------------------------

def test_absolute_evidence_under_a_root_is_rewritten(roots, tmp_path):
    m = _manifest(roots)
    rep = _merge(m, [_primal(), _ok(evidence=str(tmp_path / "ev.jsonl") + "#key=1")])
    assert rep["merged"] == 2
    ev = m["rows"][0]["features"]["stress_param_sens_local"]["evidence"]
    assert ev == "t:ev.jsonl#key=1"
    assert to_locator("/elsewhere/x.json", roots) == "/elsewhere/x.json"


def test_absolute_evidence_outside_every_root_is_refused(roots):
    rep = _merge(_manifest(roots), [_ok(evidence="/etc/hostname")])
    assert rep["merged"] == 0


# ---- deterministic output ------------------------------------------------------------

def test_rebuilding_unchanged_inputs_rewrites_identical_bytes(tmp_path, roots):
    m = _manifest(roots)
    m.update(schema="x", generated="2026-10-01T00:00:00+00:00", statuses=[],
             inputs={}, data_quality={})
    for r in m["rows"]:
        r.update(repository="r", url="", commit="", sha256={}, bytes={}, retrieval={},
                 interface=None, data_quality=[])
    out = tmp_path / "out"
    write_outputs(m, out)
    first = (out / "corpus_manifest.json").read_bytes()
    write_outputs({**m, "generated": "2030-01-01T00:00:00+00:00"}, out)
    assert (out / "corpus_manifest.json").read_bytes() == first
    m["rows"][0]["source_id"] = "s/changed.f"
    write_outputs({**m, "generated": "2030-01-01T00:00:00+00:00"}, out)
    assert b"2030-01-01" in (out / "corpus_manifest.json").read_bytes()


# ---- Residual Assembler records (Noether) ----------------------------------------------

def _ra(problem, status, feature="residual_sens", **over):
    rec = {"schema": "ra-corpus-residual/1", "source_id": SID, "feature": feature,
           "problem": problem, "status": status,
           "reference": "centred FD of R ... relative steps [0.01, 0.001, 0.0001]; "
                        ">=3-step plateau",
           "max_abs": 1e-9, "max_rel": 1e-10,
           "tolerance": {"rtol": 1e-6, "atol": "1e-09 * max|R| / |p|", "plateau_steps": 3},
           "what": "assembled nodal residual R", "wrt": "PROPS slots [1]",
           "held_fixed": "u_n, incoming state -- local, one increment",
           "evidence": "t:ev.jsonl", "material_path": "live OTI provider",
           "object_sha256": "a" * 64}
    rec.update(over)
    return rec


def test_ra_verified_is_inconclusive_on_the_provider_build(roots):
    cells, report = ra_records_to_cells(
        [_ra("p1", "verified"), _ra("p2", "verified"), _ra("p3", "unsupported"),
         _ra("p1", "verified", feature="assembly_consistency")], roots=roots)
    assert report["skipped_features"] == {"assembly_consistency": 1}
    (cell,) = cells
    assert cell["status"] == "inconclusive" and cell["producer_status"] == "verified"
    assert cell["build"]["kind"] == "provider" and cell["fd_steps"] == [0.01, 0.001, 0.0001]
    m = _manifest(roots)
    rep = merge_feature_results(m, cells)
    assert rep["merged"] == 1 and rep["rejected"] == []
    assert m["rows"][0]["features"]["residual_sens"]["status"] == "not_attempted"
    assert m["rows"][0]["features_other_builds"]["provider"]["residual_sens"][
        "status"] == "inconclusive"


def test_ra_failed_on_any_problem_is_failed(roots):
    cells, _ = ra_records_to_cells([_ra("p1", "verified"),
                                    _ra("p2", "failed", failure_class="x")], roots=roots)
    assert cells[0]["status"] == "failed"
    cells, _ = ra_records_to_cells([_ra("p1", "unsupported", object_sha256=None,
                                        reason="provider won't build")], roots=roots)
    assert cells[0]["status"] == "unsupported"
    m = _manifest(roots)
    assert merge_feature_results(m, cells)["merged"] == 1
    assert m["rows"][0]["features"]["residual_sens"]["status"] == "not_attempted"


# ---- the real B1 evidence, when present ------------------------------------------------

NOETHER = CAMPAIGN / "batches/B1/noether/records.jsonl"
GAUSS_B1 = CAMPAIGN / "batches/B1/gauss/evidence/fv44/manifest_cells.jsonl"


@pytest.mark.skipif(not NOETHER.is_file(), reason="Noether's B1 records not present")
def test_noethers_b1_records_fold_without_rejection_and_stay_out_of_the_pipeline():
    cells, report = ra_records_to_cells(NOETHER)
    assert report["schemas"] == {"ra-corpus-residual/1": report["records"]}
    assert all(c["build"]["kind"] == "provider" for c in cells)
    assert not [c for c in cells if c["status"] == "verified"]
    for c in cells:
        assert validate_cell(c["feature"], {k: v for k, v in c.items()
                                            if k not in ("source_id", "feature")}) == []


@pytest.mark.skipif(not GAUSS_B1.is_file(), reason="Gauss's B1 cells not present")
def test_gauss_b1_cells_do_not_meet_the_b2_contract_as_verified():
    """The B1 harness cells carry no build and no observed plateau; none may verify."""
    for line in GAUSS_B1.read_text().splitlines():
        cell = json.loads(line)
        if cell.get("status") != "verified":
            continue
        rest = {k: v for k, v in cell.items() if k not in ("source_id", "feature")}
        rest["evidence"] = to_locator(rest.get("evidence", ""))
        assert validate_cell(cell["feature"], rest), cell["source_id"]
