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

from umat_oti.app.plain_language import (_verdict, may_say_verified,
                                         verified_summary)
from umat_oti.app.refusal_cards import card_for

__all__ = ["verdict_for", "render_verdict", "VERIFIED_SENTENCE", "main"]

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

_COLOUR_WORD = {"green": "GREEN: VERIFIED",
                "amber": "AMBER: PARTLY CHECKED",
                "blue": "BLUE: I NEED ONE THING FROM YOU",
                "red": "RED: CANNOT BE VERIFIED"}


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


def verdict_for(record: Any) -> dict:
    """The verdict as data: colour, headline, lines and the one next action."""
    flat = _record_for_gates(record)
    summary = verified_summary(flat)
    state = _state_of(record)
    reason = _reason_of(record)
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
                          "routine against your original. Until then call "
                          "this 'derivatives checked numerically', not "
                          "'verified'.")
            else:
                why = summary["why not"] or "the six checks were not all measured"
                sentence = ("A result was produced, but it cannot be called "
                            f"verified: {why}")
                action = ("Run the full check (with Abaqus) before quoting "
                          "this as verified; until then call it "
                          "'derivatives checked numerically'.")
        else:
            sentence, whose, action = (card.sentence, card.whose_move,
                                       card.next_action)
            if state in AMBER_STATES:
                colour = "amber"
            elif whose == "you":
                colour = "blue"
            else:
                colour = "red"

    assert colour != "green" or (may_say_verified(flat) and state in ("", "fully_verified"))
    return {
        "colour": colour,
        "headline": ("AMBER: DERIVATIVES CHECKED, ABAQUS NOT RUN"
                     if state == "derivative_check_passed_abaqus_not_run"
                     else _COLOUR_WORD[colour]),
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


def render_verdict(record: Any) -> str:
    """The one-page verdict as plain text."""
    v = verdict_for(record)
    bar = "=" * 70
    out = [bar, v["headline"], bar, v["sentence"]]
    out += v["caution"]
    if v["colour"] != "green":
        out.append(f"Whose move: {v['whose move']}.")
    out.append(f"Next: {v['next action']}")
    if v["terminal state"] == "derivative_check_passed_abaqus_not_run":
        out.append("Abaqus checks: not run.")
        out.append('"Verified" needs all six Abaqus checks: ' + VERIFIED_SENTENCE)
        return "\n".join(out)
    out.append(f"Checks that held: {_n(v['gates that hold'])} of 6"
               + (f"; did not hold: {_n(v['gates that did not hold'])}"
                  if v["gates that did not hold"] else "")
               + (f"; never measured: {_n(v['gates never established'])}"
                  if v["gates never established"] else "") + ".")
    if v["reason recorded"] and v["colour"] != "green":
        out.append("What the run recorded: " + v["reason recorded"][:400])
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
