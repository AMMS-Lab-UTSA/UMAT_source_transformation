"""The one-page verdict: a colour, a sentence, and one next action.

``umat-oti`` leaves a results file with every stage in it. A reader wants to
know four things before anything else: may I call this verified, if not why
not, whose move is it, and what do I do next. This turns a results record into
exactly that, as text a terminal or a report can print.

Colours:

* **green**  -- :func:`~umat_oti.app.plain_language.may_say_verified` is true:
  all six gates were measured and all six read true. Nothing else is green,
  whatever the pipeline's own ``verdict`` string says.
* **amber**  -- something was produced and partly checked, but not all six
  gates: a derivative check that did not settle, a truncated derivative, a
  loading that may not have exercised the material, or a pipeline verdict of
  "verified" with no six-gate evidence recorded.
* **blue**   -- the next move is the user's (constants, a missing file, a
  loading).
* **red**    -- it cannot be done, or it failed, and the move is the author's
  or this program's.

The record may be a corpus registry row, a store record, or a command-line
results file in which the six-gate block and the terminal state are nested
anywhere (they are found by name).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

from umat_oti.app.plain_language import (GATE_PLAIN, _verdict, may_say_verified,
                                         plain_sentence, verified_summary)
from umat_oti.app.refusal_cards import card_for, state_after_reading

__all__ = ["verdict_for", "render_verdict", "VERIFIED_SENTENCE", "banner_for_card", "card_colour",
           "elsewhere_texts", "ELSEWHERE_BANNER", "TRIAL_SENTENCE", "abaqus_hint", "main"]

VERIFIED_SENTENCE = (
    "Both versions of your material ran and agreed on the stresses, and the "
    "derivatives matched an independent check of your original routine, in "
    "this test only.")

#: States where a result exists and was partly checked.
AMBER_STATES = frozenset({
    "tangent_not_verified", "derivative_truncated",
    "experiment_not_informative", "informativeness_not_established",
    "primal_mismatch_explained",
})

#: States whose card speaks about a numerical check that ran without Abaqus.
NUMERICAL_CHECK_STATES = frozenset({"tangent_not_verified", "primal_control_not_decided",
                                    "primal_mismatch_explained", "derivative_truncated"})

_COLOUR_WORD = {"green": "GREEN: VERIFIED",
                "amber": "AMBER: PARTLY CHECKED",
                "blue": "BLUE: I NEED ONE THING FROM YOU",
                "red": "RED: CANNOT BE VERIFIED"}


#: The six checks as yes-or-no questions, so that a list of them never reads as a list of passes.
CHECK_QUESTION = {
    "abaqus_job_completed": "did the Abaqus job run to the end?",
    "all_requested_outputs_present": "did every step report results?",
    "complete_history_finite": "are all the results real numbers?",
    "primal_agreed": "did both versions compute the same stresses?",
    "derivatives_verified": "did the derivatives match a numerical check?",
    "mechanically_informative": "did the test make the material act?",
}


def _n(x) -> int:
    return len(x) if isinstance(x, (list, tuple, set)) else int(x or 0)


def _find(obj: Any, key: str) -> Any:
    """The first value stored under ``key`` anywhere in nested dicts/lists."""
    if isinstance(obj, dict):
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
        for v in obj.values():
            hit = _find(v, key)
            if hit not in (None, ""):
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find(v, key)
            if hit not in (None, ""):
                return hit
    return None


def _evidence_block(record: Any) -> dict:
    block = _find(record, "evidence")
    return {"evidence": block} if isinstance(block, dict) else {}


def _record_for_gates(record: Any) -> dict:
    """A flat dict ``may_say_verified`` can read, from whatever was given."""
    if isinstance(record, dict) and isinstance(record.get("evidence"), dict):
        return record
    flat = dict(record) if isinstance(record, dict) else {}
    flat.update(_evidence_block(record))
    if "evidence" not in flat:
        # Corpus registry rows carry the gates as ``gate_<name>`` fields.
        word = {"true": True, "false": False, True: True, False: False}
        gates = {k[len("gate_"):]: word.get(v.lower() if isinstance(v, str) else v)
                 for k, v in flat.items() if k.startswith("gate_")}
        if gates:
            flat["evidence"] = gates
    return flat


def _state_of(record: Any) -> str:
    state = _find(record, "terminal_state")
    if state:
        return str(state)
    stage = _find(record, "stage")
    if stage:
        return _verdict(str(stage)).state
    return ""


def _reason_of(record: Any) -> str:
    for key in ("not_verified_reason", "reason", "blocker", "message"):
        value = _find(record, key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


ELSEWHERE_BANNER = "AMBER: VERIFIED ANOTHER WAY, NOT BY THIS CHECK COMMAND"

#: What the Abaqus command does, said plainly: ``umat-oti verify`` runs both versions of the file in Abaqus,
#: in a scratch folder, and gives the same six checks the corpus uses.
TRIAL_SENTENCE = ("That command runs both versions of your file in Abaqus, in a scratch folder, and applies the same "
                  "six checks the corpus uses. It needs Abaqus, an Intel Fortran compiler and your deck with its "
                  "material constants, and takes a few minutes.")


def abaqus_hint(command: str) -> str:
    """The one sentence pair that offers the Abaqus command and says what it needs."""
    return f"If you have Abaqus, this runs your files there:  {command}  {TRIAL_SENTENCE}"


def elsewhere_texts(elsewhere: str, other_deck: Optional[str] = None, command: Optional[str] = None) -> tuple:
    """(what happened, next step) for a file this check command cannot take but the corpus record verified.

    ``other_deck``: the record verified the same UMAT with that other deck, not the one given.
    ``command``: the Abaqus comparison a user with Abaqus can run on their own version of the files.
    """
    what = ("This check command (it does not run Abaqus) covers small-deformation solid models (strains of a few "
            "percent at most) only. ")
    if other_deck:
        what += (f"The full corpus run verified this file with a different deck ({other_deck}; run {elsewhere}), "
                 "not with yours.")
    else:
        what += f"The full corpus run verified this exact file another way (run {elsewhere})."
    nxt = ("Nothing to do for this exact file: the corpus result stands."
           if not other_deck else
           "Nothing is broken. The verified result belongs to that other deck; with yours there is none yet.")
    if command:
        nxt += (" If you change the file or the deck, a verified result for your version needs the six-check "
                f"Abaqus comparison. {abaqus_hint(command)}")
    return what, nxt


def card_colour(state: str, whose: str) -> str:
    """amber where a result exists and was partly checked; blue where it is the user's move; else red."""
    if state in AMBER_STATES:
        return "amber"
    return "blue" if whose == "you" else "red"


