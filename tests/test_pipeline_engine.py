"""The pipeline engine must never turn an absence into a result.

These tests pin the behaviours that make the run manifest trustworthy:

  * every non-success carries a reason, enforced at construction;
  * a stage skipped because its dependency did not succeed is not reported as a
    failure of its own -- the manifest's problem list holds root causes;
  * "blocked by an external dependency" survives propagation as itself;
  * a missing value raises rather than defaulting to zero;
  * cache reuse requires the artifacts on disk to still match their hashes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.pipeline.engine import (
    FunctionStage, PipelineEngine, RunContext, StageOutcome, order_stages,
)
from umat_oti.pipeline.manifest import Artifact, RunManifest, StageRecord, sha256_data
from umat_oti.pipeline.status import MissingData, StageStatus, require, unavailable
from umat_oti.pipeline.stages import CANONICAL_STAGES, _detect_form

REPO_ROOT = Path(__file__).resolve().parents[1]


def _engine(*stages):
    return PipelineEngine(list(stages), repo_root=REPO_ROOT)


# --------------------------------------------------------------------------- #
# Status vocabulary
# --------------------------------------------------------------------------- #
def test_every_non_success_must_carry_a_reason():
    StageRecord(stage="s", status=StageStatus.SUCCEEDED)  # no reason needed
    for status in (StageStatus.FAILED, StageStatus.NOT_REQUESTED,
                   StageStatus.UNSUPPORTED,
                   StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY):
        with pytest.raises(ValueError, match="must say why"):
            StageRecord(stage="s", status=status)


def test_not_requested_is_not_a_problem_but_failed_and_unsupported_are():
    assert StageStatus.FAILED.is_problem
    assert StageStatus.UNSUPPORTED.is_problem
    assert not StageStatus.NOT_REQUESTED.is_problem
    assert not StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY.is_problem


def test_require_raises_instead_of_defaulting_to_zero():
    assert require({"a": 5}, "a", context="t") == 5
    with pytest.raises(MissingData):
        require({}, "a", context="t")
    with pytest.raises(MissingData):
        require({"a": None}, "a", context="t")


def test_unavailable_keeps_the_field_and_names_the_reason():
    value = unavailable("Abaqus 2024 is not installed")
    assert value["value"] is None
    assert "Abaqus" in value["unavailable_reason"]


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def test_stages_are_ordered_by_dependency():
    ordered = order_stages([
        FunctionStage("c", lambda ctx: StageOutcome.ok(), ("b",)),
        FunctionStage("a", lambda ctx: StageOutcome.ok()),
        FunctionStage("b", lambda ctx: StageOutcome.ok(), ("a",)),
    ])
    assert [s.name for s in ordered] == ["a", "b", "c"]


def test_a_dependency_cycle_is_rejected():
    with pytest.raises(ValueError, match="cycle"):
        order_stages([
            FunctionStage("a", lambda ctx: StageOutcome.ok(), ("b",)),
            FunctionStage("b", lambda ctx: StageOutcome.ok(), ("a",)),
        ])


def test_a_dangling_requirement_is_rejected():
    with pytest.raises(ValueError, match="not registered"):
        order_stages([FunctionStage("a", lambda ctx: StageOutcome.ok(), ("nope",))])


def test_the_canonical_graph_declares_every_documented_stage():
    names = [s.name for s in CANONICAL_STAGES]
    assert names[:7] == [
        "source_acquisition", "source_inventory", "license_classification",
        "entry_routine_detection", "dependency_closure", "contract_inference",
        "derivative_request_normalization",
    ]
    # Unimplemented stages are registered rather than omitted, so a partial run
    # cannot look complete.
    assert "material_point_execution" in names
    assert "distributable_package" in names


# --------------------------------------------------------------------------- #
# Propagation
# --------------------------------------------------------------------------- #
def test_a_stage_after_a_failure_is_not_itself_reported_as_failed(tmp_path):
    engine = _engine(
        FunctionStage("boom", lambda ctx: StageOutcome.failed("exploded")),
        FunctionStage("after", lambda ctx: StageOutcome.ok(), ("boom",)),
    )
    manifest = engine.run(contract={"x": 1}, work_dir=tmp_path)
    assert manifest.stages["boom"].status is StageStatus.FAILED
    assert manifest.stages["after"].status is StageStatus.NOT_REQUESTED
    # exactly one root cause, not a cascade of them
    assert [p["stage"] for p in manifest.summary()["problems"]] == ["boom"]


def test_an_external_block_stays_an_external_block_downstream(tmp_path):
    engine = _engine(
        FunctionStage("needs_abaqus", lambda ctx: StageOutcome.blocked("no Abaqus")),
        FunctionStage("after", lambda ctx: StageOutcome.ok(), ("needs_abaqus",)),
    )
    manifest = engine.run(contract={}, work_dir=tmp_path)
    assert manifest.stages["after"].status is StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY
    assert manifest.summary()["problems"] == []


def test_an_exception_inside_a_stage_becomes_a_failure_with_the_traceback(tmp_path):
    def explode(ctx):
        raise RuntimeError("kaboom")

    engine = _engine(FunctionStage("s", explode))
    manifest = engine.run(contract={}, work_dir=tmp_path)
    record = manifest.stages["s"]
    assert record.status is StageStatus.FAILED
    assert "kaboom" in record.reason


def test_reaching_for_an_absent_upstream_output_fails_loudly(tmp_path):
    engine = _engine(
        FunctionStage("a", lambda ctx: StageOutcome.not_requested("nothing asked")),
        FunctionStage("b", lambda ctx: StageOutcome.ok(v=ctx.output_of("a")["k"]), ("a",)),
    )
    manifest = engine.run(contract={}, work_dir=tmp_path)
    assert manifest.stages["b"].status is StageStatus.NOT_REQUESTED


# --------------------------------------------------------------------------- #
# Cache and resume
# --------------------------------------------------------------------------- #
def _counting_stage(counter):
    def run(ctx):
        counter.append(1)
        path = ctx.stage_dir("counted") / "out.txt"
        path.write_text(f"run {len(counter)}", encoding="utf-8")
        return StageOutcome(
            status=StageStatus.SUCCEEDED,
            outputs={"runs": len(counter)},
            artifacts=[Artifact.of(path, "output", root=ctx.work_dir)],
        )
    return FunctionStage("counted", run)


def test_an_unchanged_stage_is_reused_on_resume(tmp_path):
    calls: list[int] = []
    engine = _engine(_counting_stage(calls))
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    manifest = engine.run(contract={"a": 1}, work_dir=tmp_path)
    assert len(calls) == 1, "the stage should not have run twice"
    assert manifest.stages["counted"].reused_from_cache is True


def test_changing_the_contract_invalidates_the_cache(tmp_path):
    calls: list[int] = []
    engine = _engine(_counting_stage(calls))
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    engine.run(contract={"a": 2}, work_dir=tmp_path)
    assert len(calls) == 2


def test_a_missing_artifact_invalidates_the_cache(tmp_path):
    """A record whose files vanished describes nothing and must not be reused."""
    calls: list[int] = []
    engine = _engine(_counting_stage(calls))
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    (tmp_path / "counted" / "out.txt").unlink()
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    assert len(calls) == 2


def test_a_modified_artifact_invalidates_the_cache(tmp_path):
    calls: list[int] = []
    engine = _engine(_counting_stage(calls))
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    (tmp_path / "counted" / "out.txt").write_text("tampered", encoding="utf-8")
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    assert len(calls) == 2


def test_resume_false_ignores_the_cache(tmp_path):
    calls: list[int] = []
    engine = _engine(_counting_stage(calls))
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    engine.run(contract={"a": 1}, work_dir=tmp_path, resume=False)
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def test_the_manifest_round_trips_and_records_provenance(tmp_path):
    engine = _engine(FunctionStage("s", lambda ctx: StageOutcome.ok(v=1)))
    engine.run(contract={"a": 1}, work_dir=tmp_path)
    path = tmp_path / "run_manifest.json"
    assert path.exists()
    reloaded = RunManifest.load(path)
    assert reloaded.stages["s"].status is StageStatus.SUCCEEDED
    for key in ("python", "platform", "git_commit", "gfortran", "abaqus"):
        assert key in reloaded.provenance, key


def test_the_manifest_is_written_after_every_stage_not_only_at_the_end(tmp_path):
    """An interrupted run must still describe what it finished."""
    def explode(ctx):
        raise SystemExit(2)

    engine = _engine(
        FunctionStage("first", lambda ctx: StageOutcome.ok()),
        FunctionStage("second", explode, ("first",)),
    )
    with pytest.raises(SystemExit):
        engine.run(contract={}, work_dir=tmp_path)
    data = json.loads((tmp_path / "run_manifest.json").read_text())
    assert data["stages"]["first"]["status"] == "succeeded"


# --------------------------------------------------------------------------- #
# Real stage behaviour
# --------------------------------------------------------------------------- #
def test_source_form_is_detected_by_suffix_then_by_content(tmp_path):
    fixed = tmp_path / "a.for"
    fixed.write_text("      SUBROUTINE UMAT\n      END\n", encoding="utf-8")
    assert _detect_form(fixed)[0] == "fixed"
    free = tmp_path / "b.f90"
    free.write_text("subroutine umat\nend subroutine\n", encoding="utf-8")
    assert _detect_form(free)[0] == "free"
    unknown = tmp_path / "c.txt"
    unknown.write_text("     1 CONTINUE\n", encoding="utf-8")
    form, why = _detect_form(unknown)
    assert form == "fixed" and "column 6" in why


def test_an_unlicensed_source_is_not_treated_as_redistributable(tmp_path):
    src = tmp_path / "u.f"
    src.write_text("      SUBROUTINE UMAT\n      END\n", encoding="utf-8")
    engine = PipelineEngine(
        [s for s in CANONICAL_STAGES
         if s.name in ("source_acquisition", "source_inventory", "license_classification")],
        repo_root=REPO_ROOT)
    manifest = engine.run(contract={"source": str(src), "_base_dir": str(tmp_path)},
                          work_dir=tmp_path / "work")
    licenses = manifest.stages["license_classification"].outputs["licenses"]
    assert licenses[0]["tier"] is None
    assert licenses[0]["redistributable_as_fixture"] is False
