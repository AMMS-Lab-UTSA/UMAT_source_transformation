"""The manifest's D-19/D-21 origin columns and their schema (D-19a rev 2 S3).

Each acquired row carries an ``origins`` block copied from the registry:
both origins, the refs, the pairing's refusal kind, the worst constant
confidence, the council sets, Vera's two acceptances, branch coverage, the
unenforced domain, the tier and whether the row counted. The enums are the
registry's, and the schema refuses a counted council row without both
acceptances.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from umat_oti.corpus_features import manifest as mf

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "paper_results/corpus/manifest"
REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"

_spec = importlib.util.spec_from_file_location(
    "build_corpus_registry", REPO / "tools/build_corpus_registry.py")
reg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("build_corpus_registry", reg)
_spec.loader.exec_module(reg)

import jsonschema  # noqa: E402 - declared in the [test] extra: the schema check must run in CI


def _row_validator():
    return jsonschema.Draft202012Validator(
        mf.manifest_schema()["properties"]["rows"]["items"])


def _a_row() -> dict:
    manifest = json.loads((OUT / "corpus_manifest.json").read_text(encoding="utf-8"))
    return copy.deepcopy(next(r for r in manifest["rows"] if r["row_kind"] == "acquired"))


def _council_origins(**kw) -> dict:
    record = reg.Record(
        source_id="o__r/u.f", material_data_origin="council_chosen",
        experiment_origin="council", refusal_kind="no_deck_in_repository",
        harvest_confidence="class-typical", interpreted_constants=0,
        council_sets="A;B", council_deck_ref="council_plans/k/council_plan.json",
        council_fingerprint="0123456789abcdef", material_data_ref="d21.jsonl#key=k",
        vera_accepted_template=True, vera_accepted_instance=True,
        branch_coverage=json.dumps({"exercised": "NTENS=6"}),
        pairing_changed=False, adequacy_tier="council_chosen",
        adequacy_tier_basis="missing_material_data for its deck; D-21",
        counted_in_tier=True)
    origins = mf.origins_of(record.as_dict())
    origins.update(kw)
    return origins


def test_the_published_schema_is_the_generated_one():
    published = json.loads((OUT / "corpus_manifest.schema.json").read_text())
    assert published == mf.manifest_schema()


def test_the_committed_manifest_validates_against_the_new_schema():
    manifest = json.loads((OUT / "corpus_manifest.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(mf.manifest_schema()).validate(manifest)


def test_a_row_with_council_origins_validates():
    row = _a_row()
    row["origins"] = _council_origins()
    _row_validator().validate(row)
    assert row["origins"]["council_sets"] == ["A", "B"]
    assert row["origins"]["branch_coverage"] == {"exercised": "NTENS=6"}


def test_a_registry_without_the_columns_gives_empty_origins_that_validate():
    record = json.loads(REGISTRY.read_text(encoding="utf-8"))["records"][0]
    origins = mf.origins_of(record)
    row = _a_row()
    row["origins"] = origins
    _row_validator().validate(row)
    assert origins["council_sets"] == [] and origins["vera_accepted_template"] in (None, False)


@pytest.mark.parametrize("field, value", [
    ("material_data_origin", "guessed"), ("experiment_origin", "council_deck"),
    ("refusal_kind", "no_deck"), ("harvest_confidence", "typical"),
    ("tier", "council"),
])
def test_a_value_outside_the_enums_is_rejected(field, value):
    row = _a_row()
    row["origins"] = _council_origins(**{field: value})
    assert list(_row_validator().iter_errors(row))


@pytest.mark.parametrize("change", [dict(vera_accepted_template=False),
                                    dict(vera_accepted_instance=None),
                                    dict(pairing_changed=True)])
def test_a_counted_council_row_needs_both_acceptances_and_an_unchanged_pairing(change):
    row = _a_row()
    row["origins"] = _council_origins(**change)
    assert list(_row_validator().iter_errors(row))


def test_the_manifest_enums_are_the_registry_enums():
    assert mf.MATERIAL_DATA_ORIGINS == reg.MATERIAL_DATA_ORIGINS
    assert mf.EXPERIMENT_ORIGINS == reg.EXPERIMENT_ORIGINS
    assert mf.REFUSAL_KINDS == reg.REFUSAL_KINDS
    assert mf.TIERS == reg.TIERS
    assert mf.CONSTANT_CONFIDENCES == reg.CONFIDENCE_ORDER
    from umat_oti.abaqus import deck_pairing
    assert mf.REFUSAL_KINDS == deck_pairing.REFUSAL_KINDS


def test_the_csv_view_carries_the_origin_columns():
    row = _a_row()
    row["origins"] = _council_origins()
    [flat] = mf.flat_rows({"rows": [row]})
    assert flat["material_data_origin"] == "council_chosen"
    assert flat["tier"] == "council_chosen" and flat["council_sets"] == "A;B"
    assert flat["vera_accepted_template"] is True
    row["origins"] = None
    [flat] = mf.flat_rows({"rows": [row]})
    assert flat["material_data_origin"] == "" and flat["counted_in_tier"] is None
