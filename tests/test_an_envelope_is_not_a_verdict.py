"""The residual screen offered all 237 materials as verified. Only 42 are.

``ServiceResult.ok`` is the ENVELOPE's flag: it means the service call itself
succeeded, which is true of every entry the service managed to look at,
including the ones it refuses. ``residual_bridge._eligible`` read it as the
verdict, so the Residual Assembler screen listed as ready-to-use every corpus
entry including the ones at ``needs_material_data``, where all six gates read
"not established" and there is no evidence block at all -- while the service
itself was returning ``eligible=False`` with three named reasons.

Offering an unverified material as verified is the one thing that screen must
never do, and it was doing it for 195 of 237 materials.

Fixing the envelope left a second, quieter version of the same mistake: the
service's ``eligible`` answers whether a FIXTURE CAN BE FROZEN, which needs a
complete finite history and asks three of the six gates. That is a weaker
question than "was this verified", and taking it alone still offered 139. The
screen asks BOTH: the six gates decide, and the service may refuse further.
"""
import json
import os
import pathlib

import pytest

from umat_oti.app import corpus_view, residual_bridge
from umat_oti.app.residual_bridge import may_say_verified
from umat_oti.app.unified_app import area_view

GATES = ("abaqus_job_completed", "all_requested_outputs_present",
         "complete_history_finite", "primal_agreed", "derivatives_verified",
         "mechanically_informative")


def _results():
    where = pathlib.Path(os.environ.get("UMAT_OTI_PASS11") or (
        pathlib.Path.home() / "softwarex_work" / "corpus_run" / "pass11"
        / "results"))
    if not (where / "store_verification.jsonl").is_file():
        pytest.skip(f"no corpus results at {where}")
    return where


def test_ok_is_not_among_the_fields_read_as_a_verdict():
    """Named, so the reason it is absent survives the next person to add a
    fallback field to that list."""
    assert "ok" not in residual_bridge.VERDICT_FIELDS
    assert "eligible" in residual_bridge.VERDICT_FIELDS


def test_a_successful_call_that_refuses_the_entry_is_a_refusal():
    """The exact shape that caused it: ok True, eligible False."""
    class _Answer:
        ok = True

        class data:            # noqa: D106 - a stand-in for HandoffResult
            eligible = False

    assert residual_bridge._verdict_in(_Answer()) is False


def test_a_service_that_answers_nothing_is_not_read_as_a_yes():
    """None, not False and not True: 'it did not answer' is its own fact."""
    class _Quiet:
        ok = True
        data = None

    assert residual_bridge._verdict_in(_Quiet()) is None
    assert residual_bridge._verdict_in(None) is None


def test_a_dataclass_payload_is_read_as_well_as_a_dict():
    """The live payload is a dataclass, so a dict-only lookup missed it and
    fell through to the envelope -- which is how this happened."""
    class _Dataclassish:
        eligible = True

    class _Answer:
        ok = False
        data = _Dataclassish()

    assert residual_bridge._verdict_in(_Answer()) is True
    assert residual_bridge._verdict_in({"data": {"eligible": False}}) is False


def test_the_screen_offers_exactly_what_the_six_gates_admit():
    where = _results()
    run = corpus_view.load_run(where)
    view = area_view("residual", results_dir=where, run=run, probe=None)

    offered = {f.source_id for f in view["offer"]["verified"]}
    passing = {e.source_id for e in run.entries if may_say_verified(e)}
    assert offered == passing

    # and that set really is the six gates, read from the records themselves
    records = [json.loads(line) for line
               in (where / "store_verification.jsonl").read_text().splitlines()
               if line.strip()]
    six = {r.get("source") for r in records
           if all((r.get("evidence") or {}).get(g) is True for g in GATES)}
    assert offered == {s for s in six if s}


def test_nothing_the_gates_refuse_is_offered_even_if_a_service_would_take_it():
    """The service's question is weaker. It may refuse further; it may not
    admit. A stub service that says yes to everything changes nothing."""
    where = _results()
    run = corpus_view.load_run(where)
    refused = [e for e in run.entries if not may_say_verified(e)]
    assert refused

    class _PermissiveService:
        @staticmethod
        def eligible(_raw):
            return {"data": {"eligible": True}}

    residual_bridge._eligibility_service.cache_clear()
    try:
        original = residual_bridge._eligibility_service
        residual_bridge._eligibility_service = lambda: _PermissiveService()
        assert not any(residual_bridge._eligible(e) for e in refused)
    finally:
        residual_bridge._eligibility_service = original
        residual_bridge._eligibility_service.cache_clear()
