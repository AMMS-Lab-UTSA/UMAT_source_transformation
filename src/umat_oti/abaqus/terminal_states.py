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
    #: The two builds' histories differ and the recorded CALLS say the
    #: arguments had already parted before the call whose outputs differ.
    #: Internal. It was filed EXTERNAL, as "about the experiment, not about the
    #: conversion" -- but the experiment is this project's deck, and in a
    #: paired run the arguments of a later call are computed by the solver from
    #: the outputs of the earlier calls of THAT build. All three entries that
    #: carry it parted at call 8 of increment 1, the first Newton iteration
    #: after seven calls whose returned tangent drove the update; one of them
    #: had DSTRAN(6) 1.03e-14 against 1.80e-14. Nothing about that is a fact
    #: about somebody's published repository, and filing it there removed
    #: three primal disagreements from this project's own column.
    "arguments_diverged_before_the_routine",
    #: The two builds disagree and a control measured WHY. Internal, and not
    #: verified: an explanation for a disagreement is not agreement. It lived
    #: briefly as an override that set the primal gate true, and thirteen
    #: entries carrying a false gate were counted as verified, promoted into
    #: the frozen baseline and offered to the Residual Assembler.
    "primal_mismatch_explained",
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
    "primal_mismatch_explained": "primal_mismatch_explained",
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
        "answers differ; the solver computed those arguments from each build's "
        "own earlier outputs, so where the paths parted is ours to find",
    "disagreement_not_in_any_recorded_call":
        "every call we recorded returned the same answer in both builds, and "
        "the comparison reported a difference anyway -- ours to explain",
    "published_stub_no_constitutive_content":
        "the author published the interface and no material model: it assigns "
        "no stress, no tangent, and calls nothing",
    "primal_mismatch_explained":
        "the two builds compute different stress and a control measured why -- "
        "which says where to look, and is not agreement",
}


def meaning_of(state: str) -> str:
    """The one-line gloss for a state, or "" where none is written yet."""
    return MEANING.get(str(state or ""), "")


#: Every gate a case must read TRUE on before it may be called verified,
#: promoted into the frozen baseline, or offered to the Residual Assembler.
ACCEPTANCE_GATES: tuple[str, ...] = (
    "abaqus_job_completed", "all_requested_outputs_present",
    "complete_history_finite", "primal_agreed", "derivatives_verified",
    "mechanically_informative")


def stage_supported_by_gates(row: dict) -> str:
    """A result row's stage, corrected where its own evidence contradicts it.

    ONE rule, used by the registry, promotion and the interface, so the three
    cannot disagree about what 'verified' means. A row may say ``verified``
    while its evidence block holds a gate reading false: thirteen did, because
    a control measured WHY the two builds differ and the harness read that
    explanation as agreement. An explanation for a disagreement is not
    agreement.

    Only an evidence block that CONTRADICTS the word demotes it. A row with no
    evidence block at all predates the gates, and demoting on an absence would
    rewrite every older row; currency checks are what catch those.
    """
    stage = str(row.get("stage") or "")
    if stage != "verified":
        return stage
    measured = row.get("evidence")
    if not measured:
        return stage
    failing = [gate for gate in ACCEPTANCE_GATES
               if measured.get(gate) is not True]
    if not failing:
        return stage
    if failing == ["primal_agreed"] and measured.get(
            "primal_difference_explained_by_a_measured_control") is True:
        return "primal_mismatch_explained"
    if "primal_agreed" in failing:
        return "primal_disagreed"
    if "derivatives_verified" in failing:
        return "tangent_not_verified"
    if "mechanically_informative" in failing:
        return "experiment_not_informative"
    return "primal_disagreed"


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
