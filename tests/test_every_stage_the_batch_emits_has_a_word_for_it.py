"""A stage nobody mapped used to become "this run never happened", and ours.

``from_stage`` defaulted to ``not_attempted`` for any rung it did not
recognise. ``not_attempted`` is INTERNAL and it means the run did not reach
this point. So the moment two new rungs were added, three pass11 entries that
HAD run -- and whose arguments diverged before the routine, which is a fact
about the experiment and not about the conversion -- were reported as runs that
never happened, filed in this project's own column.

Agent 6 found it by rendering the real pass11 file. Two wrongs from one silent
default: the wrong event and the wrong owner.

So there is no default. An unknown stage raises and says what to do about it,
and this test walks every stage the batch actually emitted and fails if any of
them has no explicit word.
"""
import json
import os
import pathlib

import pytest

from umat_oti.abaqus import terminal_states as ts


def _pass11():
    where = pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or pathlib.Path.home() / "softwarex_work" / "corpus_run")
    results = where / "pass11" / "results" / "store_verification.jsonl"
    if not results.exists():
        pytest.skip(f"no corpus results at {results}")
    return [json.loads(line) for line in results.read_text().splitlines()
            if line.strip()]


def test_every_stage_in_the_real_results_has_an_explicit_word():
    stages = {record.get("stage") for record in _pass11()}
    stages.discard(None)
    stages.discard("")
    missing = sorted(s for s in stages if s not in ts.FROM_STAGE)
    assert not missing, (
        f"these stages are in the results and have no terminal state: "
        f"{missing}. They would have become 'not_attempted' and been filed "
        f"as this project's own unfinished work.")


def test_no_real_stage_translates_to_not_attempted():
    """The specific damage: a run that happened reported as one that did not."""
    for record in _pass11():
        stage = record.get("stage")
        if not stage:
            continue
        assert ts.from_stage(stage).state != "not_attempted", stage


def test_an_unmapped_stage_raises_instead_of_inventing_a_verdict():
    with pytest.raises(ts.UntranslatedStage) as caught:
        ts.from_stage("a_rung_nobody_mapped_yet")
    message = str(caught.value)
    assert "FROM_STAGE" in message
    assert "when unsure, internal" in message


def test_an_empty_stage_is_still_not_attempted():
    """An entry with no rung recorded really has not been attempted, and that
    is the one case the old default was right about."""
    assert ts.from_stage("").state == "not_attempted"
    assert ts.from_stage(None).state == "not_attempted"


def test_the_two_new_rungs_carry_the_owner_the_evidence_supports():
    """arguments_diverged is ours -- the two builds were handed different
    arguments before the call whose outputs differ, and the solver computed
    those arguments from each build's own earlier outputs on this project's
    deck. disagreement_not_in_any_recorded_call is about THIS HARNESS -- every
    paired call was bit-identical and the history comparison reported a
    difference anyway. Neither is a fact about somebody's published file."""
    assert ts.from_stage("arguments_diverged_before_the_routine").kind == "internal"
    assert ts.from_stage("disagreement_not_in_any_recorded_call").kind == "internal"


def test_the_three_entries_that_exposed_this_are_internal():
    records = [r for r in _pass11()
               if r.get("stage") == "arguments_diverged_before_the_routine"]
    if not records:
        pytest.skip("no entry reached arguments_diverged in this run")
    for record in records:
        verdict = ts.from_stage(record["stage"])
        assert verdict.kind == "internal"
