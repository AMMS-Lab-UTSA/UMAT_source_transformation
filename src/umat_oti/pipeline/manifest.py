"""The run manifest: a machine-readable record of what every stage did.

One JSON file per run, rewritten after each stage so a crash leaves the work
already done still described. It is the resume point, the provenance record and
the audit trail, and it is the only place a downstream reader has to look to
learn what happened.

Provenance is captured once per run -- interpreter, platform, compiler, git
commit, dirty flag -- because an evidence row without a toolchain is not
reproducible. Every artifact carries its SHA256, so a later reader can tell
whether the file on disk is the file the manifest describes.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from umat_oti.pipeline.status import StageStatus

SCHEMA = "umat-oti-run-manifest/1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_data(data: Any) -> str:
    """Stable hash of a JSON-serialisable value, for cache keys."""
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Artifact:
    """One file a stage produced, identified by content."""

    path: str
    role: str
    sha256: str
    bytes: int

    @classmethod
    def of(cls, path: Path, role: str, *, root: Path | None = None) -> "Artifact":
        path = Path(path)
        shown = str(path.relative_to(root)) if root and path.is_relative_to(root) else str(path)
        return cls(path=shown, role=role, sha256=sha256_file(path),
                   bytes=path.stat().st_size)


@dataclass
class StageRecord:
    """What one stage did, and why it did not do more."""

    stage: str
    status: StageStatus
    reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    cache_key: str | None = None
    reused_from_cache: bool = False
    #: Which earlier run a reused result came from, so a cached row is traceable
    #: to the execution that actually produced it rather than appearing to have
    #: run now.
    reused_from_run_id: str | None = None
    reused_from_recorded_at: str | None = None
    #: Stage identity: bump the version to invalidate every cached result.
    stage_version: str | None = None
    implementation: str | None = None
    #: Digest of the resolved cache inputs (source, dependency, contract,
    #: compiler and environment hashes) that produced ``cache_key``.
    input_digest: dict[str, Any] | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = StageStatus(self.status)
        if self.status.requires_reason and not self.reason:
            raise ValueError(
                f"stage {self.stage!r} reported {self.status.value!r} without a reason. "
                f"Every outcome other than 'succeeded' must say why, so that "
                f"'not requested' is never read as 'failed' and neither is read as a pass."
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["artifacts"] = [asdict(a) for a in self.artifacts]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageRecord":
        payload = dict(data)
        payload["artifacts"] = [Artifact(**a) for a in payload.get("artifacts", [])]
        payload["status"] = StageStatus(payload["status"])
        return cls(**payload)


def capture_provenance(repo_root: Path) -> dict[str, Any]:
    """Toolchain and repository identity for this run."""
    def run(cmd: list[str]) -> str | None:
        try:
            out = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                                 text=True, timeout=30)
            return out.stdout.strip() or None
        except Exception:
            return None

    gfortran = run(["gfortran", "--version"])
    return {
        "captured_at": _utcnow(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git_commit": run(["git", "rev-parse", "HEAD"]),
        "git_branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "git_dirty": bool(run(["git", "status", "--porcelain"])),
        "gfortran": gfortran.splitlines()[0] if gfortran else None,
        # Recorded as null-with-reason rather than omitted: a reader must be able
        # to tell "no Abaqus here" from "nobody looked".
        "abaqus": run(["bash", "-lc", "command -v abaqus"]) or None,
    }


@dataclass
class RunManifest:
    """Everything one pipeline run did, resumable from disk."""

    run_id: str
    contract_hash: str
    repo_root: str
    provenance: dict[str, Any]
    stages: dict[str, StageRecord] = field(default_factory=dict)
    schema: str = SCHEMA
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    @classmethod
    def create(cls, *, run_id: str, contract: Any, repo_root: Path) -> "RunManifest":
        return cls(
            run_id=run_id,
            contract_hash=sha256_data(contract),
            repo_root=str(repo_root),
            provenance=capture_provenance(repo_root),
        )

    def record(self, result: StageRecord) -> None:
        self.stages[result.stage] = result
        self.updated_at = _utcnow()

    @staticmethod
    def archive_previous(manifest_path: Path) -> Path | None:
        """Move an existing manifest into history rather than overwriting it.

        Replacing the only record of an earlier run destroys the evidence that a
        result was ever produced differently.
        """
        manifest_path = Path(manifest_path)
        if not manifest_path.exists():
            return None
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        stamp = str(previous.get("updated_at") or "unknown").replace(":", "").replace("-", "")
        run = str(previous.get("run_id") or "run")
        history = manifest_path.parent / "history"
        history.mkdir(parents=True, exist_ok=True)
        target = history / f"run_manifest_{run}_{stamp}.json"
        if not target.exists():
            target.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
        return target

    def status_of(self, stage: str) -> StageStatus | None:
        record = self.stages.get(stage)
        return record.status if record else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "contract_hash": self.contract_hash,
            "repo_root": self.repo_root,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provenance": self.provenance,
            "stages": {name: rec.to_dict() for name, rec in self.stages.items()},
            "summary": self.summary(),
        }

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for record in self.stages.values():
            counts[record.status.value] = counts.get(record.status.value, 0) + 1
        problems = [
            {"stage": r.stage, "status": r.status.value, "reason": r.reason}
            for r in self.stages.values() if r.status.is_problem
        ]
        return {
            "stages_recorded": len(self.stages),
            "status_counts": counts,
            "problems": problems,
            # Deliberately not a boolean "ok": a run with everything
            # not_requested is not a success, it is an empty run.
            "stages_succeeded": counts.get(StageStatus.SUCCEEDED.value, 0),
        }

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError(f"unexpected manifest schema {data.get('schema')!r}")
        manifest = cls(
            run_id=data["run_id"], contract_hash=data["contract_hash"],
            repo_root=data["repo_root"], provenance=data["provenance"],
            created_at=data["created_at"], updated_at=data["updated_at"],
        )
        for name, record in data.get("stages", {}).items():
            manifest.stages[name] = StageRecord.from_dict(record)
        return manifest
