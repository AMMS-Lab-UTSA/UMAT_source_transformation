"""A rung nobody taught the registry must stop the build, not pick a default.

``terminal_states.from_stage`` answers ``not_attempted`` for a name it does not
know. That is a real state with a real meaning -- no batch ever reached this
source -- and it is INTERNAL, so an unknown rung silently becomes this
project's own unfinished work.

pass11 is where that stopped being hypothetical. Three entries settled at
``arguments_diverged_before_the_routine``, a rung the verification tool had
added and the shared table had not been told about. Under the default they
became three sources nobody had tried, filed in this project's column, with
the evidence that the difference was in the author's own deck -- the arguments
had already parted at call 8 -- sitting unread in the record.

So the registry translates through a table that RAISES, and the three states
the tool can now emit are pinned here with the owner each belongs to.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_corpus_registry import (ALL_EXTERNAL, ALL_INTERNAL,  # noqa: E402
                                   LOCAL_STATES, STATE_MEANS,
                                   UntranslatableStage, build, kind_of,
                                   translate_stage)

pytestmark = pytest.mark.unit

#: The three states this registry is required to carry, and whose move each
#: one is. Written out rather than read from the table under test, because a
#: test that asks the code what it thinks cannot catch the code changing its
#: mind.
REQUIRED = {
    "arguments_diverged_before_the_routine": "internal",
    "disagreement_not_in_any_recorded_call": "internal",
    "published_stub_no_constitutive_content": "external",
}


@pytest.mark.parametrize("stage,owner", sorted(REQUIRED.items()))
def test_each_new_state_translates_with_the_right_owner(stage, owner):
    verdict = translate_stage(stage, "because")
    assert verdict.state == stage
    assert verdict.kind == owner
    assert verdict.reason == "because"
    assert kind_of(stage) == owner


@pytest.mark.parametrize("stage,owner", sorted(REQUIRED.items()))
def test_each_new_state_is_in_the_published_vocabulary_once(stage, owner):
    """The report prints this list. A state missing from it is a state whose
    count cannot be added to either total, and the two totals are what the
    completion figure is kept honest by."""
    external, internal = list(ALL_EXTERNAL), list(ALL_INTERNAL)
    assert external.count(stage) + internal.count(stage) == 1
    assert (stage in external) is (owner == "external")


@pytest.mark.parametrize("stage", sorted(REQUIRED))
def test_each_new_state_has_something_written_beside_it(stage):
    """A table of names is not a human-readable report."""
    assert len(STATE_MEANS.get(stage, "")) > 40


def test_an_unknown_stage_raises_rather_than_defaulting():
    with pytest.raises(UntranslatableStage) as raised:
        translate_stage("a_rung_nobody_has_taught_this_registry")
    said = str(raised.value)
    assert "a_rung_nobody_has_taught_this_registry" in said
    # It has to say what to do, and that the default is the trap.
    assert "not_attempted" in said and "default" in said


def test_the_default_it_refuses_is_the_one_that_would_be_wrong():
    """The state an unknown rung used to become, named here so the reason this
    test exists survives the code it guards.

    The shared vocabulary no longer HAS that default -- an unmapped rung raises
    rather than becoming anything. This test was written while it still did,
    and what it was protecting is worth keeping: the default was
    ``not_attempted``, which is INTERNAL and says the run never happened, so an
    unmapped rung was reported as this project's own unfinished work twice
    over. Both halves are asserted: that the old answer would have been wrong,
    and that it is no longer given.
    """
    import pytest as _pytest

    from umat_oti.abaqus.terminal_states import (UntranslatedStage, from_stage,
                                                 kind_of as shared)
    assert shared("not_attempted") == "internal"
    with _pytest.raises(UntranslatedStage):
        from_stage("a_rung_nobody_has_taught_this_registry")


def test_every_rung_the_verification_tool_can_settle_at_is_translatable():
    """The completeness check, taken from the tool rather than from a list
    somebody maintained by hand: whatever the ladder can emit, the registry
    must have a corpus verdict for."""
    import verify_store_in_abaqus as batch
    rungs = set(batch.STAGES) | {batch.WAITS_FOR_INPUT, batch.HARNESS_ERROR,
                                 batch.NOT_A_UMAT, batch.NO_EXPERIMENT}
    for rung in sorted(rungs):
        verdict = translate_stage(rung)
        assert verdict.kind in ("verified", "external", "internal"), rung


def test_a_local_state_that_the_shared_table_adopts_must_agree_with_it():
    """The stopgap is allowed to be temporary and not allowed to be a second
    opinion. If ``terminal_states`` later files
    ``arguments_diverged_before_the_routine`` as internal, that is a real
    disagreement about whose move it is, and it must surface rather than be
    resolved by whichever table happens to be consulted first."""
    from umat_oti.abaqus.terminal_states import FROM_STAGE, kind_of as shared
    for state, owner in LOCAL_STATES.items():
        if state in FROM_STAGE:
            assert shared(FROM_STAGE[state]) == owner, (
                f"{state} is {owner} in the registry and "
                f"{shared(FROM_STAGE[state])} in terminal_states")


def test_a_batch_row_at_an_unknown_stage_stops_the_build(tmp_path):
    """Not merely the translator: the whole registry, because a build that
    carried on and wrote a file is a build whose reader has nothing to go on."""
    import json
    transform = tmp_path / "transform.json"
    transform.write_text(json.dumps({"rows": [
        {"source": "owner__a/umat.for", "outcome": "transformed",
         "key": "k1", "compiled": True}]}))
    abaqus = tmp_path / "store_verification.jsonl"
    abaqus.write_text(json.dumps({
        "source": "owner__a/umat.for", "key": "k1",
        "stage": "a_rung_nobody_has_taught_this_registry",
        "fingerprint": "ff", "reason": "whatever"}) + "\n")
    with pytest.raises(UntranslatableStage):
        build(transform, abaqus, None, store_fingerprint="ff")


def test_a_confident_published_stub_is_external_not_our_refusal():
    """The one refusal class ``from_transform_failure`` has no parameter for.

    Left to it, both published stubs came back ``transform_refused`` --
    INTERNAL, glossed "the transform could not convert it, our work" -- when
    there is no model to convert. matmodlab2's ``umat_stub.f90`` is 16 logical
    lines that assign neither STRESS nor DDSDDE and make no CALL; the
    ufc-fem-kernel adapter is 9 whose body is a PRINT.
    """
    import json
    from pathlib import Path as _P
    path = _P(__file__).resolve().parents[1] / \
        "paper_results/corpus/corpus_registry.json"
    if not path.is_file():                         # pragma: no cover - guard
        pytest.skip("the registry has not been built in this tree")
    records = json.loads(path.read_text(encoding="utf-8"))["records"]
    stubs = [r for r in records
             if r["refusal_class"] == "published_stub_no_constitutive_content"
             and r["refusal_class_confident"]]
    assert stubs, "no source is classified as a published stub"
    for record in stubs:
        assert record["terminal_state"] == \
            "published_stub_no_constitutive_content", record["source_id"]
        assert record["kind"] == "external", record["source_id"]
        # And it may not be counted as a UMAT that could have been driven.
        assert record["adequately_specified"] is False, record["source_id"]
        assert record["adequacy_kind"] == "external", record["source_id"]


def test_an_unsettled_published_stub_keeps_the_safer_verdict():
    """A classification that is not confident leaves the verdict where it was,
    which keeps the error in the direction that overstates this project's own
    unfinished work rather than the corpus's incompleteness."""
    import json
    from pathlib import Path as _P
    path = _P(__file__).resolve().parents[1] / \
        "paper_results/corpus/corpus_registry.json"
    if not path.is_file():                         # pragma: no cover - guard
        pytest.skip("the registry has not been built in this tree")
    records = json.loads(path.read_text(encoding="utf-8"))["records"]
    unsure = [r for r in records
              if r["refusal_class"] == "published_stub_no_constitutive_content"
              and not r["refusal_class_confident"]]
    for record in unsure:
        assert record["kind"] == "internal", record["source_id"]
