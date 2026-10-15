"""A failed informativeness gate says which of its rules failed.

``mechanically_informative`` fails when the material did not act, but also when
it acted and its stress grew far beyond the scales the problem supplies (its
constants, the smallest probe). The verdict said "did the test make the
material act?" and asked for a stronger loading in both cases; for the second
that is wrong on both counts. The rule that failed is recorded
(``informative_failed_rules``) and named, and the card for a response beyond
scale asks for the units and a smaller loading instead.
"""
from __future__ import annotations

from umat_oti.app.verdict_page import informative_question, render_verdict

GATES_HELD = {"abaqus_job_completed": True, "all_requested_outputs_present": True,
              "complete_history_finite": True, "primal_agreed": True,
              "derivatives_verified": True, "mechanically_informative": False}

NO_TIME_SCALE = ("this source declares no time scale of its own, so there is nothing here to "
                 "measure the experiment's duration against")
ACTED = "the material is active over the run that was verified (departure_from_linearity)"
DID_NOTHING = ("nothing in the run that was verified indicates the material did anything: no "
               "state moved, no departure from linearity, no tangent change")
BEYOND = ("the response is not accounted for by the scales this problem supplies, so it is not "
          "verified on that basis until it is explained: peak stress 2.9e+07 against 3193 expected "
          "by proportionality from 7.98 at an amplitude of 2.5e-05, a ratio of 9138 -- beyond 1e+01, "
          "so this is not more of what the search measured")
WITHIN = "the response sits within the scales this problem supplies: peak stress 3.1 against 2e+05"


def record(reason: str, rules=None) -> dict:
    block = {"informative": False, "reason": reason}
    entry = {"stage": "experiment_not_informative", "terminal_state": "experiment_not_informative",
             # another stage's reason comes first in a real record
             "reason": "4 of 4 chosen states judged and every entry agrees",
             "evidence": dict(GATES_HELD), "mechanically_informative": block}
    if rules is not None:
        entry["informative_failed_rules"] = rules
    return entry


def test_a_material_that_acted_beyond_the_problem_scale_is_told_so():
    page = render_verdict(record("; ".join([NO_TIME_SCALE, ACTED, BEYOND]), ["response_beyond_scale"]))
    assert "did the test make the material act?" not in page
    assert "Failed: did the stress stay within the scale the problem supplies?" in page
    assert "The material did act, but its stress grew far beyond the scale" in page
    assert "Give a stronger loading" not in page


def test_an_older_record_without_the_rules_is_read_from_its_reason():
    page = render_verdict(record("; ".join([NO_TIME_SCALE, ACTED, BEYOND])))
    assert "Failed: did the stress stay within the scale the problem supplies?" in page
    assert "The material did act" in page


def test_a_material_that_did_nothing_keeps_its_card():
    page = render_verdict(record("; ".join([NO_TIME_SCALE, DID_NOTHING, WITHIN]), ["no_activation"]))
    assert "Failed: did the test make the material act?" in page
    assert "Give a stronger loading" in page
    assert "did the stress stay within" not in page
    # read from the reason alone, too
    assert informative_question(record("; ".join([NO_TIME_SCALE, DID_NOTHING]))) == \
        "did the test make the material act?"


def test_every_failed_rule_is_named_and_a_family_criterion_by_its_name():
    question = informative_question(record("", ["no_activation", "response_beyond_scale",
                                                "coverage:growth tensor developed"]))
    assert "did the test make the material act?" in question
    assert "did the stress stay within the scale the problem supplies?" in question
    assert "(growth tensor developed)" in question


def test_a_held_gate_keeps_its_plain_question():
    held = record(ACTED)
    held["evidence"]["mechanically_informative"] = True
    held["terminal_state"] = held["stage"] = "fully_verified"
    page = render_verdict(held)
    assert "did the test make the material act?" in page
