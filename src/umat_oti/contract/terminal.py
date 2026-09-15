"""Terminal states across the contract boundary, with their owner attached.

The vocabulary is NOT defined here. It is defined in
:mod:`umat_oti.abaqus.terminal_states` and imported, because two copies of one
vocabulary are two vocabularies and they drift. What this module adds is what a
cross-repository boundary needs and a single repository does not:

**A stage nobody mapped is refused, never defaulted.**

``from_stage`` used to answer ``not_attempted`` for a rung it had no word for.
``not_attempted`` is INTERNAL and reads "this run never happened", and it said
that about three of the 237 frozen entries -- entries that RAN, produced
output, and were isolated to a call whose INPUTS already differed before the
routine was entered. That is an EXTERNAL fact about somebody's published file,
booked into this project's own column by a default nobody chose. The
vocabulary raises :class:`UntranslatedStage` now; this module refuses in the
same direction and for the same reason, and does so whether or not the
checkout it runs against has grown that raise yet.

**And the vocabulary is published, because the consumer cannot import it.**

Residual_Assembler is a different project and cannot import
``terminal_states`` at all. A vocabulary a consumer cannot read is not an
agreement, so :data:`PUBLISHED_OWNERS` carries it across -- a publication of
the authority, never a second definition. :func:`vocabulary_gap` is what holds
the two together: a state this checkout can emit that the contract does not
publish would arrive at a consumer with no owner, which is the dangerous
direction, and it is reported by name rather than resolved silently.

Two words were added after the default did its damage:
``arguments_diverged_before_the_routine`` (published EXTERNAL at 2.0.0 and
INTERNAL from 3.0.0: the arguments that parted were computed by the solver from
each build's own earlier outputs, on this project's deck)
and ``disagreement_not_in_any_recorded_call`` (INTERNAL -- the histories
differ and nothing this project recorded accounts for it, which is a gap in
the recording rather than a fact about the source).

The owner
---------
``EXTERNAL``
    A fact about somebody's published repository. More engineering here changes
    none of them.
``INTERNAL``
    A limitation of this project. Every one of these is work.

An internal limitation transmitted as an external blocker is a claim that
somebody else's file is at fault for this pipeline's gap, and the contract
refuses to carry one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from umat_oti.abaqus.terminal_states import (ALL, EXTERNAL, FROM_STAGE,
                                             FULLY_VERIFIED, INTERNAL,
                                             WAITS_FOR_INPUT, kind_of)

try:  # the vocabulary raises on an unmapped rung since it grew two new ones
    from umat_oti.abaqus.terminal_states import UntranslatedStage
except ImportError:  # a checkout that predates that; see translate_stage
    class UntranslatedStage(KeyError):
        """Placeholder for a checkout whose vocabulary still defaults."""

__all__ = ["TerminalState", "TerminalStateError", "OWNERS", "EXTERNAL_OWNER",
           "INTERNAL_OWNER", "VERIFIED_OWNER", "translate_stage",
           "owner_of", "known_states", "PUBLISHED_OWNERS",
           "UntranslatedStage", "vocabulary_gap"]

EXTERNAL_OWNER = "EXTERNAL"
INTERNAL_OWNER = "INTERNAL"
#: Finished and verified is owned by nobody: there is no next move.
VERIFIED_OWNER = "NONE"

OWNERS = (VERIFIED_OWNER, EXTERNAL_OWNER, INTERNAL_OWNER)

#: The vocabulary as PUBLISHED across the boundary, state by owner.
#:
#: The authority is :mod:`umat_oti.abaqus.terminal_states`, which this module
#: imports rather than copies. This table exists because the consuming
#: repository cannot import that module at all -- it is a different project --
#: and a vocabulary a consumer cannot read is not an agreement. It is
#: therefore a PUBLICATION of the authority, not a second definition, and
#: :func:`vocabulary_gap` is what holds the two together: any disagreement is
#: reported by name rather than resolved silently.
#:
#: Two members were added after three entries that RAN were filed as runs that
#: never happened, and both are here because a consumer switching on this enum
#: must not fall through on them:
#:
#: ``arguments_diverged_before_the_routine`` -- INTERNAL (it was EXTERNAL at
#:     2.0.0). The paired call was isolated and its INPUTS already differed
#:     before the routine was entered -- but those inputs are what the solver
#:     computed from each build's own earlier outputs, on a deck this project
#:     generated, so where the two paths parted is this project's to find. It
#:     is never a fact about somebody's published repository.
#: ``disagreement_not_in_any_recorded_call`` -- INTERNAL. The histories differ
#:     and no recorded call accounts for it, which is a gap in what this
#:     project recorded.
PUBLISHED_OWNERS: dict = {
    "fully_verified": "NONE",
    "missing_material_data": "EXTERNAL",
    "not_a_umat": "EXTERNAL",
    "incomplete_or_corrupt_source": "EXTERNAL",
    "external_dependency_unavailable": "EXTERNAL",
    "published_stub_no_constitutive_content": "EXTERNAL",
    "waits_for_input": "EXTERNAL",
    "arguments_diverged_before_the_routine": "INTERNAL",
    "transform_refused": "INTERNAL",
    "experiment_not_generated": "INTERNAL",
    "experiment_not_informative": "INTERNAL",
    "informativeness_not_established": "INTERNAL",
    "unsupported_formulation": "INTERNAL",
    "support_build_failed": "INTERNAL",
    "original_job_failed": "INTERNAL",
    "transformed_job_failed": "INTERNAL",
    "primal_disagreed": "INTERNAL",
    # The two builds disagree and a control measured WHY. Never verified: an
    # explanation for a disagreement is not agreement. Thirteen entries were
    # carried across this boundary as verified before the rung existed.
    "primal_mismatch_explained": "INTERNAL",
    "disagreement_not_in_any_recorded_call": "INTERNAL",
    "derivative_truncated": "INTERNAL",
    "tangent_not_verified": "INTERNAL",
    "not_attempted": "INTERNAL",
    "harness_error": "INTERNAL",
}


class TerminalStateError(ValueError):
    """A stage or state the contract will not carry across the boundary."""


@dataclass(frozen=True)
class TerminalState:
    """One entry's final answer, its owner, and why."""

    state: str
    owner: str
    reason: str = ""
    #: The producing pipeline's own word for the rung, kept so that a reader
    #: can get back to the run's artefacts.
    stage: str = ""

    @property
    def finished(self) -> bool:
        """Verified, or external. An internal state is unfinished work."""
        return self.owner in (VERIFIED_OWNER, EXTERNAL_OWNER)

    @property
    def verified(self) -> bool:
        return self.state == FULLY_VERIFIED

    def as_dict(self) -> dict:
        return {"state": self.state, "owner": self.owner,
                "finished": self.finished, "reason": self.reason,
                "stage": self.stage}


