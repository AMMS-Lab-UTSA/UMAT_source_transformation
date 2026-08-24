"""Cache invalidation must follow content, not paths.

Keying source acquisition on paths alone was a correctness bug: editing a
Fortran source without touching the contract left every downstream stage
reusing artifacts built from the previous text. These tests exist so that
"source changes invalidate the cache" is a measured fact rather than a claim.

Each test counts how many times a stage body actually executed, which is the
only thing that distinguishes a reuse from a rerun.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.pipeline.engine import FunctionStage, PipelineEngine, StageOutcome
from umat_oti.pipeline.stages import (
    CANONICAL_STAGES, _acquisition_cache_inputs, _closure_cache_inputs,
    _compilation_cache_inputs, _transformation_cache_inputs,
)
from umat_oti.pipeline.engine import RunContext
from umat_oti.pipeline.manifest import RunManifest, sha256_data

REPO_ROOT = Path(__file__).resolve().parents[1]

FIXED_SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS)
      INCLUDE 'helper.inc'
      DIMENSION STRESS(NTENS)
      STRESS(1) = 1.0D0
      END
"""
HELPER_INC = "      REAL*8 SCRATCH\n"


@pytest.fixture()
def project(tmp_path):
    src = tmp_path / "model.for"
    src.write_text(FIXED_SOURCE, encoding="utf-8")
    (tmp_path / "helper.inc").write_text(HELPER_INC, encoding="utf-8")
    contract = {"source": "model.for", "_base_dir": str(tmp_path)}
    return tmp_path, src, contract


def _ctx(contract, tmp_path, options=None, results=None):
    manifest = RunManifest.create(run_id="t", contract=contract, repo_root=REPO_ROOT)
    return RunContext(contract=contract, work_dir=tmp_path / "w", repo_root=REPO_ROOT,
                      manifest=manifest, results=dict(results or {}),
                      options=dict(options or {}))


# --------------------------------------------------------------------------- #
# The cache inputs themselves
# --------------------------------------------------------------------------- #
def test_acquisition_key_contains_source_contents_not_only_paths(project):
    tmp_path, src, contract = project
    before = _acquisition_cache_inputs(_ctx(contract, tmp_path))
    assert list(before["source_hashes"].values())[0] is not None

    src.write_text(FIXED_SOURCE.replace("1.0D0", "2.0D0"), encoding="utf-8")
    after = _acquisition_cache_inputs(_ctx(contract, tmp_path))
    assert before["source_hashes"] != after["source_hashes"]
    assert before["declared"] == after["declared"], "the path did not change; the content did"


def test_acquisition_key_covers_included_files(project):
    tmp_path, _src, contract = project
    before = _acquisition_cache_inputs(_ctx(contract, tmp_path))
    assert any("helper.inc" in key for key in before["included_hashes"])
    (tmp_path / "helper.inc").write_text(HELPER_INC + "      REAL*8 EXTRA\n", encoding="utf-8")
    after = _acquisition_cache_inputs(_ctx(contract, tmp_path))
    assert before["included_hashes"] != after["included_hashes"]


def test_a_deleted_dependency_changes_the_key_rather_than_vanishing(project):
    tmp_path, _src, contract = project
    before = _acquisition_cache_inputs(_ctx(contract, tmp_path))
    (tmp_path / "helper.inc").unlink()
    after = _acquisition_cache_inputs(_ctx(contract, tmp_path))
    assert before != after
    # the entry survives as null so the deletion is visible, not silently dropped
    assert any(value is None for value in after["included_hashes"].values())


def test_compile_option_changes_the_transformation_key(project):
    tmp_path, _src, contract = project
    cold = _transformation_cache_inputs(_ctx(contract, tmp_path, {"compile": False}))
    hot = _transformation_cache_inputs(_ctx(contract, tmp_path, {"compile": True}))
    assert cold["options"]["compile_generated"] != hot["options"]["compile_generated"]
    assert sha256_data(cold) != sha256_data(hot), (
        "a non-compiled run must not satisfy a later --compile run")


