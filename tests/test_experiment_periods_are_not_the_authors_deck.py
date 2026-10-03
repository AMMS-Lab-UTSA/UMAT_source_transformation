"""The generated experiment's step periods are not the author's deck (G0).

``harness.resolve_entry`` used to put the probe's segment periods -- the
experiment the verification GENERATED, 1,1,1 or 1,1,1,10 on 32 of the 121
routine-level pass20 entries -- under ``deck_periods``, and
``model_domain`` cited every ``deck_periods`` as "author's deck". The
periods now travel as ``experiment_periods``; ``author_deck_periods`` (the
paired block's ``*STEP`` times, recorded by the Abaqus pass) is carried
beside them, and only a match with it is cited as the author's deck.

G0 is label-only (Vera, D-19a rev 2): the numbers keep flowing to time_max,
the shortening and the clock exactly as before. The A/B over the 176 pass20
records that resolve (121 routine-level among them) is in
corpus_campaign/batches/B7/gauss_g0/ (0 numeric differences).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from umat_oti.corpus_features import harness as H
from umat_oti.corpus_features.loading_paths import model_domain, paths_for

pytestmark = pytest.mark.unit

GROWTH = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,TIME,DTIME)
      IF ((TIME(2)+DTIME) .LE. 1.0) THEN
        G11 = 1.0 + 0.1*(TIME(2)+DTIME)
      ELSE IF ((TIME(2)+DTIME) .LE. 5.0) THEN
        G11 = 1.1
      END IF
      STATEV(1) = G11
      END
"""


def _entry(**kw):
    base = {
        "source_id": "someone__repo/umat.f",
        "family": "growth / morphoelasticity",
        "ntens": 6,
        "kinematics": "small strain",
        "props": [1.0e3],
        "activation_amplitude": 0.01,
        "source_text": GROWTH,
    }
    base.update(kw)
    return base


def _cited_as_deck(domain) -> bool:
    return any(w.split(": ", 1)[1].startswith("author's deck") for w in domain["witnesses"])


def _numbers(paths):
    return [
        (p.name, p.purpose, [(i.dtime, i.dstran, i.dfgrd1, i.temp) for i in p.increments])
        for p in paths
    ]


def test_generated_periods_are_not_cited_as_the_authors_deck():
    dom = model_domain(_entry(experiment_periods=[1.0, 1.0, 1.0], author_deck_periods=None))
    assert dom["time_max"] == pytest.approx(3.0)
    assert not _cited_as_deck(dom)
    assert "periods of the generated experiment" in dom["time_provenance"]
    assert "not recorded" in dom["time_provenance"]


def test_recorded_author_periods_that_match_are_the_authors_deck():
    dom = model_domain(_entry(experiment_periods=[1.0, 1.2], author_deck_periods=[1.0, 1.2]))
    assert _cited_as_deck(dom)
    assert dom["time_max"] == pytest.approx(2.2)


def test_recorded_author_periods_that_differ_are_named_and_not_enforced():
    dom = model_domain(_entry(experiment_periods=[1.0, 1.0, 1.0], author_deck_periods=[20.0]))
    assert not _cited_as_deck(dom)
    assert "the author's deck runs 20" in dom["time_provenance"]
    # label only: the bound is still the experiment's 3.0, not the deck's 20
    assert dom["time_max"] == pytest.approx(3.0)


@pytest.mark.parametrize("author", [None, [1.0, 1.0, 1.0], [7.0]])
def test_the_label_never_moves_a_number(author):
    legacy = paths_for(_entry(deck_periods=[1.0, 1.0, 1.0]))
    renamed = paths_for(_entry(experiment_periods=[1.0, 1.0, 1.0], author_deck_periods=author))
    assert _numbers(legacy) == _numbers(renamed)
    a = model_domain(_entry(deck_periods=[1.0, 1.0, 1.0]))
    b = model_domain(_entry(experiment_periods=[1.0, 1.0, 1.0], author_deck_periods=author))
    assert a["time_max"] == b["time_max"]


def test_resolve_entry_carries_both_and_never_calls_the_probe_the_deck(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    (cache / "someone__repo").mkdir(parents=True)
    (cache / "someone__repo" / "umat.f").write_text(GROWTH)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"records": [
        {"key": "k1", "source_id": "someone__repo/umat.f",
         "cache_path": "someone__repo/umat.f"},
        {"key": "k2", "source_id": "someone__repo/umat.f",
         "cache_path": "someone__repo/umat.f"}]}))
    manifest = {"ntens": 6, "nstatv": 1, "props": [1.0e3],
                "loading": [{"period": 1.0}, {"period": 1.0}, {"period": 1.0}]}
    records = tmp_path / "store_verification.jsonl"
    records.write_text(
        json.dumps({"key": "k1", "manifest": manifest}) + "\n"
        + json.dumps({"key": "k2", "manifest": manifest,
                      "author_deck_periods": [1.0, 1.0, 1.0]}) + "\n")
    monkeypatch.setattr(H, "REGISTRY", registry)
    monkeypatch.setattr(H, "PASS16", records)
    monkeypatch.setattr(H, "CACHE", cache)
    monkeypatch.setattr(H, "STORE", tmp_path / "store")
    monkeypatch.setattr(H, "FAMILIES", tmp_path / "families.json")
    monkeypatch.setattr(H, "EXPERIMENT_WORK", tmp_path / "work")

    probe_only = H.resolve_entry("k1").as_mapping()
    assert "deck_periods" not in probe_only
    assert probe_only["experiment_periods"] == [1.0, 1.0, 1.0]
    assert probe_only["author_deck_periods"] is None
    assert not _cited_as_deck(model_domain(probe_only))

    recorded = H.resolve_entry("k2").as_mapping()
    assert recorded["author_deck_periods"] == [1.0, 1.0, 1.0]
    assert _cited_as_deck(model_domain(recorded))


def test_the_abaqus_pass_records_the_authors_step_periods(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo / "src"))
    monkeypatch.syspath_prepend(str(repo / "tools"))
    sys.modules.pop("verify_store_in_abaqus", None)
    import verify_store_in_abaqus as tool

    columns = tool._material_columns(tool.ManifestPlan(author_deck_periods=[1.0, 1.2]))
    assert columns["author_deck_periods"] == [1.0, 1.2]
    assert tool._material_columns(tool.ManifestPlan())["author_deck_periods"] is None
