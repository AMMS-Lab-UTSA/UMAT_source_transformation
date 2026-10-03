"""The tangent gate as one word: verified, failed or unresolved (Vera's final review, pass21).

* (a) Registry and manifest carry ``tangent_verdict``, derived from the D-4
  gate's ``tangent.verified`` / ``tangent.failed``; the stage keeps its name
  ``tangent_not_verified`` for both non-verified answers.
* (b) ``ddsdde_legacy_gate`` no longer calls every non-verified tangent
  "failed": an unresolved row reads ``unresolved``, and a D-4 row carries the
  D-4 rule text, not the legacy plateau rule.
* (c) "could not pin the tangent down" is never shown for a row with
  ``tangent.failed``, in the corpus page or in plain language.
* (d) A council row whose council_sets is empty is never counted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.app import corpus_tab, plain_language
from umat_oti.corpus_features import manifest as mf

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "build_corpus_registry", REPO / "tools/build_corpus_registry.py")
reg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("build_corpus_registry", reg)
_spec.loader.exec_module(reg)

PIN = "could not pin the tangent down"
FAILED = {"verified": False, "failed": True, "reason": "entry (1,1) disagrees"}
UNRESOLVED = {"verified": False, "failed": False, "reason": "no FD plateau"}
VERIFIED = {"verified": True, "failed": False, "reason": "agreed"}
LEGACY_UNRESOLVED = {"verified": False, "reason": "no plateau"}   # pre-G10: no "failed"


@pytest.mark.parametrize("tangent, verdict", [
    (VERIFIED, "verified"), (FAILED, "failed"), (UNRESOLVED, "unresolved"),
    (LEGACY_UNRESOLVED, "unresolved"), ({"verified": True, "failed": True}, "failed"),
    (None, ""), ({}, "unresolved"),
])
def test_the_verdict_is_derived_from_verified_and_failed(tangent, verdict):
    assert mf.tangent_verdict(tangent) == verdict
    assert set(mf.TANGENT_VERDICTS) == {"verified", "failed", "unresolved"}


def _row(tangent, sid="o__r/u.f"):
    return {"source": sid, "key": "k", "stage": "tangent_not_verified",
            "fingerprint": "", "tangent": tangent, "reason": "r"}


@pytest.mark.parametrize("tangent, verdict", [(FAILED, "failed"),
                                              (UNRESOLVED, "unresolved")])
def test_the_registry_records_the_verdict_and_keeps_the_stage(tmp_path, tangent, verdict):
    results = tmp_path / "store_verification.jsonl"
    results.write_text(json.dumps(_row(tangent)) + "\n", encoding="utf-8")
    [record] = reg.build(None, results, None, inventory_ids=["o__r/u.f"])
    assert record.tangent_verdict == verdict
    assert record.stage == "tangent_not_verified"
    assert record.terminal_state == "tangent_not_verified"


def _features(tangent):
    inp = SimpleNamespace(current_pass="pass21", internal_jacobian_round="a",
                          param_sens_round="b")
    stages = {"eligible": {"status": "verified", "reason": "", "evidence": "e"},
              "primal_agreed": {"status": "verified", "reason": "", "evidence": "e"}}
    pr = {"stage": "tangent_not_verified", "tangent": tangent}
    ev = {"derivatives_verified": tangent.get("verified"), "primal_agreed": True,
          "abaqus_job_completed": True}
    return mf._features({"is_umat": True}, pr, ev, stages, "pass:x", 1e-6, None, {}, {},
                        inp)


@pytest.mark.parametrize("tangent, gate", [(FAILED, "failed"), (UNRESOLVED, "unresolved"),
                                           (LEGACY_UNRESOLVED, "unresolved"),
                                           (VERIFIED, "passed")])
def test_the_manifest_gate_follows_the_verdict(tangent, gate):
    legacy = _features(tangent)["_legacy"]
    assert legacy["gate"] == gate
    assert legacy["tangent_verdict"] == mf.tangent_verdict(tangent)
    assert legacy["counts_as_verified"] is False


def test_a_d4_row_carries_the_d4_rule_and_a_legacy_row_the_legacy_rule():
    assert _features(UNRESOLVED)["_legacy"]["rule"] == mf.D4_ABAQUS_DDSDDE_RULE
    assert "legacy OTI-vs-FD" not in _features(UNRESOLVED)["ddsdde"]["reason"]
    assert _features(LEGACY_UNRESOLVED)["_legacy"]["rule"] == mf.LEGACY_DDSDDE_RULE


def test_the_schema_accepts_unresolved_and_the_verdict():
    legacy = mf.manifest_schema()["properties"]["rows"]["items"]["properties"][
        "ddsdde_legacy_gate"]["properties"]
    assert "unresolved" in legacy["gate"]["enum"]
    assert set(mf.TANGENT_VERDICTS) <= set(legacy["tangent_verdict"]["enum"])


def test_the_corpus_page_never_says_could_not_pin_over_a_failed_tangent():
    assert PIN not in corpus_tab.GLOSS["tangent_not_verified"]
    assert PIN not in corpus_tab.gloss_for("tangent_not_verified", FAILED)
    assert "disagreed" in corpus_tab.gloss_for("tangent_not_verified", FAILED)
    assert PIN not in corpus_tab.gloss_for("tangent_not_verified", None, verdict="failed")
    assert PIN in corpus_tab.gloss_for("tangent_not_verified", UNRESOLVED)
    assert corpus_tab.gloss_for("primal_disagreed") == corpus_tab.GLOSS["primal_disagreed"]
    # nor the registry's report, which takes its glosses from the page
    assert PIN not in reg.STATE_MEANS["tangent_not_verified"]


@pytest.mark.parametrize("record", [_row(FAILED), {"stage": "tangent_not_verified",
                                                   "tangent_verdict": "failed"}])
def test_plain_language_says_the_check_disagreed_for_a_failed_tangent(record):
    status = plain_language.plain_status(record)
    assert status.headline == plain_language.TANGENT_DISAGREED["headline"]
    assert "did not settle" not in status.headline
    assert "cannot confirm or deny" not in status.means
    assert status.terminal_state == "tangent_not_verified"
    for word in plain_language.EXPERT_TERMS:
        assert word not in status.headline + status.means, word


def test_plain_language_keeps_did_not_settle_for_an_unresolved_tangent():
    status = plain_language.plain_status(_row(UNRESOLVED))
    assert status.headline == plain_language.PLAIN["tangent_not_verified"]["headline"]


def test_a_council_row_with_no_council_sets_is_never_counted():
    record = reg.Record(source_id="o__r/u.f", material_data_origin="author_published_outside_deck",
                        experiment_origin="council", council_sets="",
                        council_deck_ref="council_plans/k/council_plan.json",
                        vera_accepted_template=True, vera_accepted_instance=True,
                        redistribution="permitted")
    cells = [{"source_id": "o__r/u.f", "feature": f, "council_set": "author",
              "council_sets": ["author"], "status": "verified"}
             for f in ("primal_stress_state", "ddsdde")]
    counts, why = reg.council_counted(record, cells, author_rerun_harness="h")
    assert counts is False
    assert "no_council_sets" in {code for code, _ in why}
    # the same row with its set named counts: the empty list is what refused it
    named = reg.Record(**{**record.as_dict(), "council_sets": "author"})
    assert reg.council_counted(named, cells, author_rerun_harness="h")[0] is True
