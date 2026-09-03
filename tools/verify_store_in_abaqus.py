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
import os
import re
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
from umat_oti.abaqus.compare import compare_primal, compare_tangent     # noqa: E402
from umat_oti.abaqus.deck import generate_deck                          # noqa: E402
from umat_oti.abaqus.manifest import (                                  # noqa: E402
    NEEDS_MATERIAL_DATA, VerificationManifest, reverse, uniaxial)
from umat_oti.abaqus.probe import CORRUPT, converged_only, parse_probe           # noqa: E402
from umat_oti.abaqus.replay import (                                    # noqa: E402
    STATE_FILE, build_replay, difference_tangent, write_state)
from umat_oti.abaqus.support import (                                   # noqa: E402
    build_support, compile_order, install_support)
from umat_oti.store import TransformStore                               # noqa: E402

# ---------------------------------------------------------------------------
# the ladder
# ---------------------------------------------------------------------------

#: Every outcome an entry can be recorded as, in the order an entry passes
#: through them. The index in this tuple is how far the entry got; the last
#: rung is the only one that may be called verified.
STAGES: tuple[str, ...] = (
    "needs_material_data",
    "manifest_refused",
    "support_build_failed",
    "original_job_failed",
    "transformed_job_failed",
    "primal_disagreed",
    "tangent_not_verified",
    "verified",
)

VERIFIED = STAGES[-1]

#: A crash in this harness. Deliberately not one of STAGES: it is not a
#: statement about the model, it is a statement about the run, so --resume
#: re-runs it rather than serving it as a settled result.
HARNESS_ERROR = "harness_error"

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
    manifest_refusals: tuple[str, ...] = ()
    #: None when the stored transform names no support units to build.
    support_ok: Optional[bool] = None
    original_completed: bool = False
    transformed_completed: bool = False
    #: None when the comparison never ran.
    primal_agrees: Optional[bool] = None
    tangent_verified: Optional[bool] = None


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
    if evidence.manifest_refusals:
        return "manifest_refused"
    if evidence.support_ok is False:
        return "support_build_failed"
    if not evidence.original_completed:
        return "original_job_failed"
    if not evidence.transformed_completed:
        return "transformed_job_failed"
    if evidence.primal_agrees is not True:
        return "primal_disagreed"
    if evidence.tangent_verified is not True:
        return "tangent_not_verified"
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


#: What one material point looks like at each tensor size this corpus uses:
#: direct components, shear components, and an element that has exactly one
#: integration point so a job drives one material point rather than several
#: identical ones. C3D4 and the plane quadrilaterals also carry no hourglass
#: modes, so no artificial stiffness has to be invented for them.
POINT_SHAPE: dict[int, tuple[int, int, str]] = {
    6: (3, 3, "C3D4"),
    4: (3, 1, "CPE4"),
    3: (2, 1, "CPS4"),
}


def point_shape(ntens: int) -> Optional[tuple[int, int, str]]:
    """(ndi, nshr, element type) for this tensor size, or None if unknown.

    None is a refusal, not a fallback. Driving an ntens the deck generator has
    no element for would mean choosing an element whose component ordering the
    source does not use, and every stress it wrote would be compared against
    the wrong component.
    """
    return POINT_SHAPE.get(int(ntens))


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


_SOLUTION_STATE = re.compile(
    r"^\s*\*INITIAL\s+CONDITIONS\b[^\n]*\bTYPE\s*=\s*SOLUTION\b", re.IGNORECASE)


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