def test_compiler_identity_is_in_the_compilation_key(project):
    tmp_path, _src, contract = project
    inputs = _compilation_cache_inputs(_ctx(contract, tmp_path, {"compile": True}))
    assert "compiler_version" in inputs
    other = _compilation_cache_inputs(
        _ctx(contract, tmp_path, {"compile": True, "compiler": "definitely-not-a-compiler"}))
    assert inputs != other
    # an absent compiler records None, never an empty string that looks like a version
    assert other["compiler_version"] is None


def test_transformation_key_tracks_the_contract_file_contents(project, tmp_path):
    _base, _src, contract = project
    config = _base / "c.json"
    config.write_text(json.dumps({"a": 1}), encoding="utf-8")
    before = _transformation_cache_inputs(_ctx(contract, _base, {"config_path": str(config)}))
    config.write_text(json.dumps({"a": 2}), encoding="utf-8")
    after = _transformation_cache_inputs(_ctx(contract, _base, {"config_path": str(config)}))
    assert before["contract_file"] != after["contract_file"]


# --------------------------------------------------------------------------- #
# End to end through the engine: count real reruns
# --------------------------------------------------------------------------- #
def _instrumented_engine(counter):
    """The first four canonical stages, with a probe counting executions."""
    wanted = ("source_acquisition", "source_inventory", "license_classification",
              "entry_routine_detection")
    stages = []
    for stage in CANONICAL_STAGES:
        if stage.name not in wanted:
            continue

        def make(inner):
            def run(ctx, _inner=inner):
                counter.setdefault(_inner.name, 0)
                counter[_inner.name] += 1
                return _inner.run_fn(ctx)
            return run

        stages.append(FunctionStage(stage.name, make(stage), stage.requires,
                                    stage.version, stage.cache_inputs_fn))
    return PipelineEngine(stages, repo_root=REPO_ROOT)


def test_an_unchanged_project_is_fully_reused(project):
    tmp_path, _src, contract = project
    calls: dict[str, int] = {}
    engine = _instrumented_engine(calls)
    work = tmp_path / "work"
    engine.run(contract=contract, work_dir=work)
    first = dict(calls)
    manifest = engine.run(contract=contract, work_dir=work)
    assert calls == first, "nothing changed, so nothing should have rerun"
    assert all(r.reused_from_cache for r in manifest.stages.values())


def test_editing_one_source_line_reruns_acquisition_and_everything_downstream(project):
    tmp_path, src, contract = project
    calls: dict[str, int] = {}
    engine = _instrumented_engine(calls)
    work = tmp_path / "work"
    engine.run(contract=contract, work_dir=work)

    src.write_text(FIXED_SOURCE.replace("1.0D0", "2.0D0"), encoding="utf-8")
    manifest = engine.run(contract=contract, work_dir=work)

    assert calls["source_acquisition"] == 2, "the source changed under the same path"
    for stage in ("source_inventory", "license_classification", "entry_routine_detection"):
        assert calls[stage] == 2, f"{stage} reused an artifact built from the old text"
        assert manifest.stages[stage].reused_from_cache is False


def test_editing_an_included_file_invalidates_the_run(project):
    tmp_path, _src, contract = project
    calls: dict[str, int] = {}
    engine = _instrumented_engine(calls)
    work = tmp_path / "work"
    engine.run(contract=contract, work_dir=work)
    (tmp_path / "helper.inc").write_text(HELPER_INC + "      REAL*8 EXTRA\n", encoding="utf-8")
    engine.run(contract=contract, work_dir=work)
    assert calls["source_acquisition"] == 2, (
        "an INCLUDE the contract never names is still a dependency")


def test_renaming_a_source_invalidates_the_run(project):
    tmp_path, src, contract = project
    calls: dict[str, int] = {}
    engine = _instrumented_engine(calls)
    work = tmp_path / "work"
    engine.run(contract=contract, work_dir=work)

    renamed = tmp_path / "renamed.for"
    src.rename(renamed)
    moved = dict(contract, source="renamed.for")
    engine.run(contract=moved, work_dir=work)
    assert calls["source_acquisition"] == 2
