#!/usr/bin/env python3
"""Run every stored transform through Abaqus and record how far each one got.

The store holds transformed sources; it holds no evidence that any of them
computes what the original computed. Compiling is not verification -- it proves
the output is Fortran. This is the batch that earns the word for the store as a
whole: for each entry it drives the ORIGINAL source and the STORED TRANSFORMED
source through Abaqus over the same deck, checks their stress and state
histories agree, and only then checks the OTI tangent against a centred
difference taken from the original replayed offline, so the two sides of the
tangent comparison share no code path.

The ladder of outcomes is named, ordered, and reported per entry:

    needs_material_data  nobody has established what this model is made of
    manifest_refused     what is known about it is not enough to run it
    support_build_failed the transform's own modules did not compile
    original_job_failed  the untransformed source did not run
    transformed_job_failed  the transformed source did not run
    primal_disagreed     the two builds do not compute the same stress
    tangent_not_verified the difference could not pin the tangent down
    verified             every one of the above passed

A stage names how far an entry got, never why it stopped -- the reason is
recorded beside it in the entry's own words. Only an entry that reached the
last rung is called verified. Every entry attempted stays in the denominator,
including the ones with no material data: a model nobody can run is a result,
not a row to drop.

Three rules this file exists to keep:

*Constants are never invented.* They are read from the deck the source's own
author shipped, named per entry in ``material_provenance``. Of the 199
transformed sources in the corpus, 158 have a paired deck that yields
constants; the other 41 are ``needs_material_data`` and stay in the count. A
plausible elastic vector would have produced 199 jobs that all ran and 199
results about materials nobody described.

*Kinematics are read, not assumed.* The paired deck's ``*STEP`` says whether
the author ran the model with NLGEOM, and that is what the manifest says.
140 of those 158 decks set NLGEOM=YES, and on 18 of them the triage scan's
guess at the kinematics disagrees with the deck. A finite-strain model driven
as small strain is asked to differentiate a strain increment it never reads.

*The exit code is not the verdict.* Abaqus 2021 on this installation aborts in
its post-analysis wrap-up -- with no user subroutine at all -- after writing
that the analysis completed. The outcome comes from the records Abaqus wrote,
via ``classify_job``; the abort is preserved as a ``post_analysis_wrapup_failure``
warning and never as a failure. Reading the exit code instead would fail every
job in the store.

  tools/verify_store_in_abaqus.py --work-dir <scratch>
  tools/verify_store_in_abaqus.py --work-dir <scratch> --resume --json
  tools/verify_store_in_abaqus.py --work-dir <scratch> --only owner__name --limit 5

Sequential by default. See DEFAULT_JOBS.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from make_verification_manifest import choose_material, portable_source  # noqa: E402
from run_abaqus_verification import run_one                             # noqa: E402
from run_discovered_verification import _cache_relative_source          # noqa: E402
from run_discovery_triage import without_machine_paths                  # noqa: E402
from umat_oti.abaqus.compare import (align_by_time, compare_primal,   # noqa: E402
                                     compare_tangent)
from umat_oti.abaqus.deck import generate_deck                          # noqa: E402
from umat_oti.abaqus.activation import detect_activation                # noqa: E402
from umat_oti.abaqus.state_regime import (                              # noqa: E402
    SMOOTH_INELASTIC, classify as classify_regime, coverage,
    response_character)
from umat_oti.abaqus.amplitude_search import (                          # noqa: E402
    ACTIVATED, CEILING, LEFT_ITS_DOMAIN, LINEAR_TO_THE_CEILING,
    enough_to_drive, first_non_finite, search_amplitude)
from umat_oti.corpus.entry_routines import classify as classify_entry   # noqa: E402
from umat_oti.fortran.normalize import detect_source_form              # noqa: E402
from umat_oti.abaqus.elements import geometry_for as element_geometry   # noqa: E402
from umat_oti.abaqus.formulation import settle                          # noqa: E402
from umat_oti.abaqus import (call_isolation, frames,                    # noqa: E402
                             primal_signature, plausibility, safe_loading,
                             time_scale)
from umat_oti.abaqus.experiment import (                                # noqa: E402
    assess, plan as plan_experiment)
from umat_oti.abaqus.manifest import (                                  # noqa: E402
    LoadingSegment, NEEDS_MATERIAL_DATA, VerificationManifest, at_rate, hold,
    reverse, rotated as rotated_loading, simple_shear, uniaxial,
    under_body_force)
from umat_oti.abaqus.rate_search import (                               # noqa: E402
    HOLD_PERIODS, RATE_FACTOR, probe_time)
from umat_oti.abaqus.job_status import blocking_statements
from umat_oti.abaqus.probe import CORRUPT, converged_only, parse_probe           # noqa: E402
from umat_oti.abaqus.replay import (                                    # noqa: E402
    STATE_FILE, build_replay, difference_tangent, write_state)
from umat_oti.abaqus.truncation import analyse as analyse_truncation    # noqa: E402
from umat_oti.abaqus.support import (                                   # noqa: E402
    build_support, compile_order, install_support)
from umat_oti.store import TransformStore                               # noqa: E402

# ---------------------------------------------------------------------------
# the ladder
# ---------------------------------------------------------------------------

#: Every outcome an entry can be recorded as, in the order an entry passes
#: through them. The index in this tuple is how far the entry got; the last
#: The two builds' histories differ, and the recorded CALLS say the difference
#: did not start in the routine.
#:
#: EXTERNAL, about the experiment rather than the transform. The arguments the
#: two builds were handed had already parted before the call whose outputs
#: differ, so what the routine returned there is not attributable to the
#: routine. Sixteen of the sixty-two disagreements in pass10 are this, all at
#: call 8 and all in one family, and calling them "the two builds do not
#: compute the same stress" was a claim the evidence underneath did not carry.
ARGUMENTS_DIVERGED = "arguments_diverged_before_the_routine"

#: INTERNAL, and about this harness. Every paired call in the probe record
#: returned bit-identical outputs and the history comparison reported a
#: difference anyway. Twelve entries in pass10 are in this shape. Whatever
#: those twelve mean, they are not evidence that a converted routine computes a
#: different stress, and they must not be reported as though they were.
DISAGREEMENT_NOT_IN_ANY_CALL = "disagreement_not_in_any_recorded_call"

#: rung is the only one that may be called verified.
STAGES: tuple[str, ...] = (
    "needs_material_data",
    "waits_for_input",
    "manifest_refused",
    "both_builds_non_finite",
    "support_build_failed",
    "original_job_failed",
    "transformed_job_failed",
    "primal_disagreed",
    ARGUMENTS_DIVERGED,
    DISAGREEMENT_NOT_IN_ANY_CALL,
    "derivative_truncated",
    "tangent_not_verified",
    "verified",
)

VERIFIED = STAGES[-1]

#: A source carrying a Fortran PAUSE does not fail a solver, it hangs one:
#: Abaqus sits on a terminal read until the job's timeout elapses and the
#: licence is spent on nothing. 25 of the 199 stored transforms carry one. This
#: is a property of the source, not of the transform and not of this machine,
#: so it is a rung of the ladder and settled -- re-running it would hang again.
WAITS_FOR_INPUT = "waits_for_input"

#: A crash in this harness. Deliberately not one of STAGES: it is not a
#: statement about the model, it is a statement about the run, so --resume
#: re-runs it rather than serving it as a settled result.
HARNESS_ERROR = "harness_error"

#: Off the ladder, like a harness error and for the same reason: it is not a
#: statement about how far a UMAT got, because the file is not a UMAT. Its
#: Abaqus entry point is something else -- twenty-five corpus files present a
#: 36-argument SUBROUTINE UEL and keep a SUBROUTINE UMAT beside it as the
#: element's own constitutive kernel. Driven through a *USER MATERIAL deck,
#: Abaqus resolved the global symbol UMAT to that kernel, and the finite
#: difference then perturbed a deformation gradient it never reads. Those rows
#: were reported as UMAT tangent failures. Reported in its own column now, and
#: never inside a count of UMATs that verified or failed.
NOT_A_UMAT = "not_a_umat"

#: ON the ladder, and ours: the amplitude search established that the model
#: produces no numbers at any amplitude it can drive, so this harness has no
#: experiment the source will run. Not a failure of the model and not a
#: disagreement between the builds. Twenty-two entries were driven at the
#: fixed 0.005 probe AFTER the search had proved the domain does not reach
#: 8e-07, and came back as "both builds went non-finite" -- a sentence that
#: reads like a conversion problem and is a missing experiment. Every one of
#: them carries a SUBROUTINE DLOAD beside its UMAT and is driven by a body
#: force through a COMMON block, which a prescribed-displacement deck never
#: supplies.
NO_EXPERIMENT = "experiment_not_generated"

#: ON the ladder, and ours: both builds ran, agreed and matched a converged
#: difference -- over an experiment in which the material did not do what it
#: is for. Shortening a clock is a legitimate repair for a failure that moves
#: with the period AND a change to the mechanical problem: a growth law whose
#: stretch ramps in total time develops less of it in less of it. An
#: agreement reached near a material's initial state is an agreement about
#: the part every build gets right, so it is not a verification and must not
#: be counted as one.
NOT_INFORMATIVE = "experiment_not_informative"

#: ON the ladder, and ours: nobody established whether the experiment
#: exercised anything. Not the same as establishing that it did not, and not
#: a verdict either -- every other rung of this ladder reads "did this step
#: demonstrably pass", and an unmeasured answer is not a pass.
INFORMATIVENESS_NOT_ESTABLISHED = "informativeness_not_established"

#: Off the ladder for the same reason as NOT_A_UMAT: the file the author
#: published does not compile, and no amount of work here changes that. A job
#: whose compile aborts writes no .sta, no .msg and no .odb, which the ladder
#: read as ``original_job_failed`` -- a name that reads like this harness's
#: fault. It is not: it is measured by compiling the UNMODIFIED source with
#: Abaqus's own compile line, so nothing this pipeline adds is present when the
#: compiler rejects it.
INCOMPLETE_OR_CORRUPT_SOURCE = "incomplete_or_corrupt_source"

#: Also off the ladder, and also about the file rather than about this run: the
#: source compiles only against a module or an include that its repository did
#: not publish beside it, or that the acquisition did not bring along. Which of
#: those it is is recorded per entry, because they are different findings.
EXTERNAL_DEPENDENCY_UNAVAILABLE = "external_dependency_unavailable"

#: Verdicts that are settled without being rungs. Each says something about the
#: file that no further work here alters, and each is external: the answer lies
#: in what somebody published, not in this pipeline.
TERMINAL_OFF_LADDER: tuple[str, ...] = (
    NOT_A_UMAT, INCOMPLETE_OR_CORRUPT_SOURCE, EXTERNAL_DEPENDENCY_UNAVAILABLE)

#: One job at a time. The licence server here is shared with other users and
#: contended: two concurrent Abaqus jobs demand two sets of tokens at once, and
#: a job that cannot get them waits -- multi-minute waits have been measured on
#: this machine, which is dead time inside the per-job timeout rather than
#: throughput. A batch of hundreds is therefore faster and far more predictable
#: run one at a time. --jobs N exists for a machine whose licence pool is not
#: shared; it is not the default anywhere.
DEFAULT_JOBS = 1

#: How closely a centred difference has to match the OTI tangent. A centred
#: difference in doubles is limited to about eps**(2/3), roughly 4e-11
#: relative, at its very best step -- and a model with a state update or a
#: local Newton solve in it is far from that best, because the perturbed and
#: unperturbed runs can converge to slightly different iterates. 1e-6 leaves
#: room for that without accepting a tangent that is merely the right order of
#: magnitude. It is what the plateau, not the tolerance, is really doing the
#: work here: see tangent_verdict.
TANGENT_TOLERANCE = 1e-6

#: How many step sizes have to agree before the difference is believed. One
#: step cannot separate truncation error from cancellation: a single lucky
#: match is not convergence, a plateau is.
MINIMUM_PLATEAU = 2


def stage_rank(stage: str) -> int:
    """How far along the ladder a named outcome is. -1 for anything else."""
    return STAGES.index(stage) if stage in STAGES else -1


@dataclass(frozen=True)
class StageEvidence:
    """What was actually observed about one entry, in the order it was observed.

    Everything here is a fact read from a build or a comparison. Nothing is
    inferred, and every field defaults to the pessimistic answer, so a step
    that was never reached cannot be mistaken for a step that passed.
    """

    material_found: bool = False
    #: The source carries a statement that waits for terminal input, and the
    #: run hung on it. Recorded before anything else about the run, because
    #: nothing after it is a measurement.
    waits_for_input: bool = False
    manifest_refusals: tuple[str, ...] = ()
    #: None when the stored transform names no support units to build.
    support_ok: Optional[bool] = None
    original_completed: bool = False
    transformed_completed: bool = False
    #: None when the comparison never ran.
    primal_agrees: Optional[bool] = None
    #: What the recorded CALLS say about a disagreement the histories report.
    #: A verdict from :mod:`umat_oti.abaqus.call_isolation`, or "" when the
    #: probe records were not there to ask.
    call_isolation: str = ""
    #: The converted source takes the real part of a seed-carrying expression
    #: and uses the result. The stress is still right and every derivative
    #: computed through that point is short by whatever it contributed, so
    #: there is nothing here for a finite difference to confirm or deny.
    derivative_truncated: bool = False
    tangent_verified: Optional[bool] = None
    #: Did the experiment this verdict rests on exercise anything? A repair
    #: that made a history finite by removing the behaviour under test has
    #: not produced a verification OF that behaviour, and a run that agreed
    #: about a material sitting near its initial state agreed about the part
    #: every build gets right. Measured on the frozen run, not on a probe.
    mechanically_informative: Optional[bool] = None


def classify_stage(evidence: StageEvidence) -> str:
    """The furthest rung this entry reached.

    The check order is the ladder's order, and every test is written as "did
    this step demonstrably pass" rather than "did it demonstrably fail". A step
    whose result was never established is not a step that passed: a primal
    comparison that never ran leaves the entry at ``primal_disagreed``, whose
    accompanying reason then says it produced no records to compare. That reads
    pessimistically on purpose. The opposite convention is how a batch reports
    agreement it never measured.
    """
    if not evidence.material_found:
        return "needs_material_data"
    if evidence.waits_for_input:
        return WAITS_FOR_INPUT
    if evidence.manifest_refusals:
        return "manifest_refused"
    if evidence.support_ok is False:
        return "support_build_failed"
    if not evidence.original_completed:
        return "original_job_failed"
    if not evidence.transformed_completed:
        return "transformed_job_failed"
    if evidence.primal_agrees is not True:
        # "The two builds do not compute the same stress" is a claim about the
        # ROUTINE, and the recorded calls are what can support it. Where they
        # say the arguments had already parted, or that no call differed at
        # all, the claim is somebody else's or ours -- not the transform's.
        if evidence.call_isolation == call_isolation.INPUTS_ALREADY_DIVERGED:
            return ARGUMENTS_DIVERGED
        if evidence.call_isolation == call_isolation.NO_DIVERGENCE:
            return DISAGREEMENT_NOT_IN_ANY_CALL
        return "primal_disagreed"
    # Before the derivative work, not after it. There is no reason to spend a
    # replay ladder on an experiment that has not been shown to exercise the
    # behaviour whose derivative is in question.
    if evidence.mechanically_informative is False:
        return NOT_INFORMATIVE
    if evidence.derivative_truncated:
        return "derivative_truncated"
    if evidence.tangent_verified is not True:
        return "tangent_not_verified"
    if evidence.mechanically_informative is False:
        # Everything agreed, and about nothing. The two builds walked an
        # experiment in which the material did not do what it is for, so what
        # they agreed on is not evidence about the behaviour under test.
        return NOT_INFORMATIVE
    if evidence.mechanically_informative is None:
        # Not measured is not measured true. Every other rung here reads
        # "did this step demonstrably pass", and this one was written to read
        # "was it demonstrably refused" -- which let an unestablished answer
        # through to a verdict, the one convention this ladder exists to
        # avoid.
        return INFORMATIVENESS_NOT_ESTABLISHED
    return VERIFIED


# ---------------------------------------------------------------------------
# what the deck says
# ---------------------------------------------------------------------------

#: An Abaqus keyword line. Abaqus ignores case and internal spacing in
#: keywords, so "*STEP" and "*Step" and "* Step" are one keyword.
_KEYWORD_LINE = re.compile(r"^\s*\*(?!\*)\s*([^,]+)(.*)$")

#: NLGEOM on a *STEP line, with or without a value. Abaqus treats the bare
#: parameter as NLGEOM=YES, which is why the value group is optional here.
_NLGEOM = re.compile(r"\bNLGEOM\b\s*(?:=\s*([A-Za-z]+))?", re.IGNORECASE)


@dataclass(frozen=True)
class Kinematics:
    """What the deck says about finite strain, and where it says it."""

    kinematics: str
    provenance: str


def deck_kinematics(text: str, deck_name: str = "the deck") -> Kinematics:
    """Finite or small strain, read from the deck's own ``*STEP`` lines.

    Not guessed and not taken from the triage row. A model whose author ran it
    with NLGEOM=YES is handed DFGRD0 and DFGRD1 and may never look at DSTRAN at
    all; driving it as small strain asks it to differentiate something it does
    not read, and the difference check then measures nothing.

    A deck with no NLGEOM on any step is small strain because that is Abaqus's
    documented default for ``*STEP``, and the provenance says so -- reading a
    documented default off a file the author wrote is not the same as guessing.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("**"):
            continue
        match = _KEYWORD_LINE.match(line)
        if not match or "".join(match.group(1).split()).upper() != "STEP":
            continue
        found = _NLGEOM.search(match.group(2) or "")
        if found and (found.group(1) or "YES").upper() == "YES":
            return Kinematics("finite", f"{deck_name} line {number}: "
                                        f"{line.strip()[:100]}")
    return Kinematics("small strain",
                      f"no *STEP in {deck_name} sets NLGEOM, which is Abaqus's "
                      f"default of NLGEOM=NO")


@dataclass
class ExitVerdict:
    """What this run's exit code should be, and the sentences that justify it."""

    code: int
    lines: list


def required_entries(args, records: list) -> set:
    """Which source ids this run is obliged to carry to 'verified'.

    Three ways to say so, most explicit first: --require names them, a
    --baseline file names the ones that verified when it was promoted, and
    failing both, a regression requires nothing and only fails on entries
    that failed. That last case is deliberately weak -- a regression with no
    baseline cannot know what used to work -- and the run says so rather than
    quietly passing.
    """
    named = {piece.strip() for piece in str(getattr(args, "require", "") or "").split(",")
             if piece.strip()}
    if named:
        return named
    baseline = getattr(args, "baseline", None)
    if baseline:
        try:
            payload = json.loads(Path(baseline).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"--baseline could not be read: {exc}")
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        return {str(row.get("source")) for row in (entries or [])
                if row.get("stage") == VERIFIED and row.get("source")}
    return set()


def exit_verdict(mode: str, records: list, required: set) -> ExitVerdict:
    """The exit code, which is a claim and has to be earned.

    ``inventory`` always exits 0. It answers "where does everything stand?",
    and every stage in it -- including a failure -- is an answer. Reading its
    exit code as a verdict is the mistake this split exists to prevent: the
    tool used to return 0 unconditionally, after printing a summary in which
    most entries had failed.

    ``regression`` and ``qualification`` are gates. They exit non-zero when a
    required entry fails, is blocked before it could be judged, or is absent
    from the run altogether -- an entry that silently stopped being attempted
    is exactly the failure a regression exists to catch, and it leaves no
    failing row to notice. They also fail on an empty selection, because a
    filter that matches nothing produces a clean run that proves nothing.

    Missing Abaqus is not a pass. A blocked entry is a failure of the gate,
    not an exemption from it.
    """
    lines: list = []
    if not records:
        if mode == "inventory":
            return ExitVerdict(0, ["  inventory: no entries were selected"])
        return ExitVerdict(2, [
            "  FAIL: no entries were selected. A gate that runs nothing "
            "proves nothing, so an empty selection is a failure rather than "
            "a clean sheet."])

    by_source = {str(row.get("source")): row for row in records}
    if mode == "inventory":
        verified = sum(1 for row in records if row.get("stage") == VERIFIED)
        return ExitVerdict(0, [
            f"  inventory: {verified} of {len(records)} verified. This mode "
            f"always exits 0; its exit code is not a verdict."])

    if mode == "qualification":
        required = required or set(by_source)

    missing = sorted(name for name in required if name not in by_source)
    failed = sorted(name for name in required
                    if name in by_source and by_source[name].get("stage") != VERIFIED)
    if not required:
        lines.append(
            "  WARNING: this regression had no required set -- no --require, "
            "no --baseline -- so it could only fail on entries that ran and "
            "failed, and cannot tell that an entry stopped being attempted.")
    for name in missing:
        lines.append(f"  FAIL missing: {name} was required and was not attempted")
    for name in failed:
        lines.append(f"  FAIL {by_source[name].get('stage')}: {name}")
    if missing or failed:
        lines.append(f"  {len(failed)} required entries failed and "
                     f"{len(missing)} were missing, of {len(required)} required")
        return ExitVerdict(1, lines)
    lines.append(f"  all {len(required)} required entries verified")
    return ExitVerdict(0, lines)


#: The ``*Material name=`` a proposal's provenance quotes, so the manifest can
#: be built from the same block the pairing was judged on rather than from
#: whichever block happens to carry the most constants.
_PROVENANCE_BLOCK = re.compile(r"\*Material\s+name=([^\s,]+)", re.IGNORECASE)


def paired_block_name(provenance: str, deck_relative: str) -> Optional[str]:
    """Which ``*MATERIAL`` block the pairing named, when it named this deck.

    Only used when the provenance quotes the same deck the pairing proposed. A
    provenance naming some other file is evidence about some other file, and
    letting its block name select in this one is how a material vector ends up
    belonging to a source that never declared it.

    Matched on the full cache-relative path, not the basename. ``job.inp`` and
    ``input.inp`` are the commonest deck names in this cache, so a basename
    test let a provenance about another repository's ``job.inp`` choose which
    block feeds this one -- the identity-by-basename mistake, inside the
    function written to prevent it.
    """
    if not provenance or not deck_relative:
        return None
    if str(deck_relative) not in provenance:
        return None
    match = _PROVENANCE_BLOCK.search(provenance)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# the manifest
# ---------------------------------------------------------------------------

#: The probe. It is chosen here and is NOT the source's own loading history: a
#: deck describes a whole finite-element job, not the strain path of one
#: material point. Recorded in every manifest's notes so a reader of a verified
#: row knows exactly what was driven. The reversal is what makes state
#: evolution observable -- a monotonic path cannot distinguish a model that
#: stores state from one that recomputes it.
PROBE_NOTE = (
    "loading is a declared probe chosen by this harness, not read from any "
    "deck and not this source's own loading history. Material constants, "
    "nstatv, unsymmetry and kinematics ARE read from the paired deck."
)


@dataclass
class ManifestPlan:
    """A manifest for one entry, or the named reason there is none."""

    manifest: Optional[VerificationManifest] = None
    stage: str = ""
    reason: str = ""
    refusals: tuple[str, ...] = ()
    deck: str = ""
    material_block: str = ""
    kinematics_provenance: str = ""
    #: Set when the deck and the triage row disagree about finite strain. The
    #: deck wins; the disagreement is recorded rather than resolved silently.
    kinematics_note: str = ""
    #: What the file's Abaqus entry point turned out to be, when it is not a
    #: UMAT. Carried whole -- the units it declares, their argument counts and
    #: who calls whom -- so the claim can be checked without re-parsing.
    entry_classification: Optional[dict] = None
    #: Which formulation the verification runs, and the two witnesses that
    #: decided it: what the source's own text does with its tensor, and what
    #: element the author's deck runs the material on.
    formulation: Optional[dict] = None
    #: Where material constants were looked for, when none were found. A
    #: refusal that does not say where it searched is a claim, not a finding.
    searched: Optional[dict] = None
    #: The experiment the planner decided, whole: which family this source
    #: belongs to, what would count as having exercised it, what drives it,
    #: and the evidence for each of those. Carried even when the plan refused,
    #: because the refusal's reasoning is the part worth reading.
    experiment: Optional[dict] = None


_SOLUTION_STATE = re.compile(
    r"^\s*\*INITIAL\s+CONDITIONS\b[^\n]*\bTYPE\s*=\s*SOLUTION\b", re.IGNORECASE)

#: The same keyword with USER, which asks Abaqus to call the source's own
#: SDVINI instead of listing values.
_SOLUTION_STATE_USER = re.compile(
    r"^\s*\*INITIAL\s+CONDITIONS\b[^\n]*\bTYPE\s*=\s*SOLUTION\b[^\n]*\bUSER\b",
    re.IGNORECASE)


def initial_state_is_computed(deck_text: str) -> bool:
    """Does the deck ask Abaqus to call the source's own SDVINI?

    Reading the values out of the Fortran and retyping them into a deck would
    be inventing what the author chose to compute, so the form is carried
    through instead. Omitting it left every state variable at zero, and a
    growth model whose stretch starts at 1.0 then divides by it and returns
    NaN from the first increment.
    """
    return any(_SOLUTION_STATE_USER.match(line)
               for line in deck_text.splitlines()
               if not line.lstrip().startswith("**"))


