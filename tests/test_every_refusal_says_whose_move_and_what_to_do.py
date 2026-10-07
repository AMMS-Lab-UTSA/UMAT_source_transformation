"""Every refusal a command-line user can meet gets a plain sentence and an action.

The corpus registry holds the refusals the pipeline actually produced. For each
non-verified record the card must come from a SPECIFIC rule or its state's own
card, never the default, name whose move it is, and use no expert vocabulary.
The flags a card tells the user to type must be real.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.abaqus.terminal_states import ALL                  # noqa: E402
from umat_oti.app.refusal_cards import (FLAGS_USED, RULES,        # noqa: E402
                                        STATE_CARDS, card_for)
from umat_oti.app.unified_app import jargon_in                    # noqa: E402

pytestmark = pytest.mark.unit
REGISTRY = REPO / "paper_results" / "corpus" / "corpus_registry.json"
WHOSE = {"you", "the author of this UMAT", "this program"}
#: States whose reason text carries the real cause: a specific rule must match.
NEEDS_RULE = {"transform_refused", "external_dependency_unavailable",
              "incomplete_or_corrupt_source", "unsupported_formulation",
              "missing_material_data", "not_a_umat"}


def _records():
    data = json.loads(REGISTRY.read_text())
    return [r for r in data["records"] if r["terminal_state"] != "fully_verified"]


def _reason(r):
    return str(r.get("reason") or r.get("not_verified_reason") or "")


def test_every_registry_refusal_maps_to_a_non_default_card():
    bad = []
    for r in _records():
        card = card_for(r["terminal_state"], _reason(r))
        if card.rule == "default" or card.whose_move not in WHOSE or not card.next_action:
            bad.append((r["source_id"], r["terminal_state"], _reason(r)[:80]))
    assert not bad, bad[:10]


def test_refusals_with_a_recorded_cause_match_a_specific_rule():
    bad = []
    for r in _records():
        reason = _reason(r)
        if r["terminal_state"] in NEEDS_RULE and reason:
            if not card_for(r["terminal_state"], reason).rule.startswith("rule:"):
                bad.append((r["terminal_state"], reason[:90]))
    assert not bad, bad[:10]


def test_every_terminal_state_has_a_card():
    missing = [s for s in ALL if s != "fully_verified" and s not in STATE_CARDS]
    assert not missing, missing


def test_no_card_uses_expert_vocabulary():
    texts = []
    for name, pattern, build in RULES:
        for probe in ("callee ABC", "[ABC]", "module XYZ"):
            s, w, a = build(probe, "transform_refused")
            texts += [s, a]
    for sentence, whose, action in STATE_CARDS.values():
        texts += [sentence, action]
    for r in _records():
        c = card_for(r["terminal_state"], _reason(r))
        texts += [c.sentence, c.next_action]
    # Routine names quoted from the user's own file (STIFFNESMATRIX, ISO_C_BINDING)
    # are theirs, not our vocabulary: strip them before judging the wording.
    texts = [re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", "NAME", t) for t in texts]
    assert jargon_in(texts) == []


def test_the_flags_a_card_names_are_real_command_line_flags():
    cli = (REPO / "src" / "umat_oti" / "cli.py").read_text()
    for flag in FLAGS_USED:
        assert f'"{flag}"' in cli, flag
    used = {f for f in FLAGS_USED}
    text = " ".join(card_for(r["terminal_state"], _reason(r)).next_action
                    for r in _records())
    import re
    for flag in set(re.findall(r"--[a-z][a-z-]+", text)):
        assert flag in used, flag


def test_nicos_worst_refusals_name_whose_move_and_the_real_flag():
    a = card_for("transform_refused", "anchors not located: missing_stress_update_regions")
    assert a.whose_move == "this program" and "could not find where" in a.sentence
    c = card_for("external_dependency_unavailable",
                 "Helper lifting for UMAT_MAT3 reached external or undefined callee STIFFNESMATRIX (called at line 255)")
    assert c.whose_move == "you" and "STIFFNESMATRIX" in c.sentence and "--dependency-root" in c.next_action
    m = card_for("transform_refused", "ASABQARRAY appears as ASABQARRAY(...) on the stress path but is not declared anywhere in this source, which USEs TENSOR without defining it.")
    assert "TENSOR" in m.sentence and "--dependency-root" in m.next_action
    d = card_for("missing_material_data", "x publishes no deck with a *USER MATERIAL block, so")
    assert d.whose_move == "you" and "--material-config" in d.next_action
