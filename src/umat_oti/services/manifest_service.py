"""ManifestService: build a derivative manifest for one source, and review one.

Building delegates to :func:`umat_oti.reports.manifest.build_manifest`, which is
what the transformation pipeline itself calls. Reviewing reads the manifest a
batch already recorded and reports what it settled and what it refused -- so a
screen showing "this experiment was refused" is showing the batch's refusal and
not a second judgement about the same source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.records import utc_now

__all__ = ["ManifestReview", "ManifestService"]

SERVICE = "manifest"

#: Rungs at which no experiment was built, so the batch's reason IS the
#: refusal. Every other rung has a manifest and a reason about something else.
REFUSAL_STAGES = frozenset({
    "manifest_refused", "needs_material_data", "experiment_not_generated",
    "experiment_not_informative", "informativeness_not_established",
    "not_a_umat", "incomplete_or_corrupt_source",
})


@dataclass
class ManifestReview:
    """A manifest as a reader needs it: what it says, and what it would not say."""

    source_id: str = ""
    manifest: dict = field(default_factory=dict)
    #: Set when the batch declined to build an experiment for this source.
    refusal: str = ""
    #: Which key the refusal was read out of, so a reader can go and check it.
    refusal_source: str = ""
    requirement: Any = None
    element_type: str = ""
    kinematics: str = ""
    ntens: Optional[int] = None
    nstatv: Optional[int] = None
    props: list = field(default_factory=list)
    material_provenance: str = ""
    deck_digest: str = ""
    loading: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def built(self) -> bool:
        """Whether there is a manifest at all. A refusal is not a manifest."""
        return bool(self.manifest) and not self.refusal

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id, "built": self.built,
            "refusal": self.refusal, "refusal_source": self.refusal_source,
            "requirement": self.requirement,
            "element_type": self.element_type, "kinematics": self.kinematics,
            "ntens": self.ntens, "nstatv": self.nstatv,
            "props": list(self.props),
            "material_provenance": self.material_provenance,
            "deck_digest": self.deck_digest, "loading": list(self.loading),
            "warnings": list(self.warnings), "manifest": dict(self.manifest),
        }


class ManifestService:
    """Build and review derivative manifests."""

    def __init__(self, *, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def build(self, *, source_path: Path, entry_routine: str, ntens: int,
              nstatv: int, nprops: int, requests, destination: Path,
              **extra) -> ServiceResult:
        """Build and write a derivative manifest. Delegates; does not reimplement."""
        from umat_oti.reports.manifest import (  # noqa: PLC0415
            build_manifest, write_manifest,
        )

        result = ServiceResult(
            service=SERVICE, outcome="built",
            provenance=self._provenance(source=str(source_path),
                                        destination=str(destination)))
        try:
            manifest = build_manifest(
                source_path=Path(source_path), entry_routine=entry_routine,
                ntens=ntens, nstatv=nstatv, nprops=nprops, requests=requests,
                **extra)
            path = write_manifest(manifest, Path(destination))
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            result.add("manifest_build_failed",
                       f"{type(error).__name__}: {error}",
                       where=str(source_path))
            result.outcome = "refused"
            return result
        result.data = ManifestReview(source_id=Path(source_path).name,
                                     manifest=manifest, ntens=ntens,
                                     nstatv=nstatv,
                                     warnings=list(manifest.get("warnings") or []))
        result.evidence_paths["manifest"] = str(path)
        return result

    def review(self, record: dict) -> ServiceResult:
        """Read the manifest a batch recorded for one source.

        A source the batch refused reports the refusal in ``refusal`` and
        ``built`` false. It does not report an empty manifest as a manifest.
        """
        result = ServiceResult(
            service=SERVICE, outcome="reviewed",
            provenance=self._provenance(key=record.get("key")))
        experiment = record.get("experiment")
        experiment = experiment if isinstance(experiment, dict) else {}
        # The manifest is written at the top level and also nested inside the
        # experiment block. Neither is canonical, so both are looked at rather
        # than one being assumed.
        manifest = record.get("manifest")
        manifest_source = "manifest"
        if not isinstance(manifest, dict):
            manifest = experiment.get("manifest")
            manifest_source = "experiment.manifest"
        manifest = manifest if isinstance(manifest, dict) else {}

        # A refusal is `experiment.refusal`, and -- where that is empty but the
        # entry stopped at a rung that IS a refusal to build an experiment --
        # the top-level reason, which is where the batch wrote it instead.
        # `experiment.reason` is deliberately NOT consulted: it holds the prose
        # explaining the criterion the experiment was built to meet, and every
        # record has one, including the verified ones. Reading it as a refusal
        # made all 237 records report as refused.
        refusal, refusal_source = "", ""
        if experiment.get("refusal") and str(experiment["refusal"]).strip():
            refusal = str(experiment["refusal"])
            refusal_source = "experiment.refusal"
        elif str(record.get("stage") or "") in REFUSAL_STAGES \
                and str(record.get("reason") or "").strip():
            refusal = str(record["reason"])
            refusal_source = "reason"

        review = ManifestReview(
            source_id=str(record.get("source") or ""),
            manifest=manifest,
            refusal=refusal,
            refusal_source=refusal_source,
            requirement=experiment.get("requirement"),
            element_type=str(record.get("element_type")
                             or manifest.get("element_type") or ""),
            kinematics=str(record.get("kinematics")
                           or manifest.get("kinematics") or ""),
            ntens=record.get("ntens") if record.get("ntens") is not None
            else manifest.get("ntens"),
            nstatv=record.get("nstatv") if record.get("nstatv") is not None
            else manifest.get("nstatv"),
            props=list(manifest.get("props") or []),
            material_provenance=str(record.get("material_provenance") or ""),
            deck_digest=str(record.get("deck_digest") or ""),
            loading=list(manifest.get("loading") or []),
            warnings=list(record.get("warnings") or []))
        result.data = review
        result.provenance.inputs["manifest_read_from"] = (
            manifest_source if manifest else "")
        if refusal:
            result.outcome = "refused"
            result.add("experiment_refused", refusal,
                       where=f"{review.source_id} ({refusal_source})",
                       severity="warning")
        elif not manifest:
            result.outcome = "no_manifest"
            result.add("no_manifest_recorded",
                       "this record carries no manifest and no refusal, so "
                       "nothing is known about the experiment that would have "
                       "been built",
                       where=review.source_id, severity="warning")
        return result
