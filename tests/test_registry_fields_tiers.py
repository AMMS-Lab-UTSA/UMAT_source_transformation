"""Both origins, the tier split, and the R6 counting rule (D-19, D-21, D-19a rev 2 S2).

* The deck-only figures on the committed pass23 registry do not move: 242
  eligible, 106 Abaqus verified under the D-4 gate (G10), 114 routine level
  (D-8). (242 / 105 / 113 at pass22; 245 / 102 / 112 at pass21.)
* A council row counts only under R6: both Vera acceptances, no pairing
  change, every parameter set verified (cells.combine_council_sets), no
  unenforced domain, no licence hold, a D-2 decision recorded, and the
  author-deck re-run at the council harness.
* An eligible harvest row cannot pull a source whose author block was
  rejected into a tier (czmHealing, D-19a R0).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parent
REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"
PASS23_CELLS = WORKSPACE / "corpus_campaign/pass24_harness/run/manifest_cells.jsonl"  # the pass24 cells; the name keeps its pass23 wording so the audit record still finds the test

sys.path.insert(0, str(REPO / "src"))
_spec = importlib.util.spec_from_file_location(
    "build_corpus_registry", REPO / "tools/build_corpus_registry.py")
reg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("build_corpus_registry", reg)
_spec.loader.exec_module(reg)

SID = "owner__repo/src/umat_council.f"


def _committed():
    return [reg.Record(**row) for row in
            json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]]


def _council_record(**kw) -> "reg.Record":
    base = dict(source_id=SID, key="k1", terminal_state="missing_material_data",
                adequately_specified=False, is_umat=True,
                material_data_origin="council_chosen", experiment_origin="council",
                adequacy_tier="council_chosen", council_sets="A;B",
                council_deck_ref="council_plans/k1/council_plan.json",
                vera_accepted_template=True, vera_accepted_instance=True,
                redistribution="permitted")
    base.update(kw)
    return reg.Record(**base)


def _cells(statuses: dict, *, defined=True) -> list:
    out = []
    for set_id, status in statuses.items():
        for feature in ("primal_stress_state", "ddsdde"):
            out.append({"source_id": SID, "feature": feature, "council_set": set_id,
                        "council_sets": sorted(statuses), "status": status,
                        "reason": f"set {set_id} {status}",
                        "stress_and_ddsdde_fully_defined": defined})
    return out


def _counted(record, cells, rerun="h1"):
    return reg.council_counted(record, cells, author_rerun_harness=rerun)


# ---------------------------------------------------------------------------
# the deck-only figures
# ---------------------------------------------------------------------------
def test_the_deck_only_figures_of_the_committed_pass23_registry_are_unchanged():
    records = reg.apply_origins(_committed(), reg.origin_inputs())
    cells = (reg._read_rows(PASS23_CELLS) if PASS23_CELLS.is_file() else None)
    tiers = reg.tier_summary(records, cells)["tiers"]
    deck = tiers[reg.TIER_AUTHOR_DECK]
    assert deck["eligible"] == 264
    assert deck["verified_abaqus"] == 106
    if cells is None:
        pytest.skip("pass24 harness cells not on this machine; 242/106 checked")
    assert deck["verified_routine"] == 114
    # the deck-only D2 itself is untouched
    assert sum(1 for r in records if r.adequately_specified) == 264
    assert {r.adequacy_tier for r in records if r.adequately_specified} == {"author_deck"}


def test_every_tier_is_reported_even_when_empty():
    tiers = reg.tier_summary([], None)["tiers"]
    assert list(tiers) == list(reg.TIERS)
    assert all(row["eligible"] == 0 for row in tiers.values())


# ---------------------------------------------------------------------------
# R6
# ---------------------------------------------------------------------------
def test_a_council_row_with_every_condition_met_counts():
    counts, why = _counted(_council_record(), _cells({"A": "verified", "B": "verified"}))
    assert counts is True, why


@pytest.mark.parametrize("missing", ["vera_accepted_template", "vera_accepted_instance"])
def test_a_council_row_without_both_acceptances_is_not_counted(missing):
    record = _council_record(**{missing: False})
    counts, why = _counted(record, _cells({"A": "verified", "B": "verified"}))
    assert counts is False
    assert any(code.startswith("R6.5") for code, _ in why)
    counts, _ = _counted(_council_record(**{missing: None}),
                         _cells({"A": "verified", "B": "verified"}))
    assert counts is False


def test_a_pairing_changed_row_is_not_counted():
    record = _council_record(pairing_changed=True)
    counts, why = _counted(record, _cells({"A": "verified", "B": "verified"}))
    assert counts is False
    assert ("R6.2_pairing_changed" in {code for code, _ in why})


def test_a_multi_set_row_with_one_failed_set_is_not_counted():
    counts, why = _counted(_council_record(), _cells({"A": "verified", "B": "failed"}))
    assert counts is False
    assert {"primal_stress_state", "ddsdde"} <= {code for code, _ in why}


def test_a_multi_set_row_with_a_missing_set_is_not_counted():
    cells = [c for c in _cells({"A": "verified", "B": "verified"}) if c["council_set"] == "A"]
    for cell in cells:
        cell["council_sets"] = ["A"]          # a cell that forgot the plan's second set
    counts, why = _counted(_council_record(), cells)
    assert counts is False, why


@pytest.mark.parametrize("change, code", [
    (dict(domain_not_enforced="strain_max stated only in words"), "domain_not_enforced"),
    (dict(licence_hold="all rights reserved"), "licence_hold"),
    (dict(redistribution=""), "D-2"),
    (dict(council_sets="A"), "D-21.3_sets"),
    (dict(council_refusal="needs_documented_geometry: ..."), "council_plan_refused"),
])
def test_every_other_r6_condition_blocks_counting(change, code):
    counts, why = _counted(_council_record(**change),
                           _cells({"A": "verified", "B": "verified"}))
    assert counts is False
    assert code in {c for c, _ in why}


def test_no_council_row_counts_before_the_author_deck_rerun():
    counts, why = _counted(_council_record(), _cells({"A": "verified", "B": "verified"}),
                           rerun="")
    assert counts is False and why[0][0] == "R6.6"


def test_a_bare_cell_cannot_count_for_a_council_row():
    cells = _cells({"A": "verified", "B": "verified"})
    cells.append({"source_id": SID, "feature": "ddsdde", "status": "verified"})
    counts, why = _counted(_council_record(), cells)
    assert counts is False and "C6_bare_cell" in {c for c, _ in why}


def test_undefined_stress_or_ddsdde_blocks_counting():
    counts, why = _counted(_council_record(),
                           _cells({"A": "verified", "B": "verified"}, defined=False))
    assert counts is False and "undefined_outputs" in {c for c, _ in why}


def test_the_tier_summary_counts_only_r6_rows():
    good = _council_record()
    bad = _council_record(source_id="owner__repo/src/other.f", pairing_changed=True)
    cells = _cells({"A": "verified", "B": "verified"})
    cells += [dict(c, source_id=bad.source_id) for c in cells]
    tiers = reg.tier_summary([good, bad], [], council_cells=cells,
                             author_rerun_harness="h1")["tiers"]
    council = tiers[reg.TIER_COUNCIL_CHOSEN]
    assert council["eligible"] == 2 and council["verified_routine"] == 1
    assert council["verified_abaqus"] is None
    assert good.counted_in_tier is True and bad.counted_in_tier is False


# ---------------------------------------------------------------------------
# origins and routing
# ---------------------------------------------------------------------------
def _harvest(eligible=True, origin="author_published_outside_deck", confidence="exact"):
    return {"source_id": SID, "key": "k1", "eligible": eligible, "duplicate_of": None,
            "material_data_origin": origin,
            "constants": [{"index": 1, "confidence": "exact"},
                          {"index": 2, "confidence": confidence}]}


def _plan(route="no_deck_in_repository", code="", **kw):
    return {"row_key": "k1", "route": route, "refusal_code": code, "refusal": "",
            "council_fingerprint": "f" * 16, "material_data_origin": "x",
            "domain_not_enforced": [], "branch_coverage": None,
            "sets": [{"set_id": "author"}], "_ref": "council_plans/k1/council_plan.json",
            **kw}


def _inputs(harvest=None, council=None, plan=None):
    return {"harvest": {SID: harvest} if harvest else {},
            "council": {SID: council} if council else {},
            "plans": {"k1": plan} if plan else {}, "plans_by_source": {},
            "acceptance": {}, "refs": {"harvest": "h.jsonl", "council": "c.jsonl"}}


def _bare(**kw):
    base = dict(source_id=SID, key="k1", terminal_state="missing_material_data",
                adequately_specified=False, is_umat=True)
    base.update(kw)
    return reg.Record(**base)


def test_an_eligible_harvest_row_on_a_council_route_is_published_with_a_council_experiment():
    [record] = reg.apply_origins([_bare()], _inputs(_harvest(confidence="interpreted"),
                                                     plan=_plan()))
    assert record.material_data_origin == "author_published_outside_deck"
    assert record.experiment_origin == "council"
    assert record.adequacy_tier == reg.TIER_PUBLISHED_COUNCIL
    assert record.harvest_confidence == "interpreted" and record.interpreted_constants == 1
    assert record.council_deck_ref and record.council_fingerprint == "f" * 16
    assert record.material_data_ref == "h.jsonl#key=k1"
    assert record.refusal_kind == "no_deck_in_repository"


def test_an_unresolved_author_deck_keeps_the_authors_experiment():
    [record] = reg.apply_origins(
        [_bare()], _inputs(_harvest(), plan=_plan(route="author_deck_unresolved",
                                                  code="not_a_council_route")))
    assert record.adequacy_tier == reg.TIER_PUBLISHED_AUTHOR
    assert record.experiment_origin == "author"


def test_a_rejected_author_block_routes_an_eligible_harvest_row_out():
    """czmHealing: STATEV(13) against *DEPVAR 12. The row is eligible and
    stays refused (D-19a R0)."""
    [record] = reg.apply_origins(
        [_bare()], _inputs(_harvest(), plan=_plan(route="author_block_rejected",
                                                  code="not_a_council_route")))
    assert record.adequacy_tier == "" and record.material_data_origin == ""
    assert "author_block_rejected" in record.adequacy_tier_basis


def test_council_constants_carry_their_sets_acceptance_and_licence_hold():
    council = {"source_id": SID, "harvest_key": "k1", "counts_in_tier": True,
               "duplicate_of": None, "experiment_origin": "council_deck",
               "licence_hold": None, "vera_accepted_template": False,
               "vera_accepted_instance": False,
               "sets": [{"set_id": "A", "constants": [{"confidence": "chosen"}]},
                        {"set_id": "B", "constants": [{"confidence": "looked-up"}]}]}
    plan = _plan(sets=[{"set_id": "A"}, {"set_id": "B"}])
    [record] = reg.apply_origins([_bare()], _inputs(council=council, plan=plan))
    assert record.adequacy_tier == reg.TIER_COUNCIL_CHOSEN
    assert record.council_sets == "A;B" and record.harvest_confidence == "chosen"
    assert record.vera_accepted_template is False
    held = dict(council, licence_hold="all rights reserved")
    [record] = reg.apply_origins([_bare()], _inputs(council=held, plan=plan))
    assert record.adequacy_tier == "" and "licence hold" in record.adequacy_tier_basis


def test_a_deck_only_record_is_the_author_deck_tier_whatever_rows_exist():
    [record] = reg.apply_origins([_bare(adequately_specified=True,
                                        terminal_state="fully_verified")],
                                 _inputs(_harvest(), plan=_plan(code="pairing_changed")))
    assert (record.material_data_origin, record.experiment_origin,
            record.adequacy_tier) == ("author_deck", "author", "author_deck")
    assert record.pairing_changed is True


def test_the_enums_are_the_ones_the_decisions_name():
    assert reg.MATERIAL_DATA_ORIGINS == ("author_deck", "author_published_outside_deck",
                                         "council_chosen")
    assert reg.EXPERIMENT_ORIGINS == ("author", "council")
    assert reg.experiment_origin_of("council_deck") == "council"
    assert reg.experiment_origin_of("author_deck_with_council_parameters") == "author"
    with pytest.raises(ValueError):
        reg.experiment_origin_of("somebody")