#: The banner words of a card printed on its own (a refusal or a request), colour first.
_CARD_BANNER = {"amber": "AMBER: PARTLY CHECKED", "blue": "BLUE: I NEED ONE THING FROM YOU", "red": "RED: REFUSED"}


def banner_for_card(state: str, whose: str) -> str:
    return _CARD_BANNER[card_colour(state, whose)]


def verdict_for(record: Any, elsewhere: Optional[str] = None, command: Optional[str] = None,
                other_deck: Optional[str] = None) -> dict:
    """The verdict as data: colour, headline, lines and the one next action."""
    flat = _record_for_gates(record)
    summary = verified_summary(flat)
    reason = _reason_of(record)
    state = state_after_reading(_state_of(record), reason)
    pipeline_word = str(_find(record, "verdict") or "")
    caution = []
    # The pipeline's own numerical check passed and none of the six Abaqus
    # gates was ever measured: its own state, amber, never green.
    derivative_only = (pipeline_word.lower() == "verified"
                       and summary["gates that hold"] in (0, [], ())
                       and _n(summary["gates never established"]) == 6)

    # Green needs the six gates AND a terminal state that says so: a record
    # whose gates all read true but whose state is, for example,
    # derivative_truncated (the converted source drops a derivative it then
    # uses) is the state's own card, never green.
    if may_say_verified(flat) and state in ("", "fully_verified"):
        colour, whose = "green", "nobody"
        sentence = VERIFIED_SENTENCE
        action = ("Open the results table to read the derivatives, or test "
                  "a larger loading to reach behaviour this test did not.")
        if flat.get("activated") is False:
            caution.append(
                "Caution: the material stayed elastic in this test, so the "
                "check says nothing about yielding or other behaviour that "
                "never happened.")
    else:
        card = card_for(state, reason) if state and state != "fully_verified" else None
        if card is None:
            # No refusal: a result with gates missing, or the pipeline's own
            # word "verified" with no six-gate evidence behind it. Never green.
            colour, whose = "amber", "you"
            if derivative_only:
                state = "derivative_check_passed_abaqus_not_run"
                sentence = ("The numerical derivative check passed; the "
                            "Abaqus checks were not run.")
                action = ("Run the Abaqus check to verify the translated "
                          "routine against your original"
                          + (f" (a verified result needs the six-check Abaqus comparison. {abaqus_hint(command)})" if command else "")
                          + ". Until then call this 'derivatives checked numerically', not "
                          "'verified'.")
            else:
                why = summary["why not"] or "the checks the word 'verified' needs were not all measured"
                sentence = ("A result was produced, but it cannot be called "
                            f"verified: {why}")
                action = ("Run the full check (with Abaqus) before quoting "
                          "this as verified"
                          + (f" (a verified result needs the six-check Abaqus comparison. {abaqus_hint(command)})" if command else "")
                          + "; until then call it 'derivatives checked numerically'.")
        else:
            sentence, whose, action = (card.sentence, card.whose_move,
                                       card.next_action)
            colour = card_colour(state, whose)

    headline = None
    if state == "unsupported_formulation" and elsewhere and colour != "green":
        # The file is not broken: this check command cannot take its kind of model, and the full
        # corpus run verified the exact file another way. Not red (red is a real failure).
        colour, whose = "amber", "nobody (nothing is broken)"
        sentence, action = elsewhere_texts(elsewhere, other_deck, command)
        headline = ELSEWHERE_BANNER
    assert colour != "green" or (may_say_verified(flat) and state in ("", "fully_verified"))
    return {
        "colour": colour,
        "headline": (headline or ("AMBER: DERIVATIVES CHECKED, ABAQUS NOT RUN"
                                  if state == "derivative_check_passed_abaqus_not_run"
                                  else _COLOUR_WORD[colour])),
        "sentence": sentence,
        "whose move": whose,
        "next action": action,
        "caution": caution,
        "terminal state": state,
        "gates that hold": summary["gates that hold"],
        "gates that did not hold": summary["gates that did not hold"],
        "gates never established": summary["gates never established"],
        "reason recorded": reason,
    }


