"""What every state of this pipeline is called when an engineer reads it.

A non-expert has to be able to finish the workflow this project exists for
without learning the pipeline's own vocabulary. ``primal_disagreed`` is a
precise name for a rung of a ladder and it is not an answer to "what happened
to my UMAT?". This module is the one place that translation lives, so the
interface cannot grow a second one.

Three separate jobs, kept separate on purpose:

**What state an entry is in, in plain words.** :func:`plain_status`. It carries
the batch's own terminal state unedited beside the plain sentence, because a
verdict rendered differently here than in the evidence is a second opinion
nobody can cite.

**Whether the word "verified" may appear.** :func:`may_say_verified`. One
function, one rule, and no caller is allowed its own: the word appears only
where all six gates were measured and all six read true. Everything else is a
result, some of them good results, and none of them is that word.

**What a reader is told when something failed.** :class:`Failure`. Five fields
and every one of them is required, because the failure messages this project
shipped before this module said what stage a thing stopped at and left the
reader to work out the rest. A traceback is never the message; it is kept, in
full, under :attr:`Failure.full_log`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

from umat_oti.abaqus.terminal_states import (ALL, EXTERNAL, FULLY_VERIFIED,
                                             INTERNAL, Verdict, from_stage,
                                             kind_of)
from umat_oti.app.corpus_view import (EVIDENCE_GATES, NOT_ESTABLISHED,
                                      gate_tally, three_state)

__all__ = [
    "STAGE_OVERRIDES", "PLAIN", "EXPERT_TERMS", "PlainStatus", "Failure",
    "plain_status", "may_say_verified", "verified_summary", "failure_for",
    "unmapped_stages", "owner_phrase", "plain_sentence", "PLAIN_PHRASES",
    "question_for", "REQUEST_OF_USER",
]


# ---------------------------------------------------------------------------
# stages the shared taxonomy does not map yet
# ---------------------------------------------------------------------------
#: Stages the batch writes that :mod:`umat_oti.abaqus.terminal_states` has no
#: entry for, with the state and ownership they should carry.
#:
#: This table exists because ``from_stage`` has a DEFAULT, and a default is
#: how a new stage becomes a silent lie. ``arguments_diverged_before_the_
#: routine`` is in pass11 three times; unmapped it falls through to
#: ``not_attempted``, which reads "this run did not reach it" over three
#: entries that ran and diverged, and which ``kind_of`` books as INTERNAL --
#: putting an external fact about somebody's file into this project's own
#: failure column. Both halves of that are wrong and neither is visible.
#:
#: The right fix is in ``terminal_states``. This module does not own that
#: file, so it overrides here and :func:`unmapped_stages` keeps the gap
#: visible until the shared table catches up.
STAGE_OVERRIDES: dict[str, tuple[str, str]] = {
    # The two builds were handed different arguments. Whatever happened
    # happened before either routine was entered, so it is not a difference
    # between the routines: it is a property of what drove them.
    "arguments_diverged_before_the_routine":
        ("arguments_diverged_before_the_routine", "external"),
    # The histories differ and no recorded call accounts for the difference.
    # Ours: the instrumentation did not capture the call that did it.
    "disagreement_not_in_any_recorded_call":
        ("disagreement_not_in_any_recorded_call", "internal"),
}


def _verdict(stage: str, reason: str = "") -> Verdict:
    """The terminal verdict for a stage, with the shared table winning.

    The shared table in :mod:`umat_oti.abaqus.terminal_states` is asked first
    and is authoritative: :data:`STAGE_OVERRIDES` is a bridge over a gap in
    it, not a second opinion about a stage it already maps. Once the shared
    table carries a stage, this function stops consulting the override for it
    and the two cannot drift.

    Never falls through to a default. A stage neither table knows gets
    ``harness_error`` and says so in its reason, because an unknown stage
    rendered as ``not_attempted`` is a claim that nothing ran -- and that
    claim, made silently over three pass11 entries that ran and diverged, is
    the defect this function was written for.

    Tolerant of both shapes of ``from_stage``: the one that defaults and the
    one that raises on an untranslated stage. The interface must not fall over
    because the taxonomy got stricter underneath it.
    """
    stage = str(stage or "")
    from umat_oti.abaqus.terminal_states import FROM_STAGE
    if not stage or stage in FROM_STAGE:
        try:
            return from_stage(stage, reason)
        except Exception:                          # pragma: no cover
            pass
    if stage in STAGE_OVERRIDES:
        state, kind = STAGE_OVERRIDES[stage]
        return Verdict(state=state, kind=kind, reason=reason)
    return Verdict(
        state="harness_error", kind="internal",
        reason=(f"this interface has no translation for the stage "
                f"{stage!r}, so it will not guess one. " + reason).strip())


def unmapped_stages(stages) -> list:
    """Stages with no entry in the shared table and no override here.

    A run whose stages are all mapped returns an empty list. Anything in it is
    a state some part of this pipeline can reach and no part of the interface
    can name, which is the one situation where showing nothing is safer than
    showing a default.
    """
    from umat_oti.abaqus.terminal_states import FROM_STAGE
    return sorted({str(s) for s in stages
                   if str(s) and str(s) not in FROM_STAGE
                   and str(s) not in STAGE_OVERRIDES})


# ---------------------------------------------------------------------------
# every terminal state, in words an engineer who has never read this code uses
# ---------------------------------------------------------------------------
#: Per terminal state: the headline, what it means, whose move it is, what the
#: user has to provide if the move is theirs, and whether pressing the button
#: again could plausibly change the answer.
#:
#: ``whose move`` has three values and they are not interchangeable. "you" is
#: something the person at the screen can supply. "the author of this UMAT" is
#: a fact about a published file that nobody here can change. "this program"
#: is our work, and saying "you" over one of those would send a user hunting
#: for a file that does not exist.
PLAIN: dict[str, dict[str, Any]] = {
    FULLY_VERIFIED: {
        "headline": "Verified",
        "means": "Both versions of your material ran, they computed the same "
                 "stresses all the way through, and the converted version's "
                 "derivatives matched a numerical check.",
        "whose move": "nobody",
        "provide": "",
        "retry": False,
    },
    "missing_material_data": {
        "headline": "Material constants are missing",
        "means": "This program could not find the numbers your material needs "
                 "-- the stiffness, the yield strength, and so on. Nobody "
                 "published them next to the source file.",
        "whose move": "you",
        "provide": "The material constants, either by typing them in or by "
                   "pointing at an input file that contains them.",
        "retry": False,
    },
    "not_a_umat": {
        "headline": "This file is not a material subroutine",
        "means": "The file's entry point is a different kind of Abaqus "
                 "subroutine, so there is no material behaviour here to "
                 "convert.",
        "whose move": "the author of this UMAT",
        "provide": "",
        "retry": False,
    },
    "published_stub_no_constitutive_content": {
        "headline": "This file is a template, not a material",
        "means": "The file has the right shape for a material subroutine and "
                 "no material in it -- it never sets a stress and never sets "
                 "a stiffness. It is a starting point somebody published for "
                 "others to fill in.",
        "whose move": "the author of this UMAT",
        "provide": "",
        "retry": False,
    },
    "incomplete_or_corrupt_source": {
        "headline": "The file does not build as published",
        "means": "The source will not compile the way its author published "
                 "it, so there is nothing to run and nothing to compare "
                 "against.",
        "whose move": "the author of this UMAT",
        "provide": "",
        "retry": False,
    },
    "external_dependency_unavailable": {
        "headline": "A file it needs was never published with it",
        "means": "The source refers to another file -- a module or an include "
                 "-- that is not in what was published, so it cannot be "
                 "built.",
        "whose move": "you",
        "provide": "The missing companion file, if you have it.",
        "retry": True,
    },
    "arguments_diverged_before_the_routine": {
        "headline": "The two runs were not given the same starting point",
        "means": "The original and the converted version were handed different "
                 "inputs, so they were never asked the same question. "
                 "Whatever differs happened before either version of your "
                 "material was reached.",
        "whose move": "the author of this UMAT",
        "provide": "",
        "retry": False,
    },
    "waits_for_input": {
        "headline": "The source stops and waits for someone to type",
        "means": "The file contains a statement that pauses for keyboard "
                 "input. In a solver there is nobody to type, so the run "
                 "holds until it is cut off.",
        "whose move": "the author of this UMAT",
        "provide": "",
        "retry": False,
    },
    "unsupported_formulation": {
        "headline": "This program cannot drive this kind of material yet",
        "means": "Your material needs a kind of test this program does not "
                 "know how to set up.",
        "whose move": "this program",
        "provide": "",
        "retry": False,
    },
    "experiment_not_generated": {
        "headline": "This program could not build a test for it",
        "means": "No test this program knows how to build will make this "
                 "material do anything.",
        "whose move": "this program",
        "provide": "",
        "retry": False,
    },
    "experiment_not_informative": {
        "headline": "The material did nothing during the test",
        "means": "Both versions ran and both agreed, but the material sat "
                 "still the whole time. Two versions agreeing about a "
                 "material that did nothing is agreement about the part every "
                 "version gets right, so it does not tell you the conversion "
                 "is correct.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
    "informativeness_not_established": {
        "headline": "Nobody measured whether the material did anything",
        "means": "The two versions agreed, and whether the material actually "
                 "did anything during the test was never checked. That is not "
                 "the same as knowing that it did.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
    "support_build_failed": {
        "headline": "This program's own support files did not build",
        "means": "The extra code this program adds alongside your material "
                 "failed to compile. That is this program's code, not yours.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
    "original_job_failed": {
        "headline": "The original version did not finish its run",
        "means": "Your material, unchanged, did not run to the end of the "
                 "test. Until it does there is nothing to compare a "
                 "conversion against.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
    "transformed_job_failed": {
        "headline": "The converted version did not finish its run",
        "means": "The original ran and the converted version did not, so the "
                 "conversion changed something it should not have.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
    "primal_disagreed": {
        "headline": "The two versions computed different stresses",
        "means": "The original and the converted version were given the same "
                 "test and did not return the same answer. Converting a "
                 "material must not change what it computes, so this is a "
                 "problem with the conversion.",
        "whose move": "this program",
        "provide": "",
        "retry": False,
    },
    "disagreement_not_in_any_recorded_call": {
        "headline": "The two versions differ and this program cannot say where",
        "means": "The results differ, and none of the individual calls this "
                 "program watched accounts for the difference. The difference "
                 "is real; the explanation for it is missing.",
        "whose move": "this program",
        "provide": "",
        "retry": False,
    },
    "derivative_truncated": {
        "headline": "The conversion drops part of the derivative",
        "means": "On the way to the stress, the converted source throws away "
                 "derivative information and then keeps using the result. The "
                 "stress is still right; the derivatives are short by whatever "
                 "was thrown away.",
        "whose move": "this program",
        "provide": "",
        "retry": False,
    },
    "tangent_not_verified": {
        "headline": "The derivative check did not settle",
        "means": "The numerical check this program compares derivatives "
                 "against did not converge, so it cannot confirm or deny that "
                 "the derivatives are right.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
    "not_attempted": {
        "headline": "Not started",
        "means": "This material has not been run. Nothing about it has "
                 "passed and nothing about it has failed.",
        "whose move": "you",
        "provide": "Press Transform and Verify to run it.",
        "retry": True,
    },
    "harness_error": {
        "headline": "This program broke, not your material",
        "means": "Something went wrong inside this program while it was "
                 "working on your material. Nothing here is a finding about "
                 "the material itself.",
        "whose move": "this program",
        "provide": "",
        "retry": True,
    },
}


#: Words a default screen must not use. Each is either Abaqus vocabulary, a
#: numerical-methods term, or an internal stage name, and the brief for this
#: interface is that a user completes the workflow without any of them. They
#: stay legal inside the Advanced and Evidence panels, which is why this is a
#: list a test checks the DEFAULT text against rather than a filter applied to
#: everything.
#: Abaqus vocabulary, numerical-methods terms and file-format detail. Each is
#: a thing the brief says a user must be able to finish the workflow without
#: understanding.
_JARGON: tuple[str, ...] = (
    "NDI", "NSHR", "NTENS", "NSTATV", "DDSDDE", "STATEV", "DFGRD", "PNEWDT",
    "Voigt", "voigt", "perturbation", "finite difference", "FD step",
    "Jacobian", "jacobian", "manifest", "JSON", "json",
    "gfortran", "-fdefault-real-8", "compiler flag", "fixed form",
    # Abaqus's own files. ".for" and ".f90" are deliberately absent: they are
    # the extensions on the user's OWN source file, and a picker that would
    # not show somebody the name of the file they just added is not protecting
    # them from anything.
    "job directory", "work_dir", "results_dir", ".inp", ".odb", ".sta",
    ".msg", ".dat",
    # Two words this pipeline uses as terms of art. "primal" is not English to
    # anybody outside it, and "tangent" here means the consistent tangent
    # stiffness rather than a line touching a curve.
    "primal", "tangent",
)


def _stage_names() -> tuple:
    """Every internal rung name, so none of them can reach a default screen.

    Read from the shared table rather than listed, so that a rung added to the
    pipeline tomorrow is forbidden on a default screen today without anybody
    remembering to add it here. The English words "stage" and "state" are
    deliberately NOT in this list: "reached the last stage" is a sentence a
    non-expert reads without difficulty, and banning the word would push the
    interface into worse English for no gain. What must not appear is
    ``primal_disagreed``, and that is what this returns.
    """
    from umat_oti.abaqus.terminal_states import ALL, FROM_STAGE
    names = set(FROM_STAGE) | set(ALL) | set(STAGE_OVERRIDES)
    return tuple(sorted(n for n in names if n and "_" in n))


#: Words a default screen must not use: the jargon above, plus every internal
#: rung name. They stay legal inside the Advanced and Evidence panels, which is
#: why this is a list a test checks the DEFAULT text against rather than a
#: filter applied to everything.
EXPERT_TERMS: tuple[str, ...] = _JARGON + _stage_names()


#: Phrases the pipeline writes into reasons and requirement details, and what
#: each one is in plain words. Applied by :func:`plain_sentence` to text that
#: reaches a DEFAULT screen; the original wording is always still available
#: under Evidence, because the pipeline's sentence is the citable one.
#:
#: Longest first when applied, so that ".inp file" becomes "Abaqus input file"
#: rather than "Abaqus input filefile".
PLAIN_PHRASES: tuple[tuple[str, str], ...] = (
    (".inp file", "Abaqus input file"),
    ("an .inp", "an Abaqus input"),
    (".inp", "Abaqus input file"),
    (".odb", "Abaqus results file"),
    ("a material block", "a section listing the material constants"),
    ("material block", "section listing the material constants"),
    ("*MATERIAL", "the material definition"),
    ("*DEPVAR", "the number of internal variables"),
    ("this routine", "this material subroutine"),
    ("DDSDDE", "the stiffness this subroutine returns"),
    ("STATEV", "the subroutine's internal variables"),
    ("NTENS", "the number of stress components"),
    ("props", "material constants"),
    ("PROPS", "material constants"),
)


def plain_sentence(text: str) -> str:
    """One sentence from the pipeline, with its jargon replaced.

    This does NOT paraphrase and does not shorten: the pipeline's reasons are
    evidence and rewriting their substance would put a second account of a
    finding on the page. It replaces named terms with what they are, and
    nothing else.

    Where a term has no plain equivalent the sentence is left alone rather
    than mangled -- a half-translated sentence is harder to read than an
    untranslated one, and :func:`~umat_oti.app.unified_app.jargon_in` will
    keep reporting it until somebody adds the phrase here.
    """
    out = str(text or "")
    for term, plain in PLAIN_PHRASES:
        out = out.replace(term, plain)
    return out


#: Per requirement the run records, the question a USER can answer about it --
#: or ``None`` where there is no question for them, because the answer is not
#: theirs to give.
#:
#: This table is what makes "targeted questions only" true rather than
#: aspirational. The run records eight requirements per entry; on a typical
#: unfinished entry several are unmet, and at most one of them is something a
#: person at a screen can do anything about. Showing all of them as questions
#: is the same failure as showing a form of twenty correct fields to fix one:
#: the user cannot tell which one is theirs.
#:
#: ``ask`` is the question. ``supply`` is what they would provide. Where both
#: are ``None`` the requirement is reported as something this program is still
#: working out, under a heading that says so, and it is not a question.
REQUEST_OF_USER: dict[str, Optional[dict]] = {
    "published material constants": {
        "ask": "What are this material's constants?",
        "supply": "The numbers your material needs -- stiffness, yield "
                  "strength, and any others its author expected. You can type "
                  "them in, or point at an Abaqus input file that has them.",
    },
    "a paired deck": {
        "ask": "Which problem should this material be tested on?",
        "supply": "An Abaqus input file that uses this material, if you have "
                  "one. Without it this program builds its own test.",
    },
    "every companion source": {
        "ask": "Is there another source file that goes with this one?",
        "supply": "Any module or include file the subroutine needs that was "
                  "not published beside it.",
    },
    # The rest are not questions for a user. Naming them here, with None,
    # is deliberate: a requirement missing from this table is one nobody has
    # decided about, and that is different from one decided to be ours.
    "a UMAT interface": None,
    "a formulation this harness can drive": None,
    "a manifest with nothing missing": None,
    "an analysis finite from end to end": None,
    "an experiment the material did something in": None,
}


def question_for(name: str) -> Optional[dict]:
    """The question to put to a user about one requirement, if there is one.

    An unmet requirement with no entry in :data:`REQUEST_OF_USER` returns a
    question marked ``undecided`` rather than ``None``. The difference
    matters: ``None`` is "this program has decided that this is not yours to
    answer", and an absence is "nobody has decided". Silently treating the
    second as the first is how a requirement a user COULD have satisfied stops
    being asked about.
    """
    if name in REQUEST_OF_USER:
        entry = REQUEST_OF_USER[name]
        return dict(entry) if entry else None
    return {"ask": f"This program needs: {name}.",
            "supply": "", "undecided": True}


def owner_phrase(whose: str) -> str:
    """The sentence that tells a reader whether they can do anything."""
    return {
        "you": "There is something you can supply that would change this.",
        "the author of this UMAT":
            "This is a property of the file as it was published. Nothing you "
            "or this program can do here changes it.",
        "this program":
            "This is a limitation of this program, not of your material.",
        "nobody": "Nothing is outstanding.",
    }.get(whose, "")


# ---------------------------------------------------------------------------
# the one rule about the word "verified"
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _verification_service():
    """Agent 5's VerificationService where it is installed, else ``None``.

    Cached. A failed import is not free -- Python re-walks every entry on the
    path each time -- and this is consulted once per entry per screen, which
    over a 237-entry library is tens of thousands of lookups and turned a
    four-second test run into forty-seven.

    The architecture rule is that the interface calls the services and does
    not carry its own copy of a verification rule. Where the service is
    importable it decides; the reading below is what a front end falls back to
    in an environment that does not have it, and the two agree by
    construction because they are the same six gates read the same way.
    """
    try:
        from umat_oti.services.verification import (  # noqa: PLC0415
            VerificationService)
    except Exception:
        try:
            from umat_oti.services import VerificationService  # noqa: PLC0415
        except Exception:
            return None
    try:
        return VerificationService()
    except Exception:                              # pragma: no cover
        return None


def may_say_verified(record: Any) -> bool:
    """TRUE only where all six gates were measured and all six read true.

    The single gate on that word anywhere in the interface. It takes the raw
    record or an :class:`~umat_oti.app.corpus_view.EntryView`, and it does not
    look at ``stage`` at all -- on pass11, 55 entries stand at the stage
    ``verified`` and 42 of them satisfy this function. The other 13 have
    ``primal_agreed`` measured FALSE with a control recorded beside it that
    explains why. An explanation is a reason, and a reason is not a gate
    reading true.

    A missing ``evidence`` block and a ``null`` inside one are both
    not-established, and not-established is not a pass.

    Delegates to ``VerificationService.what_may_be_claimed`` where that
    service is installed. The fallback is the same six gates read the same
    way, and it is only ever reached in an environment without the service --
    but the delegation is what stops the two from drifting when a seventh
    gate is added there and not here.
    """
    service = _verification_service()
    if service is not None:
        raw = record if isinstance(record, dict) else _raw_of(record)
        if raw:
            try:
                claim = service.what_may_be_claimed(raw)
            except Exception:                      # pragma: no cover
                claim = None
            if isinstance(claim, dict) and "may_be_called_verified" in claim:
                return bool(claim["may_be_called_verified"])
            value = getattr(claim, "may_be_called_verified", None)
            if isinstance(value, bool):
                return value
    evidence = _evidence_of(record)
    return all(evidence.get(name) is True for name, _w, _r in EVIDENCE_GATES)


def _evidence_of(record: Any) -> dict:
    """The six-gate block out of a raw record or an EntryView."""
    if isinstance(record, dict):
        block = record.get("evidence")
        if isinstance(block, dict):
            return block
        # An EntryView serialised: ``evidence`` is the row list.
        if isinstance(block, list):
            return {r.get("field"): r.get("passed") for r in block
                    if isinstance(r, dict)}
        return {}
    rows = getattr(record, "evidence", None)
    if isinstance(rows, list):
        return {r.get("field"): r.get("passed") for r in rows
                if isinstance(r, dict)}
    return {}


def verified_summary(record: Any) -> dict:
    """The word, the gates behind it, and the explanation kept apart.

    Both facts the brief demands are here and neither can be rendered without
    the other: ``verified`` is the answer to "may this be called verified",
    and ``gates that did not hold`` is what stops it. An explanation, where the
    batch recorded one, travels in ``explained`` -- a separate key, so that no
    template can substitute it for a gate.
    """
    raw = record if isinstance(record, dict) else _raw_of(record)
    evidence = _evidence_of(record)
    tally = gate_tally({"evidence": evidence})
    verified = may_say_verified(record)

    gates = []
    for name, what, where in EVIDENCE_GATES:
        value = evidence.get(name)
        gates.append({
            "gate": name,
            "plain": GATE_PLAIN.get(name, name.replace("_", " ")),
            "holds": three_state(value),
            "established": value is not None,
            "passed": None if value is None else bool(value),
            "what it measures": what,
            "read from": where,
        })

    explained = ""
    primal = (raw.get("primal") or {}) if isinstance(raw, dict) else {}
    association = (raw.get("association_control") or {}) if isinstance(raw, dict) else {}
    if evidence.get("primal_agreed") is False:
        if primal.get("explained_by_operation_order") or association:
            own = primal.get("own_sensitivity")
            explained = (
                "The two versions differ, and this program measured how much "
                "the ORIGINAL differs from itself when the same arithmetic is "
                "done in a different but equally valid order"
                + (f" -- by {own:.3e}" if isinstance(own, (int, float)) else "")
                + ". The conversion is no further from the original than the "
                "original is from itself. That is a measured explanation and "
                "it is not the check passing.")
        elif primal.get("explained_by_declared_precision"):
            explained = (
                "The two versions differ, and this program measured the "
                "difference as the precision the author's own source "
                "declares. That is a measured explanation and it is not the "
                "check passing.")

    return {
        "verified": verified,
        "headline": "Verified" if verified else "Not verified",
        "gates": gates,
        "gates that hold": tally["held"],
        "gates that did not hold": tally["did not hold"],
        "gates never established": tally["never established"],
        "explained": explained,
        "why not": ("" if verified else _why_not(tally, evidence)),
    }


#: The six gates said in the words of somebody who has to act on them.
GATE_PLAIN: dict[str, str] = {
    "abaqus_job_completed": "the test ran to the end",
    "all_requested_outputs_present": "every step of the test reported results",
    "complete_history_finite": "every number in the results is a number",
    "primal_agreed": "both versions computed the same stresses",
    "derivatives_verified": "the derivatives matched a numerical check",
    "mechanically_informative": "the material actually did something",
}


def _why_not(tally: dict, evidence: dict) -> str:
    broke, unestablished = tally["did not hold"], tally["never established"]
    if len(unestablished) == len(EVIDENCE_GATES):
        return ("Nothing was measured. This material never reached a run any "
                "of the six checks could be made on, so none of them passed "
                "and none of them failed.")
    parts = []
    if broke:
        parts.append("these checks were measured and did not pass: "
                     + ", ".join(GATE_PLAIN.get(n, n) for n in broke))
    if unestablished:
        parts.append("these checks were never measured, which is not the same "
                     "as passing: "
                     + ", ".join(GATE_PLAIN.get(n, n) for n in unestablished))
    return "; ".join(parts).capitalize() + "."


def _raw_of(record: Any) -> dict:
    for name in ("raw", "record", "row"):
        value = getattr(record, name, None)
        if isinstance(value, dict):
            return value
    return {}


# ---------------------------------------------------------------------------
# one entry's state, in plain words
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlainStatus:
    """What state a material is in, for somebody who has not read this code."""

    headline: str
    means: str
    whose_move: str
    what_you_must_provide: str
    can_retry: bool
    verified: bool
    #: The batch's own words, carried unedited so the plain sentence can be
    #: checked against the evidence rather than trusted.
    terminal_state: str
    stage: str
    kind: str
    #: The qualification the six gates make necessary, empty where there is
    #: none. A headline of "Verified" with a non-empty qualifier is a bug and
    #: :func:`plain_status` never builds one.
    qualifier: str = ""
    #: The batch's own reason, verbatim. Belongs under Evidence, not on the
    #: headline.
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "headline": self.headline, "means": self.means,
            "whose move": self.whose_move,
            "what you must provide": self.what_you_must_provide,
            "can retry": self.can_retry, "verified": self.verified,
            "terminal state": self.terminal_state, "stage": self.stage,
            "kind": self.kind, "qualifier": self.qualifier,
            "reason": self.reason,
        }


def plain_status(record: Any) -> PlainStatus:
    """One entry's state in plain words, with the evidence's words beside it.

    The headline reads "Verified" only where :func:`may_say_verified` does. An
    entry the batch stopped at the stage ``verified`` whose ``primal_agreed``
    was measured false gets the plain sentence for what actually happened --
    the two versions computed different stresses -- and carries the batch's
    own ``verified`` stage in :attr:`PlainStatus.stage` so the two can be read
    against each other.
    """
    raw = record if isinstance(record, dict) else _raw_of(record)
    stage = str((raw.get("stage") if raw else None)
                or getattr(record, "stage", "") or "")
    reason = str((raw.get("reason") if raw else None)
                 or getattr(record, "reason", "") or "")
    verdict = _verdict(stage, reason)
    verified = may_say_verified(record)
    summary = verified_summary(record)

    state = verdict.state
    if state == FULLY_VERIFIED and not verified:
        # The batch reached its own last rung and the six gates do not all
        # hold. The plain sentence describes what the gates measured, never
        # the rung -- naming the rung here is how "verified" ends up on a
        # screen over an entry whose stresses disagreed.
        broke = summary["gates that did not hold"]
        state = _state_for_broken_gate(broke)

    entry = PLAIN.get(state) or PLAIN["harness_error"]
    qualifier = "" if verified else summary["why not"]
    return PlainStatus(
        headline=entry["headline"],
        means=entry["means"],
        whose_move=entry["whose move"],
        what_you_must_provide=entry["provide"],
        can_retry=bool(entry["retry"]),
        verified=verified,
        terminal_state=verdict.state,
        stage=stage,
        kind=verdict.kind,
        qualifier=qualifier,
        # The VERDICT's reason, not the raw one. Where a stage had no
        # translation, ``_verdict`` puts that fact at the front of it, and
        # carrying the raw reason here instead would throw away the only
        # notice anybody gets that the interface did not understand the state
        # it is rendering.
        reason=verdict.reason or reason,
    )


def _state_for_broken_gate(broken) -> str:
    """The state that describes a gate reading false, not the rung reached."""
    for gate, state in (("primal_agreed", "primal_disagreed"),
                        ("derivatives_verified", "tangent_not_verified"),
                        ("mechanically_informative",
                         "experiment_not_informative"),
                        ("complete_history_finite", "transformed_job_failed"),
                        ("all_requested_outputs_present",
                         "transformed_job_failed"),
                        ("abaqus_job_completed", "original_job_failed")):
        if gate in broken:
            return state
    return "informativeness_not_established"


# ---------------------------------------------------------------------------
# what a reader is told when something fails
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Failure:
    """A failure, said the way this project requires every failure to be said.

    Five fields, all required. The rule they encode is that a reader must
    never have to open a log to learn what went wrong -- the log is there, in
    :attr:`full_log`, and it is never the message.
    """

    #: What failed, in one sentence, in words the reader uses.
    what_failed: str
    #: Why this program believes that. The reasoning, not the symptom.
    why: str
    #: What was measured or read that supports it, and where it can be seen.
    evidence: list = field(default_factory=list)
    #: Whether pressing the same button again could plausibly change it.
    can_retry_automatically: bool = False
    #: What the person at the screen has to supply. Empty where the answer is
    #: not theirs to give -- and then :attr:`whose_move` says whose it is.
    what_you_must_provide: str = ""
    whose_move: str = "this program"
    #: Everything the run wrote. Expandable panel, never the message.
    full_log: str = ""

    def __post_init__(self) -> None:
        if not self.what_failed.strip():
            raise ValueError("a failure must say what failed")
        if not self.why.strip():
            raise ValueError("a failure must say why this program believes it")
        if self.what_you_must_provide.strip() and self.whose_move != "you":
            raise ValueError(
                "a failure that asks the user for something must say the move "
                "is theirs")

    def as_dict(self) -> dict:
        return {
            "what failed": self.what_failed,
            "why this program believes that": self.why,
            "the evidence for it": list(self.evidence),
            "can this be retried automatically": self.can_retry_automatically,
            "what you must provide": self.what_you_must_provide,
            "whose move": self.whose_move,
            "full log": self.full_log,
        }


def failure_for(record: Any, *, full_log: str = "") -> Optional[Failure]:
    """The failure for an entry, or ``None`` where there is nothing to report.

    ``None`` means exactly one thing: this entry may be called verified.
    Everything else -- including a state whose answer lies with the author of
    the file rather than with anybody here -- is something a reader is owed an
    account of, so it comes back as a :class:`Failure` with ``whose move``
    saying who can act.
    """
    if may_say_verified(record):
        return None
    status = plain_status(record)
    summary = verified_summary(record)
    raw = record if isinstance(record, dict) else _raw_of(record)

    evidence: list = []
    for gate in summary["gates"]:
        if gate["passed"] is False:
            evidence.append({
                "finding": gate["plain"],
                "result": "measured, and it did not pass",
                "where it was read": gate["read from"],
            })
        elif not gate["established"]:
            evidence.append({
                "finding": gate["plain"],
                "result": NOT_ESTABLISHED + " -- nobody measured this",
                "where it was read": gate["read from"],
            })
    if summary["explained"]:
        evidence.append({
            "finding": "a control this program ran afterwards",
            "result": summary["explained"],
            "where it was read": "primal / association_control / "
                                 "precision_control",
        })
    if status.reason:
        evidence.append({
            "finding": "what the run recorded, in its own words",
            "result": status.reason,
            "where it was read": "the run's record for this entry",
        })
    for requirement in (raw.get("refusals") or []) if isinstance(raw, dict) else []:
        if isinstance(requirement, dict) and requirement.get("reason"):
            evidence.append({"finding": "a requirement that was not met",
                             "result": str(requirement["reason"]),
                             "where it was read": "refusals"})

    return Failure(
        what_failed=status.headline,
        why=status.means,
        evidence=evidence,
        can_retry_automatically=status.can_retry and status.whose_move != "you",
        what_you_must_provide=(status.what_you_must_provide
                               if status.whose_move == "you" else ""),
        whose_move=status.whose_move,
        full_log=full_log,
    )
