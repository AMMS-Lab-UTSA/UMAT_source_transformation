"""ExperimentService: formulation-aware deck generation and activation search.

Deck design already exists, in ``umat_oti.abaqus.experiment``,
``umat_oti.abaqus.formulation`` and ``umat_oti.abaqus.deck``. This service is
the reusable face of it: it chooses nothing itself, holds no thresholds and
generates no ``.inp`` text of its own.

**It does not import the harness, and that is a boundary rather than a
preference.** ``umat_oti.store.transform_store`` fingerprints every module
under ``umat_oti`` except ``abaqus``, ``app``, ``assist``, ``publication`` and
``store``, and keys stored transforms on that fingerprint. If a fingerprinted
module imported the harness, a change to the harness would alter what
fingerprinted code does without altering the fingerprint, and stale transforms
would be served as current. ``tests/test_the_fingerprint_covers_the_transform``
enforces it, and nothing else in this package crosses it.

So the two halves are separated rather than blurred:

*Reading* what a batch already planned or already searched needs no harness at
all, and :meth:`read_plan` and :meth:`activation_search` do it from the record.

*Planning or generating* needs ``umat_oti.abaqus``, so :meth:`plan_deck` and
:meth:`generate_deck` take the planner and the generator as arguments. A caller
that already lives on the harness side of the boundary -- the interface, a
tool, the batch -- passes them in. Called without one, the service returns a
refusal naming what is missing. It does not reach for the import through
``importlib`` to get past the check: that would leave the exemption genuinely
unsound while making it look sound, which is worse than the import.

**And it never runs Abaqus.** The amplitude ladder drives real jobs; requesting
one goes through :class:`AbaqusExecutionService` and the lead's queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT
from .manifest_service import REFUSAL_STAGES
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

    def read_plan(self, record: dict) -> ServiceResult:
        """The experiment a batch already planned, out of the record.

        No harness is needed to read one, so this is the method the interface
        wants in almost every case.
        """
        result = ServiceResult(
            service=SERVICE, outcome="read",
            provenance=self._provenance(key=record.get("key")))
        experiment = record.get("experiment")
        experiment = experiment if isinstance(experiment, dict) else {}
        manifest = record.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else (
            experiment.get("manifest") if isinstance(
                experiment.get("manifest"), dict) else {})
        family = experiment.get("family")
        formulation = record.get("formulation")
        formulation = formulation if isinstance(formulation, dict) else {}

        # The refusal is written in `experiment.refusal` where there was one,
        # and in the top-level `reason` where the batch stopped at a rung that
        # IS a refusal to build an experiment. Read from the same place
        # ManifestService reads it, rather than growing a second rule.
        refusal = str(experiment.get("refusal") or "")
        if not refusal.strip() and str(record.get("stage") or "") in REFUSAL_STAGES:
            refusal = str(record.get("reason") or "")

        plan = ExperimentPlan(
            source_id=str(record.get("source") or ""),
            family=(family.get("name") if isinstance(family, dict)
                    else str(family or "")),
            criterion=str(experiment.get("criterion") or ""),
            element=str(record.get("element_type")
                        or formulation.get("element") or ""),
            element_family=str(formulation.get("family") or ""),
            formulation_provenance=str(formulation.get("provenance") or ""),
            kinematics=str(record.get("kinematics") or ""),
            kinematics_provenance=str(record.get("kinematics_provenance") or ""),
            ntens=record.get("ntens"),
            segments=list(manifest.get("loading") or []),
            deck_path=str(record.get("deck") or ""),
            refusal=refusal,
            warnings=list(experiment.get("warnings") or []))
        result.data = plan
        if plan.refusal:
            result.outcome = "refused"
            result.add("experiment_refused", plan.refusal,
                       where=plan.source_id, severity="warning")
        elif not plan.family:
            result.outcome = "not_established"
            result.add("no_experiment_recorded",
                       "this record carries no experiment and no refusal, so "
                       "nothing is known about what would have been run",
                       where=plan.source_id, severity="warning")
        return result

    def plan_deck(self, source: Path, repository: Path, *,
                  planner=None, name: str = "") -> ServiceResult:
        """Choose an experiment for one source, using an injected planner.

        ``planner`` is ``umat_oti.abaqus.experiment.plan``. It is passed in
        rather than imported: see the module docstring for why this service may
        not import the harness.
        """
        source = Path(source)
        result = ServiceResult(
            service=SERVICE, outcome="planned",
            provenance=self._provenance(source=str(source),
                                        repository=str(repository)))
        if planner is None:
            result.add(
                "no_planner_supplied",
                "planning an experiment needs umat_oti.abaqus.experiment.plan, "
                "which this service may not import: it is fingerprinted code "
                "and the harness is exempt from the fingerprint. Pass "
                "planner=umat_oti.abaqus.experiment.plan from the caller, or "
                "read the plan a batch already made with read_plan().",
                where=str(source))
            result.outcome = "refused"
            return result
        if not source.is_file():
            result.add("source_not_found", f"{source} is not a file",
                       where=str(source))
            result.outcome = "refused"
            return result
        try:
            plan = planner(source, Path(repository), name=name or source.stem)
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

    def generate_deck(self, manifest, *, generator=None) -> ServiceResult:
        """The Abaqus deck for a manifest, using an injected generator.

        ``generator`` is ``umat_oti.abaqus.deck.generate_deck``. One generator
        exists and this service does not become a second one; it is passed in
        for the same boundary reason as the planner.
        """
        result = ServiceResult(service=SERVICE, outcome="generated",
                               provenance=self._provenance())
        if generator is None:
            result.add(
                "no_generator_supplied",
                "generating a deck needs umat_oti.abaqus.deck.generate_deck, "
                "which this service may not import. Pass generator= from a "
                "caller on the harness side.",
                where="generate_deck")
            result.outcome = "refused"
            return result
        try:
            result.data = {"deck": generator(manifest)}
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
