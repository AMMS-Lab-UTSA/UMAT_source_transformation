"""CorpusService: import, list, search and filter the sources under study.

Reads the batch's own results file (``store_verification.jsonl``) rather than
keeping a second opinion about what is in the corpus. The record there is a raw
dict written by ``tools/verify_store_in_abaqus.py``; this service gives it a
typed shape so the CLI and the GUI agree on what a source *is*, and so a screen
never has to decide for itself what a missing key means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ._support import REPO_ROOT, read_jsonl
from .gates import GATES, GateSet, census, read_gates
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.stages import label_for_internal

__all__ = ["SourceSummary", "CorpusListing", "CorpusService"]

SERVICE = "corpus"


@dataclass
class SourceSummary:
    """One source, as every screen and every command should see it."""

    key: str
    source_id: str
    source_sha256: str
    repository: str
    stage: str
    stage_label: Optional[str]
    stage_internal: str
    stage_mapped: bool
    ntens: Optional[int] = None
    nstatv: Optional[int] = None
    props_count: Optional[int] = None
    kinematics: str = ""
    element_type: str = ""
    deck: str = ""
    material_provenance: str = ""
    seconds: Optional[float] = None
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    gates: Optional[GateSet] = None

    @property
    def all_six_hold(self) -> bool:
        return bool(self.gates and self.gates.all_six_hold)

    def as_dict(self) -> dict:
        return {
            "key": self.key, "source_id": self.source_id,
            "source_sha256": self.source_sha256, "repository": self.repository,
            "stage": self.stage, "stage_label": self.stage_label,
            "stage_internal": self.stage_internal,
            "stage_mapped": self.stage_mapped,
            "ntens": self.ntens, "nstatv": self.nstatv,
            "props_count": self.props_count, "kinematics": self.kinematics,
            "element_type": self.element_type, "deck": self.deck,
            "material_provenance": self.material_provenance,
            "seconds": self.seconds, "reason": self.reason,
            "warnings": list(self.warnings),
            "all_six_hold": self.all_six_hold,
            "gates": self.gates.as_dict() if self.gates else None,
        }


@dataclass
class CorpusListing:
    """A set of sources, with the denominator it was drawn from kept beside it."""

    sources: list[SourceSummary] = field(default_factory=list)
    #: How many records the file held. A filtered listing that does not say
    #: what it was filtered from is a number without a denominator.
    records_in_file: int = 0
    unreadable_records: int = 0
    filters: dict[str, Any] = field(default_factory=dict)
    stage_counts: dict[str, int] = field(default_factory=dict)
    gate_census: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sources": [s.as_dict() for s in self.sources],
            "shown": len(self.sources),
            "records_in_file": self.records_in_file,
            "unreadable_records": self.unreadable_records,
            "filters": dict(self.filters),
            "stage_counts": dict(self.stage_counts),
            "gate_census": list(self.gate_census),
        }


def _summarise(record: dict) -> SourceSummary:
    stage = str(record.get("stage") or "")
    mapping = label_for_internal(stage)
    return SourceSummary(
        key=str(record.get("key") or ""),
        source_id=str(record.get("source") or ""),
        source_sha256=str(record.get("source_sha256") or ""),
        repository=str(record.get("repository") or ""),
        stage=stage,
        stage_label=mapping["label"],
        stage_internal=stage,
        stage_mapped=bool(mapping["mapped"]),
        ntens=record.get("ntens"),
        nstatv=record.get("nstatv"),
        props_count=record.get("props_count"),
        kinematics=str(record.get("kinematics") or ""),
        element_type=str(record.get("element_type") or ""),
        deck=str(record.get("deck") or ""),
        material_provenance=str(record.get("material_provenance") or ""),
        seconds=record.get("seconds"),
        reason=str(record.get("reason") or ""),
        warnings=list(record.get("warnings") or []),
        gates=read_gates(record),
    )


class CorpusService:
    """The corpus as one reusable interface, for the CLI and the GUI alike."""

    def __init__(self, results_path: Path, *, repo_root: Path = REPO_ROOT) -> None:
        self.results_path = Path(results_path)
        self.repo_root = Path(repo_root)

    # -- reading -----------------------------------------------------------

    def _records(self) -> tuple[list[dict], int]:
        records, unreadable = [], 0
        for row in read_jsonl(self.results_path):
            if "unparseable" in row:
                unreadable += 1
                continue
            records.append(row)
        return records, unreadable

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        from umat_oti.jobs.records import utc_now
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def list_sources(self, *, stage: Optional[str] = None,
                     all_six_hold: Optional[bool] = None,
                     limit: int = 0) -> ServiceResult:
        """Every source, or those matching the filters, with the denominator."""
        result = ServiceResult(service=SERVICE, outcome="listed",
                               provenance=self._provenance(
                                   results=str(self.results_path),
                                   stage=stage, all_six_hold=all_six_hold))
        if not self.results_path.is_file():
            result.add("results_file_missing",
                       f"{self.results_path} does not exist, so there is no "
                       f"corpus to list. This is not an empty corpus.",
                       where=str(self.results_path))
            result.outcome = "no_results_file"
            result.data = CorpusListing(filters={"stage": stage})
            return result

        records, unreadable = self._records()
        summaries = [_summarise(r) for r in records]
        stage_counts: dict[str, int] = {}
        for summary in summaries:
            stage_counts[summary.stage] = stage_counts.get(summary.stage, 0) + 1

        selected = summaries
        if stage is not None:
            selected = [s for s in selected if s.stage == stage]
        if all_six_hold is not None:
            selected = [s for s in selected if s.all_six_hold == all_six_hold]
        if limit > 0:
            selected = selected[:limit]

        result.data = CorpusListing(
            sources=selected,
            records_in_file=len(records) + unreadable,
            unreadable_records=unreadable,
            filters={"stage": stage, "all_six_hold": all_six_hold,
                     "limit": limit},
            stage_counts=stage_counts,
            gate_census=[census(records, gate) for gate in GATES])
        if unreadable:
            result.add("unreadable_records",
                       f"{unreadable} line(s) in {self.results_path} would not "
                       f"parse and are counted in the denominator but not "
                       f"summarised; the listing is short by that many",
                       severity="warning")
        result.evidence_paths["results"] = str(self.results_path)
        return result

    def search(self, text: str, *, limit: int = 0) -> ServiceResult:
        """Substring search over the fields a reader would search on."""
        listing = self.list_sources()
        if not listing.ok:
            return listing
        needle = text.strip().lower()
        data: CorpusListing = listing.data
        if needle:
            data.sources = [
                s for s in data.sources
                if needle in s.source_id.lower()
                or needle in s.repository.lower()
                or needle in s.key.lower()
                or needle in s.deck.lower()
                or needle in s.stage.lower()]
        if limit > 0:
            data.sources = data.sources[:limit]
        data.filters = {"search": text, "limit": limit}
        listing.outcome = "searched"
        return listing

    def filter_sources(self, predicate) -> ServiceResult:
        """Arbitrary filter, with the denominator preserved."""
        listing = self.list_sources()
        if not listing.ok:
            return listing
        data: CorpusListing = listing.data
        data.sources = [s for s in data.sources if predicate(s)]
        data.filters = {"predicate": getattr(predicate, "__name__", "callable")}
        listing.outcome = "filtered"
        return listing

    def get(self, key: str) -> ServiceResult:
        """One source by its store key, or a refusal naming what was searched."""
        result = ServiceResult(service=SERVICE, outcome="found",
                               provenance=self._provenance(key=key))
        records, _ = self._records()
        for record in records:
            if str(record.get("key") or "") == key:
                result.data = _summarise(record)
                return result
        result.outcome = "not_found"
        result.add("no_such_source",
                   f"no entry with key {key!r} in {self.results_path} "
                   f"({len(records)} records searched)",
                   where=str(self.results_path))
        return result

    # -- importing ---------------------------------------------------------

    def import_source(self, path: Path, *, cache_root: Path,
                      source_id: str = "") -> ServiceResult:
        """Take a local UMAT into the corpus cache and analyse what it is.

        Analysis is delegated to :func:`umat_oti.services.workbench.analyse_source`
        -- the same function the workbench runs -- so the interface's view of a
        newly imported file is the pipeline's view of it and not a second one.
        """
        from .workbench import analyse_source  # noqa: PLC0415

        path = Path(path)
        source_id = source_id or path.name
        result = ServiceResult(service=SERVICE, outcome="imported",
                               provenance=self._provenance(
                                   path=str(path), source_id=source_id))
        if not path.is_file():
            result.add("source_not_found", f"{path} is not a file",
                       where=str(path))
            result.outcome = "refused"
            return result
        import hashlib
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        destination = Path(cache_root) / source_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
        try:
            analysis = analyse_source(destination)
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            analysis = {}
            result.add("analysis_failed",
                       f"{type(error).__name__}: {error}", where=str(destination),
                       severity="warning")
        result.data = {"source_id": source_id, "source_sha256": digest,
                       "cached_at": str(destination), "analysis": analysis}
        result.evidence_paths["source"] = str(destination)
        return result