def build_manifest(
    source_id: str,
    row: Optional[dict],
    proposal: Optional[dict],
    cache_root: Path,
    *,
    strain: float = 0.005,
    increments: int = 10,
    include_reversal: bool = True,
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

    ntens = int(row.get("ntens") or 0)
    shape = point_shape(ntens)

    proposed = str(((proposal or {}).get("pairing") or {}).get("proposed") or "")
    if not proposed:
        plan.stage = NEEDS_MATERIAL_DATA
        plan.reason = ("no deck is paired with this source, so it has no "
                       "published material constants")
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
    found = deck_kinematics(deck_text, Path(proposed).name)
    plan.kinematics_provenance = found.provenance
    if (row.get("kinematics") or "") and row["kinematics"] != found.kinematics:
        plan.kinematics_note = (
            f"the triage scan called this source {row['kinematics']}; the "
            f"paired deck runs it as {found.kinematics}, and the deck is what "
            f"the manifest follows")

    declared_state = initial_solution_state(deck_text)
    # The transform's own bound on STATEV, from the subscripts the source uses.
    # Reported as an inference everywhere: it is not the author's *DEPVAR and
    # must never read as one.
    inferred_nstatv = int((proposal or {}).get("nstatv_inferred") or 0)

    loading = [uniaxial(strain, increments)]
    if include_reversal:
        loading.append(reverse(loading[0]))

    relative, _ = portable_source(cache_root / source_id)
    ndi, nshr, element = shape or (3, 3, "C3D4")
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
        initial_statev_provenance=(
            f"{Path(proposed).name} *INITIAL CONDITIONS, TYPE=SOLUTION: "
            f"{len(declared_state)} values" if declared_state else ""),
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
    if shape is None:
        # Not a material problem, so not needs_material_data: what is missing
        # is an element this harness can drive one point of at this tensor size.
        refusals.append(
            f"ntens={ntens} has no single-point element in this harness, and "
            f"choosing one whose component order the source does not use would "
            f"compare every stress against the wrong component")
    plan.refusals = tuple(refusals)
    plan.manifest = manifest
    plan.stage = "manifest_refused" if refusals else ""
    plan.reason = "; ".join(refusals)
    return plan


# ---------------------------------------------------------------------------
# one manifest, two builds
# ---------------------------------------------------------------------------


class DifferentDecks(ValueError):
    """The two builds would not have been asked the same question."""


def deck_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_plan(manifest: VerificationManifest, original: Path, transformed: Path,
               work_dir: Path, timeout: int) -> tuple[dict, dict]:
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
    common = {"manifest": manifest, "timeout": timeout}
    original_call = dict(common, source=Path(original), job="original",
                         work_dir=Path(work_dir) / "original", support_dir=None)
    transformed_call = dict(common, source=Path(transformed), job="transformed",
                            work_dir=Path(work_dir) / "transformed",
                            support_dir=None)
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
    """The size of the strain increment the difference steps are relative to.

    A relative ladder means the same sweep says the same thing for a model
    loaded to a percent of strain and one loaded to a millionth. An increment
    of exactly zero would make every step zero, so it falls back to one.
    """
    magnitudes = [abs(float(value)) for value in (entry.get("DSTRAN") or ())]
    largest = max(magnitudes, default=0.0)
    return largest or 1.0


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

    Two conditions, and both are needed. The best step has to agree to the
    tolerance -- and the agreement has to hold over a plateau of steps, because
    one step cannot tell a truncation error from a cancellation one. A single
    step that happens to land on the right answer while its neighbours do not
    is the signature of a coincidence, and reporting it as verification is how
    a finite-difference check gets to say whatever the author wants.
    """
    sweep = list(comparison.get("sweep") or ())
    if not sweep:
        return False, "no step size produced a difference to compare against"
    best = comparison.get("best_relative")
    frobenius = comparison.get("best_frobenius")
    if best is None or frobenius is None:
        return False, "the sweep recorded no best step"
    threshold = 10.0 * frobenius if frobenius > 0 else 0.0
    plateau = [point["step"] for point in sweep
               if "step" in point and point.get("frobenius", 0.0) <= threshold]
    if best > tolerance:
        return False, (f"the closest step agreed only to {best:.3e}, against a "
                       f"tolerance of {tolerance:.0e}")
    if len(plateau) < minimum_plateau:
        return False, (f"the difference agreed at {len(plateau)} step size(s); "
                       f"{minimum_plateau} are required, because one step "
                       f"cannot separate truncation error from cancellation")
    return True, (f"agreed to {best:.3e} over {len(plateau)} step sizes, "
                  f"{min(plateau):g} to {max(plateau):g}")


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
    """
    return stage in STAGES


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


def should_skip(key: str, previous: dict[str, str], resume: bool) -> bool:
    """Has this exact entry already been carried to a settled outcome?"""
    return bool(resume) and is_terminal(previous.get(key, ""))


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
    }