def vocabulary_gap() -> dict:
    """Where this checkout's vocabulary and the published one disagree.

    ``{"missing_here": [...], "unpublished": [...]}``. The first is states the
    contract publishes that this checkout predates -- harmless for a reader,
    fatal for a producer, because it cannot emit a state it has never heard
    of. The second is the dangerous direction: a state this checkout can
    produce that the contract does not publish, which a consumer would receive
    and be unable to assign an owner to.
    """
    return {"missing_here": sorted(set(PUBLISHED_OWNERS) - set(ALL)),
            "unpublished": sorted(set(ALL) - set(PUBLISHED_OWNERS))}


def owner_of(state: str) -> str:
    """The owner of a state: EXTERNAL, INTERNAL, or NONE for fully_verified.

    The local vocabulary is the authority wherever it knows the state, so that
    this never disagrees with ``terminal_states.kind_of``. A state the local
    checkout predates is answered from :data:`PUBLISHED_OWNERS` and is not a
    guess -- it is the published answer, which is precisely what a consumer
    reads. A state in neither is refused.
    """
    if state in ALL:
        kind = kind_of(state)
        owner = {"verified": VERIFIED_OWNER, "external": EXTERNAL_OWNER,
                 "internal": INTERNAL_OWNER}[kind]
        published = PUBLISHED_OWNERS.get(state)
        if published is not None and published != owner:
            raise TerminalStateError(
                f"this checkout's vocabulary says {state!r} is owned by "
                f"{owner} and the published contract says {published}. One of "
                f"them is transmitting an internal limitation as an external "
                f"blocker, or the reverse. Neither is carried until they "
                f"agree.")
        return owner
    if state in PUBLISHED_OWNERS:
        return PUBLISHED_OWNERS[state]
    raise TerminalStateError(
        f"{state!r} is not a terminal state in this contract. The vocabulary "
        f"is defined in umat_oti.abaqus.terminal_states and published in "
        f"umat_oti.contract.terminal.PUBLISHED_OWNERS, which between them "
        f"have {len(set(ALL) | set(PUBLISHED_OWNERS))} members. Add it to "
        f"both, deciding deliberately whose problem it is.")


