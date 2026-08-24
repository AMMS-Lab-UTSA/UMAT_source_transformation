"""The stage engine: one resumable, cacheable runner for the whole pipeline.

A stage declares its name, the stages it consumes, and a version. The engine
orders them by dependency, decides for each whether it can run at all, runs it,
hashes its artifacts, and rewrites the run manifest -- after every stage, so an
interrupted run still describes the work it completed.

**Resume and cache.** A stage's cache key is derived from its version, the
contract hash, its declared inputs and the cache keys of everything upstream.
If a previous manifest holds a succeeded record with the same key *and* every
artifact it named still hashes to the recorded value, the stage is reused
instead of rerun. Changing a contract, a source file or an upstream stage
changes the key and forces recomputation; nothing is reused on the strength of
its name alone.

**Propagation.** A stage whose dependency did not succeed does not run, and does
not report ``failed`` either -- reporting failure for something that was never
attempted would be a lie. It inherits the shape of the upstream outcome:
``not_requested`` upstream yields ``not_requested`` here, an external block
stays an external block. That way the manifest's problem list contains root
causes, not their shadows.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

from umat_oti.pipeline.manifest import (
    Artifact, RunManifest, StageRecord, sha256_data, sha256_file,
)
from umat_oti.pipeline.status import MissingData, StageStatus


@dataclass
class RunContext:
    """Everything a stage may read, and where it may write."""

    contract: dict[str, Any]
    work_dir: Path
    repo_root: Path
    manifest: RunManifest
    #: Outputs of upstream stages, keyed by stage name.
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def output_of(self, stage: str) -> dict[str, Any]:
        """Outputs of an upstream stage, or raise -- never a silent empty dict."""
        if stage not in self.results:
            raise MissingData(
                f"stage {stage!r} produced no outputs, so anything derived from it "
                f"cannot be computed. This is not an empty result; it is an absent one."
            )
        return self.results[stage]

    def stage_dir(self, stage: str) -> Path:
        path = self.work_dir / stage
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass
class StageOutcome:
    """What a stage hands back to the engine."""

    status: StageStatus
    reason: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls, **outputs: Any) -> "StageOutcome":
        return cls(status=StageStatus.SUCCEEDED, outputs=outputs)

    @classmethod
    def not_requested(cls, reason: str) -> "StageOutcome":
        return cls(status=StageStatus.NOT_REQUESTED, reason=reason)

    @classmethod
    def unsupported(cls, reason: str) -> "StageOutcome":
        return cls(status=StageStatus.UNSUPPORTED, reason=reason)

    @classmethod
    def blocked(cls, reason: str) -> "StageOutcome":
        return cls(status=StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY, reason=reason)

    @classmethod
    def failed(cls, reason: str) -> "StageOutcome":
        return cls(status=StageStatus.FAILED, reason=reason)


class Stage(Protocol):
    """A unit of pipeline work."""

    name: str
    requires: tuple[str, ...]
    version: str

    def cache_inputs(self, ctx: RunContext) -> Any: ...
    def run(self, ctx: RunContext) -> StageOutcome: ...


@dataclass
class FunctionStage:
    """A stage backed by a plain function, which is most of them."""

    name: str
    run_fn: Callable[[RunContext], StageOutcome]
    requires: tuple[str, ...] = ()
    version: str = "1"
    #: Extra values folded into the cache key beyond contract and upstream keys.
    cache_inputs_fn: Callable[[RunContext], Any] | None = None

    def cache_inputs(self, ctx: RunContext) -> Any:
        return self.cache_inputs_fn(ctx) if self.cache_inputs_fn else None

    def run(self, ctx: RunContext) -> StageOutcome:
        return self.run_fn(ctx)


def order_stages(stages: Sequence[Stage]) -> list[Stage]:
    """Dependency order, rejecting cycles and dangling requirements."""
    by_name = {stage.name: stage for stage in stages}
    for stage in stages:
        for need in stage.requires:
            if need not in by_name:
                raise ValueError(
                    f"stage {stage.name!r} requires {need!r}, which is not registered"
                )
    ordered: list[Stage] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        if name in visiting:
            raise ValueError(f"dependency cycle involving stage {name!r}")
        visiting.add(name)
        for need in by_name[name].requires:
            visit(need)
        visiting.discard(name)
        seen.add(name)
        ordered.append(by_name[name])

    for stage in stages:
        visit(stage.name)
    return ordered


class PipelineEngine:
    """Runs a stage graph and keeps the run manifest truthful."""

    def __init__(self, stages: Sequence[Stage], *, repo_root: Path) -> None:
        self.stages = order_stages(stages)
        self.repo_root = Path(repo_root)

    def _cache_key(self, stage: Stage, ctx: RunContext,
                   upstream: dict[str, str]) -> str:
        return sha256_data({
            "stage": stage.name,
            "version": stage.version,
            "contract": ctx.manifest.contract_hash,
            "inputs": stage.cache_inputs(ctx),
            "upstream": {name: upstream.get(name) for name in stage.requires},
        })

    def _reusable(self, previous: RunManifest | None, stage: Stage,
                  cache_key: str, ctx: RunContext) -> StageRecord | None:
        if previous is None:
            return None
        record = previous.stages.get(stage.name)
        if record is None or record.status is not StageStatus.SUCCEEDED:
            return None
        if record.cache_key != cache_key:
            return None
        for artifact in record.artifacts:
            path = Path(artifact.path)
            if not path.is_absolute():
                path = ctx.work_dir / artifact.path
            # An artifact that vanished or changed invalidates the cache. Reusing
            # a record whose files no longer match it would publish a hash that
            # describes nothing on disk.
            if not path.exists() or sha256_file(path) != artifact.sha256:
                return None
        return record

    def run(self, *, contract: dict[str, Any], work_dir: Path,
            run_id: str = "run", resume: bool = True,
            options: dict[str, Any] | None = None,
            only: Iterable[str] | None = None) -> RunManifest:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = work_dir / "run_manifest.json"

        previous: RunManifest | None = None
        if resume and manifest_path.exists():
            try:
                candidate = RunManifest.load(manifest_path)
                # Only resume a manifest describing the same contract.
                if candidate.contract_hash == sha256_data(contract):
                    previous = candidate
            except Exception:
                previous = None

        manifest = RunManifest.create(run_id=run_id, contract=contract,
                                      repo_root=self.repo_root)
        ctx = RunContext(contract=contract, work_dir=work_dir,
                         repo_root=self.repo_root, manifest=manifest,
                         options=dict(options or {}))

        selected = set(only) if only else None
        upstream_keys: dict[str, str] = {}

        for stage in self.stages:
            if selected is not None and stage.name not in selected:
                manifest.record(StageRecord(
                    stage=stage.name, status=StageStatus.NOT_REQUESTED,
                    reason="not included in the requested stage subset"))
                manifest.write(manifest_path)
                continue

            blocked_by = self._upstream_block(stage, manifest)
            if blocked_by is not None:
                manifest.record(blocked_by)
                manifest.write(manifest_path)
                continue

            cache_key = self._cache_key(stage, ctx, upstream_keys)
            upstream_keys[stage.name] = cache_key

            reused = self._reusable(previous, stage, cache_key, ctx)
            if reused is not None:
                record = StageRecord(
                    stage=stage.name, status=StageStatus.SUCCEEDED,
                    reason=None, cache_key=cache_key, reused_from_cache=True,
                    outputs=reused.outputs, artifacts=list(reused.artifacts),
                    diagnostics=list(reused.diagnostics),
                    started_at=reused.started_at, finished_at=reused.finished_at,
                    duration_seconds=reused.duration_seconds,
                )
                ctx.results[stage.name] = dict(reused.outputs)
                manifest.record(record)
                manifest.write(manifest_path)
                continue

            started = time.time()
            started_at = manifest.updated_at
            try:
                outcome = stage.run(ctx)
            except MissingData as exc:
                outcome = StageOutcome.failed(f"required data was absent: {exc}")
            except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
                outcome = StageOutcome.failed(
                    f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}")
            elapsed = time.time() - started

            record = StageRecord(
                stage=stage.name, status=outcome.status, reason=outcome.reason,
                started_at=started_at, duration_seconds=round(elapsed, 6),
                cache_key=cache_key, outputs=outcome.outputs,
                artifacts=list(outcome.artifacts), diagnostics=list(outcome.diagnostics),
            )
            if outcome.status is StageStatus.SUCCEEDED:
                ctx.results[stage.name] = dict(outcome.outputs)
            manifest.record(record)
            manifest.write(manifest_path)

        manifest.write(manifest_path)
        return manifest

    @staticmethod
    def _upstream_block(stage: Stage, manifest: RunManifest) -> StageRecord | None:
        """Propagate an upstream non-success without inventing a new failure."""
        for need in stage.requires:
            status = manifest.status_of(need)
            if status is None:
                return StageRecord(
                    stage=stage.name, status=StageStatus.NOT_REQUESTED,
                    reason=f"upstream stage {need!r} did not run")
            if status is not StageStatus.SUCCEEDED:
                inherited = (
                    StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY
                    if status is StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY
                    else StageStatus.NOT_REQUESTED
                    if status is StageStatus.NOT_REQUESTED
                    else StageStatus.UNSUPPORTED
                    if status is StageStatus.UNSUPPORTED
                    else StageStatus.NOT_REQUESTED
                )
                return StageRecord(
                    stage=stage.name, status=inherited,
                    reason=(f"upstream stage {need!r} reported {status.value!r}; this "
                            f"stage was not attempted, so it is not itself a failure"))
        return None
