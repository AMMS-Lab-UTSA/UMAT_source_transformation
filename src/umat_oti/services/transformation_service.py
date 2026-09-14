"""TransformationService: transform, compile, and report the diagnostics.

A thin typed face over :func:`umat_oti.services.transformation.run_transformation`,
which is already the one implementation the CLI uses (``umat-oti config`` and
``umat-oti-config`` both call it). The service exists so the GUI calls the same
function through the same result schema instead of assembling a compile command
in a callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT
from .results import Provenance, ServiceResult, repo_commit
from .transformation import TransformationOptions, run_transformation
from umat_oti.jobs.records import utc_now

__all__ = ["TransformationReport", "TransformationService"]

SERVICE = "transformation"

#: Outcomes in which nothing was compiled and nothing was verified. Kept
#: explicit so no caller can read "transform_success" as a verification.
NOT_A_VERIFICATION = (
    "compilation is not verification: a source that transformed and compiled "
    "has had nothing checked numerically")


@dataclass
class TransformationReport:
    config: str = ""
    out_dir: str = ""
    source: str = ""
    status_category: str = ""
    transform_success: Optional[bool] = None
    blockers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    compilation: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    manifest_path: str = ""
    semantic_checks: dict = field(default_factory=dict)
    exit_code: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "config": self.config, "out_dir": self.out_dir,
            "source": self.source, "status_category": self.status_category,
            "transform_success": self.transform_success,
            "blockers": list(self.blockers), "warnings": list(self.warnings),
            "compilation": dict(self.compilation),
            "artifacts": dict(self.artifacts),
            "manifest_path": self.manifest_path,
            "semantic_checks": dict(self.semantic_checks),
            "exit_code": self.exit_code,
            "what_this_is_not": NOT_A_VERIFICATION,
        }


class TransformationService:
    """Transform one contract into an artifact set."""

    def __init__(self, *, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def transform(self, config_path: Path, out_dir: Path, *,
                  compile_generated: bool = False,
                  options: Optional[TransformationOptions] = None) -> ServiceResult:
        options = options or TransformationOptions(
            compile_generated=compile_generated)
        result = ServiceResult(
            service=SERVICE, outcome="transformed",
            provenance=self._provenance(config=str(config_path),
                                        out_dir=str(out_dir),
                                        options=options.cache_identity()))
        summary, exit_code = run_transformation(Path(config_path),
                                                Path(out_dir), options)
        report = TransformationReport(
            config=str(summary.get("config") or config_path),
            out_dir=str(summary.get("out_dir") or out_dir),
            source=str(summary.get("source") or ""),
            status_category=str(summary.get("status_category") or ""),
            transform_success=summary.get("transform_success"),
            blockers=list(summary.get("blockers") or []),
            warnings=list(summary.get("warnings") or []),
            compilation=dict(summary.get("compilation") or {}),
            artifacts=dict(summary.get("artifacts") or {}),
            manifest_path=str(summary.get("manifest") or ""),
            semantic_checks=dict(summary.get("semantic_checks") or {}),
            exit_code=exit_code)
        result.data = report
        result.outcome = report.status_category or (
            "succeeded" if exit_code == 0 else "failed")
        if exit_code != 0:
            result.ok = False
        for blocker in report.blockers:
            if isinstance(blocker, dict):
                result.add(str(blocker.get("code") or "blocked"),
                           str(blocker.get("message") or blocker),
                           where=report.source)
            else:
                result.add("blocked", str(blocker), where=report.source)
        for warning in report.warnings:
            result.add("transform_warning", str(warning), where=report.source,
                       severity="warning")
        if summary.get("error"):
            result.add("transform_error", str(summary["error"]),
                       where=str(config_path))
        if report.manifest_path:
            result.evidence_paths["manifest"] = report.manifest_path
        if summary.get("report_path"):
            result.evidence_paths["report"] = str(summary["report_path"])
        if summary.get("combined_source"):
            result.evidence_paths["combined_source"] = str(
                summary["combined_source"])
        return result

    def compile(self, config_path: Path, out_dir: Path) -> ServiceResult:
        """Transform and compile. The same call; the flag is the difference."""
        return self.transform(config_path, out_dir, compile_generated=True)

    def diagnostics(self, source_path: Path, *, roots=(), entry: str = "UMAT",
                    exclude=()) -> ServiceResult:
        """What a source is, before anything is transformed.

        Delegates to :func:`umat_oti.services.workbench.analyse_source`, which
        the workbench already uses, so the interface's first screen and the
        pipeline see the same closure.
        """
        from .workbench import analyse_source  # noqa: PLC0415

        result = ServiceResult(
            service=SERVICE, outcome="analysed",
            provenance=self._provenance(source=str(source_path), entry=entry))
        source_path = Path(source_path)
        if not source_path.is_file():
            result.add("source_not_found", f"{source_path} is not a file",
                       where=str(source_path))
            result.outcome = "refused"
            return result
        analysis = analyse_source(source_path, roots, entry, exclude)
        result.data = analysis
        if analysis.get("dependency_error"):
            result.outcome = "dependencies_unresolved"
            result.add(str(analysis.get("dependency_error_code")
                           or "dependency_error"),
                       str(analysis["dependency_error"]),
                       where=str(source_path))
        for missing in analysis.get("missing_symbols") or []:
            result.add("missing_symbol",
                       f"{missing.get('symbol')} could not be resolved from the "
                       f"declared dependency roots",
                       where=str(source_path), severity="warning")
        return result
