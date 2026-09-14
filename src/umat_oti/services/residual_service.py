"""ResidualAssemblyService: hand a verified fixture to the Residual Assembler.

The rules for what may be frozen live in ``tools/export_residual_fixture.py``
and this service **delegates to them**. It does not carry its own copy of
``REQUIRED_GATES`` and it does not decide for itself whether a history is
finite: two copies of a freezing rule is how the two copies come to disagree,
and the one in the tool is the one the Makefile and the promotion tool already
use.

What this service adds is an answer to "may this one be handed over, and if not,
what exactly is wrong with it" that a screen can render without importing a
4000-line batch tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT, ToolUnavailable, load_tool
from .gates import NOT_ESTABLISHED, TRUE, read_gate, read_gates
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.records import utc_now

__all__ = ["HandoffResult", "ResidualAssemblyService"]

SERVICE = "residual_assembly"


@dataclass
class HandoffResult:
    source_id: str = ""
    eligible: Optional[bool] = None
    refused_because: list[str] = field(default_factory=list)
    required_gates: list[str] = field(default_factory=list)
    gate_readings: list[dict] = field(default_factory=list)
    fixture_path: str = ""
    schema: str = ""
    increments_carried: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id, "eligible": self.eligible,
            "refused_because": list(self.refused_because),
            "required_gates": list(self.required_gates),
            "gate_readings": list(self.gate_readings),
            "fixture_path": self.fixture_path, "schema": self.schema,
            "increments_carried": self.increments_carried,
        }


class ResidualAssemblyService:
    """Decide whether a case may be frozen, and freeze it."""

    def __init__(self, *, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def _tool(self, result: ServiceResult):
        try:
            return load_tool("export_residual_fixture")
        except ToolUnavailable as error:
            result.add("fixture_rules_unavailable", str(error),
                       where="tools/export_residual_fixture.py")
            result.outcome = "refused"
            return None

    def eligible(self, record: dict) -> ServiceResult:
        """Whether this case may be handed over, by the tool's own rules."""
        result = ServiceResult(
            service=SERVICE, outcome="eligible",
            provenance=self._provenance(key=record.get("key")))
        tool = self._tool(result)
        if tool is None:
            return result

        required = list(getattr(tool, "REQUIRED_GATES", ()))
        readings = [read_gate(record.get("evidence"), gate) for gate in required]
        refused = [
            f"{r.gate} reads {r.reading}: {r.why}"
            for r in readings if r.reading != TRUE]

        handoff = HandoffResult(
            source_id=str(record.get("source") or ""),
            eligible=not refused,
            refused_because=refused,
            required_gates=required,
            gate_readings=[r.as_dict() for r in readings],
            schema=str(getattr(tool, "SCHEMA", "")))
        result.data = handoff
        if refused:
            result.outcome = "refused"
            for line in refused:
                result.add("required_gate_not_true", line,
                           where=handoff.source_id, severity="warning")
        return result

    def handoff(self, record: dict, work_dir: Path, out_dir: Path, *,
                increments: Optional[int] = None) -> ServiceResult:
        """Freeze one verified case as a fixture, or refuse with the reasons."""
        result = ServiceResult(
            service=SERVICE, outcome="frozen",
            provenance=self._provenance(key=record.get("key"),
                                        work_dir=str(work_dir),
                                        out_dir=str(out_dir)))
        tool = self._tool(result)
        if tool is None:
            return result

        handoff = HandoffResult(
            source_id=str(record.get("source") or ""),
            required_gates=list(getattr(tool, "REQUIRED_GATES", ())),
            schema=str(getattr(tool, "SCHEMA", "")))
        try:
            fixture = tool.freeze(
                record, Path(work_dir),
                **({"increments": increments} if increments else {}))
        except Exception as error:  # noqa: BLE001 - FixtureRefused and anything else
            handoff.eligible = False
            handoff.refused_because = [str(error)]
            result.data = handoff
            result.outcome = "refused"
            result.add("fixture_refused", str(error),
                       where=handoff.source_id)
            return result

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        import hashlib
        import json as _json
        stem = Path(handoff.source_id).stem.lower() or "fixture"
        digest = hashlib.sha256(handoff.source_id.encode()).hexdigest()[:10]
        path = out_dir / f"{stem}--{digest}.json"
        path.write_text(_json.dumps(fixture, indent=1) + "\n", encoding="utf-8")

        handoff.eligible = True
        handoff.fixture_path = str(path)
        handoff.increments_carried = (fixture.get("finite_history") or {}).get(
            "increments_carried")
        result.data = handoff
        result.evidence_paths["fixture"] = str(path)
        return result
