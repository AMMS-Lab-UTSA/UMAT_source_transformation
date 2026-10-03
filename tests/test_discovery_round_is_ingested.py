"""The sources a discovery round accepted are in the inventory the pass reads.

``tools/transform_all.py --all`` attempts every row of
``paper_results/discovery/discovery_triage.csv`` and the registry seeds one
record per row, so a source accepted by a later round but missing from that
file is never transformed, verified or counted -- and nothing would say so.
These tests pin the 2026-10-02 family round's 14 accepted sources into it, and
the ingest tool's refusals.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import ingest_discovery_round as ingest_tool  # noqa: E402

ROUND = REPO / "paper_results/discovery/family_round_2026-10-02"
INVENTORY = REPO / "paper_results/discovery"


def _accepted():
    return json.loads((ROUND / "acceptance.json").read_text(encoding="utf-8"))["accepted"]


def _inventory_csv():
    with (INVENTORY / "discovery_triage.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _inventory_json():
    return json.loads((INVENTORY / "discovery_triage.json").read_text(encoding="utf-8"))


def test_every_accepted_source_is_in_the_inventory_with_the_rounds_triage_row():
    accepted = _accepted()
    assert len(accepted) == 14
    rows = {r["source"]: r for r in _inventory_json()["rows"]}
    in_csv = {r["source"] for r in _inventory_csv()}
    round_rows = {r["source"]: r for r in json.loads(
        (ROUND / "discovery_triage.json").read_text(encoding="utf-8"))["rows"]}
    for entry in accepted:
        source = entry["source"]
        assert source in in_csv, source
        assert rows[source] == round_rows[source], source


def test_the_rejected_candidates_stay_out():
    rejected = json.loads((ROUND / "acceptance.json").read_text(encoding="utf-8"))["rejected"]
    sources = {r["source"] for r in _inventory_csv()}
    names = [r.get("source") or f"{r.get('repository', '').replace('/', '__')}/{r.get('path', '')}"
             for r in rejected]
    assert names and not (set(names) & sources)


def test_csv_and_json_agree_and_the_summary_counts_the_rows():
    payload = _inventory_json()
    csv_sources = [r["source"] for r in _inventory_csv()]
    json_sources = [r["source"] for r in payload["rows"]]
    assert csv_sources == json_sources
    assert len(set(csv_sources)) == len(csv_sources) == 405
    assert csv_sources == sorted(csv_sources, key=ingest_tool._order)
    summary = payload["summary"]
    assert summary["sources"] == 405
    assert sum(summary["by_stage"].values()) == 405
    assert summary["transformed"] == summary["by_stage"]["transformed"]
    (entry,) = [r for r in summary["rounds_ingested"]
                if r["round"].endswith("family_round_2026-10-02")]
    assert entry["added"] == 14
    assert entry["acceptance_sha256"] == hashlib.sha256(
        (ROUND / "acceptance.json").read_bytes()).hexdigest()


def test_every_accepted_repository_has_a_pinned_commit_and_licence():
    import build_corpus_registry as registry_tool
    provenance = registry_tool.acquisition_provenance(registry_tool.DEFAULT_ACQUISITION)
    for entry in _accepted():
        repo_dir = entry["source"].split("/", 1)[0]
        assert len(provenance[repo_dir]["commit"]) == 40, repo_dir
        assert provenance[repo_dir]["commit"] == entry["commit"], repo_dir
        assert provenance[repo_dir]["license_spdx"], repo_dir


def test_the_registry_and_the_manifest_read_the_same_acquisition_manifests():
    import build_corpus_manifest as manifest_tool
    import build_corpus_registry as registry_tool
    registry = [str(p.relative_to(REPO)) for p in registry_tool.DEFAULT_ACQUISITION]
    assert registry == list(manifest_tool.ACQUISITION_MANIFESTS)
    assert "paper_results/discovery/family_round_2026-10-02/companions.json" in registry


def _scratch(tmp_path):
    inventory = tmp_path / "inventory"
    inventory.mkdir()
    for name in ("discovery_triage.csv", "discovery_triage.json"):
        shutil.copy(INVENTORY / name, inventory / name)
    return inventory


def test_ingesting_again_changes_nothing(tmp_path):
    inventory = _scratch(tmp_path)
    before = {p.name: p.read_bytes() for p in inventory.iterdir()}
    assert ingest_tool.ingest(ROUND, inventory, cache_dir=None) == []
    assert {p.name: p.read_bytes() for p in inventory.iterdir()} == before


def _round_copy(tmp_path):
    round_dir = tmp_path / "round"
    round_dir.mkdir()
    for name in ("acceptance.json", "discovery_triage.json"):
        shutil.copy(ROUND / name, round_dir / name)
    return round_dir


def test_a_cached_file_that_is_not_the_accepted_one_is_refused(tmp_path):
    round_dir = _round_copy(tmp_path)
    cache = tmp_path / "cache"
    for entry in _accepted():
        target = cache / entry["source"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("      SUBROUTINE UMAT\n      END\n")
    with pytest.raises(ingest_tool.IngestError, match="sha256"):
        ingest_tool.accepted_rows(round_dir, cache)


def test_a_source_with_a_different_row_already_in_the_inventory_is_refused(tmp_path):
    round_dir = _round_copy(tmp_path)
    triage = json.loads((round_dir / "discovery_triage.json").read_text())
    first = _accepted()[0]["source"]
    for row in triage["rows"]:
        if row["source"] == first:
            row["stage"] = "transformed" if row["stage"] != "transformed" else "blocked"
    (round_dir / "discovery_triage.json").write_text(json.dumps(triage))
    with pytest.raises(ingest_tool.IngestError, match="different triage row"):
        ingest_tool.ingest(round_dir, _scratch(tmp_path), cache_dir=None)


def test_a_round_whose_summary_disagrees_with_its_list_is_refused(tmp_path):
    round_dir = _round_copy(tmp_path)
    acceptance = json.loads((round_dir / "acceptance.json").read_text())
    acceptance["accepted"] = acceptance["accepted"][:-1]
    (round_dir / "acceptance.json").write_text(json.dumps(acceptance))
    with pytest.raises(ingest_tool.IngestError, match="summary"):
        ingest_tool.accepted_rows(round_dir, None)


def test_a_fresh_inventory_gets_exactly_the_accepted_rows(tmp_path):
    inventory = _scratch(tmp_path)
    payload = json.loads((inventory / "discovery_triage.json").read_text())
    accepted = {e["source"] for e in _accepted()}
    payload["rows"] = [r for r in payload["rows"] if r["source"] not in accepted]
    payload["summary"].pop("rounds_ingested", None)
    (inventory / "discovery_triage.json").write_text(json.dumps(payload))
    with (inventory / "discovery_triage.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ingest_tool.COLUMNS),
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload["rows"])
    added = ingest_tool.ingest(ROUND, inventory, cache_dir=None)
    assert sorted(added) == sorted(accepted)
    assert (inventory / "discovery_triage.csv").read_bytes() == \
        (INVENTORY / "discovery_triage.csv").read_bytes()
