"""The one-page verdict: green only where all six gates were measured true."""
import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app.corpus_view import EVIDENCE_GATES              # noqa: E402
from umat_oti.app.verdict_page import render_verdict, verdict_for  # noqa: E402

pytestmark = pytest.mark.unit
GATES = [g[0] for g in EVIDENCE_GATES]


def _all_true():
    return {"terminal_state": "fully_verified",
            "evidence": {g: True for g in GATES}}


def test_all_six_gates_is_green():
    assert verdict_for(_all_true())["colour"] == "green"
    assert "this test only" in render_verdict(_all_true())


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("value", [False, None])
def test_one_gate_missing_or_false_is_never_green(gate, value):
    rec = _all_true()
    rec["evidence"][gate] = value
    out = verdict_for(rec)
    assert out["colour"] != "green"
    assert "GREEN" not in render_verdict(rec)


def test_a_pipeline_verdict_of_verified_without_gates_is_amber_not_green():
    rec = {"stages": {"sensitivities": {"verification": {"result": {"verdict": "verified"}}}}}
    out = verdict_for(rec)
    assert out["colour"] == "amber" and "GREEN" not in render_verdict(rec)


def test_stage_verified_with_an_unmeasured_gate_is_not_green():
    rec = {"stage": "verified", "terminal_state": "fully_verified",
           "evidence": {g: True for g in GATES[:-1]}}
    assert verdict_for(rec)["colour"] != "green"


def test_colours_follow_whose_move_it_is():
    blue = verdict_for({"terminal_state": "missing_material_data",
                        "reason": "x publishes no deck with a *USER MATERIAL block"})
    assert blue["colour"] == "blue" and "--material-config" in blue["next action"]
    red = verdict_for({"terminal_state": "transform_refused",
                       "reason": "anchors not located: missing_stress_update_regions"})
    assert red["colour"] == "red"
    amber = verdict_for({"terminal_state": "tangent_not_verified"})
    assert amber["colour"] == "amber"
    for v in (blue, red, amber):
        assert v["next action"]


def test_registry_rows_render_green_exactly_when_the_rule_says():
    import json
    data = json.loads((REPO / "paper_results/corpus/corpus_registry.json").read_text())
    for r in data["records"]:
        green = verdict_for(r)["colour"] == "green"
        assert green == bool(r["verified_on_every_gate"]), r["source_id"]


def test_a_derivative_only_success_is_its_own_amber_state_with_its_own_next_action():
    rec = {"stages": {"sensitivities": {"verification": {"result": {"verdict": "verified"}}}}}
    v = verdict_for(rec)
    assert v["colour"] == "amber"
    assert v["terminal state"] == "derivative_check_passed_abaqus_not_run"
    assert "numerical derivative check passed" in v["sentence"]
    assert "Run the Abaqus check to verify the translated routine against your original" in v["next action"]
    text = render_verdict(rec)
    assert "GREEN" not in text and "Nothing was measured" not in text and "0 of 6" not in text


def test_the_derivative_only_state_never_applies_once_any_gate_is_measured_false():
    rec = {"stages": {"v": {"verdict": "verified"}},
           "evidence": {**{g: None for g in GATES}, GATES[0]: False}}
    assert verdict_for(rec)["terminal state"] != "derivative_check_passed_abaqus_not_run"
    assert verdict_for(rec)["colour"] != "green"


@pytest.mark.parametrize("state", ["derivative_truncated", "tangent_not_verified", "primal_control_not_decided"])
def test_all_six_gates_true_but_a_terminal_state_that_is_not_fully_verified_is_not_green(state):
    rec = {"terminal_state": state, "evidence": {g: True for g in GATES}}
    out = verdict_for(rec)
    assert out["colour"] != "green"
    assert "GREEN" not in render_verdict(rec)
    assert out["terminal state"] == state


@pytest.mark.parametrize("record", [{"evidence": {g: True for g in GATES}},
                                    {"terminal_state": "", "evidence": {g: True for g in GATES}},
                                    {"terminal_state": "fully_verified", "evidence": {g: True for g in GATES}}])
def test_all_six_gates_true_with_an_empty_or_fully_verified_state_is_green(record):
    assert verdict_for(record)["colour"] == "green"


def test_the_six_checks_are_named_and_a_run_that_made_none_does_not_contradict_its_own_card():
    from umat_oti.app.plain_language import GATE_PLAIN
    rec = {"terminal_state": "tangent_not_verified"}
    text = render_verdict(rec)
    line = [ln for ln in text.splitlines() if ln.startswith("The six checks the word")]
    assert len(line) == 1, text
    from umat_oti.app.verdict_page import CHECK_QUESTION
    for question in CHECK_QUESTION.values():
        assert question in line[0]
    assert "held: none. Failed: none. Not run here (they need Abaqus" in line[0], line[0]
    assert "0 of 6" not in text and "never measured: 6" not in text and "None of the checks" not in text
    assert any(ln.startswith("What is said above about the stresses and the derivatives comes from the numerical check") for ln in text.splitlines())
    assert "the stresses agreed and no derivative disagreed" in text


def test_a_partly_measured_record_names_the_checks_that_held_and_those_that_did_not():
    rec = {"terminal_state": "primal_disagreed",
           "evidence": {"abaqus_job_completed": True, "primal_agreed": False}}
    text = render_verdict(rec)
    line = [ln for ln in text.splitlines() if ln.startswith("The six checks the word")][0]
    assert "held: did the Abaqus job run to the end?." in line
    assert "Failed: did both versions compute the same stresses?." in line
    assert "Not run here (they need Abaqus, which this check command does not run): did every step report results?" in line
    assert "None of the checks" not in text, "never says none ran when one did"


def test_the_recorded_reason_is_shown_in_plain_words():
    text = render_verdict({"terminal_state": "missing_material_data",
                           "reason": "Automatic material configuration failed: Discovered model is not supported by the small-strain NTENS=6 sensitivity provider."})
    recorded = text.split("What the run recorded: ", 1)[1].splitlines()[0]
    assert "NTENS" not in recorded and "provider" not in recorded and "this check command" in recorded and "six stress values per point" not in recorded or "this check command" in recorded
