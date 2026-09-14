"""What the interface shows is plain language; what it is mapped from stays.

An engineer reading the screen wants "Comparing mechanical histories", not
``primal_disagreed``. But the evidence files, the store records and the papers
are keyed on the internal rung, so a label that cannot be traced back to the
rung it came from is a label nobody can audit. Both are carried.

And an internal rung nobody mapped must RAISE rather than defaulting. The
default is what did the damage: ``FROM_STAGE.get(stage, "not_attempted")``
reported three runs that happened as runs that never did.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from umat_oti.jobs.stages import (  # noqa: E402
    STAGE_KEYS, STAGE_LABELS, STAGES, UntranslatedStage, label_for_internal,
    require_stage_for_internal, stage_for_internal, unmapped_internal_names,
)

pytestmark = pytest.mark.unit

#: The Abaqus batch ladder, from tools/verify_store_in_abaqus.py, plus the
#: off-ladder terminal states that also appear as `stage` in the store records.
ABAQUS_LADDER = (
    "needs_material_data", "waits_for_input", "manifest_refused",
    "both_builds_non_finite", "support_build_failed", "original_job_failed",
    "transformed_job_failed", "primal_disagreed",
    "arguments_diverged_before_the_routine",
    "disagreement_not_in_any_recorded_call", "derivative_truncated",
    "tangent_not_verified", "verified", "not_a_umat",
    "incomplete_or_corrupt_source", "experiment_not_generated",
    "experiment_not_informative", "informativeness_not_established",
)


def test_the_nine_stages_are_the_owner_s_words_in_order():
    assert len(STAGES) == 9
    assert list(STAGE_LABELS) == [
        "Analyzing the UMAT",
        "Finding material data",
        "Building a mechanical experiment",
        "Searching for yielding, damage or time dependence",
        "Running the original routine",
        "Running the transformed routine",
        "Comparing mechanical histories",
        "Verifying derivatives",
        "Creating the regression test",
    ]
    assert len(set(STAGE_KEYS)) == 9


def test_no_internal_rung_is_claimed_by_two_stages():
    seen: dict[str, str] = {}
    for stage in STAGES:
        for name in stage.internal_names:
            assert name not in seen, (name, seen.get(name), stage.key)
            seen[name] = stage.key


def test_the_corpus_funnel_ladder_maps_with_nothing_left_over():
    from umat_oti.corpus.funnel import STAGES as FUNNEL  # noqa: PLC0415

    assert unmapped_internal_names(FUNNEL) == []


def test_the_corpus_store_ladder_maps_with_nothing_left_over():
    from umat_oti.corpus import _STAGE_ORDER  # noqa: PLC0415

    assert unmapped_internal_names(_STAGE_ORDER) == []


def test_the_abaqus_batch_ladder_maps_with_nothing_left_over():
    assert unmapped_internal_names(ABAQUS_LADDER) == []


def test_the_internal_rung_is_kept_beside_the_label():
    mapping = label_for_internal("primal_disagreed")
    assert mapping["label"] == "Comparing mechanical histories"
    assert mapping["internal"] == "primal_disagreed"
    assert mapping["mapped"] is True
    assert mapping["means"], "the stage says what it establishes"


def test_an_unmapped_rung_raises_rather_than_becoming_a_neighbour():
    """The default is the bug. There is no default."""
    with pytest.raises(UntranslatedStage) as raised:
        require_stage_for_internal("a_rung_nobody_declared")
    assert "a_rung_nobody_declared" in str(raised.value)
    assert "do not let it fall through" in str(raised.value)


def test_the_asking_variant_answers_none_and_says_so():
    """`stage_for_internal` is for callers whose question is 'is this mapped?'."""
    assert stage_for_internal("a_rung_nobody_declared") is None
    mapping = label_for_internal("a_rung_nobody_declared")
    assert mapping["mapped"] is False
    assert mapping["label"] is None
    assert "guessed into a neighbouring stage" in mapping["note"]


def test_the_reporter_refuses_a_rung_it_cannot_translate(tmp_path):
    """A running job cannot file progress under a stage nobody mapped."""
    from umat_oti.jobs import StageReporter  # noqa: PLC0415

    reporter = StageReporter(tmp_path)
    with pytest.raises(UntranslatedStage):
        reporter.succeeded("a_rung_nobody_declared", "some detail")
    assert not (tmp_path / "stages.jsonl").exists(), (
        "nothing may be written for a stage that could not be translated")


def test_every_stage_of_the_real_pass11_file_translates():
    """The vocabulary is checked against the stages that actually occur."""
    import json  # noqa: PLC0415

    import os  # noqa: PLC0415

    path = Path(os.environ.get(
        "UMAT_OTI_CORPUS_RUN",
        str(Path(__file__).resolve().parents[1].parent / "corpus_run"
            / "pass11" / "results" / "store_verification.jsonl")))
    if not path.is_file():
        pytest.skip(f"{path} is not on this machine")
    stages = {json.loads(line).get("stage")
              for line in path.read_text(encoding="utf-8").splitlines()
              if line.strip()}
    assert stages, "no stages found; the test is stale"
    assert unmapped_internal_names(sorted(stages)) == []
    for stage in sorted(stages):
        assert require_stage_for_internal(stage).label in STAGE_LABELS
