"""The frozen regression cases are well formed, licence-clean, and still check.

* every ``umat/cases/<id>/case.json`` matches its files (hashes, configs,
  reference) and ``index.json``;
* a case whose source is not redistributable (D-2) carries no source and no
  transformed Fortran in the repository; the CI tier holds only permitted ones;
* (gfortran) one CI case passes R and P, the same case with a corrupted frozen
  reference FAILS, and the hidden-state toy canary is rejected while its
  control is accepted.
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

CASE_DIRS = sorted(p.parent for p in cc.CASES.glob("*/case.json"))
CI_CASES = [d for d in CASE_DIRS if json.loads((d / "case.json").read_text())["tiers"]["ci"]]


def test_there_is_a_ci_tier_of_at_least_three_cases():
    assert len(CI_CASES) >= 3


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda d: d.name[:60])
def test_a_case_matches_its_files_and_its_licence(case_dir):
    case = json.loads((case_dir / "case.json").read_text())
    assert case["schema"] == cc.SCHEMA and case["case_id"] == case_dir.name
    assert cc.sha256_file(case_dir / case["reference"]["file"]) == case["reference"]["sha256"]
    for p in case["experiment"]["paths"]:
        assert cc.sha256_file(case_dir / p["config"]) == p["config_sha256"]
        assert p["judged_states"] > 0
    assert case["freeze_check"]["ok"] is True
    for key in ("transform_fingerprint", "harness_fingerprint"):
        assert case["fingerprints"][key]
    status = case["source"]["licence"]["redistribution"]
    if status == "permitted":
        assert cc.sha256_file(case_dir / case["source"]["in_case"]) == case["source"]["sha256"]
        for item in case["transform"]["files"]:
            assert cc.sha256_file(case_dir / "transformed" / item["path"]) == item["sha256"]
    else:
        assert not (case_dir / "source").exists() and not (case_dir / "transformed").exists()
        assert case["source"]["in_case"] is None and case["tiers"]["ci"] is False
        assert case["source"]["sha256"] and case["source"]["fetch"]


def test_the_index_lists_exactly_the_case_directories():
    index = json.loads((cc.CASES / "index.json").read_text())
    assert sorted(r["case_id"] for r in index["cases"]) == sorted(d.name for d in CASE_DIRS)


@pytest.mark.fortran
def test_hidden_state_toy_is_rejected_and_its_control_accepted(tmp_path):
    if shutil.which("gfortran") is None:
        pytest.fail("gfortran is required (a missing compiler is a failure, not a skip)")
    canary = cc.hidden_state_canary(tmp_path)
    assert canary["rejected"] and canary["toy_accepted"] is False and canary["control_accepted"]


@pytest.mark.fortran
@pytest.mark.slow
def test_a_ci_case_passes_and_the_same_case_with_a_corrupted_reference_fails(tmp_path):
    if shutil.which("gfortran") is None:
        pytest.fail("gfortran is required (a missing compiler is a failure, not a skip)")
    case_dir = CI_CASES[0]
    case = json.loads((case_dir / "case.json").read_text())
    good = cc.check_case(case_dir, case, ("regenerate", "replay"), tmp_path / "good",
                         current_rule=cc.rule_id())
    assert good["ok"], good["failures"][:3]
    assert all(c["rejected"] for c in good["canaries"])

    bad_dir = tmp_path / "bad_case"
    shutil.copytree(case_dir, bad_dir)
    ref = cc.read_gz_json(bad_dir / "reference.json.gz")
    entry = ref["paths"][0]["judged"][0]["entries"][0]
    entry[2] = entry[2] * (1 + 1e-2) + 1e-6          # move one frozen FD reference value
    cc.write_gz_json(bad_dir / "reference.json.gz", ref)
    stale = cc.check_case(bad_dir, case, ("replay",), tmp_path / "stale", current_rule=cc.rule_id())
    assert any(f["kind"] == "case_corrupted" for f in stale["failures"])
    case = dict(case, reference=dict(case["reference"],
                                     sha256=cc.sha256_file(bad_dir / "reference.json.gz")))
    bad = cc.check_case(bad_dir, case, ("replay",), tmp_path / "bad", current_rule=cc.rule_id())
    assert not bad["ok"]
    assert any(f["kind"] == "tolerance" and f.get("comparator") == "tangent" for f in bad["failures"])