def initial_solution_state(deck_text: str) -> tuple[float, ...]:
    """The state variables a deck declares its material starts from.

    Read, never assumed. Thirteen of the paired decks in this corpus declare
    ``*INITIAL CONDITIONS, TYPE=SOLUTION`` -- growth and damage models whose
    authors published a nonzero starting state, typically an initial stretch of
    1.0. Running one of those from zeros is a different model than the deck
    describes, and it could still climb the ladder to "verified".

    A deck that declares none is not a problem: zeros are then the deck's own
    statement about where the material starts.
    """
    lines = deck_text.splitlines()
    values: list[float] = []
    collecting = False
    for line in lines:
        if line.lstrip().startswith("**"):
            continue
        if _SOLUTION_STATE.match(line):
            collecting = True
            continue
        if collecting:
            if line.lstrip().startswith("*"):
                break
            for token in line.split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    values.append(float(token))
                except ValueError:
                    # The first field of the first data line is the element set
                    # or node set the state belongs to, not a number.
                    continue
    return tuple(values)


def searched_places(source_id: str, proposal: Optional[dict]) -> dict:
    """Every place a material constant was looked for, and what was there.

    "No deck is paired with this source" is a statement about this pipeline
    until it says where it looked. The pairing scan already records it -- the
    decks in the repository, how many constants each publishes, and how many
    the source's own PROPS references reach -- so the refusal quotes it
    rather than asserting a negative.
    """
    pairing = (proposal or {}).get("pairing") or {}
    alternatives = list(pairing.get("alternatives") or ())
    repository = str((proposal or {}).get("repository") or "")
    return {
        "repository": repository,
        "decks_scanned": len(alternatives),
        "decks": alternatives[:40],
        "decks_not_listed": max(0, len(alternatives) - 40),
        "scanner": str(pairing.get("checked_by") or ""),
        "evidence": str(pairing.get("evidence") or ""),
        "verdict": str(pairing.get("verdict") or ""),
        "expected_nprops": (pairing.get("metadata") or {}).get("expected_nprops"),
        "documentation": ("every .md, .rst and .txt in the repository was "
                          "scanned for a *MATERIAL or *USER MATERIAL block "
                          "naming this routine; an extracted block is written "
                          "beside its document as <file>.extracted.inp and "
                          "enters this same scan"),
    }


def where_we_looked(source_id: str, proposal: Optional[dict]) -> str:
    """The refusal, with the search in it."""
    places = searched_places(source_id, proposal)
    count = places["decks_scanned"]
    where = places["repository"] or Path(source_id).parts[0]
    if not count:
        return (f"no material constants are published for this source: its "
                f"repository ({where}) contains no .inp file at all, and no "
                f"document in it carries a *MATERIAL or *USER MATERIAL block "
                f"naming this routine. Searched: every .inp in the "
                f"repository, and every .md, .rst and .txt in it for an "
                f"embedded material block")
    evidence = places["evidence"] or "no deck published enough constants"
    return (f"no material constants are published for this source. Searched "
            f"{count} .inp file(s) in {where}, and every .md, .rst and .txt "
            f"in it for an embedded *MATERIAL block naming this routine: "
            f"{evidence}. Supplying constants from anywhere else would be "
            f"inventing them")


def _portable(value, cache_root: Path):
    """The same structure with this machine's cache prefix taken out.

    A results file is evidence somebody else reads, and the repository audit
    fails a build that writes an absolute home path into one. The planner's
    refusals quote the directories they searched -- which is exactly what makes
    them findings rather than claims -- so the paths are kept and only the part
    that names this machine is removed.
    """
    root = str(Path(cache_root).resolve())
    if isinstance(value, str):
        return value.replace(root + "/", "").replace(root, "<cache>")
    if isinstance(value, dict):
        return {key: _portable(item, cache_root) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portable(item, cache_root) for item in value]
    return value


def _from_experiment(plan: "ManifestPlan", answer, source_id: str,
                     cache_root: Path, *, inferred_nstatv: int,
                     fd_steps: Sequence[float],
                     row: Optional[dict] = None) -> "ManifestPlan":
    """Fill a ManifestPlan from a planned experiment, and keep the old guards.

    The planner decides the experiment. It does not get to decide that a
    missing requirement is acceptable, so ``missing_requirements()`` and the
    state-count check below still run against whatever it produced -- they are
    about whether the manifest can be executed honestly, which is a separate
    question from whether the experiment is the right one.
    """
    manifest = answer.manifest
    if fd_steps:
        manifest = replace(manifest, fd_steps=tuple(fd_steps))

    pairing = answer.pairing
    material = getattr(pairing, "material", None) if pairing is not None else None
    deck_relative = ""
    if material is not None:
        try:
            deck_relative = str(Path(material.deck).relative_to(cache_root))
        except ValueError:
            deck_relative = str(material.deck)
        plan.deck = deck_relative
        plan.material_block = material.name or "(unnamed)"
    if answer.settled is not None and hasattr(answer.settled, "as_dict"):
        # Scrubbed like everything else recorded: the formulation's provenance
        # names the deck it read, and it reads it by absolute path.
        plan.formulation = _portable(answer.settled.as_dict(), cache_root)

    # Four things the record needs that the planner does not set, because they
    # are about how this harness reports a run rather than about the physics.
    #
    # The source path must be portable. An absolute path names this machine and
    # nothing else, and a manifest is evidence somebody else has to be able to
    # read -- the registry audit fails on one.
    relative, _ = portable_source(cache_root / source_id)
    # The deck must be named the way the corpus names it. Two repositories
    # publish a job.inp and a basename cannot tell them apart.
    provenance = manifest.material_provenance
    if deck_relative and deck_relative not in provenance:
        provenance = f"{deck_relative}: {provenance}"
    # And the manifest has to say that its loading is a probe THIS harness
    # chose, not the loading the author ran. Everything downstream that reports
    # a result reads that sentence out of the manifest.
    notes = manifest.notes or PROBE_NOTE
    # The deck's own material name, because it becomes CMNAME and several
    # routines in this corpus branch on it -- taking a different path, or
    # refusing outright, under a name their author never used. The source's
    # stem is the fallback for an unnamed block and is a label inside a
    # generated deck, never this entry's identity.
    block = getattr(material, "name", "") if material is not None else ""
    name = (block or Path(source_id).stem or "umat")[:60]
    manifest = replace(manifest, source=Path(relative), name=name,
                       material_provenance=provenance, notes=notes)

    # The kinematics witness, from the deck, kept separate from the planner's
    # reason for the experiment: "the author's own step carries NLGEOM=YES" is
    # a fact about the deck and belongs in the record under its own name.
    provenance_of_kinematics = ""
    if material is not None:
        try:
            deck_text = Path(material.deck).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            deck_text = ""
        if deck_text:
            provenance_of_kinematics = deck_kinematics(
                deck_text, Path(material.deck).name).provenance
    plan.kinematics_provenance = _portable(
        provenance_of_kinematics or answer.experiment.reason, cache_root)
    plan.experiment = _portable(answer.experiment.as_dict(), cache_root)
    # The triage scan recorded a kinematics for every source and it recorded it
    # from the source text alone. Where the author's deck says otherwise the
    # deck wins -- it is the analysis the material was published to run in --
    # and the disagreement is written down rather than resolved in silence.
    declared = (row or {}).get("kinematics") or ""
    if declared and declared != manifest.kinematics:
        plan.kinematics_note = (
            f"the triage scan called this source {declared}; the paired deck "
            f"runs it as {manifest.kinematics}, and the deck is what the "
            f"manifest follows")

    refusals = list(manifest.missing_requirements())
    # An anisotropic law's local axes ARE part of the material. The planner can
    # now read them where the deck publishes them, so the refusal applies only
    # where it could not: running a material in a frame its author never
    # described and calling the result verified would be a statement about a
    # model nobody wrote down.
    orientation = getattr(material, "orientation", "") if material else ""
    if orientation and not getattr(manifest, "orientation_axes", ()):
        refusals.append(
            f"the deck uses this material with *ORIENTATION {orientation}, and "
            f"the local axes of an anisotropic material are part of what it is "
            f"made of. This harness read the orientation's name but not its "
            f"axes, and will not run the material in a frame its author never "
            f"published")
    # A state count nobody published is not the same fact as one read from a
    # deck. The transform's inference is a bound derived from the subscripts
    # the source itself applies, so it is used and always reported as an
    # inference; only a source with neither is refused, because there the
    # number really would be invented here.
    declared_state = getattr(material, "nstatv", None) if material else None
    if declared_state is None and not inferred_nstatv and not manifest.nstatv:
        refusals.append(
            "the paired deck declares no *DEPVAR and the transform inferred no "
            "state-variable count, so nobody has established how many this "
            "material has. A UMAT that writes past the end of an array of one "
            "either corrupts memory or measures a truncated state")

    plan.refusals = tuple(refusals)
    plan.manifest = manifest
    plan.stage = "manifest_refused" if refusals else ""
    plan.reason = "; ".join(refusals)
    return plan


def build_manifest(
    source_id: str,
    row: Optional[dict],
    proposal: Optional[dict],
    cache_root: Path,
    *,
    strain: float = 0.005,
    increments: int = 10,
    include_reversal: bool = True,
    include_shear: bool = True,
    fd_steps: Sequence[float] = (),
) -> ManifestPlan:
    """What this source is made of, read from the deck its author shipped.

    Every number here comes from a file somebody published: the constants,
    their count, the state-variable count and the symmetry of the tangent from
    the paired deck's ``*MATERIAL`` block, the kinematics from its ``*STEP``,
    and the tensor size from the triage row that scanned the source. Nothing is
    filled in when a source is missing one of them -- the plan comes back as
    ``needs_material_data``, which keeps the entry in the denominator and out
    of the numerator.
    """
    plan = ManifestPlan()
    if row is None:
        plan.stage = NEEDS_MATERIAL_DATA
        plan.reason = ("no triage row for this source, so nothing has "
                       "established its tensor size or form")
        return plan

    # Before anything else: is this file even a UMAT? The entry point is
    # decided by parsing -- routine name, exact dummy-argument count, and
    # whether a sibling unit calls it -- never by the filename. Twenty-five
    # corpus files present a 36-argument SUBROUTINE UEL to Abaqus and keep a
    # SUBROUTINE UMAT beside it as the element's own constitutive kernel.
    # Driven through a *USER MATERIAL deck, Abaqus resolved the global symbol
    # UMAT to that kernel and the finite difference then perturbed a
    # deformation gradient it never reads, giving a difference of exactly
    # zero. Those rows were being reported as UMAT tangent failures.
    source_path = cache_root / source_id
    if source_path.is_file():
        entry_kind = classify_entry(
            source_path.read_text(errors="replace"), path=source_path)
        if not entry_kind.is_umat:
            plan.stage = NOT_A_UMAT
            plan.reason = entry_kind.reason
            plan.entry_classification = entry_kind.as_dict()
            return plan

    # The experiment comes from the source and the repository that published
    # it, not from one rule applied to all of them. Four decisions were
    # universal here and the corpus is not: which deck the constants come from,
    # where the element stands, what drives it, and what would count as having
    # exercised it. Each of those was wrong for a family that can be named --
    # a growth law is driven by its own clock and not by a prescribed strain, a
    # cohesive law by a separation, a body-force problem by DLOAD, which is
    # never called when every node's displacement is prescribed.
    #
    # Measured before switching, offline, over all 1933 proposal rows: 198
    # entries that already produced a manifest still produce one, 364 that
    # produced none now do, and 21 stop. Exactly one of those 21 had reached
    # 'verified' -- mholla__growth/umats/umat_iso_Mandel.f -- and withdrawing
    # it is the point rather than the cost: the routine reads PROPS(1:5) by
    # literal subscript, so it names every constant it takes, and every block
    # published in that repository declares 8, 9 or 12. It was being verified
    # against five numbers that mean something else.
    experiment_plan = None
    if source_path.is_file():
        try:
            experiment_plan = plan_experiment(
                source_path, cache_root / Path(source_id).parts[0])
        except Exception as error:            # pragma: no cover - defensive
            # A crash in planning is this harness's fault and is recorded as
            # such. It must not be reported as anything about the source.
            plan.stage = "manifest_refused"
            plan.reason = (f"the experiment planner raised "
                           f"{type(error).__name__}: {error}")
            return plan

    if experiment_plan is not None:
        plan.experiment = _portable(
            experiment_plan.experiment.as_dict(), cache_root)
        pairing = experiment_plan.pairing
        if pairing is not None and not pairing.found:
            # Not "this harness has no experiment for it". The constants are
            # missing, and saying which and where we looked is the whole
            # difference between a finding and a shrug.
            plan.stage = NEEDS_MATERIAL_DATA
            plan.reason = _portable(pairing.refusal, cache_root)
            plan.searched = _portable(
                dict(getattr(pairing, "searched", {}) or {}), cache_root)
            return plan
        if not experiment_plan.found:
            plan.stage = "manifest_refused"
            plan.reason = _portable(
                experiment_plan.experiment.refusal, cache_root)
            return plan
        return _from_experiment(plan, experiment_plan, source_id, cache_root,
                                inferred_nstatv=int(
                                    (proposal or {}).get("nstatv_inferred") or 0),
                                fd_steps=fd_steps, row=row)

    proposed = str(((proposal or {}).get("pairing") or {}).get("proposed") or "")
    if not proposed:
        plan.stage = NEEDS_MATERIAL_DATA
        plan.reason = where_we_looked(source_id, proposal)
        plan.searched = searched_places(source_id, proposal)
        return plan
    plan.deck = proposed
    deck_path = Path(cache_root) / proposed
    if not deck_path.is_file():
        plan.stage = NEEDS_MATERIAL_DATA
        plan.reason = f"the paired deck {proposed} is not in the cache"
        return plan

    wanted = paired_block_name(
        str(((proposal or {}).get("material") or {}).get("provenance") or ""),
        proposed)
    material = choose_material(deck_path, wanted)
    if material is None or not material.props:
        plan.stage = NEEDS_MATERIAL_DATA
        plan.reason = (f"{proposed} declares no *MATERIAL block with constants"
                       + (f" named {wanted}" if wanted else ""))
        return plan
    plan.material_block = material.name or "(unnamed)"

    deck_text = deck_path.read_text(encoding="utf-8", errors="replace")

    # Which formulation this UMAT is called in, from two independent
    # witnesses: what the routine's own text does with its tensor, and what
    # element the author's deck runs the material on. The triage row is NOT
    # one of them -- it recorded ntens=6 for every source in the corpus,
    # because 6 is the default it was handed and nothing ever inferred it. A
    # plane-strain routine driven on a six-component element is asked for
    # components it never computes.
    settled = settle(source_path.read_text(errors="replace") if source_path.is_file()
                     else "", source_id, deck_text, Path(proposed).name,
                     material.name)
    plan.formulation = settled.as_dict()
    if not settled.element:
        plan.stage = "manifest_refused"
        plan.reason = settled.formulation.reason
        return plan
    element = settled.element
    geometry = element_geometry(element)
    ndi, nshr, ntens = geometry.ndi, geometry.nshr, geometry.ntens

    found = deck_kinematics(deck_text, Path(proposed).name)
    plan.kinematics_provenance = found.provenance
    if (row.get("kinematics") or "") and row["kinematics"] != found.kinematics:
        plan.kinematics_note = (
            f"the triage scan called this source {row['kinematics']}; the "
            f"paired deck runs it as {found.kinematics}, and the deck is what "
            f"the manifest follows")

    declared_state = initial_solution_state(deck_text)
    state_from_sdvini = initial_state_is_computed(deck_text)
    # The transform's own bound on STATEV, from the subscripts the source uses.
    # Reported as an inference everywhere: it is not the author's *DEPVAR and
    # must never read as one.
    inferred_nstatv = int((proposal or {}).get("nstatv_inferred") or 0)

    # Uniaxial extension, then shear, then a reversal. Uniaxial alone leaves
    # most of DDSDDE untested: it drives one direct component, so the shear
    # rows and columns are only ever exercised by whatever coupling the model
    # happens to have, and a transform can be wrong about them without a
    # uniaxial path ever noticing. The reversal makes state evolution
    # observable -- a monotonic path cannot tell a model that stores state
    # from one that recomputes it, because both give the same answer going
    # out. All three are probes chosen here, not the author's loading, and
    # the manifest records them as such.
    loading = [uniaxial(strain, increments)]
    if include_shear:
        loading.append(simple_shear(strain, increments))
    if include_reversal:
        loading.append(reverse(loading[0]))

    relative, _ = portable_source(cache_root / source_id)
    provenance = (
        f"{Path(proposed).name} *MATERIAL {plan.material_block}: "
        f"{len(material.props)} constants"
        + (f", *DEPVAR {material.nstatv}" if material.nstatv
           else (f", no *DEPVAR: nstatv {inferred_nstatv} INFERRED by the "
                 f"transform from the subscripts the source uses"
                 if inferred_nstatv else ", no *DEPVAR and no inference"))
        + (", UNSYMM" if material.unsymmetric else "")
        + f" (paired deck {proposed})")
    manifest = VerificationManifest(
        # The deck's own material name, because it becomes CMNAME, and a UMAT
        # that branches on CMNAME -- several in this corpus do -- takes a
        # different path or refuses outright under a name its author never
        # used. Falls back to the source's stem only when the block is
        # unnamed; that is a label inside a generated deck and never this
        # entry's identity, which is its path within the cache.
        name=(material.name or Path(source_id).stem or "umat")[:60],
        source=Path(relative),
        element_type=element,
        kinematics=found.kinematics,
        ntens=ntens, ndi=ndi, nshr=nshr,
        nprops=len(material.props), props=tuple(material.props),
        nstatv=material.nstatv or inferred_nstatv or 1,
        unsymmetric=bool(material.unsymmetric),
        material_provenance=provenance,
        initial_statev=declared_state,
        initial_state_from_user_subroutine=state_from_sdvini,
        initial_statev_provenance=(
            f"{Path(proposed).name} *INITIAL CONDITIONS, TYPE=SOLUTION, USER: "
            f"the source's own SDVINI computes the starting state"
            if state_from_sdvini else
            (f"{Path(proposed).name} *INITIAL CONDITIONS, TYPE=SOLUTION: "
             f"{len(declared_state)} values" if declared_state else "")),
        loading=tuple(loading),
        fd_steps=tuple(fd_steps) or VerificationManifest.fd_steps,
        notes=PROBE_NOTE)

    refusals = list(manifest.missing_requirements())

    # An orientation is material data for an anisotropic law -- the local axes
    # ARE the model. The deck parser gives the orientation's NAME, not its
    # axes, and the manifest needs three Euler angles, so there is nothing here
    # to carry over honestly. Refusing is the only option that does not invent
    # a frame the author never published: running such a material in the global
    # frame and calling the result verified would be a statement about a model
    # nobody described.
    if material.orientation:
        refusals.append(
            f"the deck uses this material with *ORIENTATION "
            f"{material.orientation}, and the local axes of an anisotropic "
            f"material are part of what it is made of. This harness can read "
            f"the orientation's name but not its axes, and will not run the "
            f"material in a frame its author never published")

    # A state-variable count nobody published is not the same fact as one read
    # from a deck, and the two were indistinguishable in the record: the
    # provenance string only mentions *DEPVAR when the deck actually had one.
    # Refusing outright was the first fix and it was too strong. The transform
    # reports a count inferred from the subscripts the source actually applies
    # to STATEV, which is a bound derived from the source rather than a number
    # somebody chose -- and a UMAT with no state at all still needs an array of
    # one for Abaqus to pass it. So the inference is used, and said to be an
    # inference wherever it is reported. Only a source with neither a deck
    # *DEPVAR nor an inference is refused: there the count really would be
    # invented here.
    if material.nstatv is None and not inferred_nstatv:
        refusals.append(
            "the paired deck declares no *DEPVAR and the transform inferred no "
            "state-variable count, so nobody has established how many this "
            "material has. A UMAT that writes past the end of an array of one "
            "either corrupts memory or measures a truncated state")
    plan.refusals = tuple(refusals)
    plan.manifest = manifest
    plan.stage = "manifest_refused" if refusals else ""
    plan.reason = "; ".join(refusals)
    return plan


# ---------------------------------------------------------------------------
# frozen experiments
# ---------------------------------------------------------------------------


