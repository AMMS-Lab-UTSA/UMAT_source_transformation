"""verify_one end to end on a recorded row (MinSur1), with the Abaqus jobs
replaced by what they produced: pass16's original and transformed runs and the
Jacobian-matched run cc_cug_20 (corpus_campaign/batches/B2/curie_g). Everything
the gate itself does -- D-12 init builds, routine-level replay, the comparison --
runs for real. Skipped where those recordings or the compilers are absent."""
import json
import shutil
import sys
from pathlib import Path

import pytest
from _workspace import WORKSPACE  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

KEY = "31e3c24fed383b14795ffc46"
PASS16 = (WORKSPACE / "corpus_run/pass16")
JM = WORKSPACE / "corpus_campaign/batches/B2/curie_g/abaqus/cc_cug_20_minsur1_jmgate"
CACHE = (WORKSPACE / "discovery_cache")

needs = pytest.mark.skipif(
    not ((PASS16 / "work" / KEY).is_dir() and JM.is_dir() and CACHE.is_dir()
         and shutil.which("ifort") and shutil.which("gfortran")),
    reason="needs the pass16 recordings, cc_cug_20, the cache, ifort and gfortran")


@needs
def test_minsur1_is_decided_by_the_routine_and_the_jacobian_matched_control(tmp_path, monkeypatch):
    import verify_store_in_abaqus as V

    from umat_oti.store import TransformStore

    row = next(json.loads(l) for l in open(PASS16 / "results/store_verification.jsonl")
               if json.loads(l)["key"] == KEY)
    stored = next(e for e in TransformStore().entries() if e.key == KEY)

    def recorded(manifest, source, job, work_dir, support_dir, timeout, form="",
                 data_roots=()):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        if job in ("original", "transformed"):
            src = PASS16 / "work" / KEY / job
            shutil.copy(src / f"{job}_probed.for", work_dir / f"{job}_probed.for")
            shutil.copy(src / f"{job}.inp", work_dir / f"{job}.inp")
            shutil.copy(src / f"{job}_history.json", work_dir / f"{job}_history.json")
            for name in ("original_probe.txt", "transformed_probe.txt"):
                if (src / name).exists():
                    shutil.copy(src / name, work_dir / name)
        else:
            shutil.copy(JM / f"{JM.name}_history.json", work_dir / f"{job}_history.json")
        history = json.loads((work_dir / f"{job}_history.json").read_text())
        return {"completed": True, "converged_records": len(history),
                "instrumented": True, "warnings": [], "reasons": []}

    monkeypatch.setattr(V, "run_one", recorded)
    monkeypatch.setattr(V, "verify_tangent", lambda *a, **k: {
        "verified": False, "reason": "tangent not run in this test"})
    frozen = {stored.source_id: {"manifest": row["manifest"], "from": "pass16",
                                 "source_sha256": stored.source_sha256}}
    rows = V.triage_rows(REPO / "paper_results/discovery/discovery_triage.csv")
    proposals = V.proposal_entries(REPO / "paper_results/discovery/proposed_corpus_entries.json")
    record = V.verify_one(stored, rows.get(stored.source_id),
                          proposals.get(stored.source_id), CACHE, tmp_path,
                          timeout=900, frozen=frozen)
    assert "primal_gate" in record, (record.get("stage"), record.get("reason"))
    gate = record["primal_gate"]
    assert gate["agrees"], (record["routine_primal"].get("reason"),
                            record["jacobian_matched_primal"].get("reason"))
    assert gate["decided_by"] == "routine_level+jacobian_matched"
    assert record["evidence"]["primal_agreed"] is True
    assert record["primal"]["informational_only"] is True
    assert record["routine_primal"]["reproduces_the_solver"]["reproduced"]
    assert record["undefined_in_original"]["established"]
    assert record["stage"] == "tangent_not_verified"
    assert record["harness_fingerprint"]
