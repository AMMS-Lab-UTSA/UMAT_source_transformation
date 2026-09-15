"""A terminal state carries an owner, and a stage with no owner is refused.

EXTERNAL is a fact about somebody's published repository; more engineering
here changes none of them. INTERNAL is a limitation of this project, and every
one is work. Transmitting an internal limitation as an external blocker claims
somebody else's file is at fault for this project's gap; the reverse hides
work behind a published-source excuse.

The vocabulary is NOT redefined here. It is imported from
``umat_oti.abaqus.terminal_states``, because two copies of one vocabulary are
two vocabularies and they drift. What the contract adds is the refusal:
``from_stage`` falls back to ``not_attempted`` for a stage it does not know,
and across the boundary that fallback is a wrong owner rather than a missing
one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umat_oti.abaqus import terminal_states
from umat_oti.contract import (EXTERNAL_OWNER, INTERNAL_OWNER, TerminalState,
                               TerminalStateError, VERIFIED_OWNER,
                               known_states, translate_stage)
from umat_oti.contract.terminal import (PUBLISHED_OWNERS, from_record,
                                        owner_of, vocabulary_gap)

#: The frozen store this contract is validated against. Located relative to
#: the checkout rather than written as an absolute path: an absolute one is
#: true on exactly one computer, and a test that silently skips everywhere
#: else is a test that proves nothing everywhere else. ``UMAT_OTI_STORE``
#: overrides it for a checkout laid out differently.
STORE_ENV = "UMAT_OTI_STORE"
STORE_RELATIVE = Path("corpus_run") / "pass11" / "results" / \
    "store_verification.jsonl"


def store_path() -> Path | None:
    """The store, or ``None`` when this machine does not have it."""
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override) if Path(override).is_file() else None
    root = Path(__file__).resolve().parents[1]
    for base in (root, root.parent, root.parent.parent):
        candidate = base / STORE_RELATIVE
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def rows() -> list:
    store = store_path()
    if store is None:
        pytest.skip(f"the frozen store ({STORE_RELATIVE}) is not on this "
                    f"machine; set {STORE_ENV} to point at one")
    return [json.loads(line) for line in store.read_text().splitlines() if line]


def test_the_contract_uses_the_vocabulary_and_does_not_redefine_it():
    """The contract PUBLISHES the vocabulary -- the consuming repository
    cannot import it -- but it never contradicts it. Every state this checkout
    has must appear in the published table with the same owner; the published
    table may be AHEAD of a stale checkout, and that difference is named by
    vocabulary_gap() rather than hidden."""
    assert set(terminal_states.ALL) <= set(known_states())
    assert vocabulary_gap()["unpublished"] == []
    for state in terminal_states.EXTERNAL:
        assert owner_of(state) == EXTERNAL_OWNER
    for state in terminal_states.INTERNAL:
        assert owner_of(state) == INTERNAL_OWNER
    assert owner_of(terminal_states.FULLY_VERIFIED) == VERIFIED_OWNER
    # A PAUSE waiting on terminal input is in the file somebody published.
    assert owner_of(terminal_states.WAITS_FOR_INPUT) == EXTERNAL_OWNER


def test_an_unknown_stage_is_refused_rather_than_defaulted():
    with pytest.raises(TerminalStateError) as exc:
        translate_stage("something_nobody_mapped")
    message = str(exc.value)
    assert "FROM_STAGE" in message
    assert "EXTERNAL" in message and "INTERNAL" in message
    assert "not_attempted" in message
    # And the message says what the default cost, so the next person to reach
    # for one knows what it bought.
    assert "three entries that ran" in message


def test_the_vocabulary_itself_no_longer_invents_one_either():
    """It used to answer ``not_attempted`` -- INTERNAL, "the run never
    happened" -- for any rung nobody mapped, and said that about three entries
    that ran and whose ARGUMENTS diverged, which is an external fact about
    somebody's file. Whichever way the checkout under test behaves, the
    contract must not end up with an invented owner."""
    try:
        verdict = terminal_states.from_stage("something_nobody_mapped")
    except Exception as exc:                # UntranslatedStage, or a KeyError
        assert "not_attempted" in str(exc) or "no word" in str(exc)
        return
    # An older checkout still defaults. The contract must not follow it.
    assert verdict.state == "not_attempted"
    with pytest.raises(TerminalStateError):
        translate_stage("something_nobody_mapped")


def test_an_absent_stage_is_not_not_attempted():
    """'The record does not say' and 'this project never tried' are different
    answers, and the second is a claim."""
    for empty in (None, "", "   "):
        with pytest.raises(TerminalStateError) as exc:
            translate_stage(empty)
        assert "inventing" in str(exc.value)


def test_a_record_cannot_declare_an_owner_the_vocabulary_disagrees_with():
    with pytest.raises(TerminalStateError) as exc:
        from_record({"terminal": {"state": "transform_refused",
                                  "owner": EXTERNAL_OWNER}})
    assert "at fault for this project's gap" in str(exc.value)
    with pytest.raises(TerminalStateError):
        from_record({"terminal": {"state": "not_a_umat",
                                  "owner": INTERNAL_OWNER}})


def test_finished_means_verified_or_external_never_internal():
    assert TerminalState("fully_verified", VERIFIED_OWNER).finished
    assert TerminalState("not_a_umat", EXTERNAL_OWNER).finished
    assert not TerminalState("transform_refused", INTERNAL_OWNER).finished
    # A completion figure pooling the two would be a claim about the corpus
    # made out of facts about the pipeline.
    assert not TerminalState("tangent_not_verified", INTERNAL_OWNER).finished


# ---------------------------------------------------------------------------
# what the real store says
# ---------------------------------------------------------------------------
def test_the_published_vocabulary_and_this_checkout_agree_where_they_overlap():
    """The consuming repository cannot import terminal_states -- it is a
    different project -- so the contract PUBLISHES the vocabulary. That
    publication is held to the authority here: any state this checkout can
    produce that the contract does not publish would reach a consumer with no
    owner, which is the dangerous direction."""
    gap = vocabulary_gap()
    assert gap["unpublished"] == [], (
        f"this checkout can produce {gap['unpublished']}, which the contract "
        f"does not publish; a consumer would receive them with no owner")
    for state in terminal_states.ALL:
        assert PUBLISHED_OWNERS[state] == owner_of(state)


def test_the_two_states_added_after_the_default_did_damage_are_published():
    """Three entries that RAN were filed as runs that never happened because
    the vocabulary had no word for what they did. Both new words are here, and
    on the side the evidence puts them."""
    assert PUBLISHED_OWNERS["arguments_diverged_before_the_routine"] == \
        INTERNAL_OWNER
    assert PUBLISHED_OWNERS["disagreement_not_in_any_recorded_call"] == \
        INTERNAL_OWNER
    assert owner_of("arguments_diverged_before_the_routine") == INTERNAL_OWNER
    assert owner_of("disagreement_not_in_any_recorded_call") == INTERNAL_OWNER


def test_the_three_rows_that_broke_the_default_are_never_not_attempted(rows):
    """Not hypothetical, and the reason the default is gone.

    Three of the 237 entries carry stage
    ``arguments_diverged_before_the_routine``. They RAN, produced output, and
    were isolated to a call whose INPUTS already differed before the routine
    was entered -- inputs the solver computed from each build's own earlier
    outputs, on this project's deck. The vocabulary had
    no word for it, so ``from_stage`` answered ``not_attempted``: INTERNAL,
    "this project never tried", booked into this project's own column.

    Two outcomes are acceptable and this test accepts either, because which
    one a checkout gives depends on whether it has the word yet. What is not
    acceptable is ``not_attempted``.
    """
    unknown = [r for r in rows
               if r["stage"] == "arguments_diverged_before_the_routine"]
    assert len(unknown) == 3
    assert all((r.get("call_isolation") or {}).get("verdict")
               == "inputs_already_diverged" for r in unknown)
    for row in unknown:
        try:
            state = from_record(row)
        except TerminalStateError as exc:
            # This checkout has no word for it, so the contract refuses.
            assert "not_attempted" in str(exc)
            assert "FROM_STAGE" in str(exc)
            continue
        # This checkout has the word, and it is this project's.
        assert state.state == "arguments_diverged_before_the_routine"
        assert state.owner == INTERNAL_OWNER
        assert state.state != "not_attempted"


def test_every_other_real_row_translates_with_an_owner(rows):
    owners = {VERIFIED_OWNER: 0, EXTERNAL_OWNER: 0, INTERNAL_OWNER: 0}
    for row in rows:
        if row["stage"] not in terminal_states.FROM_STAGE:
            continue
        state = from_record(row)
        assert state.owner in owners
        assert state.stage == row["stage"]
        owners[state.owner] += 1
    # The three counts are reported apart on purpose: pooling external and
    # internal would report this pipeline's gaps as the corpus's limits.
    assert owners[VERIFIED_OWNER] == 55
    assert sum(owners.values()) in (234, 237)    # 237 once the two words land
    if sum(owners.values()) == 234:
        assert owners[EXTERNAL_OWNER] == 67      # 36 + 27 + 4
        assert owners[INTERNAL_OWNER] == 112
    else:
        # The three arguments_diverged entries are INTERNAL: ours to locate.
        assert owners[EXTERNAL_OWNER] == 67
        assert owners[INTERNAL_OWNER] == 115


def test_no_real_row_becomes_not_attempted(rows):
    """``not_attempted`` is a legal state and nothing in a run that ran should
    reach it. If a row did, the fallback would be operating."""
    for row in rows:
        if row["stage"] not in terminal_states.FROM_STAGE:
            continue
        assert from_record(row).state != "not_attempted"
