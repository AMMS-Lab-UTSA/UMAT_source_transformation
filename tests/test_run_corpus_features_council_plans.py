"""tools/run_corpus_features.py --council-plans points the harness at the council
plans folder written at the harness fingerprint being run, and nothing else."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
spec = importlib.util.spec_from_file_location("run_corpus_features",
                                              REPO / "tools" / "run_corpus_features.py")
rcf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rcf)


def test_the_flag_sets_the_plans_folder_the_council_key_is_resolved_from(tmp_path, monkeypatch):
    import umat_oti.corpus_features.harness as H
    seen = {}

    def resolve(key):
        seen["plans"] = H.COUNCIL_PLANS
        raise LookupError("stop here")
    monkeypatch.setattr(rcf, "resolve_entry", resolve)
    monkeypatch.setattr(H, "COUNCIL_PLANS", H.COUNCIL_PLANS)      # restored afterwards
    plans = tmp_path / "plans"
    plans.mkdir()
    assert rcf.main(["--key", "k#A", "--council-plans", str(plans), "--out", str(tmp_path / "o")]) == 0
    assert seen["plans"] == plans.resolve()
    record = json.loads((tmp_path / "o" / "corpus_features.jsonl").read_text().splitlines()[0])
    assert record["key"] == "k#A" and record["status"] == "blocked"


def test_without_the_flag_the_harness_default_is_kept(tmp_path, monkeypatch):
    import umat_oti.corpus_features.harness as H
    seen = {}
    default = H.COUNCIL_PLANS

    def resolve(key):
        seen["plans"] = H.COUNCIL_PLANS
        raise LookupError("stop here")
    monkeypatch.setattr(rcf, "resolve_entry", resolve)
    assert rcf.main(["--key", "k#A", "--out", str(tmp_path / "o")]) == 0
    assert seen["plans"] == default