def translate_stage(stage: Any, reason: str = "") -> TerminalState:
    """Translate a run's rung into a terminal state, or refuse.

    Never invents one. The vocabulary's own ``from_stage`` raises
    ``UntranslatedStage`` for a rung nobody mapped -- it used to fall through
    to ``not_attempted``, which is INTERNAL and says the run never happened,
    and that silent default reported three entries that RAN as this project's
    unfinished work. This refuses in the same direction and for the same
    reason, and does so whether or not the checkout it is running against has
    grown that raise yet.
    """
    text = "" if stage is None else str(stage)
    if not text.strip():
        raise TerminalStateError(
            "this record declares no stage, so there is no terminal state to "
            "translate. An entry with no stage is not 'not attempted' -- that "
            "is itself a state, and claiming it here would be inventing the "
            "answer the record declines to give.")
    state = FROM_STAGE.get(text)
    if state is None:
        raise TerminalStateError(
            f"stage {text!r} has no entry in "
            f"umat_oti.abaqus.terminal_states.FROM_STAGE, so this contract "
            f"cannot say whether it is EXTERNAL -- a fact about somebody's "
            f"published repository -- or INTERNAL, a limitation of this "
            f"project. Refusing to translate it rather than defaulting: the "
            f"default was 'not_attempted', which is INTERNAL and asserts this "
            f"project never tried, and it said that about three entries that "
            f"ran. Add the stage to FROM_STAGE with its owner, and to "
            f"PUBLISHED_OWNERS, then re-run.")
    return TerminalState(state=state, owner=owner_of(state),
                         reason=str(reason or ""), stage=text)


def from_record(record: Mapping[str, Any]) -> TerminalState:
    """Terminal state out of a store-verification row or a contract record."""
    block = record.get("terminal")
    if isinstance(block, Mapping):
        state = str(block.get("state") or "")
        declared = str(block.get("owner") or "")
        actual = owner_of(state)          # refuses a state in neither table
        if declared and declared != actual:
            raise TerminalStateError(
                f"this record says terminal state {state!r} is owned by "
                f"{declared}, but the vocabulary says {actual}. An internal "
                f"limitation transmitted as an external blocker claims "
                f"somebody else's file is at fault for this project's gap; "
                f"the reverse hides work behind a published-source excuse. "
                f"Neither is carried.")
        return TerminalState(state=state, owner=actual,
                             reason=str(block.get("reason") or ""),
                             stage=str(block.get("stage") or ""))
    return translate_stage(record.get("stage"), record.get("reason") or "")


def known_states() -> dict:
    """The vocabulary with owners, for a consumer that wants to switch on it.

    The union of what this checkout has and what the contract publishes, so a
    consumer gets the whole enum rather than however much of it the producing
    checkout happens to be up to date with.
    """
    return {state: owner_of(state)
            for state in sorted(set(ALL) | set(PUBLISHED_OWNERS))}


#: Sanity: the imported vocabulary must partition into the three owners.
assert set(ALL) == {FULLY_VERIFIED, WAITS_FOR_INPUT} | set(EXTERNAL) | set(INTERNAL)
