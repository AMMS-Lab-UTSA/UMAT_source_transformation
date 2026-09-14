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
    #: The two builds' histories differ and the recorded CALLS say the
    #: arguments had already parted before the call whose outputs differ, so
    #: what the routine returned there is not attributable to the routine.
    #: External: about the experiment, not about the conversion.
    "arguments_diverged_before_the_routine",
    #: The author published the INTERFACE and no constitutive content: a file
    #: presenting the 37-argument UMAT header that assigns neither STRESS nor
    #: DDSDDE anywhere and makes no CALL at all. matmodlab2's umat_stub.f90 is
    #: 22 lines; the ufc-fem-kernel adapter is 55, and its body is one PRINT.
    #:
    #: External, and its own state rather than a borrowed one. It was sitting
    #: at transform_refused, which is INTERNAL and says this project could not
    #: convert a model -- there is no model. incomplete_or_corrupt_source was
    #: the near miss and is worse than nothing: it is glossed "does not
    #: compile", and a template compiles perfectly well.
    "published_stub_no_constitutive_content",
)

#: Unfinished, and ours. Named as precisely as the evidence allows, because
#: the cluster a failure belongs to is what decides which fix is worth making.
INTERNAL: tuple[str, ...] = (
    "transform_refused",
    "experiment_not_generated",
    "experiment_not_informative",
    "informativeness_not_established",
    "unsupported_formulation",
    "support_build_failed",
    "original_job_failed",
    "transformed_job_failed",
    "primal_disagreed",
    #: Every paired call in the probe record returned bit-identical outputs and
    #: the history comparison reported a difference anyway. Whatever those
    #: entries are, they are not evidence that a converted routine computes a
    #: different stress. Ours, and ours to explain.
    "disagreement_not_in_any_recorded_call",
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
    "experiment_not_generated": "experiment_not_generated",
    "published_stub_no_constitutive_content":
        "published_stub_no_constitutive_content",
    "experiment_not_informative": "experiment_not_informative",
    "informativeness_not_established": "informativeness_not_established",
    "support_build_failed": "support_build_failed",
    "original_job_failed": "original_job_failed",
    "transformed_job_failed": "transformed_job_failed",
    "both_builds_non_finite": "primal_disagreed",
    "primal_disagreed": "primal_disagreed",
    "arguments_diverged_before_the_routine":
        "arguments_diverged_before_the_routine",
    "disagreement_not_in_any_recorded_call":
        "disagreement_not_in_any_recorded_call",
    "published_stub_no_constitutive_content":
        "published_stub_no_constitutive_content",
    "derivative_truncated": "derivative_truncated",
    "tangent_not_verified": "tangent_not_verified",
    "harness_error": "harness_error",
}


#: What each state MEANS, in one line, in plain language.
#:
#: Here rather than on the page, because the meaning of a terminal state is a
#: property of the state and not of whatever is rendering it. It used to live
#: in the GUI package and the corpus registry imported it from there, so a
#: report's vocabulary depended on a display module -- and adding a state was
#: possible without giving it a meaning at all, which is how three new rungs
#: reached a results file with no words attached.
MEANING: dict[str, str] = {
    FULLY_VERIFIED: "both builds ran, agreed over the whole history, and the "
                    "tangent matched a converged difference",
    "arguments_diverged_before_the_routine":
        "the two runs were handed different arguments before the call whose "
        "answers differ, so the difference is not the routine's",
    "disagreement_not_in_any_recorded_call":
        "every call we recorded returned the same answer in both builds, and "
        "the comparison reported a difference anyway -- ours to explain",
    "published_stub_no_constitutive_content":
        "the author published the interface and no material model: it assigns "
        "no stress, no tangent, and calls nothing",
}


def meaning_of(state: str) -> str:
    """The one-line gloss for a state, or "" where none is written yet."""
    return MEANING.get(str(state or ""), "")


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


class UntranslatedStage(KeyError):
    """A batch rung this vocabulary has no word for."""


def from_stage(stage: str, reason: str = "") -> Verdict:
    """The corpus verdict for a batch rung, with the batch's own reason kept.

    An unknown stage RAISES. It used to fall through to ``not_attempted``,
    which is internal and means "this run did not reach it", and that silent
    default did real damage the moment two new rungs were added: three entries
    that ran and whose ARGUMENTS diverged -- an external fact -- were reported
    as runs that never happened, booked into this project's own column. A
    default that quietly invents a verdict for a stage nobody mapped will do
    that again for the next rung, so it is gone.

    An EMPTY stage still answers ``not_attempted``, because that is what an
    entry with no rung recorded actually is.
    """
    name = str(stage or "")
    if not name:
        return Verdict(state="not_attempted", kind=kind_of("not_attempted"),
                       reason=reason)
    try:
        state = FROM_STAGE[name]
    except KeyError:
        raise UntranslatedStage(
            f"{name!r} is a verification stage this vocabulary has no word "
            f"for. Add it to FROM_STAGE and to EXTERNAL or INTERNAL, deciding "
            f"deliberately whose problem it is -- when unsure, internal. It "
            f"must not default: the default was 'not_attempted', which says a "
            f"run never happened and files it as ours.") from None
    return Verdict(state=state, kind=kind_of(state), reason=reason)


def from_transform_failure(reason: str, compiles: bool | None = None,
                           companions_missing: bool = False,
                           is_umat: bool | None = None) -> Verdict:
    """The verdict for a source the transform refused.

    A transform refusal is ours -- unless the file it refused is one nobody
    could have transformed. A source that does not compile as its author
    published it, and a source whose companion module was never published
    beside it, are external whatever the transformer says about them, and the
    compile check is what tells those apart from a gap in the transformer.

    And a file whose Abaqus entry point is not a UMAT is not a UMAT whatever
    stage it stopped at. Three UEL sources began failing a semantic check
    when the constancy analysis stopped inferring dummy arguments constant;
    counting them as a gap in the transformer would have put an external
    fact about somebody's file into this pipeline's column. The direction of
    that error is the safe one -- it overstates our own failures rather than
    the corpus's completeness -- but it is still the wrong answer, and it
    costs a cluster that cannot be fixed because there is nothing wrong.
    """
    if is_umat is False:
        return Verdict("not_a_umat", "external", reason)
    if companions_missing:
        return Verdict("external_dependency_unavailable", "external", reason)
    if compiles is False:
        return Verdict("incomplete_or_corrupt_source", "external", reason)
    return Verdict("transform_refused", "internal", reason)