def render_verdict(record: Any, elsewhere: Optional[str] = None, command: Optional[str] = None,
                   other_deck: Optional[str] = None) -> str:
    """The one-page verdict as plain text."""
    v = verdict_for(record, elsewhere, command, other_deck)
    bar = "=" * 70
    if v["colour"] == "green":
        out = [bar, v["headline"], bar, v["sentence"]] + v["caution"] + [f"Next: {v['next action']}"]
    else:
        # the one next step first, then what happened and whose move it is
        out = [bar, v["headline"], bar, f"Next: {v['next action']}", v["sentence"]] + v["caution"]
        out.append(f"Whose move: {v['whose move']}.")
    if v["terminal state"] == "derivative_check_passed_abaqus_not_run":
        out.append("Abaqus checks: not run.")
        out.append('The word "verified" needs all the Abaqus checks: ' + VERIFIED_SENTENCE)
        return "\n".join(out)
    def names(items) -> str:
        return "; ".join(CHECK_QUESTION.get(x, str(x).replace("_", " ")) for x in items) or "none"

    held, broke, never = v["gates that hold"], v["gates that did not hold"], v["gates never established"]
    out.append("The six checks the word 'verified' needs, each a yes-or-no question about the Abaqus runs: "
               f"held: {names(held)}. Failed: {names(broke)}. "
               + (f"Not run here (they need Abaqus, which this check command does not run): {names(never)}."
                  if _n(never) else "Not run here: none."))
    if _n(never) and not _n(held) and not _n(broke) and v["terminal state"] in NUMERICAL_CHECK_STATES:
        out.append("What is said above about the stresses and the derivatives comes from the numerical check "
                   "made without Abaqus (each constant is nudged a little and the change in stress is compared), "
                   "so it does not contradict the line above.")
    if v["reason recorded"] and v["colour"] != "green":
        out.append("What the run recorded: " + plain_sentence(v["reason recorded"])[:400])
    out.append('"Verified" means: ' + VERIFIED_SENTENCE)
    return "\n".join(out)


def main(argv: Optional[list] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m umat_oti.app.verdict_page RESULTS.json")
        return 2
    record = json.loads(Path(args[0]).read_text())
    print(render_verdict(record))
    return 0


if __name__ == "__main__":                         # pragma: no cover
    raise SystemExit(main())
