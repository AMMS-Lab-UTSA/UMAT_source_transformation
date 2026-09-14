"""The stage vocabulary the interface shows, and what it is mapped from.

The interface must not show a reader ``transformed_executed`` or
``manifest_refused``. Those are this project's internal rungs and they mean
nothing to a mechanical engineer who wants to know whether their UMAT
differentiated. But they must not be *thrown away* either: the internal name is
what the evidence files, the store records and the papers are keyed on, so a
plain-language label that cannot be traced back to the rung it came from is a
label nobody can audit.

So every stage here carries both. :attr:`Stage.label` is what the interface
prints; :attr:`Stage.internal_names` is every internal rung, across all three
vocabularies in this repository, that maps onto it.

The three internal vocabularies, all of which a caller may hand to
:func:`stage_for_internal`:

``umat_oti.corpus.funnel.STAGES``
    the offline funnel, thirteen rungs from ``discovered`` to
    ``derivatives_verified``.
``umat_oti.corpus._STAGE_ORDER``
    the corpus store's ten-rung ladder.
``tools/verify_store_in_abaqus.py STAGES``
    the Abaqus ladder, whose rungs are named after the way a candidate *stops*
    (``primal_disagreed``, ``original_job_failed``) rather than after what it
    passed. Those are the names in ``store_verification.jsonl``.

An internal name this module has never heard of is reported as unmapped, with
the name preserved. It is never bucketed into a neighbouring stage: a reader
being shown "Comparing mechanical histories" for a rung nobody mapped would be
reading a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "UntranslatedStage",
    "Stage",
    "STAGES",
    "STAGE_KEYS",
    "STAGE_LABELS",
    "STATE_NOT_RUN",
    "STATE_RUNNING",
    "STATE_SUCCEEDED",
    "STATE_FAILED",
    "STATE_SKIPPED",
    "STATE_REFUSED",
    "STAGE_STATES",
    "stage_for_internal",
    "require_stage_for_internal",
    "stage_by_key",
    "label_for_internal",
    "unmapped_internal_names",
]

#: A stage that has not run. This is the default, and it is never optimistic:
#: nothing may report a stage as anything else until the stage itself said so.
STATE_NOT_RUN = "not_run"
STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
#: Deliberately not attempted, with a reason -- distinct from ``not_run``,
#: which means nothing has happened yet and the stage may still run.
STATE_SKIPPED = "skipped"
#: The stage ran and declined to produce a result, which is an answer and not
#: a failure: a manifest that refuses an underdetermined model, for instance.
STATE_REFUSED = "refused"

STAGE_STATES = (STATE_NOT_RUN, STATE_RUNNING, STATE_SUCCEEDED, STATE_FAILED,
                STATE_SKIPPED, STATE_REFUSED)


class UntranslatedStage(KeyError):
    """An internal rung nobody mapped to a displayed stage.

    This raises rather than defaulting, because the default is what caused the
    damage: ``FROM_STAGE.get(stage, "not_attempted")`` reported three runs that
    happened as runs that never did. A stage nobody mapped is a bug to fix in
    this module, not a value to render.
    """

    def __init__(self, internal: str) -> None:
        super().__init__(internal)
        self.internal = internal

    def __str__(self) -> str:  # KeyError repr quotes its argument; this does not
        return (f"internal stage {self.internal!r} has no plain-language "
                f"mapping in umat_oti.jobs.stages. Add it to the Stage whose "
                f"rung it is; do not let it fall through to a neighbour.")


@dataclass(frozen=True)
class Stage:
    """One rung as the interface shows it, and every internal name behind it."""

    key: str
    label: str
    internal_names: tuple[str, ...]
    #: What this stage establishes, in the words a reader of the paper would use.
    means: str

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "internal_names": list(self.internal_names), "means": self.means}


#: The nine stages, in the order they happen. Index in this tuple is the only
#: ordering there is; nothing computes a stage number from a string.
STAGES: tuple[Stage, ...] = (
    Stage(
        key="analyze_umat",
        label="Analyzing the UMAT",
        means=("the file was read, its entry routine found, and every helper it "
               "calls resolved"),
        internal_names=(
            # funnel
            "discovered", "license_classified", "entry_detected",
            "dependencies_resolved",
            # corpus store ladder (umat_oti.corpus._STAGE_ORDER)
            "entry_routine_detected", "dependencies_complete",
            # Abaqus ladder: how it stops here
            "not_a_umat", "incomplete_or_corrupt_source",
        )),
    Stage(
        key="find_material_data",
        label="Finding material data",
        means=("property values and a loading path were found in the repository "
               "the source came from, with the file and block they came from "
               "recorded"),
        internal_names=(
            "contract_constructed", "contract_built",
            "needs_material_data",
            "experiment_not_generated",
        )),
    Stage(
        key="build_experiment",
        label="Building a mechanical experiment",
        means=("an Abaqus deck and a derivative manifest were built for this "
               "source, at an element type and formulation the deck itself names"),
        internal_names=(
            "manifest_refused", "waits_for_input",
        )),
    Stage(
        key="search_activation",
        label="Searching for yielding, damage or time dependence",
        means=("the loading amplitude was searched until something in the "
               "routine departed from linear elasticity, or it was established "
               "that nothing does"),
        internal_names=(
            "experiment_not_informative", "informativeness_not_established",
        )),
    Stage(
        key="run_original",
        label="Running the original routine",
        means="the unmodified UMAT ran to completion in Abaqus",
        internal_names=(
            "original_compiled", "original_executed",
            "support_build_failed", "original_job_failed",
        )),
    Stage(
        key="run_transformed",
        label="Running the transformed routine",
        means="the OTI-transformed UMAT ran to completion in Abaqus",
        internal_names=(
            "transformed", "generated_compiled", "generated_source_compiled",
            "transformed_executed", "transformed_job_failed",
        )),
    Stage(
        key="compare_histories",
        label="Comparing mechanical histories",
        means=("the two builds were compared increment by increment on stress "
               "and state; they are not comparable as derivatives until they "
               "agree here"),
        internal_names=(
            "primal_parity", "primal_parity_verified",
            "primal_disagreed", "both_builds_non_finite",
            "arguments_diverged_before_the_routine",
            "disagreement_not_in_any_recorded_call",
        )),
    Stage(
        key="verify_derivatives",
        label="Verifying derivatives",
        means=("the transformed routine's derivative was compared against a "
               "finite-difference reference able to resolve it"),
        internal_names=(
            "reference_resolved", "derivatives_verified",
            "derivatives_numerically_verified", "abaqus_verified",
            "tangent_not_verified", "derivative_truncated", "verified",
        )),
    Stage(
        key="create_regression",
        label="Creating the regression test",
        means=("the verified history was frozen as a fixture a later run, or "
               "the Residual Assembler, can be checked against"),
        internal_names=(
            "fixture_frozen", "fixture_refused", "regression_recorded",
        )),
)

STAGE_KEYS: tuple[str, ...] = tuple(s.key for s in STAGES)
STAGE_LABELS: tuple[str, ...] = tuple(s.label for s in STAGES)

_BY_KEY = {s.key: s for s in STAGES}
_BY_INTERNAL: dict[str, Stage] = {}
for _stage in STAGES:
    for _name in _stage.internal_names:
        if _name in _BY_INTERNAL:  # pragma: no cover - guarded by a test
            raise RuntimeError(
                f"internal stage name {_name!r} is claimed by both "
                f"{_BY_INTERNAL[_name].key!r} and {_stage.key!r}")
        _BY_INTERNAL[_name] = _stage


def stage_by_key(key: str) -> Optional[Stage]:
    return _BY_KEY.get(key)


def stage_for_internal(internal: Optional[str]) -> Optional[Stage]:
    """The displayed stage an internal rung belongs to, or None if unmapped.

    None is a real answer here. A caller that gets None must show the internal
    name and say it is unmapped, rather than pick the nearest stage.
    """
    if not internal:
        return None
    return _BY_INTERNAL.get(str(internal).strip())


def label_for_internal(internal: Optional[str]) -> dict:
    """Plain-language label for an internal rung, with the rung kept beside it.

    Always returns both, so no caller can display the label without being able
    to show what it was mapped from.
    """
    stage = stage_for_internal(internal)
    if stage is None:
        return {"label": None, "key": None, "internal": internal,
                "mapped": False,
                "note": ("this internal stage name has no plain-language "
                         "mapping; it is shown as itself rather than guessed "
                         "into a neighbouring stage")}
    return {"label": stage.label, "key": stage.key, "internal": internal,
            "mapped": True, "means": stage.means}


def require_stage_for_internal(internal: str) -> Stage:
    """The displayed stage for an internal rung, or raise.

    Use this wherever a running job reports its own rung: there, an unmapped
    name is a defect in this module and must stop the translation rather than
    be shown as something it is not. :func:`stage_for_internal` is the variant
    for callers whose actual question is "is this mapped?".
    """
    stage = stage_for_internal(internal)
    if stage is None:
        raise UntranslatedStage(str(internal))
    return stage


def unmapped_internal_names(names) -> list[str]:
    """Which of ``names`` this module has no mapping for. Order preserved."""
    return [n for n in names if n and n not in _BY_INTERNAL]