def verify_one(stored, row: Optional[dict], proposal: Optional[dict],
               cache_root: Path, work_root: Path, *, timeout: int,
               tangent_tolerance: float = TANGENT_TOLERANCE,
               strain: float = 0.005, increments: int = 10) -> dict:
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

    def settle(reason: str, **extra: Any) -> dict:
        record.update(stage=classify_stage(StageEvidence(**seen)), reason=reason,
                      seconds=round(time.time() - started, 1), **extra)
        return scrub(record, *roots)

    plan = build_manifest(stored.source_id, row, proposal, cache_root,
                          strain=strain, increments=increments)
    record.update(_material_columns(plan))
    if plan.stage == NEEDS_MATERIAL_DATA or plan.manifest is None:
        return settle(plan.reason)
    manifest = plan.manifest
    seen["material_found"] = True
    seen["manifest_refusals"] = plan.refusals
    if plan.refusals:
        return settle(plan.reason, refusals=list(plan.refusals))

    # Both files have to be on disk before anything is spent on them. The
    # original is what the whole comparison is against: without it there is
    # nothing to compare the transform to, and letting run_one discover that
    # would spend a licence token and report it as a crashed harness.
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

    original_call, transformed_call = build_plan(
        manifest, original, stored.entry_source, work, timeout)
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

    original_report = run_one(**original_call)
    original_job = job_evidence(original_report)
    record["original"] = {
        "completed": original_job.completed,
        "increments": original_job.increments,
        "converged_records": original_job.converged_records,
        "instrumented": original_job.instrumented,
        "warnings": list(original_job.warnings),
        "reasons": list(original_job.reasons),
    }
    # post_analysis_wrapup_failure and the nonzero exit code that comes with it
    # live here, beside the result, and never in the verdict.
    record["warnings"] += [f"original: {w}" for w in original_job.warnings]
    seen["original_completed"] = original_job.completed
    if not original_job.completed:
        harness = looks_like_a_harness_failure(original_report)
        if harness:
            record["stage"] = HARNESS_ERROR
            record["reason"] = f"original: {harness}"
            return record
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
    }
    record["warnings"] += [f"transformed: {w}" for w in transformed_job.warnings]
    seen["transformed_completed"] = transformed_job.completed
    if not transformed_job.completed:
        harness = looks_like_a_harness_failure(transformed_report)
        if harness:
            record["stage"] = HARNESS_ERROR
            record["reason"] = f"transformed: {harness}"
            return record
        return settle("; ".join(transformed_job.reasons)
                      or "the transformed build did not complete")

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

    primal = compare_primal(original_history, transformed_history,
                            tolerance=manifest.primal_tolerance,
                            near_zero_fraction=manifest.near_zero_fraction)
    record["primal"] = primal.as_dict()
    seen["primal_agrees"] = primal.agrees
    if not primal.agrees:
        return settle(primal.reason
                      or "the two builds produced no records to compare")

    tangent = verify_tangent(
        manifest, original, transformed_history, work / "replay",
        form=str((row or {}).get("form") or "fixed"),
        tolerance=tangent_tolerance, timeout=timeout)
    record["tangent"] = tangent
    seen["tangent_verified"] = tangent.get("verified")
    return settle(tangent.get("reason", ""))


def verify_tangent(manifest: VerificationManifest, original: Path,
                   transformed_history: Sequence[dict], work_dir: Path, *,
                   form: str = "fixed", tolerance: float = TANGENT_TOLERANCE,
                   timeout: int = 900) -> dict:
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
    chosen = choose_probe_record(list(transformed_history))
    if chosen is None:
        outcome["reason"] = ("no converged record carries both a DDSDDE and "
                             "the ENTRY state its increment began from, so "
                             "the increment cannot be replayed")
        return outcome
    position, record = chosen
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
    sweep = difference_tangent(build, work_dir, manifest.ntens,
                               manifest.fd_steps, scale=scale)
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
              resume: bool = False) -> list[dict]:
    """Every selected entry, in order, with each result on disk before the next."""
    previous = previous or {}
    lock = Lock()
    total = len(entries)

    def one(index_entry) -> Optional[dict]:
        index, stored = index_entry
        if should_skip(stored.key, previous, resume):
            print(f"[{index}/{total}] {stored.source_id[:70]}  "
                  f"skipped, already {previous[stored.key]}", flush=True)
            return None
        print(f"[{index}/{total}] {stored.source_id[:70]}", flush=True)
        try:
            record = verify_one(stored, rows.get(stored.source_id),
                                proposals.get(stored.source_id), cache_root,
                                work_root, timeout=timeout,
                                tangent_tolerance=tangent_tolerance,
                                strain=strain, increments=increments)
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
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--gate-report", type=Path, default=None,
                        help="an offline stress-parity gate report; only "
                             "entries it decided AGREED are queued")
    parser.add_argument("--only", default="",
                        help="substring of the source's path within the cache")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="seconds per Abaqus job")
    parser.add_argument("--strain", type=float, default=0.005)
    parser.add_argument("--increments", type=int, default=10)
    parser.add_argument("--tangent-tolerance", type=float, default=TANGENT_TOLERANCE)
    parser.add_argument("--include-stale", action="store_true",
                        help="also run entries built by an earlier transform. "
                             "They are excluded by default because they are "
                             "not evidence about the transform as it stands.")
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
    earlier = previous_records(results_path) if args.resume else []
    previous = previous_outcomes(results_path) if args.resume else {}

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
        print("  nothing to verify")
        return 0

    rows = triage_rows(args.triage)
    proposals = proposal_entries(args.proposals)
    fresh = run_batch(entries, rows, proposals, args.cache_dir, args.work_dir,
                      results_path, timeout=args.timeout, jobs=max(1, args.jobs),
                      tangent_tolerance=args.tangent_tolerance,
                      strain=args.strain, increments=args.increments,
                      previous=previous, resume=args.resume)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
