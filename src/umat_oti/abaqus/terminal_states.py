"""What a corpus entry's final answer is, and whose problem it is.

A batch's ladder says how far an entry got. That is the right vocabulary for a
run and the wrong one for a corpus, because "primal_disagreed" answers "where
did it stop?" and a reader of a corpus is asking "is this finished, and if not,
whose move is it?".

Two kinds of unfinished, and conflating them is the failure this module exists
to prevent:

**External.** The answer lies in what somebody published. Nobody wrote down
what the material is made of; the file is not a UMAT; the source does not
compile; a module it needs was never published beside it. More engineering
here changes none of them, and each is a legitimate final answer with evidence.

**Internal.** The answer lies in this repository. The transform refused, the
deck generator had no element, the converted build dropped a derivative, the
finite difference could not resolve one. Every one of these is work, and
calling any of them a terminal state would be relabelling our own limitation
as somebody else's.

The counts are reported separately for that reason, and a completion figure
that pooled them would be a claim about the corpus made out of facts about the
pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The one state that means finished and verified.
FULLY_VERIFIED = "fully_verified"

#: Final answers whose cause is outside this repository.
EXTERNAL: tuple[str, ...] = (
    "missing_material_data",
    "not_a_umat",
    "incomplete_or_corrupt_source",
    "external_dependency_unavailable",
)

#: Unfinished, and ours. Named as precisely as the evidence allows, because
#: the cluster a failure belongs to is what decides which fix is worth making.
INTERNAL: tuple[str, ...] = (
    "transform_refused",
    "unsupported_formulation",
    "support_build_failed",
    "original_job_failed",
    "transformed_job_failed",
    "primal_disagreed",
    "derivative_truncated",
    "tangent_not_verified",
    "not_attempted",
    "harness_error",
)

#: A property of the source that stops a solver rather than failing it: a
#: Fortran PAUSE waits on terminal input, so the job holds a licence until its
#: timeout. External, because it is in the file somebody published.
WAITS_FOR_INPUT = "waits_for_input"

ALL: tuple[str, ...] = (FULLY_VERIFIED,) + EXTERNAL + (WAITS_FOR_INPUT,) + INTERNAL

#: How the verification batch's own rungs map onto this vocabulary. The batch
#: keeps its words in its own artefacts; this is the translation, in one place,
#: so the two cannot drift.
FROM_STAGE: dict[str, str] = {
    "verified": FULLY_VERIFIED,
    "not_a_umat": "not_a_umat",
    "incomplete_or_corrupt_source": "incomplete_or_corrupt_source",
    "external_dependency_unavailable": "external_dependency_unavailable",
    "needs_material_data": "missing_material_data",
    "waits_for_input": WAITS_FOR_INPUT,
    "manifest_refused": "unsupported_formulation",
    "support_build_failed": "support_build_failed",
    "original_job_failed": "original_job_failed",
    "transformed_job_failed": "transformed_job_failed",
    "both_builds_non_finite": "primal_disagreed",
    "primal_disagreed": "primal_disagreed",
    "derivative_truncated": "derivative_truncated",
    "tangent_not_verified": "tangent_not_verified",
    "harness_error": "harness_error",
}


@dataclass(frozen=True)
class Verdict:
    """One entry's final answer and who has to move next."""

    state: str
    kind: str          # "verified", "external" or "internal"
    reason: str = ""

    @property
    def finished(self) -> bool:
        return self.kind in ("verified", "external")

    def as_dict(self) -> dict:
        return {"terminal_state": self.state, "kind": self.kind,
                "finished": self.finished, "reason": self.reason}


def kind_of(state: str) -> str:
    if state == FULLY_VERIFIED:
        return "verified"
    if state in EXTERNAL or state == WAITS_FOR_INPUT:
        return "external"
    return "internal"


def from_stage(stage: str, reason: str = "") -> Verdict:
    """The corpus verdict for a batch rung, with the batch's own reason kept."""
    state = FROM_STAGE.get(str(stage or ""), "not_attempted")
    return Verdict(state=state, kind=kind_of(state), reason=reason)


def from_transform_failure(reason: str, compiles: bool | None = None,
                           companions_missing: bool = False) -> Verdict:
    """The verdict for a source the transform refused.

    A transform refusal is ours -- unless the file it refused is one nobody
    could have transformed. A source that does not compile as its author
    published it, and a source whose companion module was never published
    beside it, are external whatever the transformer says about them, and the
    compile check is what tells those apart from a gap in the transformer.
    """
    if companions_missing:
        return Verdict("external_dependency_unavailable", "external", reason)
    if compiles is False:
        return Verdict("incomplete_or_corrupt_source", "external", reason)
    return Verdict("transform_refused", "internal", reason)
