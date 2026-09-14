"""ExperimentService: formulation-aware deck generation and activation search.

Deck design already exists, in ``umat_oti.abaqus.experiment``,
``umat_oti.abaqus.formulation`` and ``umat_oti.abaqus.deck``. This service is
the reusable face of it: it chooses nothing itself, holds no thresholds and
generates no ``.inp`` text of its own. It calls ``experiment.plan`` -- the same
chain the batch runs -- and returns the plan in a schema the CLI and the GUI
can both render.

**Activation search needs Abaqus and this service does not run Abaqus.** The
amplitude ladder in ``umat_oti.abaqus.amplitude_search`` drives real jobs. So
:meth:`activation_search` has two modes and they are named apart: ``read``
reports the search a batch already performed, out of the record; ``request``
files the search as a job through :class:`AbaqusExecutionService` for the lead's
queue. There is no third mode that reports a search nobody ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.records import utc_now

__all__ = ["ExperimentPlan", "ActivationSearch", "ExperimentService"]

SERVICE = "experiment"


@dataclass
class ExperimentPlan:
    """The experiment chosen for one source, and why that one."""

    source_id: str = ""
    family: str = ""
    criterion: str = ""
    element: str = ""
    element_family: str = ""
    formulation_provenance: str = ""
    kinematics: str = ""
    kinematics_provenance: str = ""
    ntens: Optional[int] = None
    segments: list[dict] = field(default_factory=list)
    deck_path: str = ""
    refusal: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.family) and not self.refusal

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id, "found": self.found,
            "family": self.family, "criterion": self.criterion,
            "element": self.element, "element_family": self.element_family,
            "formulation_provenance": self.formulation_provenance,
            "kinematics": self.kinematics,
            "kinematics_provenance": self.kinematics_provenance,
            "ntens": self.ntens, "segments": list(self.segments),
            "deck_path": self.deck_path, "refusal": self.refusal,
            "warnings": list(self.warnings),
        }


@dataclass
class ActivationSearch:
    """Whether anything departed from linear elasticity, and what fired."""

    #: Three states, not two: None means no search is recorded, which is not
    #: the same as a search that found nothing.
    activated: Optional[bool] = None
    fired: list[str] = field(default_factory=list)
    indicators: list[dict] = field(default_factory=list)
    not_measured: list[str] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    amplitude: Optional[float] = None
    increments: Optional[int] = None
    outcome: str = ""
    source_of_this_reading: str = ""

    @property
    def established(self) -> bool:
        return self.activated is not None

    def as_dict(self) -> dict:
        return {
            "activated": self.activated, "established": self.established,
            "fired": list(self.fired), "indicators": list(self.indicators),
            "not_measured": list(self.not_measured),
            "attempts": list(self.attempts), "amplitude": self.amplitude,
            "increments": self.increments, "outcome": self.outcome,
            "source_of_this_reading": self.source_of_this_reading,
        }


class ExperimentService:
    """Plan a mechanical experiment; read or request an activation search."""

    def __init__(self, *, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    def plan_deck(self, source: Path, repository: Path, *,
                  name: str = "") -> ServiceResult:
        """Choose an experiment for one source. Delegates to ``abaqus.experiment``."""
        from umat_oti.abaqus import experiment as experiment_module  # noqa: PLC0415

        source = Path(source)
        result = ServiceResult(
            service=SERVICE, outcome="planned",
            provenance=self._provenance(source=str(source),
                                        repository=str(repository)))
        if not source.is_file():
            result.add("source_not_found", f"{source} is not a file",
                       where=str(source))
            result.outcome = "refused"
            return result
        try:
            plan = experiment_module.plan(source, Path(repository),
                                          name=name or source.stem)
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            result.add("planning_failed",
                       f"{type(error).__name__}: {error}", where=str(source))
            result.outcome = "refused"
            return result
        result.data = self._plan_from(plan, source.name)
        if result.data.refusal:
            result.outcome = "refused"
            result.add("experiment_refused", result.data.refusal,
                       where=str(source), severity="warning")
        return result

    @staticmethod
    def _plan_from(plan: Any, source_id: str) -> ExperimentPlan:
        experiment = getattr(plan, "experiment", plan)
        family = getattr(experiment, "family", None)
        manifest = getattr(experiment, "manifest", None)
        return ExperimentPlan(
            source_id=source_id,
            family=getattr(family, "name", "") if family else "",
            criterion=str(getattr(experiment, "criterion", "") or ""),
            element=str(getattr(manifest, "element_type", "") or ""),
            kinematics=str(getattr(manifest, "kinematics", "") or ""),
            ntens=getattr(manifest, "ntens", None),
            segments=[s.__dict__ if hasattr(s, "__dict__") else dict(s)
                      for s in (getattr(manifest, "loading", ()) or ())],
            refusal=str(getattr(experiment, "refusal", "") or ""),
            warnings=list(getattr(experiment, "warnings", ()) or ()))

    def generate_deck(self, manifest) -> ServiceResult:
        """The Abaqus deck for a manifest. One generator, delegated to."""
        from umat_oti.abaqus.deck import generate_deck  # noqa: PLC0415

        result = ServiceResult(service=SERVICE, outcome="generated",
                               provenance=self._provenance())
        try:
            result.data = {"deck": generate_deck(manifest)}
        except Exception as error:  # noqa: BLE001
            result.add("deck_generation_failed",
                       f"{type(error).__name__}: {error}")
            result.outcome = "refused"
        return result

    def activation_search(self, record: dict) -> ServiceResult:
        """Read the activation search a batch already performed.

        This reads; it does not search. A record with no search block reports
        ``activated: None`` and ``established: False`` -- never ``activated:
        False``, which would claim a search ran and found nothing.
        """
        result = ServiceResult(
            service=SERVICE, outcome="read",
            provenance=self._provenance(key=record.get("key")))
        frozen = record.get("activation_on_the_frozen_run")
        discovery = record.get("discovery")
        discovery = discovery if isinstance(discovery, dict) else {}

        if isinstance(frozen, dict):
            search = ActivationSearch(
                activated=frozen.get("activated"),
                fired=list(frozen.get("fired") or []),
                indicators=list(frozen.get("indicators") or []),
                not_measured=list(frozen.get("not_measured") or []),
                increments=frozen.get("increments"),
                attempts=list(discovery.get("attempts") or []),
                amplitude=discovery.get("amplitude"),
                outcome=str(frozen.get("summary") or ""),
                source_of_this_reading="activation_on_the_frozen_run")
        elif discovery:
            search = ActivationSearch(
                activated=(discovery.get("activation") or {}).get("activated")
                if isinstance(discovery.get("activation"), dict) else None,
                attempts=list(discovery.get("attempts") or []),
                amplitude=discovery.get("amplitude"),
                source_of_this_reading="discovery")
        else:
            search = ActivationSearch(
                source_of_this_reading="nothing in this record records a search")
            result.outcome = "not_established"
            result.add("no_activation_search_recorded",
                       "this record carries no activation search, so whether "
                       "anything departs from linear elasticity is not "
                       "established. It is not recorded as 'did not activate'.",
                       where=str(record.get("key") or ""), severity="warning")
        result.data = search
        return result
