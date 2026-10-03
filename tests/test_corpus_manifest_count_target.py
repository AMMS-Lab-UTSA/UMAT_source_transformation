"""count_target.py (corpus_campaign): tier columns and the R6.4 Fisher test (S3).

* The deck-only column is the D-8 figure: 245 eligible, 102 Abaqus (D-4
  gate, G10), 112 routine level on the pass21 registry and harness cells,
  whether or not a council row is added beside them (238 / 67 / 109 at
  pass20, before the D-4 Abaqus gate and the 2026-10-02 discovery round).
* The Fisher exact test is two-sided, matches reference values, and runs only
  when both arms have n >= 5 attempted.

Skipped where the campaign workspace is not on this machine.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CAMPAIGN = REPO.parent / "corpus_campaign"
COUNT_TARGET = CAMPAIGN / "count_target.py"
CELLS = CAMPAIGN / "pass21_harness/run/manifest_cells.jsonl"
REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"

if not COUNT_TARGET.is_file():
    pytest.skip("corpus_campaign/count_target.py is not on this machine",
                allow_module_level=True)

_spec = importlib.util.spec_from_file_location("count_target", COUNT_TARGET)
ct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ct)
reg = ct._registry_tool()


def _families():
    try:
        return ct.families()
    except OSError:
        pytest.skip("family classifications not on this machine")


@pytest.mark.parametrize("table, p", [
    ((3, 1, 1, 3), 0.48571428571428565),
    ((1, 9, 11, 3), 0.0027594561852200836),
    ((0, 5, 5, 0), 0.007936507936507938),
    ((2, 30, 60, 178), 0.013746743368816688),   # scipy.stats.fisher_exact, two-sided
])
def test_the_fisher_test_is_two_sided_and_exact(table, p):
    assert ct.fisher_exact_two_sided(*table) == pytest.approx(p, rel=1e-9)


def test_the_deck_only_column_is_the_d8_figure():
    if not CELLS.is_file():
        pytest.skip("pass21 harness cells not on this machine")
    fam = _families()
    records = json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]
    denom, abaqus, routine = ct.deck_counts(records, fam, CELLS)
    assert (sum(denom.values()), sum(abaqus.values()), sum(routine.values())) == (245, 102, 112)
    # the same figure from a registry that carries the tier columns, with a
    # council row added beside it: the deck column does not move
    tiered = [r.as_dict() for r in reg.apply_origins(
        [reg.Record(**r) for r in records], reg.origin_inputs())]
    council_before = sum(c["eligible"] for c in
                         ct.tier_counts(tiered, fam, CELLS)["council_chosen"].values())
    tiered.append(reg.Record(source_id="o__r/council.f", terminal_state="missing_material_data",
                             adequately_specified=False, material_data_origin="council_chosen",
                             experiment_origin="council",
                             adequacy_tier="council_chosen").as_dict())
    again = ct.deck_counts(tiered, fam, CELLS)
    assert (sum(again[0].values()), sum(again[1].values()), sum(again[2].values())) == \
        (245, 102, 112)
    tiers = ct.tier_counts(tiered, fam, CELLS)
    # the committed registry is built with the S2 options, so it carries its
    # own council_chosen rows (30 at pass21); the added row is one more
    assert sum(c["eligible"] for c in tiers["council_chosen"].values()) == council_before + 1
    assert sum(c["routine"] for c in tiers["council_chosen"].values()) == 0


def test_fisher_runs_only_when_both_arms_have_five_attempted():
    tiers = {t: collections.defaultdict(collections.Counter) for t in ct.TIER_LABELS}
    tiers["council_chosen"]["growth"].update(routine=0)
    attempted = {"author_deck": collections.Counter(growth=20, other=20),
                 "council": collections.Counter(growth=6, other=4)}
    out = ct.fisher_by_family({"growth": 20, "other": 20}, tiers, attempted)
    assert out["growth"]["status"] == "HOLD for review" and out["growth"]["p"] < 0.05
    assert out["other"]["status"].startswith("not run")
    assert "p" not in out["other"]
    assert ct.fisher_by_family(None, tiers, attempted)["growth"]["status"].startswith("not run")
