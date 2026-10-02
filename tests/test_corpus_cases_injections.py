"""Tampering with a frozen case makes ``check`` FAIL (Vera, B5 review item 1).

Each test copies one CI case into a scratch ``cases/`` directory together with
its committed index row, injects one defect, and asserts the check names it:

* a frozen FD reference value moved by 2 tau (a 'pass' entry, and a
  'zero_pass' entry) -> tangent tolerance failure;
* judged states or a whole path dropped from the reference (with the
  reference digest in case.json refreshed) -> coverage / reference failure,
  never a crash;
* case.json edited to agree with a tampered reference -> the index.json
  anchor outside the case directory disagrees;
* a preserved transformed file corrupted (its digest refreshed in case.json)
  -> the anchor disagrees and the replay fails;
* a reference value moved by far less than tau but beyond 10x the frozen
  error floor -> drift.

The consistency tests need no compiler; the replay tests need gfortran.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("corpus_cases", REPO / "tools" / "corpus_cases.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

INDEX = json.loads((cc.CASES / "index.json").read_text())
CI = [r for r in INDEX["cases"] if r["tiers"]["ci"]]
CASE_ID = next((r["case_id"] for r in CI if "m3-j2" in r["case_id"]), CI[0]["case_id"])


def _copy(tmp_path: Path):
    """(case_dir, case, row) of a scratch copy carrying the COMMITTED index row."""
    cases = tmp_path / "cases"
    case_dir = cases / CASE_ID
    shutil.copytree(cc.CASES / CASE_ID, case_dir)
    row = next(r for r in INDEX["cases"] if r["case_id"] == CASE_ID)
    cc.write_json(cases / "index.json", {"schema": INDEX["schema"], "cases": [row]})
    return case_dir, json.loads((case_dir / "case.json").read_text()), row


def _rewrite_reference(case_dir: Path, case: dict, ref: dict) -> dict:
    """Write the tampered reference and make case.json agree with it (the
    'updated sha' variant of each injection)."""
    cc.write_gz_json(case_dir / "reference.json.gz", ref)
    case["reference"]["sha256"] = cc.sha256_file(case_dir / "reference.json.gz")
    cc.write_json(case_dir / "case.json", case)
    return case


def _rebaseline_index(case_dir: Path) -> dict:
    """What a reviewer would see as an index.json diff: the anchors re-derived."""
    row = dict(next(r for r in INDEX["cases"] if r["case_id"] == CASE_ID))
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    row.update(digest=cc.case_digest(case_dir), paths=len(ref["paths"]),
               judged_states=sum(len(p["judged"]) for p in ref["paths"]))
    return row


def _entry(ref: dict, code: str):
    for p in ref["paths"]:
        for s in p["judged"]:
            for e in s["entries"]:
                if e[4] == code and e[3] > 0:
                    return e
    return None


def _kinds(result) -> set:
    return {f["kind"] for f in result["failures"]}


def _replay(case_dir, case, tmp_path, row):
    return cc.check_case(case_dir, case, ("replay",), tmp_path / "work",
                         current_rule=cc.rule_id(), with_original=False, row=row)


# ---- consistency (no compiler) -------------------------------------------
def test_the_committed_case_is_consistent_with_its_index(tmp_path):
    case_dir, case, row = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    assert cc.consistency_failures(case_dir, case, ref, cc.index_row(case_dir)) == []


def test_dropping_judged_states_with_the_sha_refreshed_is_a_coverage_failure(tmp_path):
    case_dir, case, row = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    ref["paths"][0]["judged"] = ref["paths"][0]["judged"][:-3]
    case = _rewrite_reference(case_dir, case, ref)
    kinds = _kinds({"failures": cc.consistency_failures(case_dir, case, ref, row)})
    assert "coverage_shrank" in kinds and "case_corrupted" in kinds


def test_dropping_a_path_from_the_reference_only_is_named_not_a_crash(tmp_path):
    case_dir, case, row = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    gone = ref["paths"].pop(0)["name"]
    case = _rewrite_reference(case_dir, case, ref)
    failures = cc.consistency_failures(case_dir, case, ref, row)
    assert any(f["kind"] == "reference_incomplete" and f.get("path") == gone for f in failures)


def test_dropping_a_path_from_reference_and_case_json_disagrees_with_the_index(tmp_path):
    case_dir, case, row = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    gone = ref["paths"].pop(0)["name"]
    case["experiment"]["paths"] = [p for p in case["experiment"]["paths"] if p["name"] != gone]
    case = _rewrite_reference(case_dir, case, ref)
    kinds = _kinds({"failures": cc.consistency_failures(case_dir, case, ref, row)})
    assert {"case_corrupted", "coverage_shrank"} <= kinds


def test_an_unindexed_case_fails(tmp_path):
    case_dir, case, _ = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    assert "not_indexed" in _kinds({"failures": cc.consistency_failures(case_dir, case, ref, None)})


def test_a_zero_pass_reference_moved_off_zero_is_a_tangent_breach():
    state = {"inc": 1, "entries": [[1, 2, 0.0, 1e-9, "zero_pass"]]}
    ok = cc.compare_tangent({1: [[0.0] * 3] * 3}, [state])
    assert ok["agrees"]
    state["entries"][0][2] = 2e-9                     # stored value moved by 2 tau
    assert not cc.compare_tangent({1: [[0.0] * 3] * 3}, [state])["agrees"]


# ---- replay (gfortran) -----------------------------------------------------


def _need_gfortran():
    if shutil.which("gfortran") is None:
        pytest.fail("gfortran is required (a missing compiler is a failure, not a skip)")


@pytest.mark.fortran
@pytest.mark.slow
@pytest.mark.parametrize("code", ["pass", "zero_pass"])
def test_a_reference_moved_by_two_tau_fails_the_replay(tmp_path, code):
    _need_gfortran()
    case_dir, case, _ = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    entry = _entry(ref, code)
    if entry is None:
        pytest.skip(f"{CASE_ID} has no {code} entry")   # the case, not the check, lacks it
    entry[2] += 2.0 * entry[3]
    case = _rewrite_reference(case_dir, case, ref)
    stale = _replay(case_dir, case, tmp_path / "stale", cc.index_row(case_dir))
    assert "case_corrupted" in _kinds(stale)           # the anchor outside the case
    bad = _replay(case_dir, case, tmp_path / "bad", _rebaseline_index(case_dir))
    assert any(f["kind"] == "tolerance" and f.get("comparator") == "tangent"
               for f in bad["failures"]), bad["failures"][:3]


@pytest.mark.fortran
@pytest.mark.slow
def test_a_reference_moved_beyond_the_drift_floor_is_drift(tmp_path):
    _need_gfortran()
    case_dir, case, _ = _copy(tmp_path)
    ref = cc.read_gz_json(case_dir / "reference.json.gz")
    entry = _entry(ref, "pass")
    path = next(p for p in ref["paths"] if any(entry in s["entries"] for s in p["judged"]))
    limit = cc.RULE["drift"]["factor"] * max(path["frozen_error"]["tangent"],
                                             cc.RULE["drift"]["floor_error_over_tolerance"])
    assert limit < 0.5, "the frozen error leaves no room for a drift-only injection"
    entry[2] += 2.0 * limit * entry[3]                 # inside tolerance, beyond drift
    case = _rewrite_reference(case_dir, case, ref)
    bad = _replay(case_dir, case, tmp_path, _rebaseline_index(case_dir))
    assert any(f["kind"] == "drift" and f.get("comparator") == "tangent" for f in bad["failures"])
    assert not any(f["kind"] == "tolerance" for f in bad["failures"])


@pytest.mark.fortran
@pytest.mark.slow
def test_a_corrupted_transformed_file_fails_even_with_its_digest_refreshed(tmp_path):
    _need_gfortran()
    case_dir, case, _ = _copy(tmp_path)
    item = next(f for f in case["transform"]["files"] if f["path"] == "umat_oti.for")
    target = case_dir / "transformed" / item["path"]
    text = target.read_text()
    assert "=PROPS(1)" in text
    target.write_text(text.replace("=PROPS(1)", "=PROPS(1)*1.000001D0", 1))   # E x (1 + 1e-6)
    item["sha256"] = cc.sha256_file(target)
    cc.write_json(case_dir / "case.json", case)
    stale = _replay(case_dir, case, tmp_path / "stale", cc.index_row(case_dir))
    assert "case_corrupted" in _kinds(stale)
    bad = _replay(case_dir, case, tmp_path / "bad", _rebaseline_index(case_dir))
    assert "tolerance" in _kinds(bad), bad["failures"][:3]


def test_the_tier_check_reports_the_index_anchor_for_every_case():
    for row in INDEX["cases"]:
        assert set(row["digest"]) == {"case_json_sha256", "reference_sha256"}, row["case_id"]
        assert cc.case_digest(cc.CASES / row["case_id"]) == row["digest"], row["case_id"]


def test_the_tier_summary_names_a_canary_that_was_not_rejected_and_fails():
    good = {"case_id": "a", "ok": True, "canaries": [{"canary": "c1", "rejected": True}]}
    line, ok = cc.tier_summary([good], [{"canary": "toy", "rejected": True}], 1.0)
    assert ok and "canaries all rejected" in line
    slipped = {"case_id": "b", "ok": True, "canaries": [{"canary": "c2", "rejected": False}]}
    line, ok = cc.tier_summary([good, slipped], [{"canary": "toy", "rejected": True}], 1.0)
    assert not ok and "all rejected" not in line and "b: c2" in line
    line, ok = cc.tier_summary([good], [{"canary": "toy", "rejected": False}], 1.0)
    assert not ok and "all rejected" not in line and "tier: toy" in line
