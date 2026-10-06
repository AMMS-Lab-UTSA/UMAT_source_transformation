"""verify_one end to end on a pass22 row (ahartloper UVCplanestress), with the
Abaqus jobs replaced by what they produced (corpus_run/pass22/work/<key>:
original, transformed, jacobian_matched) and the finite-difference tangent
stubbed. Everything else the verifier does -- the D-12 init builds, the
routine-level replay, the Jacobian-matched comparison, the informativeness
gate, the record -- runs for real.

pass23-prep (beae90e) bound a local ``frames`` inside verify_one, so the module
``frames`` used 40 lines later raised UnboundLocalError on every row that got
that far and every real run was a harness_error; the one test that walked this
path (test_primal_gate_verify_one) skipped because the pass16 recordings had
been cleaned away. This one reads the CURRENT pass's recordings and skips only
where the workspace has none. The source is read from the discovery cache, never
copied into the repository.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
from _workspace import WORKSPACE  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

KEY = "6cd9d2c3097479d1eeb4998f"
PASS = WORKSPACE / "corpus_run/pass22"
CACHE = WORKSPACE / "discovery_cache"
STORE = WORKSPACE / "transform_store" / KEY

needs = pytest.mark.skipif(
    not ((PASS / "work" / KEY / "jacobian_matched").is_dir() and CACHE.is_dir()
         and STORE.is_dir() and shutil.which("ifort") and shutil.which("gfortran")),
    reason="needs the pass22 recordings of UVCplanestress, the cache and the store, ifort and gfortran")


@needs
def test_a_recorded_row_reaches_the_tangent_stage_without_a_harness_error(tmp_path, monkeypatch):
    import verify_store_in_abaqus as V

    from umat_oti.store import TransformStore

    row = next(json.loads(l) for l in open(PASS / "results/store_verification.jsonl")
               if json.loads(l)["key"] == KEY)
    stored = next(e for e in TransformStore().entries() if e.key == KEY)
    recorded_dir = PASS / "work" / KEY

    def recorded(manifest, source, job, work_dir, support_dir, timeout, form="",
                 data_roots=()):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        src = recorded_dir / job
        for name in (f"{job}_probed.for", f"{job}.inp", f"{job}_history.json",
                     "original_probe.txt", "transformed_probe.txt"):
            if (src / name).exists():
                shutil.copy(src / name, work_dir / name)
        history = json.loads((work_dir / f"{job}_history.json").read_text())
        return {"completed": True, "converged_records": len(history),
                "instrumented": True, "warnings": [], "reasons": []}

    monkeypatch.setattr(V, "run_one", recorded)
    monkeypatch.setattr(V, "verify_tangent", lambda *a, **k: {
        "verified": False, "reason": "tangent not run in this test"})
    frozen = {stored.source_id: {"manifest": row["manifest"], "from": "pass22",
                                 "source_sha256": stored.source_sha256}}
    rows = V.triage_rows(REPO / "paper_results/discovery/discovery_triage.csv")
    proposals = V.proposal_entries(REPO / "paper_results/discovery/proposed_corpus_entries.json")
    record = V.verify_one(stored, rows.get(stored.source_id),
                          proposals.get(stored.source_id), CACHE, tmp_path,
                          timeout=900, frozen=frozen)
    assert record["stage"] != "harness_error", record.get("reason")
    assert "primal_gate" in record, (record.get("stage"), record.get("reason"))
    assert record["primal_gate"]["agrees"] is True
    assert record["primal_gate"]["decided_by"] == "routine_level+jacobian_matched"
    assert record["stage"] == "tangent_not_verified", (record["stage"], record["reason"])
    assert record["evidence"]["primal_agreed"] is True
