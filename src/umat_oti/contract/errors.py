"""The error envelope: how one side tells the other that something is wrong.

An error that crosses the boundary has to answer three questions the exception
text alone does not:

**Whose problem is it?** The same ``owner`` vocabulary as a terminal state --
EXTERNAL for a fact about somebody's published repository, INTERNAL for a
limitation of this project, and a third, ``CONTRACT``, for the boundary itself
being wrong: a version mismatch, a schema violation, a field this reader has
never heard of. Keeping CONTRACT apart matters because it is the only one of
the three that is fixed by changing this file rather than by changing a
pipeline or waiting on an upstream author.

**Is this terminal?** A terminal error is an answer. A non-terminal one is a
step that failed and may be retried or worked around. Reporting a retryable
failure as a terminal state inflates the corpus's count of finished entries.

**What is still true?** An error does not erase the gates that were measured
before it. ``established`` carries whatever three-state facts survive, so a
consumer is not forced to treat a late failure as though nothing had been
measured at all.

There is deliberately no ``message``-only form. A bare string cannot be
switched on, cannot be counted, and cannot be told apart from another error
with similar wording, which is how two different failures end up in one bucket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .identity import UmatIdentity
from .terminal import (EXTERNAL_OWNER, INTERNAL_OWNER, OWNERS, TerminalState,
                       VERIFIED_OWNER)

__all__ = ["ContractError", "CONTRACT_OWNER", "ERROR_OWNERS", "CODES",
           "error_dict"]

#: The boundary itself is wrong -- not the corpus, and not the pipeline.
CONTRACT_OWNER = "CONTRACT"

ERROR_OWNERS = (EXTERNAL_OWNER, INTERNAL_OWNER, CONTRACT_OWNER)

#: The closed set of error codes this contract version defines. Adding one is
#: a MINOR change *only* if consumers are documented as treating an unknown
#: code as CONTRACT/unknown rather than crashing; a consumer that switches on
#: this set exhaustively must pin the major version.
CODES: dict = {
    # -- CONTRACT: the boundary --------------------------------------------
    "contract.version_mismatch":
        "the two ends declare incompatible contract versions",
    "contract.schema_violation":
        "a record does not validate against the schema for its version",
    "contract.untranslatable_stage":
        "a run rung with no entry in terminal_states.FROM_STAGE, so its owner "
        "is unknown and defaulting it would assert one",
    "contract.identity_not_unique":
        "an identity that cannot distinguish one source from another, such as "
        "a bare basename",
    "contract.null_read_as_pass":
        "a three-state field was consumed as a two-state one",
    "contract.fixture_fingerprint_mismatch":
        "a fixture frozen at a transform fingerprint other than the store's",
    "contract.provenance_missing":
        "a material constant carried with no record of where it was read",
    # -- EXTERNAL: somebody's published repository -------------------------
    "external.no_material_data":
        "no deck in the publishing repository declares this routine's constants",
    "external.not_a_umat":
        "the file's Abaqus entry point is not a UMAT",
    "external.source_incomplete":
        "the source does not compile as published, or a module it needs was "
        "never published beside it",
    "external.published_stub":
        "the author published the interface and no constitutive content",
    "external.waits_for_input":
        "the source blocks on terminal input, so a job holds a licence until "
        "its timeout",
    "internal.arguments_diverged_before_the_routine":
        "the paired call was isolated and its INPUTS already differed before "
        "the routine was entered. The solver computed those inputs from each "
        "build's own earlier outputs on this project's deck, so where the two "
        "paths parted is this project's to find",
    # -- INTERNAL: this project --------------------------------------------
    "internal.transform_refused":
        "this project's transform could not convert the source",
    "internal.experiment_not_generated":
        "no verification experiment could be built for this formulation",
    "internal.job_failed": "an Abaqus job this project generated did not run",
    "internal.derivative_not_verified":
        "the generated derivative was not checked, or did not agree",
    "internal.disagreement_not_in_any_recorded_call":
        "the two histories differ and no call this project recorded accounts "
        "for the difference, which is a gap in what was recorded rather than "
        "a fact about the source",
    "internal.harness_error":
        "this project's harness failed for a reason that is not about the "
        "source",
}


@dataclass(frozen=True)
class ContractError:
    """One machine-readable failure crossing the boundary."""

    code: str
    owner: str
    message: str
    terminal: bool = False
    identity: Optional[UmatIdentity] = None
    #: Three-state facts that survived the failure, as raw JSON values.
    established: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)
    contract_version: str = ""

    def __post_init__(self) -> None:
        if self.owner not in ERROR_OWNERS:
            raise ValueError(
                f"error owner {self.owner!r} is not one of "
                f"{', '.join(ERROR_OWNERS)}. An error with no owner cannot be "
                f"routed: EXTERNAL waits on an upstream author, INTERNAL is "
                f"work here, CONTRACT is this boundary being wrong.")
        if not str(self.message).strip():
            raise ValueError(
                f"{self.code}: an error crossing the boundary needs a message "
                f"a person can act on, not only a code.")
        prefix = self.code.split(".", 1)[0] if "." in self.code else ""
        expected = {"contract": CONTRACT_OWNER, "external": EXTERNAL_OWNER,
                    "internal": INTERNAL_OWNER}.get(prefix)
        if expected and expected != self.owner:
            raise ValueError(
                f"error code {self.code!r} is namespaced {prefix!r} but is "
                f"declared owned by {self.owner}. An internal limitation "
                f"transmitted as an external blocker claims somebody else's "
                f"file is at fault for this project's gap; the reverse hides "
                f"work behind a published-source excuse.")

    @classmethod
    def from_terminal(cls, state: TerminalState, identity=None) -> "ContractError":
        """An error envelope for an entry that ended somewhere other than verified."""
        if state.owner == VERIFIED_OWNER:
            raise ValueError(
                "fully_verified is not an error. Building an error envelope "
                "around it would put a verified entry into a failure count.")
        code = ("external.no_material_data" if state.state == "missing_material_data"
                else "external.not_a_umat" if state.state == "not_a_umat"
                else "external.source_incomplete"
                if state.state in ("incomplete_or_corrupt_source",
                                   "external_dependency_unavailable")
                else "external.published_stub"
                if state.state == "published_stub_no_constitutive_content"
                else "external.waits_for_input" if state.state == "waits_for_input"
                else "internal.arguments_diverged_before_the_routine"
                if state.state == "arguments_diverged_before_the_routine"
                else "internal.disagreement_not_in_any_recorded_call"
                if state.state == "disagreement_not_in_any_recorded_call"
                else "internal.derivative_not_verified"
                if state.state in ("tangent_not_verified", "derivative_truncated")
                else "internal.job_failed"
                if state.state in ("original_job_failed", "transformed_job_failed",
                                   "support_build_failed")
                else "internal.harness_error" if state.state == "harness_error"
                else "internal.experiment_not_generated"
                if state.state in ("experiment_not_generated",
                                   "experiment_not_informative",
                                   "informativeness_not_established",
                                   "unsupported_formulation")
                else "internal.transform_refused")
        return cls(code=code, owner=state.owner,
                   message=state.reason or f"terminal state {state.state}",
                   terminal=state.finished, identity=identity,
                   detail={"terminal_state": state.state,
                           "stage": state.stage})

    def as_dict(self) -> dict:
        return {"code": self.code, "owner": self.owner,
                "message": self.message, "terminal": self.terminal,
                "identity": self.identity.as_dict() if self.identity else None,
                "established": dict(self.established),
                "detail": dict(self.detail),
                "contract_version": self.contract_version}


def error_dict(code: str, message: str, *, owner: Optional[str] = None,
               terminal: bool = False, **detail: Any) -> dict:
    """Shorthand for producing a conforming error object."""
    if owner is None:
        prefix = code.split(".", 1)[0]
        owner = {"contract": CONTRACT_OWNER, "external": EXTERNAL_OWNER,
                 "internal": INTERNAL_OWNER}.get(prefix, CONTRACT_OWNER)
    return ContractError(code=code, owner=owner, message=message,
                         terminal=terminal, detail=detail).as_dict()


assert set(OWNERS) - {VERIFIED_OWNER} <= set(ERROR_OWNERS)
