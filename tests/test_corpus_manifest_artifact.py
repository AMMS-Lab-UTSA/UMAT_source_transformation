"""The published corpus manifest is complete, consistent and honest.

Reads ``paper_results/corpus/manifest/corpus_manifest.json`` (built by
``tools/build_corpus_manifest.py``). Every row has a status for every stage and
every feature, every count block sums to its denominator, no cell is
``verified`` without an evidence locator, and the document validates against
the JSON Schema published beside it.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from umat_oti.corpus_features.manifest import (
    FEATURES,
    OTHER_BUILDS,
    SCHEMA_ID,
    STAGES,
    STATUSES,
    expand_roots,
    manifest_schema,
    resolve_locator,
    validate_cell,
)

REPO = Path(__file__).resolve().parents[1]
#: ``UMAT_OTI_MANIFEST_DIR`` checks a scratch build instead of the published one.
OUT = Path(os.environ.get("UMAT_OTI_MANIFEST_DIR")
           or REPO / "paper_results" / "corpus" / "manifest")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((OUT / "corpus_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads((REPO / "paper_results/corpus/corpus_registry.json")
                      .read_text(encoding="utf-8"))


def test_the_manifest_validates_against_its_schema(manifest):
    import jsonschema  # declared in the [test] extra: the schema check must run in CI
    published = json.loads((OUT / "corpus_manifest.schema.json").read_text())
    assert published == manifest_schema(), "schema file is stale: rebuild"
    jsonschema.Draft202012Validator(published).validate(manifest)
    assert manifest["schema"] == SCHEMA_ID


def test_one_row_per_acquired_source_plus_the_unacquired_counted_apart(manifest,
                                                                        registry):
    acquired = [r for r in manifest["rows"] if r["row_kind"] == "acquired"]
    assert {r["source_id"] for r in acquired} == \
        {r["source_id"] for r in registry["records"]}
    assert len(acquired) == len(registry["records"])
    others = [r for r in manifest["rows"] if r["row_kind"] != "acquired"]
    d = manifest["summary"]["denominators"]
    assert d["discovered_not_acquired"]["count"] == len(others)
    assert d["D0_discovered_files"]["count"] == len(acquired) + len(others)
    assert not ({r["source_id"] for r in others} & {r["source_id"] for r in acquired})
    ids = [r["source_id"] for r in manifest["rows"]]
    assert len(ids) == len(set(ids))


def test_every_row_has_a_status_for_every_stage_and_feature(manifest):
    for row in manifest["rows"]:
        assert set(row["pipeline"]) == set(STAGES), row["source_id"]
        assert set(row["features"]) == set(FEATURES), row["source_id"]
        for name, cell in list(row["pipeline"].items()) + list(row["features"].items()):
            assert cell["status"] in STATUSES, (row["source_id"], name)
            assert cell["reason"] or cell["status"] == "verified", \
                (row["source_id"], name, "a non-verified status needs a reason")


def _all_cells(row):
    cells = list(row["pipeline"].items()) + list(row["features"].items())
    for layout, c in (row["pipeline"]["compiled"].get("layouts") or {}).items():
        cells.append((f"compiled/{layout}", c))
    for b, block in (row.get("features_other_builds") or {}).items():
        cells.extend((f"{b}/{f}", c) for f, c in block.items())
    return cells


def test_no_verified_without_an_evidence_path(manifest):
    roots = set(manifest["roots"])
    for row in manifest["rows"]:
        for name, cell in _all_cells(row):
            if cell["status"] != "verified":
                continue
            ev = cell.get("evidence") or ""
            assert ev, (row["source_id"], name)
            assert ev.split(":", 1)[0] in roots, (row["source_id"], name, ev)


def test_every_evidence_locator_resolves_to_a_file(manifest):
    unresolved = []
    for row in manifest["rows"]:
        for name, cell in _all_cells(row):
            if cell.get("evidence"):
                path, why = resolve_locator(cell["evidence"], expand_roots(manifest["roots"]))
                if path is None:
                    unresolved.append((row["source_id"], name, why))
    assert unresolved == [], unresolved[:5]


def test_every_feature_cell_passes_the_merge_validator(manifest):
    for row in manifest["rows"]:
        cells = list(row["features"].items()) + [
            (f, c) for block in row["features_other_builds"].values()
            for f, c in block.items()]
        for feat, cell in cells:
            assert validate_cell(feat, cell, roots=expand_roots(manifest["roots"])) == [], \
                (row["source_id"], feat, validate_cell(feat, cell, roots=expand_roots(manifest["roots"])))


def test_the_legacy_ddsdde_gate_is_shown_and_never_counted(manifest, registry):
    gates = registry["summary"]["evidence_gate_census"]["gates"]
    legacy = manifest["summary"]["ddsdde_legacy_gate"]["D1_acquired"]
    assert legacy["passed"] == gates["derivatives_verified"]["true"]
    for row in manifest["rows"]:
        lg = row["ddsdde_legacy_gate"]
        assert lg["counts_as_verified"] is False
        cell = row["features"]["ddsdde"]
        if cell["status"] == "verified":
            # only merged D-4 evidence, and only with the primal agreeing
            assert cell.get("producer"), row["source_id"]
            assert cell.get("plateau_basis") == "fd_only"
            assert row["features"]["primal_stress_state"]["status"] == "verified"


def test_lifted_and_provider_cells_are_never_pooled(manifest):
    s = manifest["summary"]
    rows = [r for r in manifest["rows"] if r["row_kind"] == "acquired"]
    for f in FEATURES:
        assert s["features"]["D1_acquired"][f]["verified"] == sum(
            1 for r in rows if r["features"][f]["status"] == "verified")
        for r in rows:
            b = (r["features"][f].get("build") or {}).get("kind")
            assert b in (None, "store"), (r["source_id"], f, b)
    for r in rows:
        for b in OTHER_BUILDS:
            for f, c in r["features_other_builds"][b].items():
                assert (c.get("build") or {}).get("kind") == b, (r["source_id"], b, f)


def test_a_primal_failure_is_a_disagreement(manifest):
    for row in manifest["rows"]:
        c = row["features"]["primal_stress_state"]
        if c["status"] == "failed":
            assert c.get("values_disagree") is True or (c.get("max_error") or 0) > 1, \
                row["source_id"]


def test_count_blocks_sum_to_their_denominators(manifest):
    s = manifest["summary"]
    for pop, blocks in s["stages"].items():
        n = s["denominators"][pop]["count"]
        for stage, counts in blocks.items():
            assert sum(counts.values()) == n, (pop, stage)
    for pop, blocks in s["features"].items():
        n = s["denominators"][pop]["count"]
        for feat, counts in blocks.items():
            assert sum(counts.values()) == n, (pop, feat)
    assert sum(s["redistribution"]["D1"].values()) == \
        s["denominators"]["D1_acquired"]["count"]


def test_counts_are_recomputable_from_the_rows(manifest):
    rows = [r for r in manifest["rows"] if r["row_kind"] == "acquired"]
    s = manifest["summary"]["stages"]["D1_acquired"]
    for stage in STAGES:
        verified = sum(1 for r in rows if r["pipeline"][stage]["status"] == "verified")
        assert s[stage]["verified"] == verified, stage


def test_the_funnel_never_widens_where_a_stage_needs_the_one_above(manifest):
    for pop, f in manifest["summary"]["funnel"].items():
        assert f["original_executed"] >= f["oti_executed"] >= f["primal_agreed"], pop
        assert f["transformed"] >= f["feature:primal_stress_state"], pop
        assert f["primal_agreed"] >= f["feature:primal_stress_state"], pop


def test_a_verified_stage_is_never_below_an_unverified_prerequisite(manifest):
    chain = ("transformed", "compiled", "original_executed", "oti_executed",
             "primal_agreed")
    for row in manifest["rows"]:
        p = row["pipeline"]
        for up, down in zip(chain, chain[1:]):
            if p[down]["status"] == "verified":
                assert p[up]["status"] == "verified", (row["source_id"], up, down)


def test_the_manifest_agrees_with_the_registry_it_was_built_from(manifest, registry):
    summ = registry["summary"]
    s = manifest["summary"]["stages"]["D1_acquired"]
    assert manifest["summary"]["denominators"]["D2_eligible"]["count"] == \
        summ["adequately_specified_genuine_umats"]
    assert s["transformed"]["verified"] == \
        summ["censuses"]["transformed"]["counts"]["True"]
    gates = summ["evidence_gate_census"]["gates"]
    assert s["primal_agreed"]["verified"] == gates["primal_agreed"]["true"]


def test_parameter_sensitivity_is_not_claimed_for_any_corpus_source(manifest):
    """The curated models share no code with the corpus; nothing may be invented."""
    for row in manifest["rows"]:
        for feat in ("stress_param_sens_local", "stress_param_sens_total",
                     "state_param_sens_local", "state_param_sens_total",
                     "internal_jacobian", "residual_sens", "global_sens",
                     "cli_driver"):
            assert row["features"][feat]["status"] != "verified"


def test_every_acquired_row_rehashed_its_cached_file(manifest):
    for row in manifest["rows"]:
        if row["row_kind"] == "acquired":
            assert row["sha256"]["recomputed"], row["source_id"]
            assert row["sha256"]["agrees"] is True, row["source_id"]


def test_frodal_gpl3_licence_file_is_not_read_as_agpl(manifest):
    rows = [r for r in manifest["rows"] if r["source_id"].startswith("frodal__SCMM-hypo/")]
    for r in rows:
        assert r["license"]["licence_file"]["detected_spdx"] == "GPL-3.0-or-later"
        assert r["license"]["redistribution"] == "permitted"


def test_redistribution_is_permitted_only_with_a_licence_file(manifest):
    for row in manifest["rows"]:
        lic = row["license"]
        assert lic["redistribution"] in ("permitted", "not_permitted", "unknown")
        assert lic["redistribution_basis"]
        if lic["redistribution"] == "permitted":
            assert lic["licence_file"] and lic["licence_file"]["path"], row["source_id"]


def test_family_figures_come_from_the_reviewed_classification(manifest):
    from umat_oti.corpus_features.manifest import FAMILY_CLASSIFICATION
    fc = manifest["family_classification"]
    assert fc["used"] == FAMILY_CLASSIFICATION and "D-11 S1" in fc["used"]
    assert fc["reporting_file"].endswith("families_reviewed_B3.json")
    assert fc["fallback_file"].endswith("material_families_checked_E.json")
    assert manifest["summary"]["families"]["classification"] == FAMILY_CLASSIFICATION
    # A source a later discovery round added (tools/ingest_discovery_round.py)
    # has no reviewed family until Scout reviews it: its review reads
    # "missing" and its family is empty -- never a provisional label passed
    # off as reviewed. Only those sources may be missing.
    triage = json.loads((REPO / "paper_results/discovery/discovery_triage.json")
                        .read_text(encoding="utf-8"))
    ingested = set()
    for entry in triage["summary"].get("rounds_ingested", []):
        acceptance = REPO / entry["round"] / "acceptance.json"
        ingested |= {a["source"] for a in json.loads(
            acceptance.read_text(encoding="utf-8"))["accepted"]}
    missing = set()
    for row in manifest["rows"]:
        if row["row_kind"] == "acquired":
            fam = row["model"]["family"]
            assert fam["classification"] == "D-11 S1"
            if fam["review"] == "missing":
                missing.add(row["source_id"])
                assert fam["family"] == "" and fam["reporting_family"] == "", row["source_id"]
                continue
            assert fam["review"] in ("agent_reviewed_code_evidence", "keyword_only")
            assert fam["human_reviewed"] is False
            assert fam["E"]["label"].startswith("secondary")
            if fam["identity_growth_scaffold"]:
                assert fam["family"] == "growth" and fam["b3_family"] != "growth"
    assert missing <= ingested, sorted(missing - ingested)


def test_the_summary_states_its_eligible_set_and_the_rows_dropped_from_the_earlier(
        manifest):
    note = manifest["summary"]["denominators_note"]
    assert note["eligible_now"] == manifest["summary"]["denominators"]["D2_eligible"]["count"]
    if note.get("dropped") is not None:
        assert note["dropped_count"] == len(note["dropped"])
        assert note["eligible_earlier"] - note["dropped_count"] + len(note["added"]) \
            == note["eligible_now"]
        assert all(d["terminal_state"] for d in note["dropped"])


def test_the_csv_view_has_one_line_per_row(manifest):
    with (OUT / "corpus_manifest.csv").open(newline="", encoding="utf-8") as fh:
        lines = list(csv.DictReader(fh))
    assert len(lines) == len(manifest["rows"])
    assert [x["source_id"] for x in lines] == [r["source_id"] for r in manifest["rows"]]


def test_d18_ddsdde_count_and_the_ritiol_cells_come_from_the_primal_ddsdde_run(manifest):
    src = manifest.get("feature_sources") or {}
    assert src.get("decision") == "D-18"
    assert src["primal_ddsdde_run"] == "campaign:pass22_harness/run/manifest_cells.jsonl"
    assert src["full_feature_run"] == "campaign:pass22_harness_full/combined_cells.jsonl"
    d2 = manifest["summary"]["features"]["D2_eligible"]["ddsdde"]
    assert d2["verified"] == 113
    ritiol = [r for r in manifest["rows"] if r["source_id"].startswith("RitioL__")
              and r["features"]["ddsdde"]["status"] == "verified"]
    assert len(ritiol) == 3
    for r in ritiol:
        assert r["features"]["ddsdde"]["evidence"].startswith(
            "campaign:pass22_harness/run/"), r["source_id"]