def frozen_manifests(collection: Optional[Path]) -> dict:
    """The experiments already verified, keyed by the source and its bytes.

    A regression that searches again is not a regression. The amplitude the
    discovery chose, the segments it built, the hold it added, the step ladder
    and the tolerances were decided once, when the material first verified;
    replaying them is what makes a later run's difference a difference in the
    CODE. Keyed on the source's digest as well as its identity, so a source
    that has changed since it was frozen does not silently reuse an experiment
    chosen for different text.
    """
    frozen: dict = {}
    if collection is None or not Path(collection).is_dir():
        return frozen
    for contract in sorted(Path(collection).glob("*/contract.json")):
        try:
            payload = json.loads(contract.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        manifest = payload.get("frozen_manifest")
        source_id = str(payload.get("source_id") or "")
        if not manifest or not source_id:
            continue
        frozen[source_id] = {
            "manifest": manifest,
            "source_sha256": str(payload.get("source_sha256") or ""),
            "states": payload.get("frozen_states") or [],
            "from": str(contract.parent.name),
        }
    return frozen


def thaw(record: dict) -> VerificationManifest:
    """A manifest back out of its frozen record, loading segments included."""
    fields = set(VerificationManifest.__dataclass_fields__)
    payload = {name: value for name, value in dict(record).items()
               if name in fields and name != "loading"}
    loading = tuple(
        LoadingSegment(**dict(segment, strain=tuple(segment["strain"])))
        for segment in (record.get("loading") or []))
    for name in ("props", "initial_statev", "fd_steps", "bundle", "outputs",
                 "perturbation_components"):
        if payload.get(name) is not None:
            payload[name] = tuple(payload[name])
    if payload.get("orientation") is not None:
        payload["orientation"] = tuple(payload["orientation"])
    payload["source"] = Path(payload.get("source") or ".")
    payload["bundle"] = tuple(Path(p) for p in payload.get("bundle", ()))
    return VerificationManifest(loading=loading, **payload)


# ---------------------------------------------------------------------------
# one manifest, two builds
# ---------------------------------------------------------------------------


class DifferentDecks(ValueError):
    """The two builds would not have been asked the same question."""


def deck_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _regime_of(state: dict):
    """The Regime object back out of a state's recorded dictionary.

    The states are carried as plain dictionaries so the whole record can be
    written to JSON; coverage() needs the object, and rebuilding it here keeps
    one definition of what a regime is.
    """
    from umat_oti.abaqus.state_regime import Regime

    found = state.get("regime") or {}
    return Regime(increment=int(found.get("increment") or 0),
                  regime=str(found.get("regime") or ""),
                  reason=str(found.get("reason") or ""),
                  activated_here=bool(found.get("activated_here")),
                  unloading=bool(found.get("unloading")))


#: How far past the bracketed transition to drive, so the loading path
#: crosses it partway along rather than ending on it. Four: enough that the
#: early increments are clearly elastic and the late ones clearly inside the
#: activated regime, and small enough not to walk the model into a regime its
#: author never wrote. Checked by an actual run before it is adopted -- a
#: material that cannot be driven that far keeps the amplitude that worked.
BEYOND_TRANSITION = 4.0

#: How far to drive a material that was ALREADY active at the smallest
#: amplitude the search tried. There is no transition to place the path around,
#: so the amplitude is chosen for RESOLUTION: large enough that the stress
#: response is well clear of what a centred difference of doubles can see, and
#: bounded so the model is not walked somewhere its author never wrote.
#:
#: Tried largest first, and the largest the model can actually be driven to is
#: the one used. 400 takes the search's floor of 1e-4 to four percent of
#: strain, which is a verification amplitude rather than a probe; the smaller
#: rungs are there for a model that will not go that far, so that "it did not
#: run" costs resolution rather than the whole result.
RESOLUTION_FACTORS = (400.0, 100.0, 25.0)


def body_force_loading(source: Path, deck: Optional[Path], increments: int
                       ) -> tuple[Optional[Any], str]:
    """The author's own body force, when that is what drives this source.

    Returns the loading segment and a sentence saying where every number in
    it came from, or ``None`` and a sentence saying what was missing. A
    source that defines DLOAD but whose repository publishes no deck naming
    the components is not given a force this pipeline invented.
    """
    from umat_oti.abaqus.body_force import (defines_dload, held_directions,
                                            read_loads)
    try:
        text = Path(source).read_text(errors="replace")
    except OSError as error:                       # pragma: no cover
        return None, f"; the source could not be read: {error}"
    if not defines_dload(text):
        return None, ""
    if not deck or not Path(deck).is_file():
        return None, ("; this source defines SUBROUTINE DLOAD, so it is "
                      "driven by a body force, but no deck is paired with it "
                      "to say which components carry it")
    loads = read_loads(Path(deck))
    if not loads.driven:
        return None, (f"; this source defines SUBROUTINE DLOAD, but "
                      f"{Path(deck).name} names no non-uniform body-force "
                      f"component for it")
    held = held_directions(Path(deck)) or (1, 2)
    return under_body_force(loads.components, held=held,
                            increments=increments,
                            provenance=loads.provenance), loads.provenance


def settle_on_safe_loading(loading, amplitude: float,
                           manifest: VerificationManifest, original: Path,
                           attempts_dir: Path, timeout: int, *,
                           increments: int, form: str,
                           data_roots: Sequence[Path]) -> tuple[list, dict]:
    """Run the chosen loading whole, and repair it until nothing in it is NaN.

    A finite prefix is what a search learns the edge of a domain from; it is
    not what a verification rests on. See
    :mod:`umat_oti.abaqus.safe_loading`.

    The repair is not "shrink the amplitude". Before anything is changed the
    failure is PROBED: the same loading is run at half the amplitude and at
    four times the increment resolution, and what matters is not whether it
    still broke but whether the break MOVED. A failure whose location is
    unchanged when the amplitude is halved is not controlled by the
    amplitude, and halving it again is the same experiment driven less far,
    failing in the same place. Only once the responding quantity is known is
    the corresponding one adapted.

    Every run here is on the ORIGINAL. The converted build is never
    consulted: a loading chosen with it in view would be a loading chosen to
    agree.
    """
    report: dict[str, Any] = {"attempts": [], "complete": False}
    points = frames.points_for(manifest.element_type)

    def walk(working, here, label):
        """One real Abaqus job on the original, and what it reached."""
        trial = attempts_dir / f"safe_{label}_{here:.6e}"
        candidate = replace(manifest, loading=tuple(working))
        try:
            outcome = run_one(manifest=candidate, timeout=timeout,
                              source=Path(original), job="original",
                              work_dir=trial, support_dir=None, form=form,
                              data_roots=data_roots)
        except Exception as exc:                   # noqa: BLE001
            return None, f"the job raised {type(exc).__name__}: {exc}"
        evidence = job_evidence(outcome)
        if not evidence.completed:
            return None, ("; ".join(evidence.reasons)
                          or "the job did not complete")
        return safe_loading.examine(history_of(trial, "original"),
                                    expected_points=points), ""

    def how_far(prefix, working) -> tuple:
        """How far along the path a run got, as a FRACTION, and where.

        A fraction: refining the resolution fourfold turns "22 of 40
        increments" into "88 of 160", and comparing the counts would say the
        failure moved when both are the same 55% of the same path.
        """
        if prefix is None:
            return -1.0, 0
        total = sum(int(segment.increments) for segment in working) or 1
        step = (prefix.first_bad[0] if not prefix.complete else 0)
        return prefix.usable / total, step

    prefix, why = walk(loading, amplitude, "as_chosen")
    if prefix is None:
        report["reason"] = why
        return list(loading), report
    if not prefix.records:
        # The job ran and wrote no history at all. That is not an experiment
        # that reached past the edge of a domain, and blaming the loading for
        # it would report a stub routine, a probe with no call site or a
        # support library that never built as "this harness has no experiment
        # for this source". Say what happened and let the ladder reach the
        # rung that can name the real cause.
        report["recorded_nothing"] = True
        report["reason"] = ""
        report["did_not_run"] = (
            "the job ran over the chosen loading and recorded no history at "
            "all, so nothing here is a statement about the loading")
        return list(loading), report
    report["prefix"] = prefix.as_dict()
    reached, broke_in = how_far(prefix, loading)
    report["attempts"].append({"varied": "none", "value": amplitude,
                               "reached": reached, "step": broke_in,
                               "complete_increments": prefix.usable,
                               "reason": prefix.reason()[:200]})
    if prefix.complete:
        report.update(complete=True, amplitude=amplitude, reason=prefix.reason())
        return list(loading), report

    # It broke. Find out what the break responds to before repairing it.
    probes = [{"varied": "amplitude", "value": amplitude,
               "reached": reached, "step": broke_in}]
    halved, why = walk(_rescaled(loading, 0.5), amplitude * 0.5, "half")
    half_reached, half_step = how_far(halved, loading)
    probes.append({"varied": "amplitude", "value": amplitude * 0.5,
                   "reached": half_reached, "step": half_step,
                   "reason": why[:160]})
    finer_loading = _refined(loading, 4)
    finer, why = walk(finer_loading, amplitude, "finer")
    fine_reached, fine_step = how_far(finer, finer_loading)
    probes.append({"varied": "increments", "value": increments * 4,
                   "reached": fine_reached, "step": fine_step,
                   "reason": why[:160]})
    probes.append({"varied": "increments", "value": increments,
                   "reached": reached, "step": broke_in})
    # And TIME, because a growth or a creep law integrates over it and
    # neither the amplitude nor the step size touches how much of it passes.
    # Measured on BodyForce-Growth-2Stages.for: the break sat at the same
    # 14.3% of the path at 0.04 and at 0.02 -- a fixed INCREMENT rather than
    # a fixed strain, which is what a clock looks like. Without this probe
    # the failure was called path_segment_limited and the repair went to cut
    # a ramp whose length was never the problem.
    briefer = _shorter_in_time(loading, 0.25)
    brief, why = walk(briefer, amplitude, "briefer")
    brief_reached, brief_step = how_far(brief, briefer)
    probes.append({"varied": "period", "value": 0.25,
                   "reached": brief_reached, "step": brief_step,
                   "reason": why[:160]})
    probes.append({"varied": "period", "value": 1.0,
                   "reached": reached, "step": broke_in})
    mechanism = safe_loading.classify(probes)
    report["failure_mechanism"] = mechanism.as_dict()

    if brief is not None and brief.complete:
        report.update(complete=True, amplitude=amplitude,
                      coverage_given_up=("the step time was shortened to a "
                                         "quarter, so any rate- or "
                                         "time-dependent branch is exercised "
                                         "over less of the clock"),
                      reason=(f"{mechanism.reason}; shortening the step time "
                              f"gave a run finite throughout: "
                              f"{brief.reason()}"))
        report["prefix"] = brief.as_dict()
        return briefer, report
    if halved is not None and halved.complete:
        report.update(complete=True, amplitude=amplitude * 0.5,
                      reason=(f"{mechanism.reason}; halving the amplitude gave "
                              f"a run finite throughout: {halved.reason()}"))
        report["prefix"] = halved.as_dict()
        return _rescaled(loading, 0.5), report
    if finer is not None and finer.complete:
        report.update(complete=True, amplitude=amplitude,
                      reason=(f"{mechanism.reason}; refining the increments "
                              f"gave a run finite throughout: "
                              f"{finer.reason()}"))
        report["prefix"] = finer.as_dict()
        return _refined(loading, 4), report

    if mechanism.kind == safe_loading.PATH_SEGMENT_LIMITED and broke_in > 0:
        # The model will not do that segment at all -- a growth law declining
        # to be driven backwards is not an amplitude and not a step size. The
        # segment is shortened to what the run proved it WILL do, and if that
        # leaves nothing the segment is dropped and the loss of coverage is
        # recorded rather than hidden: an experiment that no longer tests
        # reversal must not be reported as though it did.
        repairs: list = []
        working = list(loading)
        here_prefix = prefix
        offending = broke_in
        # Successive segments, because a model that will not be driven
        # backwards may also not be held. Measured on
        # BodyForce-Growth-2Stages.for: dropping 'uniaxial_reversed' moved the
        # break into the hold that followed it. Each drop is recorded, and
        # what the experiment stops exercising is recorded with it.
        for _round in range(len(loading)):
            repaired = None
            for how in ("shorten", "drop"):
                candidate, note = _shortened(working, offending, here_prefix, how)
                if candidate is None:
                    repairs.append(note)
                    continue
                attempt, why = walk(candidate, amplitude, f"{how}{_round}")
                if attempt is None:
                    repairs.append(why)
                    continue
                report["attempts"].append(
                    {"varied": "segment",
                     "value": f"{how} step {offending}",
                     "reached": how_far(attempt, candidate)[0],
                     "step": attempt.first_bad[0],
                     "reason": attempt.reason()[:200]})
                repairs.append(note)
                if attempt.complete:
                    report["prefix"] = attempt.as_dict()
                    report["segment_repair"] = "; then ".join(repairs)
                    report.update(
                        complete=True, amplitude=amplitude,
                        coverage_given_up="; ".join(
                            r for r in repairs if "dropped" in r or "cut" in r),
                        reason=(f"{mechanism.reason}; "
                                + "; then ".join(repairs)
                                + f": {attempt.reason()}"))
                    return candidate, report
                repaired = (candidate, attempt)
                break
            if repaired is None:
                break
            working, here_prefix = repaired
            if here_prefix.first_bad[0] < 1:
                break
            offending = here_prefix.first_bad[0]
        report["segment_repair"] = "; then ".join(repairs)
        report["reason"] = f"{mechanism.reason}. " + "; then ".join(repairs)
        return list(loading), report

    if mechanism.kind == safe_loading.INCREMENT_RESOLUTION_LIMITED:
        # The loading is right and the solver was being asked to walk it in
        # steps too large. Refine rather than shrink: shrinking would remove
        # the behaviour the experiment exists to exercise.
        working, here = _refined(loading, 4), amplitude
        bracket = "increments"
    elif mechanism.kind == safe_loading.TIME_LIMITED:
        # The clock is what it will not run past, so the clock is what gets
        # shortened. The loading keeps its shape, its amplitude and its
        # increments; only the time they are walked in changes.
        working, here = briefer, amplitude
        bracket = "period"
    elif mechanism.kind == safe_loading.AMPLITUDE_LIMITED:
        working, here = list(loading), amplitude
        bracket = "amplitude"
    else:
        report["reason"] = (
            f"{prefix.reason()}; and the repair is not an amplitude: "
            f"{mechanism.reason}")
        return list(loading), report

    # Bracket the safe endpoint by RERUNNING, not by trusting a margin. The
    # margin is only the first proposal; what makes an endpoint safe is a
    # complete finite run at it, recorded with its distance from the failure
    # that was actually observed.
    for attempt in range(safe_loading.REBUILDS):
        rebuilt = safe_loading.reconstruct(prefix, here, working)
        report["rebuilt"] = rebuilt.as_dict()
        if not rebuilt.possible:
            report["reason"] = (f"{prefix.reason()}; and the loading could not "
                                f"be rebuilt: {rebuilt.reason}")
            return list(loading), report
        if bracket == "period":
            working = _shorter_in_time(working, 0.5)
        elif bracket == "increments":
            working = _refined(working, 2)
        else:
            working = _rescaled(working, rebuilt.fraction)
            here = rebuilt.amplitude
        prefix, why = walk(working, here, f"rebuild{attempt}")
        if prefix is None:
            report["reason"] = why
            return list(loading), report
        report["attempts"].append({"varied": bracket, "value": here,
                                   "last_complete": prefix.usable,
                                   "reason": prefix.reason()[:200]})
        report["prefix"] = prefix.as_dict()
        if prefix.complete:
            report.update(
                complete=True, amplitude=here,
                safety_distance=rebuilt.as_dict(),
                reason=(f"{mechanism.reason}; rebuilt and rerun whole: "
                        f"{prefix.reason()}"))
            return working, report
    report["reason"] = (
        f"the loading was rebuilt {safe_loading.REBUILDS} times and the model "
        f"left its domain inside every one of them; {mechanism.reason}")
    return list(loading), report


def _shortened(loading, step: int, prefix, how: str = "shorten"):
    """Cut back, or drop, the segment the model refuses.

    Two strategies in order, because they give up different amounts. Cutting
    the segment back to what the run demonstrably walked keeps the path going
    that way, only less far. Dropping it gives up a behaviour, and the note
    that comes back says which -- an experiment that stopped testing reversal
    must not be reported as though it still did.

    Measured on BodyForce-Growth-2Stages.for: cutting 'uniaxial_reversed'
    from ten increments to one still left its domain at the first increment
    of it, which is the model saying it will not be driven backwards at all.
    """
    if step < 1 or step > len(loading):
        return None, f"there is no step {step} in this loading to shorten"
    segment = loading[step - 1]
    working = list(loading)
    if how == "drop":
        dropped = working.pop(step - 1)
        if not working:
            return None, (f"'{dropped.name}' is the only segment there is, so "
                          f"dropping it would leave no experiment at all")
        return working, (f"'{dropped.name}' was dropped: the model left its "
                         f"domain inside it however short it was made, so "
                         f"this experiment no longer exercises that path")
    walked = prefix.last_safe[1] if prefix.last_safe[0] == step else 0
    keep = int(walked * safe_loading.MARGIN)
    if keep < 1:
        return None, (f"the model left its domain inside '{segment.name}' "
                      f"before completing one increment of it, so there is "
                      f"nothing of it to keep")
    working[step - 1] = replace(segment, increments=keep,
                                strain=tuple(value * keep / max(1, segment.increments)
                                             for value in segment.strain))
    return working, (f"'{segment.name}' was cut from {segment.increments} "
                     f"increments to {keep}, which is {safe_loading.MARGIN:g} "
                     f"of what the model demonstrably walked; the path still "
                     f"goes that way, less far")


def _shorter_in_time(loading, factor: float) -> list:
    """The same path, walked in less time. Shape and amplitude untouched.

    A growth law, a creep law or a relaxation integrates over the clock, and
    neither the amplitude nor the increment size changes how much of it
    passes. This is the only quantity that does.
    """
    return [replace(segment, period=max(1e-12, float(segment.period) * factor))
            for segment in loading]


def _refined(loading, factor: int) -> list:
    """The same path, walked in smaller steps. Amplitude and shape untouched."""
    return [replace(segment, increments=max(1, int(segment.increments) * factor))
            for segment in loading]


def _rescaled(loading, fraction: float) -> list:
    """The same path, driven less far. Shape, order and timing untouched."""
    return [replace(segment, strain=tuple(value * fraction
                                          for value in segment.strain))
            for segment in loading]


def discover_loading(manifest: VerificationManifest, original: Path,
                     work_dir: Path, timeout: int, *,
                     increments: int = 10, form: str = "",
                     data_roots: Sequence[Path] = (),
                     deck: Optional[Path] = None,
                     enabled: bool = True) -> tuple[VerificationManifest, dict]:
    """Raise the amplitude on the ORIGINAL until the material does something.

    The fixed probe is a guess about somebody else's material. Driven at a
    strain the model answers elastically it tests the part of a UMAT that
    every build gets right -- stress linear in strain, the elastic tangent,
    state that never moves -- so a converted routine wrong about yielding,
    damage or hardening agrees perfectly and the row is recorded as verified.

    So the amplitude is searched for. Each candidate is a real Abaqus job on
    the ORIGINAL source; :func:`detect_activation` reads its probe history and
    says whether anything happened. The converted build is never run here: a
    loading chosen with it in view would be a loading chosen to agree.

    Returns the manifest to verify with and what the search found. When
    nothing activates up to the ceiling the ORIGINAL manifest comes back
    unchanged -- for a linear elastic material that is the right answer, and
    the amplitude that ran is still the one the comparison uses.
    """
    record: dict = {"ran": False, "reason": "adaptive discovery was not enabled"}
    if not enabled:
        return manifest, record

    # An amplitude search only means something where an amplitude is what
    # drives the material. A growth law is driven by its own clock, a cohesive
    # law by a separation, a body-force problem by DLOAD -- and raising "the
    # strain" on any of them raises a number that does not appear in the law.
    # On the growth family the search ran from 8e-07 to 1, found the model
    # non-finite at every amplitude, and reported that as a property of the
    # source; the model was non-finite because the unit cube stood on
    # x^2 - y^2 = 0, which no amplitude was ever going to change.
    driver = manifest.loading[0].driven_by if manifest.loading else "strain"
    if driver != "strain":
        record["reason"] = (
            f"the driver of this source is {driver}, not a prescribed strain, "
            f"so there is no amplitude to search: raising one would raise a "
            f"number that does not appear in this law")
        record["driver"] = driver
        return manifest, record

    attempts_dir = Path(work_dir) / "discovery"
    # A search job only has to answer "did anything happen?", and four
    # increments per segment answers it as well as thirty. The FINAL
    # verification still runs at full resolution -- this is the cost of
    # looking, not the cost of the measurement.
    coarse = max(3, increments // 3)

    def run_at(amplitude: float, steps: int = 0):
        """One Abaqus job on the original at this amplitude.

        ``steps`` is how finely to walk the path. The SEARCH walks it coarsely
        -- four increments per segment answer "did anything happen?" as well
        as thirty, and every step is a real Abaqus job. The EXTENSION does not
        get that discount: what it decides is the amplitude the verification
        will run at, and a model can walk a coarse path to a strain it cannot
        reach along a fine one. Measured on Growth-Alex.for: 0.01 completed at
        three increments per segment, was adopted, and the verification at ten
        put 2800 of 3990 compared values past the end of the model's domain.
        """
        walk = steps or coarse
        trial = attempts_dir / f"a{amplitude:.6e}x{walk}"
        loading = [uniaxial(amplitude, walk),
                   simple_shear(amplitude, walk)]
        loading.append(reverse(loading[0]))
        candidate = replace(manifest, loading=tuple(loading))
        call = dict(manifest=candidate, timeout=timeout, source=Path(original),
                    job="original", work_dir=trial, support_dir=None, form=form,
                    data_roots=data_roots)
        try:
            report = run_one(**call)
        except Exception as exc:                       # noqa: BLE001
            return False, [], f"the job raised {type(exc).__name__}: {exc}"
        evidence = job_evidence(report)
        if not evidence.completed:
            return False, [], "; ".join(evidence.reasons) or "the job did not complete"
        return True, history_of(trial, "original"), ""

    # The search walks coarsely to keep its cost down. Whether a model can be
    # driven AT ALL is a question about the increment size as well as the
    # amplitude, so a source about to be refused is asked again at the
    # resolution the verification would actually use.
    found = search_amplitude(
        run_at, run_fine=lambda amplitude: run_at(amplitude, steps=increments),
        declared=(manifest.loading[0].strain[0] if manifest.loading else 0.0),
        reversal_at=2 * coarse)
    record = found.as_dict()
    record["ran"] = True
    record["jobs"] = len(found.attempts)

    # The amplitude to VERIFY at is not the amplitude at which activation was
    # first seen. Driving to exactly there puts the transition at the end of
    # the path, so every increment is either before it or on it, and there is
    # no smooth state inside the activated regime to check a tangent at.
    # Measured on From-2D-to-2D-Axe.for: activation at 2.5e-05, and both
    # chosen states came out after it with none before.
    #
    # Driving PAST it puts the transition partway along, so the early
    # increments are smooth elastic, the late ones are smooth inelastic, and
    # the states either side can be chosen with clearance from the corner.
    # No fallback to the fixed probe when the search FOUND that the model has
    # no domain there. Falling back put thirteen entries on 0.005 -- fifty
    # times the amplitude that had just returned NaN -- and both builds went
    # non-finite at their second increment.
    amplitude = found.amplitude
    if not amplitude:
        if found.outcome == LEFT_ITS_DOMAIN:
            # Before giving up: a prescribed-displacement deck is the wrong
            # question for a model driven by a force per unit volume. If this
            # source carries the routine Abaqus calls for one, and its author
            # published a deck saying which components carry it, that is the
            # experiment -- and nothing about it is chosen here.
            driven, note = body_force_loading(original, deck, increments)
            if driven is not None:
                record["chosen_amplitude"] = 0.0
                record["body_force"] = note
                record["refused"] = ""
                return replace(manifest, loading=(driven,)), record
            record["chosen_amplitude"] = 0.0
            # "The model produced no numbers" and "no job ever ran" are
            # different findings. Without a licence token every attempt comes
            # back ran=False, and blaming the experiment for that reports a
            # harness that could not run anything as a source this harness
            # has no experiment for. Only a search whose jobs ACTUALLY RAN
            # and returned values that are not numbers has established
            # anything about the loading.
            if any(attempt.ran for attempt in found.attempts):
                record["refused"] = f"{found.reason}{note}"
            else:
                record["did_not_run"] = found.reason
            return manifest, record
        amplitude = manifest.loading[0].strain[0]
    # Reached whenever the search came back with an amplitude, not only when
    # it came back ACTIVATED. A material whose domain ends in a non-finite
    # tail still has a usable history below it, and the question the
    # extension asks -- "this amplitude runs, but is it big enough to measure
    # at?" -- is exactly the question those need answered. Measured on
    # thirteen entries: the search settles on 1e-04, which leaves one smooth
    # state where two are needed, and the extension's own ladder reaches the
    # amplitude that leaves two. Every rung is still confirmed by a real run
    # at the verification's resolution before it is adopted.
    if found.outcome in (ACTIVATED, LEFT_ITS_DOMAIN) and amplitude:
        # Two different situations wear the same word. A material that was
        # quiet and then activated has a transition, and the loading should
        # cross it partway along. A material that was ALREADY doing something
        # at the search's smallest amplitude has no transition the search can
        # see -- a growth or a swelling law is driven by time and is active
        # from its first increment -- and for that one the amplitude decides
        # nothing about branches and everything about whether a finite
        # difference can resolve anything at all.
        #
        # Measured on From-2D-to-2D-Axe.for: activated at 1e-4, the first
        # amplitude tried, verified at 1e-4, and the tangent came back with
        # one-sided gaps that GREW as the step shrank -- 0.006 at 1e-3 and 70
        # at 1e-7, which is cancellation and not a corner -- and a centred
        # difference 0.9% from the OTI value. There is no transition there to
        # step past; there is a response too small to difference.
        # "Activated at the first amplitude tried" is the question, and the
        # bracket cannot answer it: the refinement starts from
        # amplitude/growth when nothing was ever quiet, so its lower end is
        # never zero. The attempts can answer it, because the first of them
        # IS the first amplitude tried.
        at_the_floor = bool(found.attempts and found.attempts[0].activated)
        ladder = RESOLUTION_FACTORS if at_the_floor else (BEYOND_TRANSITION,)
        record.setdefault("extension", {})
        tried: list = []
        for factor in ladder:
            # Bounded by the ceiling the search itself respects. Measured on
            # BodyForce-Growth-2Stages.for, where the search settled on 0.005
            # and the resolution ladder multiplied it by four hundred to give
            # TWO -- two hundred percent of strain, twice the ceiling, and
            # exactly the regime the ceiling exists to keep a model out of.
            # The ladder's own docstring says it is "bounded so the model is
            # not walked somewhere its author never wrote"; it was not.
            wanted = min(amplitude * factor, CEILING)
            if wanted <= amplitude:
                tried.append({"factor": factor, "amplitude": wanted,
                              "ran": False,
                              "reason": (f"a factor of {factor:g} would pass "
                                         f"the ceiling of {CEILING:g}, and "
                                         f"the amplitude is already there")})
                continue
            ran, _records, why = run_at(wanted, steps=increments)
            # "The job completed" is not "the model was still itself". A run
            # that returned NaN at its fourth increment completes: Abaqus
            # writes the history and exits. Adopting that amplitude hands the
            # verification a path the model has already left, and the search
            # itself would have rejected it -- it is the same test, applied
            # in the one place that was not applying it.
            # The same bar the search uses: a run whose prefix is a history
            # is a run this amplitude can be verified at, and one that breaks
            # too early is not. Asking for every record to be finite here
            # while the search asks for five would make the two disagree
            # about the same run.
            if ran and not enough_to_drive(_records):
                broke_at = first_non_finite(_records)
                ran = False
                why = (f"the model returned a value that is not a number at "
                       f"increment {broke_at} of this run, too early to leave "
                       f"a history, so its domain does not reach this "
                       f"amplitude")
            tried.append({"factor": factor, "amplitude": wanted, "ran": ran,
                          "reason": why[:200]})
            if ran:
                amplitude = wanted
                record["extension"] = {
                    "amplitude": wanted, "factor": factor, "tried": tried,
                    "at_the_search_floor": at_the_floor,
                    "why": (
                        f"this material was already active at the smallest "
                        f"amplitude tried, so there is no transition to cross; "
                        f"driven up by {factor:g} instead, to a strain a "
                        f"centred difference can resolve"
                        if at_the_floor else
                        "driven past the transition so the path crosses it "
                        "partway along and carries smooth states on both "
                        "sides")}
                break
        else:
            record["extension"] = {
                "amplitude": None, "tried": tried,
                "at_the_search_floor": at_the_floor,
                "why": ("the material could not be driven further than the "
                        "search reached, so the path stops where it was and "
                        "only the states it reached are available")}

    # No amplitude asks whether this material cares about TIME. A Kelvin-Voigt
    # solid driven at one rate is linear in the strain at every amplitude, so
    # the search above reports "linear to the ceiling" -- nothing here to
    # activate -- about a material whose whole subject is time. Measured on
    # umat_viscoelastic.for, whose stiffness carries eta/(E*dtime): six runs
    # from 1e-4 to 1 strain, every one of them linear, every one at one DTIME.
    #
    # So the same path is walked again at a different step time, with a hold on
    # the end. Two jobs, and only where they can decide something: a material
    # the amplitude search already activated is already being verified on a
    # branch every build can get wrong.
    time_finding = None
    if enabled:
        time_finding = probe_time_dependence(
            manifest, original, attempts_dir, timeout, amplitude=amplitude,
            increments=coarse, form=form, data_roots=data_roots)
        record["time"] = time_finding.as_dict()

    loading = [uniaxial(amplitude, increments), simple_shear(amplitude, increments)]
    loading.append(reverse(loading[0]))
    # A hold earns its place in the VERIFICATION loading only when the probe
    # showed the material answers it. On a rate-independent material it is ten
    # increments of the same answer, and on a rate-dependent one it is the only
    # part of the path where the time-dependent branch is exercised at all.
    if time_finding is not None and time_finding.time_dependent:
        loading.append(hold(loading[0], period=HOLD_PERIODS * loading[0].period,
                            increments=max(3, increments // 2)))
        record["hold_added"] = time_finding.reason

    # Everything above chose the loading from probes. This runs the ORIGINAL
    # over the loading that was chosen, whole, and will not hand it on until
    # every record of it is finite -- because a verification is allowed to
    # rest only on an analysis that completed, and a frozen regression
    # fixture that replays a truncated failure is not a fixture.
    loading, safety = settle_on_safe_loading(
        loading, amplitude, manifest, original, attempts_dir, timeout,
        increments=increments, form=form, data_roots=data_roots)
    record["discovery_usable_prefix"] = safety.get("prefix")
    record["safe_loading_reconstructed"] = safety.get("rebuilt")
    record["complete_finite_verification_run"] = safety.get("complete", False)
    # The whole account of how the experiment was settled on: what the
    # failure responded to, what was tried, what was given up and how far the
    # endpoint finally sat from the failure that was observed.
    record["failure_mechanism"] = safety.get("failure_mechanism")
    record["segment_repair"] = safety.get("segment_repair")
    record["safety_distance"] = safety.get("safety_distance")
    record["coverage_given_up"] = safety.get("coverage_given_up")
    record["safe_loading_attempts"] = safety.get("attempts")
    if not safety.get("complete"):
        record["chosen_amplitude"] = 0.0
        # Only a run that PRODUCED a history and left its domain says
        # anything about the loading. A job that recorded nothing is a
        # statement about the build, and the rungs below can name it.
        if safety.get("reason"):
            record["refused"] = safety["reason"]
        else:
            record["did_not_run"] = safety.get("did_not_run", "")
        return manifest, record
    amplitude = safety.get("amplitude", amplitude)
    record["chosen_amplitude"] = amplitude
    return replace(manifest, loading=tuple(loading)), record


def probe_time_dependence(manifest: VerificationManifest, original: Path,
                          attempts_dir: Path, timeout: int, *,
                          amplitude: float, increments: int,
                          form: str = "", data_roots: Sequence[Path] = ()):
    """Two runs of the ORIGINAL that differ only in how much time passed.

    The slow one carries a hold, so relaxation and rate dependence cost two
    jobs between them rather than three. Same targets, same increments, so
    increment k of one is at the same strain as increment k of the other and a
    difference between their stresses is time dependence and nothing else.
    """
    def run(label: str, segments) -> tuple:
        trial = Path(attempts_dir) / label
        candidate = replace(manifest, loading=tuple(segments))
        try:
            report = run_one(manifest=candidate, timeout=timeout,
                             source=Path(original), job="original",
                             work_dir=trial, support_dir=None, form=form,
                             data_roots=data_roots)
        except Exception as exc:                    # noqa: BLE001
            return False, [], f"the job raised {type(exc).__name__}: {exc}"
        evidence = job_evidence(report)
        if not evidence.completed:
            return False, [], "; ".join(evidence.reasons) or "the job did not complete"
        return True, history_of(trial, "original"), ""

    pull = uniaxial(amplitude, increments)
    held = hold(pull, period=HOLD_PERIODS * pull.period, increments=increments)
    return probe_time(
        lambda: run("time_slow", [pull, held]),
        lambda: run("time_fast", [at_rate(pull, RATE_FACTOR)]),
        hold_from=increments)


def build_plan(manifest: VerificationManifest, original: Path, transformed: Path,
               work_dir: Path, timeout: int,
               form: str = "",
               data_roots: Sequence[Path] = ()) -> tuple[dict, dict]:
    """The two ``run_one`` calls, both carrying the very same manifest object.

    Returned as a pair rather than made at two call sites because the pair is
    the thing that has to be checked. The whole comparison rests on both builds
    being driven by one deck: if the original ran on one material vector and
    the transformed on another, ``compare_primal`` reports a disagreement that
    is the harness's and not the transform's, and -- far worse -- a matching
    pair of the wrong decks would report agreement about a model neither build
    was asked to compute.

    Only the source, the job name and the working directory differ. Neither
    call carries a support directory, because the transform's own modules are
    built and installed into the transformed job's directory before either job
    runs -- letting ``run_one`` build them again would compile them twice and
    would put the support rung of the ladder after a job that did not need to
    run. Nothing that reaches the deck differs, which ``require_one_manifest``
    then insists on.
    """
    common = {"manifest": manifest, "timeout": timeout,
              "data_roots": tuple(data_roots)}
    # The ORIGINAL is driven in the form the triage read off it. The
    # TRANSFORMED source is left to declare its own, because the transform --
    # not the triage -- decided what it emitted, and its suffix says so.
    original_call = dict(common, source=Path(original), job="original",
                         work_dir=Path(work_dir) / "original", support_dir=None,
                         form=form)
    transformed_call = dict(common, source=Path(transformed), job="transformed",
                            work_dir=Path(work_dir) / "transformed",
                            support_dir=None, form="")
    return original_call, transformed_call


def require_one_manifest(original_call: dict, transformed_call: dict) -> str:
    """Refuse to run two builds that would be handed different decks.

    Checked by identity first, because the same object cannot drift, and then
    by the text the deck generator produces from each -- which is what Abaqus
    will actually read. Returns the digest of that deck so the result record
    can name the question both builds were asked.
    """
    left, right = original_call["manifest"], transformed_call["manifest"]
    if left is right:
        return deck_digest(generate_deck(left))
    first, second = deck_digest(generate_deck(left)), deck_digest(generate_deck(right))
    if first != second:
        raise DifferentDecks(
            "the two builds would be driven by different decks "
            f"({first} and {second}), so any agreement between them would be "
            f"about two different questions")
    return first


def require_same_deck(original_text: str, transformed_text: str) -> str:
    """The decks Abaqus actually read, compared after the fact.

    ``require_one_manifest`` checks the intention; this checks the outcome, by
    reading back the two ``.inp`` files the runs wrote. It costs nothing and it
    is the only check that would survive somebody rewriting a deck between the
    two jobs.
    """
    first, second = deck_digest(original_text), deck_digest(transformed_text)
    if first != second:
        raise DifferentDecks(
            "the deck the original build ran is not the deck the transformed "
            f"build ran ({first} against {second}); the comparison between "
            f"them would be meaningless")
    return first


# ---------------------------------------------------------------------------
# the support units
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupportPlan:
    """Which of the transform's own units have to be compiled, and whether."""

    units: tuple[Path, ...] = ()
    build_required: bool = False
    refusal: str = ""


def support_plan(directory: Path, entry_source: Path) -> SupportPlan:
    """The stored transform's compile order, minus the file Abaqus builds itself.

    ``abaqus user=`` compiles the entry source, so building it here as well
    defines every routine in the file twice and the link fails on all of them
    at once. That exclusion is not optional, which is why it lives here rather
    than at the call site.
    """
    directory = Path(directory)
    if not (directory / "compile_order.txt").is_file():
        return SupportPlan(refusal=(
            "the stored transform carries no compile_order.txt, so the order "
            "its modules have to be built in is not recorded and the support "
            "cannot be built the way the UMAT will be"))
    units = compile_order(directory, exclude=Path(entry_source))
    if not units:
        return SupportPlan(build_required=False)
    return SupportPlan(units=tuple(units), build_required=True)


# ---------------------------------------------------------------------------
# reading a job
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobEvidence:
    """What one build did, read from the records Abaqus wrote."""

    completed: bool = False
    increments: Optional[int] = None
    converged_records: int = 0
    instrumented: bool = False
    warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    #: What the driver printed, kept only for a job that did not complete.
    #: Three entries left no .dat, no .msg and no .odb, so the compiler's own
    #: diagnostic on the console was the only evidence there was -- and this
    #: reduction dropped it. They were diagnosable afterwards only by
    #: reproducing the compile offline with each job's own flags, which
    #: happened to be possible and will not always be.
    console_tail: str = ""


def job_evidence(report: dict) -> JobEvidence:
    """One ``run_one`` report, reduced to what the ladder needs.

    ``completed`` is whatever ``classify_job`` decided from the .sta, .msg and
    .odb -- never the process exit code. Abaqus 2021 here aborts in its
    post-analysis wrap-up after writing that the analysis completed, and a
    control job with no user subroutine at all aborts identically, so treating
    the exit code as the verdict would have failed every job in the store. The
    abort survives as a warning, which is where a reader can see it.

    ``run_one`` reports two kinds of warning under two keys: the job status's
    own tuple, and a single string for a build whose probe found no call site.
    Both are gathered here. The second one matters more than it looks: a build
    with no probe records still runs and still completes, and reading only the
    tuple left the batch with a completed job, an empty history, and nothing
    saying why.
    """
    warnings = list(report.get("warnings") or ())
    if report.get("warning"):
        warnings.append(str(report["warning"]))
    return JobEvidence(
        completed=bool(report.get("completed")),
        increments=report.get("increments"),
        converged_records=int(report.get("converged_records") or 0),
        instrumented=bool(report.get("instrumented")),
        warnings=tuple(warnings),
        reasons=tuple(report.get("reasons") or ()),
        console_tail=str(report.get("console") or ""),
    )


def history_of(work_dir: Path, job: str) -> list[dict]:
    """The converged records one build wrote, as run_one saved them."""
    path = Path(work_dir) / f"{job}_history.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return converged_only(parse_probe(Path(work_dir) / f"{job}_probe.txt"))


def corrupt_records(history: Sequence[dict]) -> list[str]:
    """Reasons any record in this history could not be read.

    A record carrying one was written after something wrote over an argument
    Abaqus passes in -- Fortran printed asterisks where NSTATV should have been
    -- so the numbers beside it are not measurements and must not be compared
    as if they were.

    A finding about the run, not about this harness, and reported without a
    cause it cannot support. On the source that raised it first, the paired
    deck's *DEPVAR, the source's highest literal STATEV subscript and its
    constant count all agree, so an undersized state array does not explain it;
    a computed subscript or an overrun local array would look identical from
    here. What can be said is that the run damaged its own interface.
    """
    return [str(record[CORRUPT]) for record in history if CORRUPT in record]


# ---------------------------------------------------------------------------
# the tangent
# ---------------------------------------------------------------------------


def choose_probe_record(records: Sequence[dict]) -> Optional[tuple[int, dict]]:
    """The converged record the tangent is checked at, and its position.

    It has to carry both a DDSDDE -- the value under test -- and the ENTRY
    state the increment began from, because the reference is the original
    source replayed from that exact state. A record missing either cannot be
    replayed, and a record that cannot be replayed is skipped rather than
    replayed from a state made up to fill the gap.

    The last such record is taken: it is the furthest along the loading path,
    which for a path-dependent model is where the tangent is least likely to be
    the elastic one that every build gets right.
    """
    for position in range(len(records) - 1, -1, -1):
        record = records[position]
        if record.get("DDSDDE") and record.get("entry"):
            return position, record
    return None


#: A comparison over fewer increments than this establishes too little to
#: rest a verification on, however well those increments agree.
MINIMUM_COMPARABLE_INCREMENTS = 5

#: How many states must yield a measurable difference before a
#: tangent may be called verified. Two, not one: one step cannot
#: separate a regime from a coincidence, and one STATE cannot
#: separate an elastic tangent every build gets right from a
#: converted one that is right everywhere.
MINIMUM_MEASURED_STATES = 2


def common_finite_prefix(original: list, transformed: list,
                         expected_points: int = 0
                         ) -> tuple[list, list, int, dict]:
    """The leading COMPLETE INCREMENTS in which both builds produced numbers.

    Increments, not records. Abaqus calls a UMAT once per material point per
    increment, so a single-element C3D8 job writes eight records per
    increment and a CPE4 four; this used to cut the histories at a raw record
    position and report it as an increment count, which said "agreed over 280
    increments" about a thirty-five increment analysis and let a prefix of
    two complete increments clear a minimum of five. See
    :mod:`umat_oti.abaqus.frames`.

    A model can leave its own domain part-way along a path. Measured on
    BodyForce-Growth-2Stages.for: both builds walk two complete increments
    and then BOTH return values that are not numbers inside the third, at the
    same increment and in the same material point. That is the growth model
    declining to be driven that far, and it says nothing about the
    conversion.

    What comes back is that common prefix, the number of COMPLETE INCREMENTS
    in it, and both histories' grouping so the caller can report what it
    actually compared. The truncation is only ever applied where BOTH stopped
    at the same increment: a converted build that goes non-finite where the
    original did not is the defect this pipeline exists to catch, and it must
    keep failing.

    Truncating is for diagnosis. It does not make a verdict: a verification
    rests on an analysis that is finite throughout, which
    :mod:`umat_oti.abaqus.safe_loading` is what builds.
    """
    left = frames.group(original, expected_points)
    right = frames.group(transformed, expected_points)
    grouping = {"original": left.as_dict(), "transformed": right.as_dict()}
    # -1 means ONLY "no truncation was applied". Whether the histories are
    # finite is a separate question and is answered separately: conflating
    # the two reported complete_finite_verification_run = True for ten
    # HelixUp entries whose ORIGINAL build carries NaN in all six stresses
    # of 72 of its 80 records, because the two builds parted company at
    # different increments and the "they diverged" branch returns -1 too.
    grouping["both_finite_throughout"] = bool(left.complete and right.complete)
    if left.complete and right.complete:
        return list(original), list(transformed), -1, grouping
    if left.complete_increments != right.complete_increments:
        # They parted company. Hand back the histories whole so the ordinary
        # comparison reports it, which is what should happen -- and it is NOT
        # a finite pair.
        return list(original), list(transformed), -1, grouping
    return left.prefix(), right.prefix(), left.complete_increments, grouping


def first_activated(records: Sequence[dict]) -> Optional[int]:
    """The index at which the material first did something.

    Read from the history the ORIGINAL produced, so the states either side of
    it can be chosen deliberately rather than landing on it by accident.
    """
    from umat_oti.abaqus.state_regime import activated_by

    for position in range(1, len(records)):
        if activated_by(records, position):
            return position
    return None


def choose_states_around_activation(records: Sequence[dict],
                                   each_side: int = 2) -> list[tuple[int, dict]]:
    """Smooth states on both sides of the transition, and none sitting on it.

    Bracketing where a material activates is not the same as verifying it.
    Measured on From-2D-to-2D-Axe.for: discovery found activation at 2.5e-05
    and the verification then evaluated at that amplitude, so every state sat
    at or past the transition and the centred difference was a chord across a
    corner at all three.

    So the transition is found first and then AVOIDED. States are taken from
    the interior of each side -- the increment either side of the transition
    is where a perturbation is most likely to cross it, so the selection steps
    away from the boundary rather than up to it.

    Falls back to the even spread when nothing activates, which for a linear
    elastic material is the whole of the material.
    """
    replayable = [(position, record) for position, record in enumerate(records)
                  if record.get("DDSDDE") and record.get("entry")]
    if not replayable:
        return []
    turn = first_activated(records)
    if turn is None:
        return choose_probe_records(records, wanted=2 * each_side)

    # One increment of clearance either side: the perturbation at a state
    # immediately adjacent to the transition is the one most likely to step
    # across it.
    before = [pair for pair in replayable if pair[0] < turn - 1]
    after = [pair for pair in replayable if pair[0] > turn + 1]

    def spread(pairs, count):
        if len(pairs) <= count:
            return list(pairs)
        stride = max(1, len(pairs) // count)
        return list(pairs[::stride])[:count]

    chosen = spread(before, each_side) + spread(after, each_side)
    if not chosen:
        return choose_probe_records(records, wanted=2 * each_side)
    return sorted(chosen, key=lambda pair: pair[0])


def choose_probe_records(records: Sequence[dict],
                         wanted: int = 3) -> list[tuple[int, dict]]:
    """Several states along the loading path, not one.

    A tangent checked at a single increment is a tangent checked in a single
    regime. On a path-dependent model the last increment is usually the
    plastic one and the first is usually elastic, and a transform can be right
    about one and wrong about the other -- an elastic tangent is the part every
    build gets right, so agreement there is the weakest evidence available.

    So: the last replayable record, the first, and the ones between them,
    spread evenly. All of them have to agree for the tangent to be verified,
    which is strictly stronger than the single-record rule it replaces and
    cannot pass anything that rule would have failed.

    A record has to carry both a DDSDDE and the ENTRY state its increment
    began from; one missing either cannot be replayed, and is skipped rather
    than replayed from a state made up to fill the gap.
    """
    replayable = [(position, record)
                  for position, record in enumerate(records)
                  if record.get("DDSDDE") and record.get("entry")]
    if not replayable:
        return []
    wanted = max(1, int(wanted))
    if len(replayable) <= wanted:
        return replayable
    # The last is always included: it is furthest along the path. The rest are
    # spread over what precedes it, first included.
    last = replayable[-1]
    if wanted == 1:
        return [last]
    head = replayable[:-1]
    stride = max(1, len(head) // (wanted - 1))
    picked = head[::stride][:wanted - 1]
    return picked + [last]


def oti_tangent(record: dict, ntens: int) -> list[list[float]]:
    """DDSDDE from a probe record, in the shape the probe wrote it.

    The probe writes ``((DDSDDE(I,J),J=1,NTENS),I=1,NTENS)``, so the flat block
    is row by row. Reading it the other way round would transpose the tangent,
    which is invisible for a symmetric material and wrong for every UNSYMM one.
    """
    flat = [float(value) for value in (record.get("DDSDDE") or ())]
    if len(flat) < ntens * ntens:
        return []
    return [flat[row * ntens:(row + 1) * ntens] for row in range(ntens)]


def perturbation_scale(entry: dict) -> float:
    """The size of the kinematic increment the difference steps are relative to.

    A relative ladder means the same sweep says the same thing for a model
    loaded to a percent of strain and one loaded to a millionth.

    Two things this has to survive, both measured on the last batch.

    A NON-FINITE component. ``max`` over values containing NaN returns NaN,
    and ``largest or 1.0`` then returns the NaN rather than the fallback,
    because NaN is truthy. Every step became NaN, every perturbed replay
    returned nothing, and the row was recorded as a tangent that could not be
    verified. Fifty states of one batch died this way. Only finite magnitudes
    are considered now, and a NaN in the record no longer decides the scale.

    A GRADIENT-DRIVEN source, whose DSTRAN is all zeros because its kinematic
    input is the deformation gradient. The old fallback then returned 1.0 --
    a strain scale of one hundred percent -- so the sweep stepped far outside
    any regime the model was in. The deformation increment is the distance of
    DFGRD1 from the identity, which is the same physical quantity expressed
    the other way, so that is used before falling back.

    The final fallback stays 1.0: an increment of exactly zero would make
    every step zero, and a sweep of zeros measures nothing.
    """
    def largest_finite(values) -> float:
        magnitudes = [abs(float(value)) for value in (values or ())
                      if math.isfinite(float(value))]
        return max(magnitudes, default=0.0)

    strain = largest_finite(entry.get("DSTRAN"))
    if strain:
        return strain

    # DFGRD1 is written row by row, so the diagonal is at 0, 4 and 8.
    gradient = [float(value) for value in (entry.get("DFGRD1") or ())
                if math.isfinite(float(value))]
    if len(gradient) >= 9:
        deviation = max(abs(value - (1.0 if index in (0, 4, 8) else 0.0))
                        for index, value in enumerate(gradient[:9]))
        if deviation:
            return deviation
    return 1.0


def replay_flags(form: str, work_dir: Path) -> tuple[str, ...]:
    """gfortran flags for replaying a source in the form the triage found it in.

    The form is not cosmetic: compiling fixed-form Fortran as free-form turns
    every continuation line into a syntax error, and the replay then reports a
    build failure that is the harness's and not the source's.

    But it must not be forced GLOBALLY, because more than one file is on the
    command line. The replay driver is free-form ``.f90`` and the UMAT beside
    it is usually fixed-form ``.for``; a global ``-ffixed-form`` compiled the
    driver as fixed and gfortran rejected every line of it with "Non-numeric
    character in statement label", so four entries that had already agreed on
    their primal histories in Abaqus were recorded as tangent failures. The
    length limits are per-form and harmless to the other, so only they are
    passed and gfortran infers each file's form from its suffix -- which is
    what the offline gate has always done, and why it did not hit this.
    """
    return ("-ffixed-line-length-132", "-ffree-line-length-none",
            "-std=legacy", "-O2", "-w", f"-J{Path(work_dir)}")


def tangent_verdict(comparison: dict, *, tolerance: float = TANGENT_TOLERANCE,
                    minimum_plateau: int = MINIMUM_PLATEAU) -> tuple[bool, str]:
    """Did the step ladder actually pin this tangent down?

    The best step has to agree to the tolerance, and that agreement has to be
    corroborated by more than one step -- one step cannot tell a truncation
    error from a cancellation one, and a single step landing on the right
    answer while its neighbours do not is the signature of a coincidence.

    Corroboration comes in two shapes, and only one of them was accepted
    before. The usual one is a plateau: the error falls as the step shrinks,
    bottoms out, and rises again as cancellation takes over, so several steps
    sit within an order of magnitude of the best. That is what a nonlinear
    model gives.

    The other shape is a sweep with no truncation regime at all, where the
    error is already at round-off at the largest step and grows monotonically
    as the step shrinks. That is what an EXACT tangent on a locally linear
    model gives -- the centred difference has no truncation error to lose, so
    only cancellation is left. Its plateau is one step wide by construction,
    and requiring two rejected it. Measured on
    BristolCompositesInstitute__abaci: 8.08e-14 at 1e-3 rising monotonically
    to 5.49e-09 at 1e-8, six steps every one of which agrees to better than
    1e-8, recorded as "the difference agreed at 1 step size".

    So a sweep in which EVERY step agrees within the tolerance also
    corroborates. That is not a weaker test than the plateau -- it is
    strictly stronger, because it asks of every step what the plateau asks of
    the best one. The tolerance itself is unchanged.
    """
    sweep = list(comparison.get("sweep") or ())
    if not sweep:
        zeroed = int(comparison.get("zero_difference_steps") or 0)
        if zeroed:
            return False, (
                f"the finite difference was identically zero at all {zeroed} "
                f"step sizes: the forward and backward replays returned the "
                f"same stress, so the perturbation moved nothing and the "
                f"tangent was never measured. This is a statement about the "
                f"reference, not about the transform")
        return False, "no step size produced a difference to compare against"
    best = comparison.get("best_relative")
    frobenius = comparison.get("best_frobenius")
    if best is None or frobenius is None:
        return False, "the sweep recorded no best step"
    if best > tolerance:
        return False, (f"the closest step agreed only to {best:.3e}, against a "
                       f"tolerance of {tolerance:.0e}")

    # A point with no recorded error is not evidence of agreement, on either
    # side. Defaulting the missing frobenius to 0.0 put such a point INSIDE the
    # plateau -- the absence of a measurement counted as a perfect one -- and
    # defaulting the missing relative error the same way would do it again.
    # Both read as failing instead.
    threshold = 10.0 * frobenius if frobenius > 0 else 0.0
    plateau = [point["step"] for point in sweep
               if "step" in point
               and point.get("frobenius", float("inf")) <= threshold]
    agreeing = [point["step"] for point in sweep
                if "step" in point
                and point.get("relative", float("inf")) <= tolerance]

    if len(plateau) >= minimum_plateau:
        return True, (f"agreed to {best:.3e} over a plateau of {len(plateau)} "
                      f"step sizes, {min(plateau):g} to {max(plateau):g}")
    # Corroboration by independent step sizes, whether or not they are
    # contiguous and whether or not EVERY step agrees.
    #
    # The rule above asks for a plateau: several steps within 10x the best
    # Frobenius error. That is the shape a nonlinear model gives. The clause
    # that used to follow demanded the opposite extreme -- agreement at every
    # step in the sweep -- and between the two sat the commonest shape of all,
    # which neither accepted. Measured on PureGravity.for:
    #
    #     1e-3  9.92e-11 | 1e-4  6.93e-10 | 1e-5  1.06e-08
    #     1e-6  1.08e-07 | 1e-7  7.04e-07 | 1e-8  5.79e-06
    #
    # Five of six steps agree, four of them by three orders of magnitude or
    # better, spanning four decades of perturbation size -- and it was
    # rejected, because the plateau counts 1 (6.93e-10 is 7x the best, and the
    # threshold is 10x the best FROBENIUS, which lands at 1.5x here) and the
    # smallest step has lost too much to cancellation for "every step" to hold.
    # Thirty-three rows in one batch agreed to 1e-6 or better -- some to
    # 6e-11 -- and were reported as unverified for this reason alone.
    #
    # The tolerance is untouched: every step counted here still had to agree
    # within it. What changes is only which ARRANGEMENT of agreeing steps
    # counts as corroboration, and the criterion is the one this function's
    # own docstring states -- more than one step, so that truncation error and
    # cancellation error can be told apart.
    #
    # The span requirement is an addition, not a relaxation. Two neighbouring
    # steps can both sit inside one cancellation regime; two steps a decade or
    # more apart cannot, because the two error terms scale oppositely in h.
    if len(agreeing) >= minimum_plateau:
        decades = math.log10(max(agreeing) / min(agreeing)) if min(agreeing) > 0 else 0.0
        if decades >= 1.0:
            return True, (
                f"agreed to {best:.3e} at the best step and within "
                f"{tolerance:.0e} at {len(agreeing)} of {len(sweep)} step "
                f"sizes, {min(agreeing):g} to {max(agreeing):g}: "
                f"{decades:.0f} decades of perturbation size, over which "
                f"truncation and cancellation error scale oppositely, so "
                f"agreement at both ends is not one regime flattering itself")
        return False, (
            f"the difference agreed to {best:.3e} at {len(agreeing)} step "
            f"size(s), but they span only {decades:.1f} decades "
            f"({min(agreeing):g} to {max(agreeing):g}); steps that close "
            f"together can sit inside a single cancellation regime")
    return False, (f"the difference agreed at {len(plateau)} step size(s) on a "
                   f"plateau and at {len(agreeing)} of {len(sweep)} overall; "
                   f"{minimum_plateau} are required, because one step cannot "
                   f"separate truncation error from cancellation")


#: How closely a ONE-SIDED difference has to match the OTI tangent. Looser
#: than the centred tolerance, and it has to be: a one-sided difference is
#: accurate to O(h), not O(h^2), so at a relative step of 1e-4 its own
#: truncation error is of order 1e-4 times the curvature. The tolerance is
#: therefore not what does the work here -- the CONVERGENCE is. See
#: one_sided_verdict.
ONE_SIDED_TOLERANCE = 1e-3

#: How many step reductions have to improve the agreement before a one-sided
#: difference is believed. Two: a first-order error falls by ten for every
#: decade, so two consecutive decades of improvement is a measured order, and
#: one could be a coincidence.
ONE_SIDED_IMPROVEMENTS = 2


def one_sided_verdict(comparison: dict, *,
                      tolerance: float = ONE_SIDED_TOLERANCE,
                      improvements: int = ONE_SIDED_IMPROVEMENTS
                      ) -> tuple[bool, str]:
    """Did a ONE-SIDED difference converge onto the OTI tangent?

    Asked only where the centred difference is the wrong reference, which is
    at a corner: the forward perturbation grows the plastic strain or the
    damage and the backward one unloads elastically, so their average is the
    slope of a chord across the corner and is not a derivative of anything.
    A rate-independent inelastic model has such a corner at EVERY increment of
    a monotonically loading path, and the consistent tangent Abaqus asks for
    is precisely the derivative along the branch the increment took.

    A one-sided difference converges at first order, so the evidence is not a
    plateau -- it is a slope. The error must FALL as the step falls, over at
    least ``improvements`` reductions, and reach the tolerance. A number that
    agrees at one step and does not improve as the step shrinks is not
    converging on anything, and the tolerance alone would have accepted it.
    """
    sweep = [point for point in (comparison.get("sweep") or ())
             if point.get("relative") is not None
             and math.isfinite(float(point["relative"]))]
    if len(sweep) < improvements + 1:
        return False, (f"only {len(sweep)} step size(s) produced a one-sided "
                       f"difference; {improvements + 1} are needed to see "
                       f"whether it converges")
    ordered = sorted(sweep, key=lambda point: -float(point["step"]))
    best = min(float(point["relative"]) for point in ordered)
    if best > tolerance:
        return False, (f"the closest one-sided step agreed only to {best:.3e}, "
                       f"against a tolerance of {tolerance:.0e}")
    falling = 0
    for earlier, later in zip(ordered, ordered[1:]):
        if float(later["relative"]) < float(earlier["relative"]):
            falling += 1
        else:
            break
    if falling < improvements:
        return False, (f"the one-sided difference agreed to {best:.3e} but "
                       f"improved over only {falling} step reduction(s); a "
                       f"first-order difference that is converging improves at "
                       f"every one until cancellation takes over")
    span = [float(point["step"]) for point in ordered[:falling + 1]]
    first, last = ordered[0], ordered[falling]
    try:
        order = (math.log10(float(first["relative"]) / float(last["relative"]))
                 / math.log10(float(first["step"]) / float(last["step"])))
    except (ValueError, ZeroDivisionError):       # pragma: no cover - defensive
        order = 0.0
    return True, (f"agreed to {best:.3e}, improving over {falling} step "
                  f"reductions from {max(span):g} to {min(span):g} at observed "
                  f"order {order:.2f} -- which is what a first-order one-sided "
                  f"difference converging on a derivative does")


# ---------------------------------------------------------------------------
# resuming
# ---------------------------------------------------------------------------


#: Console signatures of a run that broke for reasons outside the model: a
#: shared licence server that made the job wait past the timeout, an Abaqus
#: that is not on PATH, a killed process. The licence server this runs against
#: is contended and multi-minute waits have been measured, so this is the
#: normal way a long batch loses an entry.
_HARNESS_SIGNATURES = (
    "TIMEOUT", "TimeoutExpired", "FileNotFoundError", "OSError",
    "PermissionError", "is not on PATH", "abaqus: command not found",
    "No licenses available", "licence", "license server", "flexlm",
    "Killed", "Aborted by system", "MemoryError",
)


def timed_out(report: dict) -> bool:
    """Did this run end because its clock ran out, rather than for a reason?

    The runner turns a TimeoutExpired into console='TIMEOUT'; a hung solver
    also leaves none of its own files behind, because it never got past the
    increment it was sitting in.
    """
    console = str(report.get("console") or "")
    if "TIMEOUT" in console or "TimeoutExpired" in console:
        return True
    reasons = " ".join(str(r) for r in (report.get("reasons") or ()))
    return (not report.get("converged_records")
            and ".sta was not written" in reasons)


def looks_like_a_harness_failure(report: dict) -> str:
    """Why this run says nothing about the model, or "" when it does.

    A job that produced no solver records at all, whose console carries a
    timeout or a missing binary or a licence wait, is a statement about this
    machine. Recording it as ``original_job_failed`` attributes a licence
    problem to somebody's UMAT -- and because every rung of the ladder is
    settled, ``--resume`` then served that verdict for as long as the results
    file lived, reproducing it verbatim instead of retrying.
    """
    if report.get("completed"):
        return ""
    if report.get("converged_records"):
        return ""              # it ran and produced records; that is the model
    console = " ".join(str(report.get(key) or "")
                       for key in ("console", "log", "warning"))
    reasons = " ".join(str(r) for r in (report.get("reasons") or ()))
    haystack = f"{console} {reasons}"
    for signature in _HARNESS_SIGNATURES:
        if signature.lower() in haystack.lower():
            return (f"the run broke before it could say anything about the "
                    f"model: {signature!r} in the solver console. Recorded as "
                    f"a harness error so a later --resume retries it")

    # A solver that wrote none of its own files did not reach the material.
    # Abaqus writes a .sta and a .msg as it goes and a .dat while reading the
    # input, so a run missing every one of them never started -- the process
    # was killed, or it was still waiting for a licence token when its timeout
    # elapsed. Measured here: a job cut off during a licence wait left only the
    # .inp and the .com behind, with an empty console, so no signature above
    # matched and the entry was recorded as original_job_failed -- a claim
    # about somebody's UMAT for a queue this machine was waiting in.
    #
    # A genuine failure looks different. A user subroutine that will not
    # compile puts the compiler's diagnostic in the console and the .log; a
    # model that diverges gets a .sta and a .msg full of cutbacks. Both leave
    # evidence, and both stay findings.
    absent = sum(1 for marker in (".sta was not written", ".msg was not written",
                                  ".dat", ".odb")
                 if marker in reasons)
    if absent >= 3 and not _carries_a_diagnostic(console):
        return ("the solver wrote none of its own files and reported no error, "
                "so it never reached the material: the process was killed or "
                "was still waiting for a licence when its timeout elapsed. "
                "Recorded as a harness error so a later --resume retries it")
    return ""


#: What a real failure leaves in the console. Abaqus prefixes its own with
#: ***ERROR or ***FATAL; ifort and gfortran prefix theirs with "error #" or
#: "Error:". Requiring the console to be *empty* instead was too strict: the
#: launcher prints its ordinary banner on every run, so a job killed during a
#: licence wait had a non-empty console with nothing wrong in it, and the
#: entry was recorded as a failure of the model.
_DIAGNOSTIC_MARKERS = ("***ERROR", "***FATAL", "Abaqus Error", "Abaqus/Analysis",
                       "error #", "Error:", "catastrophic error", "undefined reference")


def _carries_a_diagnostic(console: str) -> bool:
    """Does this console say something went wrong, as opposed to nothing at all?"""
    text = str(console or "")
    return any(marker.lower() in text.lower() for marker in _DIAGNOSTIC_MARKERS)


def is_terminal(stage: str) -> bool:
    """Is this a settled result, or a run that has to be done again?

    Every rung of the ladder is settled, including ``needs_material_data``:
    it is a finding in its own right and re-running it changes nothing while
    the deck and the source stay as they are.

    A harness error is not settled. It says the run broke, not the model, and
    the commonest cause here is a shared licence server making a job wait past
    its timeout -- a machine-state artifact that must not become a published
    finding about a UMAT. A resumed batch does those again.

    The off-ladder verdicts are settled too. ``not_a_umat``,
    ``incomplete_or_corrupt_source`` and ``external_dependency_unavailable``
    are statements about the file rather than about how far it got, and none of
    them changes while the file does not.
    """
    return stage in STAGES or stage in TERMINAL_OFF_LADDER


def previous_outcomes(path: Path) -> dict[str, str]:
    """Store key to recorded stage, from a previous results file.

    Keyed by the STORE key, not by the source, and that is load-bearing. The
    store key digests the source identity, the source bytes and a fingerprint
    of the transform code together, so a results file written before a change
    to the transform matches nothing afterwards and the whole batch re-runs.
    Keying on the source would have quietly served yesterday's verdict about
    code that no longer exists.
    """
    return {str(record["key"]): str(record["stage"])
            for record in previous_records(path)
            if record.get("key") and record.get("stage")}


def should_skip(key: str, previous: dict[str, str], resume: bool,
                retry: Sequence[str] = ()) -> bool:
    """Has this exact entry already been carried to a settled outcome?

    ``retry`` names stages a resumed run must do again anyway. The use for it
    is a fix to the harness: a run that recorded ``tangent_not_verified``
    under a coverage rule that has since been corrected has a settled outcome
    that is settled about the old rule. Re-running only those entries costs
    what they cost; re-running the batch costs what all of it cost, and
    leaving them costs the truth.
    """
    stage = previous.get(key, "")
    if retry and stage in set(retry):
        return False
    return bool(resume) and is_terminal(stage)


def previous_records(path: Path) -> list[dict]:
    """Every record a previous results file holds, in the order written.

    A line that will not parse is dropped and the rest are kept: a batch killed
    mid-write leaves a truncated last line, and losing every hour of Abaqus
    before it over that is exactly what --resume exists to prevent.
    """
    records: list[dict] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue          # a half-written line from a crashed batch
    return records


def merge_records(previous: Sequence[dict], fresh: Sequence[dict]) -> list[dict]:
    """One record per store key, the latest written winning.

    A resumed batch appends to the file it read, so the same key can appear
    twice -- once skipped, once re-run. Counting both would inflate the
    denominator, which is exactly the kind of silent change of denominator this
    project refuses.
    """
    merged: dict[str, dict] = {}
    for record in list(previous) + list(fresh):
        key = str(record.get("key") or record.get("source") or id(record))
        merged[key] = record
    return list(merged.values())


# ---------------------------------------------------------------------------
# selection and accounting
# ---------------------------------------------------------------------------


def restrict_to_gate(entries: Sequence[Any], report_path: Path,
                     ) -> tuple[list[Any], dict[str, int]]:
    """Only the entries an offline gate decided AGREED, and why the rest went.

    The gate costs seconds per source and an Abaqus pair costs minutes against
    a shared, contended licence server, so a source whose two builds already
    disagree at one material point -- or whose transform returns NaN there --
    should be fixed before it is given a token. Twenty-seven of the store's
    entries return a non-finite stress offline; queueing those would spend
    hours establishing what a five-second build already said.

    What is dropped is reported by the gate's own verdict rather than merely
    counted, because "not queued" is not a verification outcome and must never
    be read as one. An entry the gate could not decide is not in this batch's
    denominator at all; it is in the gate's.
    """
    import json as _json

    try:
        report = _json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"could not read the gate report: {error}") from None
    verdicts = {str(row.get("source_id") or ""): str(row.get("outcome") or "")
                for row in report.get("entries") or report.get("rows") or []}
    earned, dropped = [], Counter()
    for entry in entries:
        outcome = verdicts.get(entry.source_id, "not in the gate report")
        if outcome == "agreed":
            earned.append(entry)
        else:
            dropped[outcome] += 1
    return earned, dict(dropped)


def select_entries(entries: Sequence[Any], only: str = "", limit: int = 0
                   ) -> list[Any]:
    """The entries this run will attempt, filtered by identity and count.

    ``only`` matches against the source's path within the cache, never its
    basename: eighteen UMATs here share a basename with something else, and a
    filter on basenames selects files from other projects.
    """
    chosen = [entry for entry in entries
              if not only or only in str(getattr(entry, "source_id", ""))]
    return chosen[:limit] if limit else chosen


def summarise(records: Sequence[dict]) -> dict[str, Any]:
    """Counts by stage and the verified list, over every entry attempted.

    The denominator is ``len(records)``: every entry this batch touched,
    including the ones with no material data and the ones the harness crashed
    on. ``counted`` is asserted equal to it in the printed summary, so a stage
    that stops being counted shows up as an inconsistency rather than as a
    better-looking rate.
    """
    counts = Counter(str(record.get("stage") or HARNESS_ERROR)
                     for record in records)
    ordered = {stage: counts[stage] for stage in STAGES if counts[stage]}
    for stage in sorted(set(counts) - set(STAGES)):
        ordered[stage] = counts[stage]
    verified = sorted(str(record.get("source") or "")
                      for record in records if record.get("stage") == VERIFIED)
    return {
        "attempted": len(records),
        "counted": sum(ordered.values()),
        "by_stage": ordered,
        "verified": verified,
        "verified_count": len(verified),
        "note": ("every entry attempted is in the denominator, including those "
                 "with no material data. Only entries at the 'verified' stage "
                 "passed the primal comparison and a converged tangent sweep."),
    }


def scrub(value: Any, *roots: Path) -> Any:
    """Every string in a record, with this machine's directories named instead.

    A compiler quotes the absolute path of every file it was handed and a
    traceback quotes the absolute path of every frame, so a blocker copied
    verbatim puts someone's home directory into committed evidence. The
    repository audit fails the build on exactly that.
    """
    if isinstance(value, str):
        return without_machine_paths(value, *roots)
    if isinstance(value, dict):
        return {key: scrub(item, *roots) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, *roots) for item in value]
    return value


# ---------------------------------------------------------------------------
# running one entry
# ---------------------------------------------------------------------------


def _material_columns(plan: ManifestPlan) -> dict[str, Any]:
    manifest = plan.manifest
    return {
        "deck": plan.deck,
        "material_block": plan.material_block,
        "material_provenance": manifest.material_provenance if manifest else "",
        "props_count": len(manifest.props) if manifest else 0,
        "nstatv": manifest.nstatv if manifest else None,
        "unsymmetric": bool(manifest.unsymmetric) if manifest else None,
        "ntens": manifest.ntens if manifest else None,
        "element_type": manifest.element_type if manifest else "",
        "kinematics": manifest.kinematics if manifest else "",
        "kinematics_provenance": plan.kinematics_provenance,
        "kinematics_note": plan.kinematics_note,
        "entry_classification": plan.entry_classification,
        "formulation": plan.formulation,
        # The experiment the planner decided and why: the family, what drives
        # it, what would count as having exercised it, and the source lines
        # that settled each. The verdict gate reads the family back out of
        # this to ask the criterion that belongs to it.
        "experiment": plan.experiment,
        # Where constants were looked for, when none were found. A refusal
        # that does not say where it searched is a claim, not a finding.
        "searched_for_material_data": plan.searched,
    }


# ---------------------------------------------------------------------------
# the precision control
# ---------------------------------------------------------------------------


def run_precision_control(manifest: VerificationManifest, original: Path,
                          transformed: Path, transformed_history: Sequence[dict],
                          work_dir: Path, *, timeout: int, form: str = "",
                          data_roots: Sequence[Path] = (),
                          increments_compared: Optional[int] = None) -> dict:
    """Test the one explanation of a primal disagreement that can be tested.

    Fortran's default real is single precision, and an explicit ``REAL``
    declaration overrides the ``IMPLICIT REAL*8(A-H,O-Z)`` that
    ``aba_param.inc`` installs. A UMAT that declares ``REAL S(6)`` and copies
    the incoming stress into it rounds to seven digits where the converted
    build -- whose OTI type is built over doubles -- does not, and the two
    stress histories then differ by the author's own truncation.

    Reported as a primal disagreement that reads as "the conversion computes
    something else". So it is put to a run: the ORIGINAL source with exactly
    the declarations the transform promoted widened to ``REAL*8``, nothing
    else touched, driven through the same deck. Agreement there says the
    difference was the declared precision and says it in numbers; disagreement
    leaves the original verdict standing, now with one explanation ruled out.

    Nothing is loosened. The control is held to the same
    ``manifest.primal_tolerance`` the original comparison used, and the
    original-versus-converted difference stays in the record beside it.
    """
    from umat_oti.abaqus.precision import survey, widen

    outcome: dict[str, Any] = {"ran": False}
    try:
        original_text = Path(original).read_text(errors="replace")
        transformed_text = Path(transformed).read_text(errors="replace")
    except OSError as error:
        outcome["reason"] = f"the sources could not be read: {error}"
        return outcome

    finding = survey(original_text, transformed_text)
    outcome["finding"] = finding.as_dict()
    if not finding.explains_a_difference:
        outcome["reason"] = finding.reason
        return outcome

    control_text, changes = widen(original_text, finding)
    if control_text == original_text:                # pragma: no cover
        outcome["reason"] = "the widening changed nothing"
        return outcome
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    control_source = work_dir / f"control{Path(original).suffix or '.f'}"
    control_source.write_text(control_text, encoding="utf-8")
    outcome.update(source=str(control_source), changes=list(changes),
                   widened=list(finding.widened))

    report = run_one(manifest=manifest, timeout=timeout, source=control_source,
                     job="control", work_dir=work_dir, support_dir=None,
                     form=form, data_roots=data_roots)
    evidence = job_evidence(report)
    outcome["ran"] = True
    outcome["completed"] = evidence.completed
    outcome["warnings"] = list(evidence.warnings)
    if not evidence.completed:
        outcome["reason"] = (
            "the control build did not run, so the declared precision could "
            "not be ruled in or out: " + ("; ".join(evidence.reasons)
                                          or "no reason recorded"))
        return outcome

    control_history = history_of(work_dir, "control")
    # The control is compared over the same window the primal comparison used,
    # so the two numbers in the record are about the same increments.
    left = list(control_history)
    right = list(transformed_history)
    if increments_compared is not None:
        left, right = left[:increments_compared], right[:increments_compared]
    comparison = compare_primal(left, right,
                                tolerance=manifest.primal_tolerance,
                                near_zero_fraction=manifest.near_zero_fraction)
    outcome["comparison"] = comparison.as_dict()
    outcome["agrees"] = bool(comparison.agrees)
    if comparison.agrees:
        outcome["reason"] = (
            f"the original and the converted build differ because the original "
            f"declares {', '.join(finding.widened)} at single precision and the "
            f"OTI type is built over doubles. Put to a run: the original with "
            f"those declarations alone widened to REAL*8 agrees with the "
            f"converted build to "
            f"{comparison.worst_stress_relative:.3e} over "
            f"{comparison.increments} increments, so what the two builds "
            f"disagree about is the author's own rounding and not the model")
    else:
        outcome["reason"] = (
            f"widening {', '.join(finding.widened)} to REAL*8 did not account "
            f"for the difference: the control still differs from the converted "
            f"build by {comparison.worst_stress_relative:.3e}")
    return outcome


# ---------------------------------------------------------------------------
# what the compiler says about the author's own file
# ---------------------------------------------------------------------------


def diagnose_original(source: Path, cache_root: Path, work_dir: Path, *,
                      form: str = "", timeout: int = 900,
                      source_id: str = "") -> dict:
    """Why the ORIGINAL did not run, from the compiler rather than from silence.

    A job whose compile aborts writes no ``.sta``, no ``.msg`` and no ``.odb``,
    and that is indistinguishable from a solver that fell over -- so the ladder
    recorded both as ``original_job_failed``, a name that reads like this
    harness's fault whichever it was. It is measured here instead, by compiling
    the UNMODIFIED source with Abaqus's own compile line. Nothing this pipeline
    adds is present, so a failure cannot be ours.

    Three outcomes, and they are three different findings:

    ``incomplete_or_corrupt_source``
        the compiler rejected the text of the file. The author published
        something that does not build. Terminal, and external.
    ``external_dependency_unavailable``
        the file needs a module or an include that its repository did not
        publish beside it, and that a second acquisition pass did not find.
        Terminal, and external -- and the record names what is missing.
    ``""``
        the source compiles. Then the job's failure is about running, not
        about building, and the ladder's own verdict stands.
    """
    from umat_oti.abaqus.companions import repository_files, resolve
    from umat_oti.abaqus.data_files import stage as stage_data_files
    from umat_oti.abaqus.support import compile_one

    found = resolve(Path(source), repository_files(Path(source), cache_root))
    outcome: dict[str, Any] = {"companions": found.as_dict(),
                               "companions_reason": found.reason()}

    # A table the routine opens by name and that nobody published is data the
    # model runs on, and it is not here. Checked before the compiler, because
    # a source can compile perfectly and still abort in the element loop on
    # the first READ -- which is what eleven corpus entries did, leaving a
    # .msg whose last legible line was the file name it wanted.
    repository = (Path(cache_root) / Path(source_id).parts[0]
                  if source_id else Path(source).parent)
    staging = stage_data_files(Path(source), Path(work_dir) / "data",
                               roots=[repository])
    outcome["data_files"] = staging.as_dict()
    outcome["data_files_reason"] = staging.reason()
    if not staging.complete:
        outcome["verdict"] = EXTERNAL_DEPENDENCY_UNAVAILABLE
        outcome["reason"] = staging.reason()
        return outcome
    work_dir = Path(work_dir)
    check = compile_one(Path(source), work_dir / "compile", form=form,
                        timeout=timeout, extra_sources=found.order,
                        include_dirs=[lay_out_includes(found, work_dir / "inc")]
                        if found.include_files else ())
    # The compiler names the file it was given, which is an absolute path on
    # this machine. The record has to name it the way the corpus does.
    def _relative(text: str) -> str:
        return str(text).replace(str(Path(source)), str(source_id or Path(source).name)) \
                        .replace(str(Path(cache_root)) + "/", "")

    compiled = check.as_dict()
    compiled["reason"] = _relative(compiled.get("reason", ""))
    compiled["defects"] = [_relative(line) for line in compiled.get("defects", [])]
    compiled["log"] = _relative(compiled.get("log", ""))[-4000:]
    outcome["compile"] = compiled
    check_reason = compiled["reason"]
    if check.ok:
        outcome["verdict"] = ""
        outcome["reason"] = ("the unmodified source compiles with Abaqus's own "
                             "compile line, so what failed was the run and not "
                             "the build")
        return outcome
    if not found.complete:
        outcome["verdict"] = EXTERNAL_DEPENDENCY_UNAVAILABLE
        outcome["reason"] = found.reason()
        return outcome
    if check.missing_dependencies:
        outcome["verdict"] = EXTERNAL_DEPENDENCY_UNAVAILABLE
        outcome["reason"] = check_reason
        return outcome
    if check.source_is_malformed:
        outcome["verdict"] = INCOMPLETE_OR_CORRUPT_SOURCE
        outcome["reason"] = check_reason
        return outcome
    outcome["verdict"] = ""
    outcome["reason"] = check_reason
    return outcome


def diagnose_transformed(stored, work_dir: Path, *, form: str = "",
                         timeout: int = 900) -> dict:
    """Why the CONVERTED build did not run, from the compiler.

    The same question as for the original and a different answer: here a
    compile failure is ours. ``abaqus user=`` builds the converted source
    itself, and a build that aborts leaves no .sta, no .msg error count and no
    .odb -- which reads as "the converted build did not run" whether it failed
    to compile or failed to converge. Those need different work, and the
    compiler can tell them apart in seconds.
    """
    from umat_oti.abaqus.support import compile_one

    outcome: dict[str, Any] = {}
    entry = Path(stored.entry_source)
    check = compile_one(entry, Path(work_dir) / "compile", form=form,
                        timeout=timeout,
                        include_dirs=[Path(stored.directory)])
    compiled = check.as_dict()
    for name in ("reason", "log"):
        compiled[name] = str(compiled.get(name, "")).replace(
            str(Path(stored.directory)) + "/", "")
    compiled["defects"] = [str(line).replace(str(Path(stored.directory)) + "/", "")
                           for line in compiled.get("defects", [])]
    outcome["compile"] = compiled
    if check.ok:
        outcome["reason"] = ("the converted source compiles with Abaqus's own "
                             "compile line, so what failed was the run and not "
                             "the build")
    else:
        outcome["reason"] = (
            f"the transform emitted Fortran the compiler will not accept: "
            f"{compiled['reason']}")
    return outcome


def lay_out_includes(found, into: Path) -> Path:
    """The include files copied under the names the source asks for.

    ``include 'ttb/ttb_library.f'`` is a path relative to wherever the compiler
    looks, so the file has to be at ``ttb/ttb_library.f`` under a directory on
    the include path -- not merely present somewhere in the cache.
    """
    import shutil

    into = Path(into)
    for asked, path in (found.include_files or {}).items():
        target = into / asked
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(path, target)
        except OSError:                            # pragma: no cover - defensive
            continue
    return into


def run_association_control(manifest: VerificationManifest, original: Path,
                            original_history: Sequence[dict], work_dir: Path,
                            *, timeout: int, form: str = "",
                            data_roots: Sequence[Path] = (),
                            increments_compared: Optional[int] = None) -> dict:
    """How much this model's own answer moves when its arithmetic is reordered.

    Some sources disagree with their conversion by an amount no precision
    difference explains and no bug is visible in. Two things can do that. A
    local Newton solve converges to a slightly different iterate when its
    residual is computed in a different order, and the difference it leaves is
    the solve's own tolerance rather than anybody's mistake. And an
    ill-conditioned expression -- a difference of two nearly equal large
    numbers, which finite-strain kinematics is full of -- loses digits that
    depend on the order the operations were done in.

    Neither is a statement about the transform, and neither can be settled by
    choosing a tolerance. So it is measured: the ORIGINAL is compiled a second
    time with reassociation permitted where Abaqus's own line forbids it, run
    on the same deck, and compared with itself. What comes back is this
    model's sensitivity to operation order, in the same units as the
    disagreement under test.

    The transform is credited only when its difference is no LARGER than the
    model's own -- not merely of the same order. A difference that exceeds it
    is the transform's, and stays so.
    """
    from umat_oti.abaqus.support import (ARITHMETIC_LADDER,
                                         association_environment)

    outcome: dict[str, Any] = {"ran": False, "attempts": []}
    work_dir = Path(work_dir)
    best = None
    for name, flags in ARITHMETIC_LADDER:
        where = work_dir / name
        where.mkdir(parents=True, exist_ok=True)
        association_environment(where, flags)
        report = run_one(manifest=manifest, timeout=timeout,
                         source=Path(original), job="association",
                         work_dir=where, support_dir=None, form=form,
                         data_roots=data_roots)
        evidence = job_evidence(report)
        attempt: dict[str, Any] = {"how": name, "flags": list(flags),
                                   "completed": evidence.completed,
                                   "warnings": list(evidence.warnings)}
        if not evidence.completed:
            attempt["reason"] = ("; ".join(evidence.reasons)
                                 or "no reason recorded")
            outcome["attempts"].append(attempt)
            continue
        # Against the ORIGINAL, not against the conversion: what is being
        # measured is how far this model moves from ITSELF, which is the
        # yardstick the conversion's difference is then held against.
        left = list(history_of(where, "association"))
        right = list(original_history)
        if increments_compared is not None:
            left, right = left[:increments_compared], right[:increments_compared]
        baseline = compare_primal(left, right,
                                  tolerance=manifest.primal_tolerance,
                                  near_zero_fraction=manifest.near_zero_fraction)
        attempt["worst_stress_relative"] = baseline.worst_stress_relative
        attempt["worst_state_relative"] = baseline.worst_state_relative
        attempt["comparison"] = baseline.as_dict()
        outcome["attempts"].append(attempt)
        if best is None or (baseline.worst_stress_relative or 0.0) > (
                best.get("worst_stress_relative") or 0.0):
            best = attempt

    if best is None:
        outcome["reason"] = (
            "the original would not run with its arithmetic computed any other "
            "way, so its own sensitivity to how it is computed could not be "
            "measured: "
            + "; ".join(str(a.get("reason") or "") for a in outcome["attempts"]))
        return outcome
    outcome["ran"] = True
    outcome["how"] = best["how"]
    outcome["comparison"] = best.get("comparison")
    outcome["worst_stress_relative"] = best.get("worst_stress_relative")
    outcome["worst_state_relative"] = best.get("worst_state_relative")
    # A rebuild that reproduced the original bit for bit did not perturb this
    # model, so it says nothing about what the model does WITH a perturbation.
    # Reporting that as a sensitivity of zero presents an unmeasured quantity
    # as a measured one, and then rests a verdict on it: twenty-one of the
    # twenty-three surviving primal disagreements were told they differ "by
    # more than their own conditioning accounts for" on the strength of a
    # zero that was never a measurement.
    moved = float(best.get("worst_stress_relative") or 0.0)
    outcome["measured"] = bool(moved)
    if not moved:
        outcome["reason"] = (
            f"every way this harness has of computing the same mathematics "
            f"differently ({', '.join(name for name, _ in ARITHMETIC_LADDER)}) "
            f"reproduced the original bit for bit, so the model was never "
            f"perturbed and its sensitivity to being perturbed is unmeasured "
            f"-- not zero")
    return outcome


def _is_informative(record: dict, manifest: VerificationManifest,
                    history: Sequence[dict], original: Path,
                    discovery: dict,
                    experiment: Optional[dict] = None) -> tuple[Optional[bool], str]:
    """Did the experiment this verdict rests on exercise anything real?

    Three questions, all measured on the FROZEN run rather than on a probe,
    and each able to answer "not established" rather than guessing.

    Did the material do something -- the indicators the amplitude search
    uses, read off the run that was actually verified.

    Where the source declares a time scale of its own, how much of it did the
    experiment reach. Recorded as a number and a role, NOT as a pass mark: a
    detected symbol may be a growth normalisation, a relaxation time, a
    loading period or a numerical parameter, and a single fraction over all
    of those would be a threshold pretending to be a criterion.

    And is the response one the problem's own scales account for. Measured on
    BodyForce-Growth-2Stages.for: the growth genuinely developed -- STATEV(9),
    which the source documents as the norm of the growth tensor, ran 0.003125
    to 0.40625 -- and both builds agreed, and the derivative matched, and the
    peak stress was 1.575e13 against a single material constant of 1e8. A
    ratio of 157,500 is not a regime this material has, and an agreement
    reached there is not a verification of it.
    """
    said: list = []
    try:
        text = Path(original).read_text(errors="replace")
    except OSError:                                # pragma: no cover
        text = ""
    coverage = time_scale.covers(text, manifest.loading)
    record["time_scale_coverage"] = coverage.as_dict()
    said.append(coverage.reason)

    activation = detect_activation(list(history))
    record["activation_on_the_frozen_run"] = activation.as_dict()
    if activation.activated:
        said.append(f"the material is active over the run that was verified "
                    f"({', '.join(activation.fired)})")
    else:
        said.append("nothing in the run that was verified indicates the "
                    "material did anything: no state moved, no departure from "
                    "linearity, no tangent change")

    plausible = plausibility.examine(
        list(history), manifest.props, discovery.get("chosen_amplitude") or 0.0,
        discovery.get("attempts") or ())
    record["response_plausibility"] = plausible.as_dict()
    said.append(plausible.reason())

    # And the criterion this family actually carries. The generic detector
    # cannot certify itself: it fired on the withdrawn growth run, where the
    # quantity that moved was STATEV(9) holding TIME(2)+DTIME -- a clock, which
    # advances in every run by construction -- while the growth tensor in
    # STATEV(8) moved 3.75%. A growth experiment is informative when the GROWTH
    # developed, and only the family knows which slots those are.
    findings: tuple = ()
    family = _family_of(experiment)
    if family is not None:
        try:
            findings = assess(family, list(history), manifest, text,
                              amplitude=discovery.get("chosen_amplitude") or 0.0,
                              attempts=discovery.get("attempts") or ())
        except Exception as error:              # pragma: no cover - defensive
            record["coverage_error"] = f"{type(error).__name__}: {error}"
            findings = ()
    findings = _measured_instead_of_declared(findings, record)
    record["coverage"] = [finding.as_dict() for finding in findings]
    failed = [finding for finding in findings if finding.met is False]
    if failed:
        return False, "; ".join(
            said + [f.reason for f in failed])
    said.extend(f.reason for f in findings)

    if not plausible.checks:
        # Nothing supplied a scale to check against. That is not a failure and
        # it is not a pass: it is an unmeasured answer, and the ladder reads
        # it as one.
        return None, "; ".join(said)
    # A criterion the family carries but the run could not answer leaves the
    # whole question unestablished rather than passed.
    if any(finding.met is None for finding in findings):
        return None, "; ".join(said)
    return bool(activation.activated and plausible.plausible), "; ".join(said)


def _measured_instead_of_declared(findings, record: dict):
    """Replace a criterion that only declares itself with the run that made it.

    ``experiment.DECLARED_ONLY`` states the criteria that cannot be read off a
    single run's probe records -- objectivity needs the same path in a rotated
    frame, rate dependence needs the same path over two step periods. They come
    back as ``met=None`` by construction, which is honest for one run and wrong
    for a verdict: left alone, every finite-strain and rate-dependent entry
    would sit at ``informativeness_not_established`` forever on a question this
    harness never asked rather than one it could not answer.

    So where the harness DID run the second experiment, its result replaces the
    declaration. Where it did not, the declaration stands and the entry stays
    unestablished, which is the correct reading of an unasked question.
    """
    from umat_oti.abaqus.experiment import Finding

    objectivity = record.get("objectivity") or {}
    replaced = []
    for finding in findings:
        if finding.met is None and "rigid rotation" in finding.reason:
            if not objectivity.get("ran"):
                replaced.append(finding)
                continue
            agreed = objectivity.get("agreed")
            replaced.append(Finding(
                "objectivity under a superposed rotation",
                None if agreed is None else bool(agreed),
                objectivity.get("reason", ""),
                float(objectivity.get("worst_stress_relative") or 0.0)))
            continue
        if finding.met is None and "two different step periods" in finding.reason:
            rate = record.get("rate_dependence") or {}
            if rate.get("measured") is None:
                replaced.append(finding)
                continue
            replaced.append(Finding(
                "rate dependence over two step periods",
                bool(rate.get("measured")), str(rate.get("reason", "")),
                float(rate.get("relative") or 0.0)))
            continue
        replaced.append(finding)
    return tuple(replaced)


def _family_of(experiment: Optional[dict]):
    """The Family object the planner recorded, rebuilt from its dictionary.

    The record carries the plan as data so a results file can be read without
    importing this package; the gate needs the object back.
    """
    recorded = (experiment or {}).get("family") or {}
    name = str(recorded.get("name") or "")
    if not name:
        return None
    from umat_oti.abaqus.experiment import Family
    return Family(name, str(recorded.get("driver") or ""),
                  tuple(recorded.get("evidence") or ()),
                  tuple(recorded.get("notes") or ()))

def _family_name(experiment: Optional[dict]) -> str:
    return str(((experiment or {}).get("family") or {}).get("name") or "")


def _after_lead_in(records: Sequence[dict]) -> list[dict]:
    """The rotated run without its rotation step, renumbered to match the base.

    The lead-in is step 1 and carries no strain at all; the author's own path
    starts at step 2. Left in place it would be compared against the base run's
    first loading step, which is a different deformation.
    """
    kept = []
    for record in records:
        step = int(record.get("step") or 0)
        if step <= 1:
            continue
        moved = dict(record)
        moved["step"] = step - 1
        kept.append(moved)
    return kept


def _objective_response(base: Sequence[dict], turned: Sequence[dict],
                        rotation: Sequence[float]) -> dict:
    """Is the rotated run's stress the base run's stress rotated?

    ``sigma' = Q sigma Q^T``, component by component, over the increments both
    runs walked. This is a property of the AUTHOR's routine: a law that
    ignores DROT answers in the frame it was handed and gives a different
    tensor here. It is recorded because it is worth knowing about a published
    material, and it is kept apart from ``agreed`` -- which is the question
    about the transform -- so that a non-objective model is never reported as
    a conversion failure.
    """
    q = [list(rotation[0:3]), list(rotation[3:6]), list(rotation[6:9])]
    # Voigt (11, 22, 33, 12, 13, 23) to the full symmetric matrix and back.
    index = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))

    worst, corotational, compared = 0.0, 0.0, 0
    for before, after in zip(base, turned):
        left = before.get("STRESS") or []
        right = after.get("STRESS") or []
        if len(left) < 6 or len(right) < 6:
            # Fewer than six components means a 2D element, where the rotation
            # is in-plane and the out-of-plane row is untouched; the same
            # arithmetic applies but the missing components cannot be filled in
            # here without assuming which they are.
            continue
        sigma = [[0.0] * 3 for _ in range(3)]
        for slot, (row, column) in enumerate(index):
            sigma[row][column] = sigma[column][row] = float(left[slot])
        rotated_sigma = [
            [sum(q[i][a] * sigma[a][b] * q[j][b]
                 for a in range(3) for b in range(3)) for j in range(3)]
            for i in range(3)]
        scale = max((abs(value) for row in sigma for value in row), default=0.0)
        if scale <= 0.0:
            continue
        for slot, (row, column) in enumerate(index):
            worst = max(worst, abs(rotated_sigma[row][column]
                                   - float(right[slot])) / scale)
            # Abaqus hands a UMAT its stress in the CO-ROTATIONAL frame, which
            # turns with the material. Under a superposed rigid rotation that
            # frame turns too, so an objective routine returns the same
            # COMPONENTS -- not the components rotated. Both are measured
            # because which convention applies is a fact to be read off the
            # runs rather than asserted from the manual.
            corotational = max(corotational, abs(sigma[row][column]
                                                 - float(right[slot])) / scale)
            compared += 1

    if not compared:
        return {"objective": None,
                "objectivity_reason": ("no increment carried six stress "
                                       "components in both runs, so Q sigma "
                                       "Q^T could not be formed")}
    # The same tolerance the primal comparison uses would be too tight here:
    # the rotated run solves a different linear system and its equilibrium
    # iterates differ in the last digits. A part in 1e-6 of the stress field is
    # far below any real frame error, which is order one.
    #
    # This number only means anything if the rotated run really walked the same
    # strain path in a turning frame. It did not, the first time it was built:
    # a prescribed displacement is ramped LINEARLY by Abaqus, half of a
    # rotation's displacement is the chord rather than half the rotation, and
    # every intermediate increment was a differently distorted state. The
    # measured evidence was that the stress TRACE differed between the two runs
    # by a factor of 24 -- and a rotation preserves the trace -- so the runs
    # were not the same deformation and the verdict was meaningless. It read
    # "objective: False" for 8 of 9 published models, which was a false claim
    # about somebody else's science and is exactly the kind of thing that must
    # never be reported. The path is now driven by one tabular amplitude per
    # degree of freedom, so the corner is required to be at Q(f)(I + f E)X at
    # every sampled fraction f.
    # WHICH FRAME THE RECORDED STRESS IS IN WAS SETTLED BY MEASUREMENT, not by
    # reading the manual. On NeoHookean_umat.for over 1680 components, with the
    # rotated path finally correct, the two candidates came out:
    #
    #     |Q sigma Q^T - sigma'|   4.405e-13      <- this one
    #     |sigma       - sigma'|   7.023e-01
    #
    # So the history carries stress in the GLOBAL basis and an objective
    # response rotates with it. The co-rotational figure is kept beside it as
    # the cross-check, because the day it is the small one is the day this
    # assumption stopped holding and the record should show that rather than
    # quietly report a non-objective model.
    objective = worst < 1e-6
    return {
        "objective": objective,
        "objectivity_worst_relative": worst,
        "objectivity_worst_corotational": corotational,
        "compared_components": compared,
        "objectivity_reason": (
            f"the author's own response {'is' if objective else 'is NOT'} the "
            f"unrotated response rotated: worst |Q sigma Q^T - sigma'| is "
            f"{worst:.3e} of the stress field over {compared} components "
            f"(the same comparison without rotating gives {corotational:.3e}, "
            f"and the smaller of the two says which basis the history is in)"),
    }


def run_objectivity(manifest: VerificationManifest, original_call: dict,
                    transformed_call: dict, work: Path, timeout: int, *,
                    tolerance: float, near_zero_fraction: float,
                    support=None, base_history: Sequence[dict] = ()) -> dict:
    """Run both builds again with a rigid rotation superposed on the path.

    The material is driven along exactly the same strain history; only the
    frame it is presented in moves, so Abaqus hands the routine F = Q(I+E) and
    a DROT carrying Q. Two separate facts come out of the pair, and they are
    not the same fact:

    ``agreed``
        whether the CONVERTED build still matches the original on the rotated
        path. This is the one that is about the transform, and it is what a
        dropped DROT breaks: the conversion can agree perfectly in an unrotated
        frame and lose the rotation term without anything noticing.

    ``objective``
        whether the ORIGINAL's own response is the unrotated response rotated.
        That is a property of the author's model, recorded because it is worth
        knowing and never charged to the conversion: a routine that is not
        objective is faithfully converted by a conversion that reproduces its
        non-objectivity exactly.
    """
    turned = replace(manifest, loading=rotated_loading(
        manifest.loading, plane=manifest.ntens == 3 and manifest.ndi == 2))
    answer: dict = {"ran": False, "agreed": None, "objective": None,
                    "rotation": list(turned.loading[0].rotation)
                    if turned.loading else [],
                    "reason": ""}
    if not turned.loading:
        answer["reason"] = "this experiment has no prescribed-strain segment"
        return answer

    where = Path(work) / "objectivity"
    try:
        left, right = build_plan(
            turned, Path(original_call["source"]),
            Path(transformed_call["source"]), where, timeout,
            form=original_call.get("form", ""),
            data_roots=original_call.get("data_roots", ()))
    except Exception as error:                     # pragma: no cover
        answer["reason"] = f"could not plan the rotated run: {error}"
        return answer

    # The rotated run is a new working directory, and the transformed build
    # needs the same compiled support modules there: without them ifort stops
    # at "error #7002: Error in opening the compiled module file" before Abaqus
    # reaches its input processor, which is the harness's fault and would have
    # been recorded as the rotated run failing.
    if support is not None and getattr(support, "ok", False):
        rotated_transformed = Path(right["work_dir"])
        rotated_transformed.mkdir(parents=True, exist_ok=True)
        install_support(support, rotated_transformed)

    reports = {}
    for name, call in (("original", left), ("transformed", right)):
        report = run_one(**call)
        evidence = job_evidence(report)
        answer[name] = {"completed": evidence.completed,
                        "reasons": list(evidence.reasons)}
        if not evidence.completed:
            answer["reason"] = (
                f"the {name} build did not complete on the rotated path: "
                + "; ".join(evidence.reasons)[:200])
            return answer
        reports[name] = report

    answer["ran"] = True
    # Read the same way the unrotated pair is read: through history_of, which
    # prefers the JSON run_one saved and falls back to the probe file.
    rotated_original = history_of(Path(left["work_dir"]), left["job"])
    rotated_transformed = history_of(Path(right["work_dir"]), right["job"])
    # The rotated run carries one extra step at the front -- the lead-in that
    # turns the element from the identity to Q at zero strain -- so its steps
    # are renumbered down by one before anything is compared with the base run.
    # Comparing without this aligned the base run's first loading step against
    # the rotation itself.
    lead_in = 1 if (turned.loading
                    and getattr(turned.loading[0], "rotation_lead_in", False)) else 0
    if lead_in:
        rotated_original = _after_lead_in(rotated_original)
        rotated_transformed = _after_lead_in(rotated_transformed)

    left_history, right_history, _, _ = common_finite_prefix(
        rotated_original, rotated_transformed,
        expected_points=frames.points_for(turned.element_type))
    if not left_history or not right_history:
        answer["reason"] = ("the rotated run produced no pair of increments "
                            "both builds walked")
        return answer

    pair = compare_primal(left_history, right_history, tolerance=tolerance,
                          near_zero_fraction=near_zero_fraction)
    answer["agreed"] = bool(pair.agrees)
    # And whether the AUTHOR's own response is objective, which is a different
    # question and is never charged to the conversion: a routine that ignores
    # DROT is faithfully converted by a conversion that ignores it identically.
    answer.update(_objective_response(base_history, rotated_original,
                                      turned.loading[0].rotation))
    answer["lead_in_steps_dropped"] = lead_in
    answer["worst_stress_relative"] = pair.worst_stress_relative
    answer["worst_state_relative"] = pair.worst_state_relative
    answer["reason"] = (
        f"the converted build {'agrees with' if pair.agrees else 'differs from'}"
        f" the original on the same path presented in a rotated frame, worst "
        f"stress difference {pair.worst_stress_relative:.3e} against a "
        f"tolerance of {tolerance:g}")
    return answer


def verify_one(stored, row: Optional[dict], proposal: Optional[dict],
               cache_root: Path, work_root: Path, *, timeout: int,
               tangent_tolerance: float = TANGENT_TOLERANCE,
               strain: float = 0.005, increments: int = 10,
               discover: bool = True, frozen: Optional[dict] = None) -> dict:
    """One stored transform, carried as far up the ladder as it will go.

    Every return goes through ``classify_stage`` on the evidence gathered so
    far, rather than naming a stage at the point it stops. Naming it at each
    stopping point is how a stage and the evidence behind it drift apart, and
    the stage is the number that gets published.
    """
    started = time.time()
    record: dict[str, Any] = {
        "key": stored.key,
        "source": stored.source_id,          # path within the cache, not a basename
        "source_sha256": stored.source_sha256,
        "fingerprint": stored.fingerprint,
        "repository": (proposal or {}).get("repository", ""),
        "stage": "", "reason": "", "warnings": [],
    }
    work = Path(work_root) / stored.key
    # The store is as machine-specific as the scratch directory, and a support
    # build's log quotes the absolute path of every unit it compiled -- all of
    # which live in the store. Those paths reached the committed results file
    # until the store root was scrubbed alongside the work root.
    roots = (Path(work_root), Path(stored.directory).parent)
    seen: dict[str, Any] = {}

    def settle(reason: str, stage: str = "", **extra: Any) -> dict:
        """Record the outcome, deriving the rung from the evidence.

        ``stage`` overrides that derivation, and only an OFF-ladder verdict
        may use it. classify_stage answers "how far up did this get?", which
        is the wrong question for a file that was never on the ladder: a
        not-a-UMAT plan carries no manifest, so the derivation fell through to
        needs_material_data and thirty UEL files were reported as UMATs whose
        material could not be found. Their reason text said UEL all along.
        """
        settled = stage or classify_stage(StageEvidence(**seen))
        record.update(stage=settled, reason=reason,
                      seconds=round(time.time() - started, 1), **extra)
        return scrub(record, *roots)

    plan = build_manifest(stored.source_id, row, proposal, cache_root,
                          strain=strain, increments=increments)
    record.update(_material_columns(plan))
    if plan.stage == NOT_A_UMAT:
        return settle(plan.reason, stage=NOT_A_UMAT,
                      entry_classification=plan.entry_classification)
    if plan.stage == NEEDS_MATERIAL_DATA or plan.manifest is None:
        # The plan's own stage when it has one. A formulation this harness
        # cannot drive leaves no manifest, and falling through to the
        # evidence-derived stage recorded it as needs_material_data -- three
        # cohesive laws and two shell UMATs whose constants were published and
        # read, reported as materials nobody had described.
        return settle(plan.reason, stage=(plan.stage
                                          if plan.stage and plan.stage
                                          != NEEDS_MATERIAL_DATA else ""))
    manifest = plan.manifest
    seen["material_found"] = True
    seen["manifest_refusals"] = plan.refusals
    if plan.refusals:
        return settle(plan.reason, refusals=list(plan.refusals))

    # Both files have to be on disk before anything is spent on them. The
    # original is what the whole comparison is against: without it there is
    # nothing to compare the transform to, and letting run_one discover that
    # would spend a licence token and report it as a crashed harness.
    # The transform seeded a fixed number of directions and extracts a tangent
    # of that shape. Running the result on an element that calls the UMAT with
    # a different NTENS is not a smaller test of the same thing -- the seed
    # directions stop corresponding to the element's components, and the
    # extracted tangent is a matrix of the right shape holding the wrong
    # derivatives. Measured on UMAT_Tissue_2d_plane_strain.f: the primal
    # history agreed exactly and the tangent was out by a factor of 5000, flat
    # across every step size.
    stored_ntens = int((getattr(stored, "metadata", {}) or {}).get("ntens") or 0)
    if stored_ntens and stored_ntens != manifest.ntens:
        seen["manifest_refusals"] = (
            f"the stored transform was built for NTENS={stored_ntens} and this "
            f"material is called with NTENS={manifest.ntens} on "
            f"{manifest.element_type}. The seed directions would not "
            f"correspond to the element's components, so the tangent it "
            f"extracts would be the wrong derivatives in the right shape. "
            f"Re-transform this source at NTENS={manifest.ntens}",)
        return settle(seen["manifest_refusals"][0])

    original = Path(cache_root) / stored.source_id
    absent = [str(name) for path, name in
              ((original, f"the original source {stored.source_id} is not in "
                          f"the cache, so there is nothing to compare against"),
               (Path(stored.entry_source),
                "the stored transformed source is missing from the store"))
              if not Path(path).is_file()]
    if absent:
        seen["manifest_refusals"] = tuple(absent)
        return settle("; ".join(absent))

    # The loading is discovered on the ORIGINAL before either verification job
    # runs, so that the deck both builds are then handed is one that makes the
    # material do something rather than one chosen in advance.
    # The form is read off the source, not taken from the triage row. The row
    # is a record of an earlier scan and the file is the thing that will be
    # compiled; where they disagree the file wins, and the disagreement is
    # recorded rather than resolved silently.
    source_form = detect_source_form(
        Path(original), Path(original).read_text(errors="replace"))
    record["source_form"] = source_form
    # Where to look for a data table the routine opens by name: beside the
    # source, then anywhere in its own repository. Not further: supplying a
    # table from another author's repository would be inventing the data the
    # model runs on.
    data_roots = (Path(cache_root) / Path(stored.source_id).parts[0],)
    # A frozen experiment replaces the search outright, and only when the
    # bytes it was chosen for are the bytes on disk now.
    kept = (frozen or {}).get(stored.source_id)
    if kept and kept.get("source_sha256") not in ("", stored.source_sha256):
        record["frozen_rejected"] = (
            f"the experiment frozen as {kept['from']} was chosen for a source "
            f"whose digest was {kept['source_sha256'][:12]}; this source's is "
            f"{stored.source_sha256[:12]}, so the frozen loading describes a "
            f"different file and the discovery is run again")
        kept = None
    if kept:
        try:
            manifest = thaw(kept["manifest"])
        except (TypeError, ValueError, KeyError) as error:
            record["frozen_rejected"] = (
                f"the frozen experiment could not be read back "
                f"({type(error).__name__}: {error}); the discovery is run again")
            kept = None
    if kept:
        record["frozen"] = {
            "from": kept["from"], "states": kept.get("states") or [],
            "why": ("the experiment this material first verified under, "
                    "replayed exactly: same amplitude, same segments, same "
                    "step ladder, same tolerances. A regression that searched "
                    "again would be measuring a different experiment")}
        record["discovery"] = {"ran": False,
                               "reason": "replaying a frozen experiment"}
        record.update(_material_columns(replace(plan, manifest=manifest)))
        if stored_ntens and stored_ntens != manifest.ntens:
            seen["manifest_refusals"] = (
                f"the frozen experiment drives this material at NTENS="
                f"{manifest.ntens} and the stored transform was built for "
                f"NTENS={stored_ntens}. Re-transform, or re-discover: "
                f"replaying the frozen loading would compare a tangent of the "
                f"wrong shape",)
            return settle(seen["manifest_refusals"][0])
    if (row or {}).get("form") and row["form"] != source_form:
        record["source_form_note"] = (
            f"the triage scan called this source {row['form']}; reading it "
            f"again says {source_form}, and the file is what ifort compiles")
    if not kept:
        manifest, discovery = discover_loading(
            manifest, Path(original), work, timeout, form=source_form,
            increments=increments, data_roots=data_roots, enabled=discover,
            deck=(Path(cache_root) / plan.deck) if plan.deck else None)
        record["discovery"] = discovery
        # A search that established the model has no domain here has decided
        # something, and running the fixed probe afterwards contradicts it.
        # Twenty-two entries were driven at 0.005 -- fifty times the smallest
        # amplitude that had ALREADY returned NaN -- and came back as "both
        # builds went non-finite", which reads as a disagreement between the
        # builds and is nothing of the kind. Every one of them is a source
        # this harness has no experiment for, and that is ours to say.
        if discovery.get("refused"):
            record["no_experiment"] = discovery["refused"]
            return settle(
                f"this harness generated no experiment this source will run: "
                f"{discovery['refused']}",
                stage=NO_EXPERIMENT)

    # The whole manifest, as it will actually be run. This is what makes a
    # regression deterministic: the amplitude the search chose, the segments
    # it built, the step ladder and the tolerances are decided ONCE, here, and
    # a later run replays them rather than searching again -- so a difference
    # between two runs is a difference in the code and not in the experiment.
    record["manifest"] = manifest.as_dict()

    original_call, transformed_call = build_plan(
        manifest, original, stored.entry_source, work, timeout, form=source_form,
        data_roots=data_roots)
    # Both builds are handed the SAME manifest object, and this refuses to run
    # them if they ever stop being. Two builds driven by different decks answer
    # two different questions, and an agreement between two different questions
    # is not evidence about the transform -- it is a coincidence between two
    # materials, and a disagreement is the harness's fault reported as the
    # transform's.
    record["deck_digest"] = require_one_manifest(original_call, transformed_call)

    # The support is built before either job rather than inside run_one, for
    # two reasons. It is the earlier rung of the ladder, so an entry whose
    # modules do not compile must be recorded there and not after a job it
    # never needed to run; and an Abaqus job costs a licence token this machine
    # contends for, so spending one on a build that cannot link is waste.
    support = support_plan(stored.directory, stored.entry_source)
    support_built = None
    record["support"] = {"units": len(support.units),
                         "required": support.build_required,
                         "ok": None, "reason": support.refusal}
    if support.refusal:
        seen["support_ok"] = False
        return settle(support.refusal)
    if support.build_required:
        transformed_dir = Path(transformed_call["work_dir"])
        transformed_dir.mkdir(parents=True, exist_ok=True)
        built = build_support(support.units, transformed_dir)
        support_built = built
        seen["support_ok"] = built.ok
        record["support"].update(ok=built.ok, reason=built.reason,
                                 objects=len(built.objects))
        if not built.ok:
            return settle(built.reason or "the support did not build",
                          support_log=(built.log or "")[-2000:])
        install_support(built, transformed_dir)
    else:
        seen["support_ok"] = None
        record["support"]["reason"] = (
            "the stored transform names no support units beyond the entry "
            "source, which abaqus user= compiles itself")

    # What the ORIGINAL source carries; the transform preserves such a
    # statement, because deleting it would be editing scientific code to make
    # a run finish.
    waiting = blocking_statements(
        Path(original).read_text(errors="replace")) if Path(original).is_file() else ()
    record["blocking_statements"] = list(waiting[:3])

    original_report = run_one(**original_call)
    original_job = job_evidence(original_report)
    record["original"] = {
        "completed": original_job.completed,
        "increments": original_job.increments,
        "converged_records": original_job.converged_records,
        "instrumented": original_job.instrumented,
        "warnings": list(original_job.warnings),
        "reasons": list(original_job.reasons),
        # Kept only for a job that did not complete, and then always: for a
        # job that left no .dat, .msg or .odb it is the only evidence there is.
        "console_tail": ("" if original_job.completed
                         else original_job.console_tail),
    }
    # post_analysis_wrapup_failure and the nonzero exit code that comes with it
    # live here, beside the result, and never in the verdict.
    record["warnings"] += [f"original: {w}" for w in original_job.warnings]
    seen["original_completed"] = original_job.completed
    if not original_job.completed:
        # Checked before the harness/model split. A source carrying a Fortran
        # PAUSE hangs the solver on a terminal read until the timeout elapses,
        # and the timeout then looks exactly like a licence wait -- which would
        # send it round the retry loop to hang again, every time.
        if waiting and timed_out(original_report):
            record["stage"] = WAITS_FOR_INPUT
            record["reason"] = (
                f"the run hung until its timeout on a statement that waits for "
                f"terminal input, which this source carries: {waiting[0]}. "
                f"Abaqus does not fail on one, it sits on it, so the licence is "
                f"spent and nothing is measured. A property of the source")
            return scrub(record, *roots)
        harness = looks_like_a_harness_failure(original_report)
        if harness:
            record["stage"] = HARNESS_ERROR
            record["reason"] = f"original: {harness}"
            return record
        # Ask the compiler before naming this a failure of the run.
        diagnosis = diagnose_original(original, cache_root, work / "diagnosis",
                                      form=source_form, timeout=timeout,
                                      source_id=stored.source_id)
        record["original_diagnosis"] = diagnosis
        if diagnosis.get("verdict"):
            return settle(diagnosis["reason"], stage=diagnosis["verdict"])
        return settle("; ".join(original_job.reasons)
                      or "the original build did not complete")

    transformed_report = run_one(**transformed_call)
    transformed_job = job_evidence(transformed_report)
    record["transformed"] = {
        "completed": transformed_job.completed,
        "increments": transformed_job.increments,
        "converged_records": transformed_job.converged_records,
        "instrumented": transformed_job.instrumented,
        "warnings": list(transformed_job.warnings),
        "reasons": list(transformed_job.reasons),
        # Kept only for a job that did not complete, and then always: for a
        # job that left no .dat, .msg or .odb it is the only evidence there is.
        "console_tail": ("" if transformed_job.completed
                         else transformed_job.console_tail),
    }
    record["warnings"] += [f"transformed: {w}" for w in transformed_job.warnings]
    seen["transformed_completed"] = transformed_job.completed
    if not transformed_job.completed:
        if waiting and timed_out(transformed_report):
            record["stage"] = WAITS_FOR_INPUT
            record["reason"] = (
                f"the transformed run hung until its timeout on a statement "
                f"that waits for terminal input, carried over from the "
                f"original: {waiting[0]}")
            return scrub(record, *roots)
        harness = looks_like_a_harness_failure(transformed_report)
        if harness:
            record["stage"] = HARNESS_ERROR
            record["reason"] = f"transformed: {harness}"
            return record
        # Ask the compiler, as for the original. Here the answer is ours
        # either way, and "it does not compile" and "it does not converge"
        # need different work.
        diagnosis = diagnose_transformed(stored, work / "transformed_diagnosis",
                                         form=source_form, timeout=timeout)
        record["transformed_diagnosis"] = diagnosis
        return settle("; ".join(transformed_job.reasons)
                      + "; " + diagnosis["reason"]
                      if transformed_job.reasons else diagnosis["reason"])

    # The decks Abaqus actually read, compared after the fact. Cheap, and the
    # only one of the two checks that would catch a deck rewritten between the
    # two jobs.
    record["deck_digest"] = require_same_deck(
        (Path(original_call["work_dir"]) / "original.inp").read_text(errors="replace"),
        (Path(transformed_call["work_dir"]) / "transformed.inp").read_text(errors="replace"))

    original_history = history_of(original_call["work_dir"], "original")
    transformed_history = history_of(transformed_call["work_dir"], "transformed")

    # A record the probe could not print is a record written after the
    # subroutine damaged its own argument list, so the numbers beside it are
    # not measurements. Checked before the comparison rather than left to it:
    # compare_primal would see a record with no STRESS and correctly refuse
    # agreement, but it would say "no resolvable response", which is the wrong
    # reason and hides a real finding about the model.
    damaged = (corrupt_records(original_history)
               + corrupt_records(transformed_history))
    if damaged:
        record["corrupt_records"] = damaged[:4]
        return settle(
            f"{len(damaged)} probe record(s) could not be printed, so this run "
            f"damaged its own argument list and none of its numbers are "
            f"measurements: {damaged[0][:160]}")

    (compared_original, compared_transformed, complete_increments_compared,
     grouping) = common_finite_prefix(list(original_history),
                                      list(transformed_history),
                                      frames.points_for(manifest.element_type))
    record["history_grouping"] = grouping
    stopped_at = complete_increments_compared
    # Paired by step, integration point and time before anything is compared:
    # two builds of the same model do not always walk the same increments, and
    # zipping them compares increment 3 of one with increment 3 of the other
    # at different times. See align_by_time.
    compared_original, compared_transformed, alignment = align_by_time(
        compared_original, compared_transformed)
    if alignment:
        record["primal_alignment"] = alignment
    primal = compare_primal(compared_original, compared_transformed,
                            tolerance=manifest.primal_tolerance,
                            near_zero_fraction=manifest.near_zero_fraction)
    record["primal"] = primal.as_dict()
    # "primal_disagreed" is a stage, not a diagnosis. Thirty-seven entries
    # reached it at magnitudes spanning nine orders, and one name over that
    # range says nothing about which share a cause. The signature is read off
    # the numbers and the source so the cluster can be worked as clusters.
    if not primal.agrees:
        # Ask the recorded calls what the histories are disagreeing about,
        # before anything calls it a disagreement between two routines.
        try:
            left_calls, right_calls = call_isolation.read_pair(work)
            isolation = call_isolation.isolate_first_divergence(
                left_calls, right_calls)
            record["call_isolation"] = isolation.as_dict()
            seen["call_isolation"] = isolation.verdict
        except (OSError, ValueError) as error:
            record["call_isolation"] = {
                "verdict": "",
                "reason": (f"the probe records could not be read, so what the "
                           f"histories disagree about was not established: "
                           f"{type(error).__name__}: {error}")}
        try:
            # review_entry, not classify: the summary numbers raise the
            # hypotheses and the recorded CALLS decide which survive. Without
            # this the record keeps every hypothesis open and the
            # confirmations and refutations live only in a branch's tests.
            record["primal_signature"] = primal_signature.review_entry(
                primal.as_dict(), work,
                Path(original).read_text(errors="replace")).as_dict()
        except OSError:                            # pragma: no cover
            pass
    seen["primal_agrees"] = primal.agrees
    # Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement
    # about the solver, not about the constitutive routine it called: a job
    # completes while its UMAT returns values that are not numbers. Measured
    # on BodyForce-Growth-2Stages.for, where both builds "completed" 35
    # increments and both were non-finite from the third. These are recorded
    # apart so a reader can see which one a verdict rests on.
    record["evidence"] = {
        # The job ran to the end, which is what Abaqus reports.
        "abaqus_job_completed": True,
        # Every increment produced every material point it should have: an
        # increment short of a point did not produce the state a comparison
        # would compare.
        "all_requested_outputs_present": all(
            (grouping[side].get("first_incomplete_increment") or {}).get(
                "present", True)
            for side in ("original", "transformed")),
        # Nothing anywhere in either history is a NaN or an infinity.
        "complete_history_finite": bool(grouping.get("both_finite_throughout")),
        "primal_agreed": bool(primal.agrees),
        # Set where the tangent is decided, not here.
        "derivatives_verified": False,
        # Whether the experiment the verdict rests on exercised anything.
        # A repair that made a history finite by removing the behaviour under
        # test has not produced a verification of that behaviour, and a run
        # that agreed about a material sitting near its initial state agreed
        # about the part every build gets right.
        "mechanically_informative": False,
    }
    # Objectivity, where the family asks for it. It cannot be measured from
    # one run -- it is a statement about two -- so the pair is run here, on the
    # same strain path presented in a rotated frame, and the finding is put in
    # the record for the gate to read. Without this the criterion stays at
    # "not measured" forever and 54 finite-strain entries can never establish
    # their informativeness, which would be an internal gap recorded as an
    # unanswerable question.
    if _family_name(record.get("experiment")) == "finite strain":
        record["objectivity"] = run_objectivity(
            manifest, original_call, transformed_call, work, timeout,
            tolerance=manifest.primal_tolerance,
            near_zero_fraction=manifest.near_zero_fraction,
            support=support_built, base_history=compared_original)

    informative, informative_why = _is_informative(
        record, manifest, compared_original, original,
        record.get("discovery") or {}, record.get("experiment"))
    record["evidence"]["mechanically_informative"] = informative
    record["mechanically_informative"] = {"informative": informative,
                                          "reason": informative_why}
    seen["mechanically_informative"] = informative
    # Read from the grouping, not from the truncation flag. "No truncation
    # was applied" and "nothing in either history is non-finite" are
    # different facts, and one of them is the one a verdict may rest on.
    record["complete_finite_verification_run"] = bool(
        grouping.get("both_finite_throughout"))
    if stopped_at >= 0:
        record["primal"]["both_builds_non_finite_from_increment"] = stopped_at + 1
        record["primal"]["complete_increments_compared"] = stopped_at
        record["primal"]["raw_output_records_compared"] = len(compared_original)
        record["primal"]["scope"] = (
            f"both builds completed {stopped_at} increment(s) with every "
            f"material point finite and both failed inside increment "
            f"{stopped_at + 1}, at the same increment. The comparison covers "
            f"those {stopped_at} complete increment(s) -- "
            f"{len(compared_original)} output records at "
            f"{grouping['original'].get('material_points_per_increment')} "
            f"material points each; nothing is claimed beyond them.")
        if stopped_at < MINIMUM_COMPARABLE_INCREMENTS:
            record["stage"] = "both_builds_non_finite"
            return settle(
                f"both builds went non-finite inside increment "
                f"{stopped_at + 1}, leaving only {stopped_at} complete "
                f"increment(s) to compare -- too few to rest a verification "
                f"on")
        # And a long prefix is no better than a short one for a VERDICT. A
        # finite prefix is what discovery learns the edge of the domain from;
        # a verification rests on an analysis that completed with every
        # requested output finite throughout. Measured on
        # BodyForce-Growth-2Stages.for: 280 records, non-finite from record
        # 23, primal agreement over the first 22 -- and a verdict of
        # "verified", whose frozen fixture would replay a failed analysis and
        # start by reproducing the failure. discover_loading rebuilds the
        # loading to stop short of the edge and reruns it whole; reaching
        # here means that was not done or did not hold.
        record["complete_finite_verification_run"] = False
        record["stage"] = NO_EXPERIMENT
        return settle(
            f"the analysis this verdict would rest on is not finite "
            f"throughout: both builds completed {stopped_at} increment(s) "
            f"and went non-finite inside increment {stopped_at + 1}. "
            f"A finite prefix locates the edge of this material's domain, "
            f"which is what a safe loading is rebuilt from -- it is not a "
            f"history a verification may be frozen on",
            stage=NO_EXPERIMENT)
    # A disagreement is not yet a verdict. The author's own declared precision
    # is the one explanation that can be tested rather than argued about, so
    # it is tested: see run_precision_control.
    reference_source = Path(original)
    precision_note = ""
    if not primal.agrees:
        control = run_precision_control(
            manifest, original, Path(stored.entry_source), compared_transformed,
            work / "precision_control", timeout=timeout, form=source_form,
            data_roots=data_roots,
            increments_compared=(stopped_at if stopped_at >= 0 else None))
        if control:
            record["precision_control"] = control
        if control.get("agrees"):
            seen["primal_agrees"] = True
            precision_note = control["reason"]
            record["primal"]["explained_by_declared_precision"] = True
            record["primal"]["control"] = control["comparison"]
            reference_source = Path(control["source"])
        else:
            # The other explanation that can be measured rather than argued
            # about: how far this model moves when its own arithmetic is
            # reordered. A local Newton solve converges to a different iterate
            # and an ill-conditioned expression loses different digits, and
            # neither is a statement about the transform.
            association = run_association_control(
                manifest, original, compared_original,
                work / "association_control", timeout=timeout, form=source_form,
                data_roots=data_roots,
                increments_compared=(stopped_at if stopped_at >= 0 else None))
            record["association_control"] = association
            own = association.get("worst_stress_relative")
            mine = primal.worst_stress_relative
            if (association.get("ran") and association.get("measured")
                    and own is not None and mine is not None
                    and mine <= own):
                seen["primal_agrees"] = True
                precision_note = (
                    f"the two builds differ by {mine:.3e}, and this model "
                    f"differs from ITSELF by {own:.3e} when the same source is "
                    f"compiled so that the same mathematics is computed "
                    f"differently ({association.get('how')}). "
                    f"The conversion is no further from the original than the "
                    f"original is from another equally valid ordering of its "
                    f"own operations, so the difference is this model's "
                    f"conditioning and not the transform's")
                record["primal"]["explained_by_operation_order"] = True
                record["primal"]["own_sensitivity"] = own
            else:
                if association.get("ran") and association.get("measured") \
                        and own is not None:
                    record["primal"]["own_sensitivity"] = own
                    return settle(
                        f"{primal.reason}; and this model differs from itself "
                        f"by only {own:.3e} when its arithmetic is reordered, "
                        f"so the difference is larger than its own conditioning "
                        f"accounts for")
                if association.get("ran"):
                    record["primal"]["own_sensitivity_unmeasured"] = \
                        association.get("reason")
                    return settle(
                        f"{primal.reason}; and this model's own sensitivity to "
                        f"round-off could not be measured against it: "
                        f"{association.get('reason')}")
                return settle(primal.reason
                              or "the two builds produced no records to compare")

    # The tangent is asked for inside the window the PRIMAL comparison
    # accepted, not over the whole history. Where both builds left their
    # domain the records after the cut are Abaqus's own NaNs -- the replay
    # state file for such a record is literally "nan nan nan nan nan nan" --
    # and a derivative cannot be taken at a point where the solver produced
    # no numbers in either build. Thirty-four rows had their last probe state
    # chosen from inside that discarded tail.
    #
    # The window is the one the primal already computed and already prints in
    # its scope line, so nothing new is being decided here. It is NOT a filter
    # on whether each record's DDSDDE is finite: a non-finite OTI tangent at a
    # FINITE state is a finding about the conversion, and dropping such a
    # record would hide exactly what this pipeline exists to catch.
    # Before spending a finite-difference budget on it: does the converted
    # source still carry the derivative by the time it computes the stress? A
    # REAL() cast of a seed-carrying expression takes the value and throws the
    # derivatives away, so the primal agrees to the last bit and the tangent
    # is a different function. There is nothing for a difference to confirm or
    # deny there, and reporting it as "the tangent did not agree" names the
    # wrong thing. Measured on 33 of 253 stored transforms.
    truncation = analyse_truncation(
        Path(stored.entry_source).read_text(errors="replace"))
    if truncation.drops_a_derivative:
        record["truncation"] = truncation.as_dict()
        seen["derivative_truncated"] = True
        return settle("; ".join(part for part in
                                (precision_note, truncation.reason()) if part))

    tangent = verify_tangent(
        manifest, reference_source, compared_transformed, work / "replay",
        transformed=Path(stored.entry_source),
        form=source_form,
        tolerance=tangent_tolerance, timeout=timeout)
    if stopped_at >= 0:
        tangent["states_taken_from"] = (
            f"the {stopped_at} increments in which both builds produced "
            f"numbers; the records after increment {stopped_at} are Abaqus's "
            f"own NaNs in both builds and carry no state to replay from")
    record["tangent"] = tangent
    seen["tangent_verified"] = tangent.get("verified")
    record.setdefault("evidence", {})["derivatives_verified"] = bool(
        tangent.get("verified"))
    return settle("; ".join(part for part in
                            (precision_note, tangent.get("reason", "")) if part))


def verify_tangent(manifest: VerificationManifest, original: Path,
                   transformed_history: Sequence[dict], work_dir: Path, *,
                   form: str = "fixed", tolerance: float = TANGENT_TOLERANCE,
                   timeout: int = 900, states: int = 3,
                   transformed: Optional[Path] = None) -> dict:
    """The OTI tangent against a difference of the original, over the ladder.

    The value under test is DDSDDE out of the transformed build's own converged
    probe record. The reference is the ORIGINAL source, compiled on its own by
    gfortran and replayed from the state that record began in, with one
    component of DSTRAN moved. The two sides therefore share no code path at
    all -- not the compiler, not the driver, not the solver -- which is the
    only arrangement in which an error in the transform cannot cancel itself
    out of its own check.
    """
    outcome: dict[str, Any] = {"verified": False, "reason": ""}
    # States either side of where the material activates, and none sitting on
    # it. Bracketing a transition is not verifying across it: evaluating AT
    # the transition makes every centred difference a chord across a corner.
    chosen = choose_states_around_activation(list(transformed_history),
                                             each_side=max(2, int(states) - 1))
    if not chosen:
        outcome["reason"] = ("no converged record carries both a DDSDDE and "
                             "the ENTRY state its increment began from, so "
                             "the increment cannot be replayed")
        return outcome

    # Every chosen state is checked and every one has to agree. The per-state
    # results are kept whole: a tangent that is right in the elastic regime
    # and wrong in the plastic one is a specific, reportable finding, and
    # collapsing the states into one verdict would lose exactly that.
    at_states: list[dict] = []
    history = list(transformed_history)
    for order, (position, record) in enumerate(chosen):
        single = _verify_tangent_at(
            manifest, original, record, position,
            Path(work_dir) / f"state{order}", form=form, tolerance=tolerance,
            timeout=timeout, transformed=transformed)
        # What KIND of point this was, decided from the history up to it and
        # from how the one-sided differences behave across the step sweep.
        # A chord across a kink is not a derivative, and a state that sits on
        # one carries no weight in either direction.
        regime = classify_regime(history, position, single.get("smoothness") or {})
        single["regime"] = regime.as_dict()
        at_states.append(single)
    outcome["states"] = at_states
    outcome["states_checked"] = len(at_states)
    # The increments a regression must return to. Chosen here by looking at
    # what the material did; frozen so that a later run measures the tangent
    # at the same places rather than at whatever it would choose next time.
    outcome["chosen_states"] = [
        {"increment": state.get("increment"),
         "record_index": state.get("record_index")} for state in at_states]
    agreed = [s for s in at_states if s.get("verified")]
    outcome["states_agreeing"] = len(agreed)
    # A state whose sweep produced nothing measurable did not DISAGREE -- the
    # reference was never obtained there, so nothing was compared. Counting it
    # as a failure reports "the tangent is wrong at increment 10" when what
    # happened is "no difference could be taken at increment 10", which are
    # different findings and belong in different columns. Measured on the last
    # batch: of 106 state-level failures, 89 were of this kind.
    measured = [s for s in at_states
                if (s.get("comparison") or {}).get("best_relative") is not None]
    unmeasured = [s for s in at_states if s not in measured]
    outcome["states_measured"] = len(measured)
    outcome["states_unmeasured"] = len(unmeasured)
    if unmeasured:
        outcome["unmeasured_reasons"] = sorted({
            str(s.get("reason") or "")[:120] for s in unmeasured})

    # The reported comparison is the WORST state, not the best: a summary that
    # quotes the closest agreement among several describes the state that
    # flattered the transform most.
    def _best_relative(state):
        value = ((state.get("comparison") or {}).get("best_relative"))
        return float("inf") if value is None else float(value)
    worst = max(at_states, key=_best_relative)
    outcome["increment"] = worst.get("increment")
    outcome["record_index"] = worst.get("record_index")
    for key in ("comparison", "driven_through", "failures",
                "perturbation_scale", "replay_header", "log"):
        if key in worst:
            outcome[key] = worst[key]
    outcome["fd_steps"] = list(manifest.fd_steps)

    # Every state where a difference COULD be taken has to agree, and at
    # least two states have to have been measurable. Two rather than one
    # keeps this stronger than the single-state rule it replaced; requiring
    # all three to be measurable would fail a material for a state its
    # reference could not reach, which is a fact about the harness.
    # Only a SMOOTH state can carry a verified derivative. A transitional one
    # is not a failure and not evidence: it is a state at which a centred
    # difference was the wrong reference.
    smooth = [s for s in measured if (s.get("regime") or {}).get("verifiable")]
    # A state at a corner is not smooth, and it is not evidence-free either:
    # where the OTI tangent converges onto the ONE-SIDED difference along the
    # branch the increment took, that is the consistent tangent Abaqus asks
    # for at that point, measured. Counted separately, never pooled with a
    # centred result, and reported as what it is.
    on_a_branch = [s for s in measured
                   if not (s.get("regime") or {}).get("verifiable")
                   and (s.get("branch") or {}).get("verified")]
    transitional = [s for s in measured
                    if not (s.get("regime") or {}).get("verifiable")
                    and s not in on_a_branch]
    outcome["states_smooth"] = len(smooth)
    outcome["states_on_a_branch"] = len(on_a_branch)
    outcome["states_transitional"] = len(transitional)

    # Does this material activate at all? Read from the ORIGINAL history the
    # loading was discovered on, not assumed.
    nonlinear = any((s.get("regime") or {}).get("activated_here") for s in at_states)
    outcome["nonlinear"] = nonlinear
    # What this material's response IS, from whether the stress returns when
    # the strain does -- not from whether a state variable moved. A STATEV can
    # hold a stretch, a time, an orientation or a copied input; measured on
    # From-2D-to-2D-Axe.for, STATEV(9) rises to 1.0589 under load and falls
    # back to 1.0058 the moment the strain is removed. Reading its movement as
    # "the material has yielded" would call a reversible response
    # irreversible, and then ask less of it than it should.
    character, character_reason = response_character(history)
    outcome["response_character"] = character
    outcome["character_reason"] = character_reason
    # A branch-verified corner carries the regime it sits in for coverage: it
    # is a measured derivative inside the activated regime, which is exactly
    # the evidence coverage exists to require.
    counted = smooth + on_a_branch
    enough, coverage_reason = coverage(
        [_regime_of(s) for s in counted], nonlinear=nonlinear,
        character=character)
    if on_a_branch:
        coverage_reason += (
            f"; {len(on_a_branch)} of those states sit at a corner and were "
            f"verified against the one-sided difference along the branch the "
            f"increment took, which is what a consistent tangent is there")
    outcome["coverage"] = coverage_reason

    disagreeing = [s for s in counted if not s.get("verified")]
    if counted and not disagreeing and enough:
        outcome["verified"] = True
        smooth = counted
        scope = (f"agreed at all {len(counted)} states where a difference "
                 f"could be taken (increments "
                 f"{', '.join(str(s.get('increment')) for s in counted)}); "
                 f"{coverage_reason}")
        if unmeasured:
            scope += (f"; {len(unmeasured)} further state(s) produced no "
                      f"measurable difference and establish nothing either way")
        outcome["reason"] = f"{scope}; worst of them: {worst.get('reason', '')}"
        return outcome
    if disagreeing:
        outcome["reason"] = (
            f"agreed at {len(counted) - len(disagreeing)} of {len(counted)} "
            f"states along the loading path where a difference could be taken; "
            f"increment {disagreeing[0].get('increment')} did not: "
            f"{disagreeing[0].get('reason', '')}")
        return outcome
    if counted and not enough:
        # Every smooth state agreed, and there were not enough of them in the
        # right places. Not a pass: for a material that activates, agreement
        # on the elastic branch is agreement about the part every build gets
        # right.
        outcome["reason"] = (
            f"every state where a difference could be taken agreed, but "
            f"{coverage_reason}")
        return outcome
    if transitional and not counted:
        # Every state WAS measured; every one of them sat on a transition, so
        # a centred difference was the wrong reference at all of them. That is
        # neither a verified tangent nor a failed one, and reporting it as
        # "no measurable difference" said the opposite of what happened.
        worst_gap = max(
            (min((s.get("regime") or {}).get("smoothness", {}).values(),
                 default=float("inf")) for s in transitional),
            default=float("inf"))
        outcome["reason"] = (
            f"all {len(transitional)} states produced a difference and all of "
            f"them sat on a constitutive transition, where the forward and "
            f"backward perturbations do not land on the same branch (smallest "
            f"one-sided gap {worst_gap:.3g}). A centred difference is not a "
            f"derivative there, so this is neither a verified tangent nor a "
            f"failed one -- the loading needs states away from the transition")
        return outcome
    outcome["reason"] = (
        f"only {len(measured)} of {len(at_states)} states produced a "
        f"measurable difference, and {MINIMUM_MEASURED_STATES} are required. "
        f"Nothing here says the tangent is wrong; it says the reference could "
        f"not be obtained: "
        + "; ".join(outcome.get("unmeasured_reasons") or ["no reason recorded"])[:200])
    return outcome


#: How closely the converted build has to reproduce the AUTHOR'S OWN tangent
#: before the two are treated as the same value for the purpose of asking what
#: a finite difference can see. This is not a tolerance on correctness -- it is
#: the threshold at which two numbers are indistinguishable to the reference.
SAME_TANGENT = 1e-9


def _resolved_by_the_reference(outcome: dict, *, tolerance: float,
                               reason: str) -> tuple[bool, str]:
    """Is the difference under test smaller than the reference's own error?

    A centred difference has an error of its own, and on a model with a local
    Newton solve or an ill-conditioned kinematic expression that error is far
    above the eps**(2/3) a smooth function would give. Measured on the same
    sweep against the same state: the author's OWN analytic DDSDDE -- a value
    that shares no code path with the converted build -- differs from the
    difference by a certain amount, and that amount is what the difference can
    see.

    Where the converted build reproduces the author's tangent to
    ``SAME_TANGENT`` and its distance from the difference is no larger than
    the author's own, the difference is not evidence that the two differ: it
    cannot tell them apart. That is a pass on a narrower claim, and it says so
    -- the conversion agrees with the author's own tangent, and the difference
    agrees with both to the extent it agrees with anything.

    It is NOT a pass when the converted build and the author's tangent differ.
    Then there are two candidate answers and a reference too coarse to choose,
    which is exactly the situation nothing may be claimed in.
    """
    author = (outcome.get("against_the_authors_tangent") or {}).get("best_relative")
    floor = (outcome.get("the_references_own_error") or {}).get("best_relative")
    mine = (outcome.get("comparison") or {}).get("best_relative")
    if author is None or floor is None or mine is None:
        return False, reason
    if author > SAME_TANGENT:
        return False, (
            f"{reason}; and the converted build differs from the author's own "
            f"DDSDDE by {author:.3e}, so there are two candidate tangents and "
            f"the difference is not close enough to either to choose between "
            f"them")
    if mine > floor:
        return False, (
            f"{reason}; the author's own DDSDDE sits {floor:.3e} from the same "
            f"difference, so the difference is not too coarse to have noticed")
    return True, (
        f"the centred difference cannot separate them: the converted build "
        f"reproduces the author's own DDSDDE to {author:.3e}, and the "
        f"difference sits {mine:.3e} from the converted tangent and "
        f"{floor:.3e} from the author's -- so its distance from the conversion "
        f"is within its own error, and the {tolerance:.0e} it misses is below "
        f"what this reference can resolve on this model")


def _verify_tangent_at(manifest: VerificationManifest, original: Path,
                       record: dict, position: int, work_dir: Path, *,
                       form: str = "fixed", tolerance: float = TANGENT_TOLERANCE,
                       timeout: int = 900,
                       transformed: Optional[Path] = None) -> dict:
    """One state: the OTI tangent there against a difference of the original."""
    outcome: dict[str, Any] = {"verified": False, "reason": ""}
    outcome["increment"] = record.get("increment")
    outcome["record_index"] = position

    oti = oti_tangent(record, manifest.ntens)
    if not oti:
        outcome["reason"] = (f"the probe recorded fewer than "
                             f"{manifest.ntens * manifest.ntens} DDSDDE values")
        return outcome

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    write_state(record["entry"], work_dir / STATE_FILE)
    build = build_replay(Path(original), work_dir, name=manifest.name,
                         flags=replay_flags(form, work_dir), timeout=timeout)
    outcome["replay_header"] = build.header
    if not build.ok:
        outcome["reason"] = build.reason or "the replay driver did not build"
        outcome["log"] = (build.log or "")[-2000:]
        return outcome

    scale = perturbation_scale(record["entry"])
    outcome["perturbation_scale"] = scale
    # The transformed file is handed over so the sweep can read which kinematic
    # input the transform seeded, and perturb THAT. The reference must
    # differentiate the quantity the OTI side differentiated.
    sweep = difference_tangent(build, work_dir, manifest.ntens,
                               manifest.fd_steps, scale=scale,
                               transformed_source=transformed,
                               near_zero_fraction=manifest.near_zero_fraction)
    outcome["driven_through"] = sweep.driven_through
    # Per step, how far the forward and backward one-sided differences
    # sat from each other. This is what says whether the two
    # perturbations were on the same constitutive branch.
    outcome["smoothness"] = dict(sweep.smoothness)
    outcome["failures"] = list(sweep.failures)
    if not sweep.ok:
        outcome["reason"] = sweep.reason or "the difference produced no tangent"
        return outcome

    comparison = compare_tangent(oti, sweep.matrices,
                                 near_zero_fraction=manifest.near_zero_fraction)
    outcome["comparison"] = comparison.as_dict()
    verified, reason = tangent_verdict(outcome["comparison"], tolerance=tolerance)
    outcome.update(verified=verified, reason=reason,
                   fd_steps=list(manifest.fd_steps))

    # A second reference, from the same replay and costing nothing: the
    # tangent the ORIGINAL routine returned at this state. The difference says
    # what the stress DOES; the author's DDSDDE says what the author SAID it
    # does. Recorded always, because the two disagreeing is a finding about
    # the source, and used below where the difference cannot separate them.
    if sweep.original_tangent:
        against_author = compare_tangent(
            oti, {0.0: sweep.original_tangent},
            near_zero_fraction=manifest.near_zero_fraction)
        reference_error = compare_tangent(
            sweep.original_tangent, sweep.matrices,
            near_zero_fraction=manifest.near_zero_fraction)
        outcome["against_the_authors_tangent"] = against_author.as_dict()
        outcome["the_references_own_error"] = reference_error.as_dict()
        if not verified:
            verified, reason = _resolved_by_the_reference(
                outcome, tolerance=tolerance, reason=reason)
            outcome.update(verified=verified, reason=reason)

    # Where the centred difference is the WRONG reference, ask the right one.
    # A rate-independent inelastic model has a corner at every increment of a
    # monotonically loading path: the forward perturbation grows the plastic
    # strain or the damage and the backward one unloads elastically, so their
    # average is the slope of a chord across the corner and belongs to neither
    # branch. The consistent tangent Abaqus asks for is the derivative along
    # the branch the increment actually took, and that is a ONE-SIDED
    # difference. Reported as one, never pooled with a centred result.
    if not verified and sweep.forward and _sits_on_a_corner(sweep.smoothness):
        outcome["branch"] = branch_verdict(
            oti, sweep, manifest, tolerance=tolerance)
        if outcome["branch"].get("verified"):
            outcome.update(verified=True,
                           reason=(f"the centred difference is not a reference "
                                   f"here ({reason}); on the branch this "
                                   f"increment took, {outcome['branch']['reason']}"))
    return outcome


#: How far the forward and backward one-sided differences have to sit from each
#: other before the centred difference between them stops being a derivative.
#: A tenth: a smooth response has them agreeing to O(h), which at these step
#: sizes is orders of magnitude below this, and a corner has them differing by
#: the ratio of two branch stiffnesses, which is of order one.
CORNER_GAP = 0.1


def _sits_on_a_corner(smoothness: dict) -> bool:
    """Do the two one-sided differences disagree at EVERY step size?

    At every step, because that is what distinguishes a corner from noise. A
    smooth response's one-sided gap falls with the step; a corner's does not,
    because the two perturbations are on different branches whatever the step.
    """
    values = [float(value) for value in (smoothness or {}).values()]
    return bool(values) and min(values) > CORNER_GAP


def branch_verdict(oti, sweep, manifest: VerificationManifest, *,
                   tolerance: float = TANGENT_TOLERANCE) -> dict:
    """The OTI tangent against each one-sided difference, and which one it is.

    Both branches are scored and both are reported. The claim earned here is
    narrower than a centred one and says so: it is that the OTI tangent is the
    derivative along the named branch, corroborated by a first-order
    convergence toward it rather than by a plateau.
    """
    outcome: dict[str, Any] = {"verified": False}
    for name, matrices in (("forward", sweep.forward), ("backward", sweep.backward)):
        if not matrices:
            continue
        comparison = compare_tangent(
            oti, matrices, near_zero_fraction=manifest.near_zero_fraction)
        agreed, why = one_sided_verdict(comparison.as_dict())
        outcome[name] = {"verified": agreed, "reason": why,
                         "comparison": comparison.as_dict()}
        if agreed and not outcome["verified"]:
            outcome.update(
                verified=True, branch=name,
                reason=(f"the {name} difference -- the one taken along the "
                        f"direction this increment moved in -- {why}"))
    if not outcome["verified"]:
        reasons = [f"{name}: {outcome[name]['reason']}"
                   for name in ("forward", "backward") if name in outcome]
        outcome["reason"] = ("neither one-sided difference converged onto the "
                             "OTI tangent either; " + "; ".join(reasons))
    return outcome


# ---------------------------------------------------------------------------
# the batch
# ---------------------------------------------------------------------------


def append_record(path: Path, record: dict, lock: Optional[Lock] = None) -> None:
    """One line per entry, flushed to disk before the next entry starts.

    A batch of this size runs for hours: 158 entries with a material vector,
    two Abaqus jobs and a step ladder of replays each. Holding the results in
    memory until the end would put every one of those hours behind a single
    crash, killed session or licence timeout. That is why --resume exists, and
    why this file is opened, written, flushed and fsynced for each entry rather
    than left to the interpreter to close.
    """
    line = json.dumps(record, sort_keys=True) + "\n"
    if lock is not None:
        lock.acquire()
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if lock is not None:
            lock.release()


def triage_rows(path: Path) -> dict[str, dict]:
    """Triage rows keyed by the source's path within the cache."""
    rows: dict[str, dict] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("source"):
                rows[row["source"]] = row
    return rows


def proposal_entries(path: Path) -> dict[str, dict]:
    """Corpus proposals keyed the same way, through the shared join.

    ``_cache_relative_source`` is imported rather than reimplemented: the join
    between "owner/name" plus a repository-relative path and the cache's
    "owner__name/path" is the identity of every row in this project, and two
    copies of it would eventually disagree.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = payload if isinstance(payload, list) else payload.get("entries", [])
    return {_cache_relative_source(entry): entry for entry in entries}


def run_batch(entries: Sequence[Any], rows: dict[str, dict],
              proposals: dict[str, dict], cache_root: Path, work_root: Path,
              results_path: Path, *, timeout: int, jobs: int = DEFAULT_JOBS,
              tangent_tolerance: float = TANGENT_TOLERANCE,
              strain: float = 0.005, increments: int = 10,
              previous: Optional[dict[str, str]] = None,
              resume: bool = False, discover: bool = True,
              frozen: Optional[dict] = None,
              retry: Sequence[str] = ()) -> list[dict]:
    """Every selected entry, in order, with each result on disk before the next."""
    previous = previous or {}
    lock = Lock()
    total = len(entries)

    def one(index_entry) -> Optional[dict]:
        index, stored = index_entry
        if should_skip(stored.key, previous, resume, retry):
            print(f"[{index}/{total}] {stored.source_id[:70]}  "
                  f"skipped, already {previous[stored.key]}", flush=True)
            return None
        print(f"[{index}/{total}] {stored.source_id[:70]}", flush=True)
        try:
            record = verify_one(stored, rows.get(stored.source_id),
                                proposals.get(stored.source_id), cache_root,
                                work_root, timeout=timeout,
                                tangent_tolerance=tangent_tolerance,
                                strain=strain, increments=increments,
                                discover=discover, frozen=frozen)
        except Exception as error:                      # noqa: BLE001
            # A crash is a finding about this harness, recorded as such and
            # never as a stage: it says nothing about the model, and --resume
            # will try it again.
            record = scrub({
                "key": stored.key, "source": stored.source_id,
                "stage": HARNESS_ERROR,
                "reason": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc()[-1200:],
            }, Path(work_root), Path(stored.directory).parent)
        append_record(results_path, record, lock)
        print(f"    {record.get('stage')}  {str(record.get('reason'))[:90]}",
              flush=True)
        return record

    numbered = list(enumerate(entries, start=1))
    if jobs <= 1:
        produced = [one(item) for item in numbered]
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            produced = list(pool.map(one, numbered))
    return [record for record in produced if record is not None]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", type=Path, default=None,
                        help="the transform store (default: the store's own default root)")
    parser.add_argument("--cache-dir", type=Path,
                        default=Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                                     or REPO_ROOT.parent / "discovery_cache"))
    parser.add_argument("--triage", type=Path,
                        default=REPO_ROOT / "paper_results/discovery/discovery_triage.csv")
    parser.add_argument("--proposals", type=Path,
                        default=REPO_ROOT / "paper_results/discovery/proposed_corpus_entries.json")
    parser.add_argument("--work-dir", type=Path, required=True,
                        help="scratch for the jobs; keep it outside the repository")
    parser.add_argument("--results-dir", type=Path,
                        default=REPO_ROOT / "paper_results/store_verification")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help=("Abaqus jobs at once. Default 1: the licence "
                              "server here is shared and contended, and two "
                              "concurrent jobs demand two sets of tokens, "
                              "which has produced multi-minute waits rather "
                              "than throughput."))
    parser.add_argument("--resume", action="store_true",
                        help="skip entries already carried to a settled outcome "
                             "in the results file")
    parser.add_argument(
        "--retry", default="",
        help=("comma-separated stages a --resume run must do again anyway, or "
              "'internal' for every stage that is this pipeline's problem "
              "rather than the corpus's. The use for it is a fix to the "
              "harness: an entry recorded under a rule that has since been "
              "corrected has a settled outcome that is settled about the old "
              "rule."))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--gate-report", type=Path, default=None,
                        help="an offline stress-parity gate report; only "
                             "entries it decided AGREED are queued")
    parser.add_argument("--only", default="",
                        help="substring of the source's path within the cache")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="seconds per Abaqus job")
    parser.add_argument("--strain", type=float, default=0.005)
    parser.add_argument(
        "--no-discovery", action="store_true",
        help="drive every material at --strain instead of searching for an "
             "amplitude that activates it. The search costs extra Abaqus jobs "
             "on the ORIGINAL, and without it a material that answers the "
             "fixed probe elastically is verified on its elastic branch only "
             "-- which is the part every build gets right.")
    parser.add_argument("--increments", type=int, default=10)
    parser.add_argument("--tangent-tolerance", type=float, default=TANGENT_TOLERANCE)
    parser.add_argument("--include-stale", action="store_true",
                        help="also run entries built by an earlier transform. "
                             "They are excluded by default because they are "
                             "not evidence about the transform as it stands.")
    parser.add_argument(
        "--mode", choices=("inventory", "regression", "qualification"),
        default="inventory",
        help="inventory (default) surveys the store and always exits 0: it is "
             "for finding out where entries stand, and a failure in it is a "
             "finding, not an error. regression and qualification are gates "
             "and exit non-zero when a required check fails, is blocked, is "
             "missing, or when the selection is unexpectedly empty. Use them "
             "in CI and in a promotion step; never treat inventory's exit "
             "code as a verdict.")
    parser.add_argument(
        "--require", default="",
        help="comma-separated source ids that MUST reach 'verified' under "
             "--mode regression. A required entry that is missing from the "
             "run, or blocked, or that fails, is a failure of the run. "
             "Without this, regression requires every attempted entry that "
             "previously verified to verify again.")
    parser.add_argument(
        "--frozen", type=Path, default=REPO_ROOT / "umat",
        help=("the verified collection, whose contracts carry the experiment "
              "each material first verified under. Under --mode regression "
              "these are replayed exactly -- same amplitude, same segments, "
              "same step ladder, same tolerances -- because a regression that "
              "searched again would be measuring a different experiment. A "
              "frozen experiment is used only when the source's digest still "
              "matches the one it was chosen for."))
    parser.add_argument(
        "--baseline", type=Path, default=None,
        help="a previous store_verification.json whose verified entries "
             "become the required set under --mode regression. Never written "
             "by this tool: promotion is a separate, deliberate step.")
    parser.add_argument("--json", action="store_true",
                        help="print the summary as JSON as well as in words")
    args = parser.parse_args(argv)

    store = TransformStore(root=args.store)
    available = store.entries() if args.include_stale else store.current_entries()
    # The gate restricts BEFORE the limit, so --limit N means N entries that
    # will actually be run rather than N drawn from the store and then mostly
    # discarded -- which made --limit 1 queue nothing at all.
    selected = select_entries(available, args.only, 0)
    if args.gate_report is not None:
        earned, dropped = restrict_to_gate(selected, args.gate_report)
        print(f"  gate {args.gate_report.name}: {len(earned)} of "
              f"{len(selected)} entries agreed offline and are queued")
        for outcome, count in sorted(dropped.items(), key=lambda kv: -kv[1]):
            print(f"      not queued, gate said {outcome}: {count}")
        selected = earned
    entries = selected[:args.limit] if args.limit else selected
    results_path = Path(args.results_dir) / "store_verification.jsonl"
    retry_stages: tuple = ()
    if str(args.retry).strip().lower() == "internal":
        from umat_oti.abaqus.terminal_states import INTERNAL, FROM_STAGE
        retry_stages = tuple(stage for stage, state in FROM_STAGE.items()
                             if state in set(INTERNAL))
    elif args.retry:
        retry_stages = tuple(piece.strip() for piece in str(args.retry).split(",")
                             if piece.strip())
    if retry_stages:
        print(f"  re-running any entry previously recorded as: "
              f"{', '.join(sorted(retry_stages))}")

    earlier = previous_records(results_path) if args.resume else []
    previous = previous_outcomes(results_path) if args.resume else {}
    if retry_stages:
        earlier = [record for record in earlier
                   if str(record.get("stage")) not in set(retry_stages)]

    # The store's summary carries no root -- it goes into published evidence,
    # which must not name the machine it was produced on -- so the path printed
    # here is the one this run was given. `broken` is entries the store
    # recorded whose files are gone; it is part of the total, not dropped from it.
    summary_note = store.summary()
    print(f"  store {args.store}: {summary_note['stored']} entries, "
          f"{summary_note['current']} current, {summary_note['stale']} stale, "
          f"{summary_note['broken']} broken")
    print(f"  attempting {len(entries)} of them"
          + (f", resuming over {len(previous)} recorded outcomes"
             if args.resume else ""))
    if not entries:
        # Under a gate, an empty selection is a failure and not a pass: a
        # regression that ran nothing has proved nothing, and returning 0 here
        # was a green result for a run that never started. exit_verdict says
        # so; this used to return before reaching it.
        print("  nothing to verify")
        outcome = exit_verdict(args.mode, [], required_entries(args, []))
        for line in outcome.lines:
            print(line)
        return outcome.code

    rows = triage_rows(args.triage)
    proposals = proposal_entries(args.proposals)
    kept = frozen_manifests(args.frozen) if args.mode == "regression" else {}
    if args.mode == "regression":
        print(f"  {len(kept)} frozen experiment(s) available to replay from "
              f"{args.frozen}")
    fresh = run_batch(entries, rows, proposals, args.cache_dir, args.work_dir,
                      results_path, timeout=args.timeout, jobs=max(1, args.jobs),
                      tangent_tolerance=args.tangent_tolerance,
                      strain=args.strain, increments=args.increments,
                      previous=previous, resume=args.resume,
                      discover=not args.no_discovery, frozen=kept,
                      retry=retry_stages)

    # The denominator is every entry this batch attempted, which on a resumed
    # run includes the ones it skipped because they were already settled.
    kept = [record for record in earlier
            if str(record.get("key")) in {e.key for e in entries}]
    records = merge_records(kept, fresh)
    summary = summarise(records)
    # Everything the store says about itself except where it is. The
    # fingerprint identifies the transform that built these entries and the
    # counts identify the batch; the root is a property of this machine, and
    # this summary is written under paper_results/ where the audit reads it.
    summary["store"] = {name: value for name, value in summary_note.items()
                        if name != "root"}
    summary["stale_excluded"] = (0 if args.include_stale
                                 else summary_note.get("stale", 0))
    # The store's root and the work directory are properties of this machine,
    # and the results file is written under paper_results/ where the repository
    # audit reads it. Scrubbed here as well as per record, because the summary
    # is assembled after the per-record scrub.
    summary = scrub(summary, args.work_dir, store.root)

    out_dir = Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "store_verification.json").write_text(
        json.dumps(scrub({"summary": summary, "entries": records},
                         args.work_dir, store.root), indent=1) + "\n",
        encoding="utf-8")

    print("")
    print(f"  attempted {summary['attempted']} entries "
          f"(counted {summary['counted']})")
    for stage, count in summary["by_stage"].items():
        print(f"    {stage:<24} {count}")
    print(f"  verified {summary['verified_count']} of {summary['attempted']}")
    for name in summary["verified"]:
        print(f"    verified: {name}")
    print(f"  wrote {out_dir / 'store_verification.json'}")
    if args.json:
        print(json.dumps(summary, indent=1))

    outcome = exit_verdict(args.mode, records, required_entries(args, records))
    for line in outcome.lines:
        print(line)
    return outcome.code


if __name__ == "__main__":
    raise SystemExit(main())
