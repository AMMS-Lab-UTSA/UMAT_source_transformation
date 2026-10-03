"""Origins on records and cells (G8, D-19a rev 2; D-21 tiers).

A council entry is resolved from its council plan (one set per entry,
``<key>#<set>``), carries material_data_origin and experiment_origin into
every record and cell, and its driver point says it is the council plan's.
An author-deck entry carries neither, so its records read as before.
"""
import json
import sys
from pathlib import Path

import pytest

from umat_oti.corpus_features import harness as H
from umat_oti.corpus_features.cells import fold

pytestmark = pytest.mark.unit

SOURCE = "      SUBROUTINE UMAT(STRESS)\n      STRESS(1) = PROPS(1)\n      END\n"


def _council_plan(set_ids=("A", "B")):
    def manifest(props):
        return {"ntens": 6, "ndi": 3, "nshr": 3, "nstatv": 1, "props": props,
                "kinematics": "small strain", "name": "MATERIAL",
                "loading": [{"period": 1.0}, {"period": 1.0}]}
    return {"material_data_origin": "council_chosen", "experiment_origin": "council_deck",
            "documented_domain": {"strain_max": {"value": 0.004, "where": "x", "quote": "q"}},
            "sets": [{"set_id": s, "plan": {"experiment": {"manifest": manifest([float(i + 1)])}}}
                     for i, s in enumerate(set_ids)]}


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    (cache / "o__r").mkdir(parents=True)
    (cache / "o__r" / "umat.f").write_text(SOURCE)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"records": [
        {"key": "c1", "source_id": "o__r/umat.f", "cache_path": "o__r/umat.f"},
        {"key": "a1", "source_id": "o__r/umat.f", "cache_path": "o__r/umat.f"}]}))
    records = tmp_path / "v.jsonl"
    records.write_text(json.dumps({"key": "c1", "stage": "needs_material_data"}) + "\n"
                       + json.dumps({"key": "a1", "manifest": {"ntens": 6, "nstatv": 1,
                                                               "props": [5.0]}}) + "\n")
    plans = tmp_path / "plans"
    (plans / "c1").mkdir(parents=True)
    (plans / "c1" / "council_plan.json").write_text(json.dumps(_council_plan()))
    for name, value in (("REGISTRY", registry), ("PASS16", records), ("CACHE", cache),
                        ("STORE", tmp_path / "store"), ("FAMILIES", tmp_path / "f.json"),
                        ("EXPERIMENT_WORK", tmp_path / "work"), ("COUNCIL_PLANS", plans)):
        monkeypatch.setattr(H, name, value)
    return tmp_path


def _path():
    from types import SimpleNamespace
    return SimpleNamespace(name="p", regime="elastic", kinematics="small strain",
                           provenance="", increments=[1, 2])


def test_each_council_set_is_its_own_entry_with_both_origins(workspace):
    a, b = H.resolve_entry("c1#A"), H.resolve_entry("c1#B")
    assert (a.key, b.key) == ("c1#A", "c1#B") and (a.props, b.props) == ([1.0], [2.0])
    for entry in (a, b):
        assert entry.provenance["material_data_origin"] == "council_chosen"
        assert entry.provenance["experiment_origin"] == "council_deck"
        assert entry.driver_point["provenance"].startswith("council plan")
        assert entry.path_hints["documented_domain"]["strain_max"]["value"] == 0.004
    # a bare key without a manifest takes the first set
    assert H.resolve_entry("c1").provenance["council_set"] == "A"


def test_every_council_cell_carries_both_origins(workspace):
    entry = H.resolve_entry("c1#B")
    records = [H._record(entry, f, _path(), {"status": "verified"}, {})
               for f in ("primal_stress_state", "ddsdde")]
    for r in records:
        assert r["material_data_origin"] == "council_chosen"
        assert r["experiment_origin"] == "council_deck" and r["council_set"] == "B"
    for cell in fold(records, evidence="x"):
        assert cell["material_data_origin"] == "council_chosen"
        assert cell["experiment_origin"] == "council_deck"


def test_an_author_deck_entry_carries_no_origin_fields(workspace):
    entry = H.resolve_entry("a1")
    record = H._record(entry, "ddsdde", _path(), {"status": "verified"}, {})
    assert "material_data_origin" not in record and "experiment_origin" not in record
    assert "material_data_origin" not in fold([record], evidence="x")[0]


def test_the_abaqus_pass_records_a_harvest_completed_origin(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo / "tools"))
    sys.modules.pop("verify_store_in_abaqus", None)
    import verify_store_in_abaqus as tool

    plain = tool._material_columns(tool.ManifestPlan())
    assert "material_data_origin" not in plain
    harvested = tool._material_columns(tool.ManifestPlan(
        material_data_origin="author_published_outside_deck", experiment_origin="author"))
    assert harvested["material_data_origin"] == "author_published_outside_deck"
    assert harvested["experiment_origin"] == "author"
