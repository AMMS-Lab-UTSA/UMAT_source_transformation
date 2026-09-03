#!/usr/bin/env python
"""The cheap gate in front of Abaqus: same inputs, same stress, no solver.

Abaqus licence time is the scarce resource in this project -- a batch over the
corpus costs hours of it -- and the transform store now holds enough entries
that spending that time on all of them, in fingerprint order, wastes most of
it on sources whose transform is broken in a way a compiler and one function
call would have shown in seconds.

So this runs first. For every stored transform it builds two standalone replay
drivers, one around the original source out of the discovery cache and one
around the transformed source, hands both the *same declared starting state*,
and asks whether they compute the same stress. That is a real comparison
between two builds that share no code path, and it is worth exactly what it
costs: seconds per source.

What it is NOT, and what no output of this tool may be read as:

* It is not Abaqus verification. Nothing here runs a solver, drives a loading
  history, or exercises the tangent. A row that agrees here has earned one
  thing -- a place in the queue for the Abaqus round -- and nothing else.
* It is not verification of the tangent. The whole point of the transform is
  that DDSDDE becomes an exact derivative, and this gate does not look at
  DDSDDE at all. ``tools/run_discovered_verification.py`` is what does.
* It is not a compilation report. A build that links proves the output is
  Fortran. The stress comparison is what this tool is for; the builds are how
  it gets there.

Two rules from the project this implements literally. Material constants are
never invented: a stored transform whose source has no published deck behind
it is classified ``needs_material_data``, stays in the denominator, and no
props are made up to get it moving. And an entry that could not be resolved --
a build that failed, a driver that produced nothing, a probe that moved
nothing -- is reported as what it was, never as agreement.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovered_verification import _cache_relative_source  # noqa: E402
from run_discovery_triage import without_machine_paths  # noqa: E402
from umat_oti.abaqus.compare import compare_primal  # noqa: E402
from umat_oti.abaqus.job_status import blocking_statements  # noqa: E402
from umat_oti.abaqus.manifest import NEEDS_MATERIAL_DATA  # noqa: E402
from umat_oti.abaqus.replay import (  # noqa: E402
    STATE_FILE, build_replay, run_replay, write_state)
from umat_oti.abaqus.support import compile_order  # noqa: E402
from umat_oti.store import TransformStore  # noqa: E402
from umat_oti.store.transform_store import file_digest  # noqa: E402

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO_ROOT.parent / "discovery_cache")
DEFAULT_PROPOSALS = (REPO_ROOT / "paper_results" / "discovery"
                     / "proposed_corpus_entries.json")
DEFAULT_MANIFESTS = REPO_ROOT / "verification_manifests"
DEFAULT_OUT = (REPO_ROOT / "paper_results" / "discovery"
               / "offline_store_gate.json")

# ---------------------------------------------------------------------------
# Outcomes. One per entry, exhaustive, and every one of them counts towards the
# denominator -- there is no bucket here that means "dropped".
# ---------------------------------------------------------------------------
AGREED = "agreed"
DISAGREED = "disagreed"
ORIGINAL_UNAVAILABLE = "original_source_unavailable"
ORIGINAL_BUILD_FAILED = "original_build_failed"
TRANSFORMED_BUILD_FAILED = "transformed_build_failed"
DRIVER_DID_NOT_RUN = "driver_did_not_run"
NO_RESPONSE = "no_response"
#: The TRANSFORMED build returned NaN or Inf where the original returned finite
#: numbers. This one is evidence against the transform.
NON_FINITE_RESPONSE = "transformed_non_finite"

#: BOTH builds returned NaN or Inf. This is not evidence against the transform
#: at all -- it says the probe drove both programs somewhere neither can
#: evaluate. Measured: of the 27 rows the gate first reported as
#: `non_finite_response`, 27 were this and none were the other, so a category
#: whose name asserted a transform defect contained no instance of one.
BOTH_NON_FINITE = "both_builds_non_finite"

#: The ORIGINAL returned NaN where the transformed build did not. Rare, and
#: still not a transform defect: the reference is what failed.
ORIGINAL_NON_FINITE = "original_non_finite"
HARNESS_ERROR = "harness_error"

#: Report order: what passed, what failed, what was never askable.
OUTCOMES = (
    AGREED, DISAGREED, NON_FINITE_RESPONSE, BOTH_NON_FINITE,
    ORIGINAL_NON_FINITE, NO_RESPONSE, ORIGINAL_BUILD_FAILED,
    TRANSFORMED_BUILD_FAILED, DRIVER_DID_NOT_RUN, ORIGINAL_UNAVAILABLE,
    NEEDS_MATERIAL_DATA, HARNESS_ERROR,
)

#: The two outcomes in which the comparison actually happened. Everything else
#: is a row this gate could not decide, and a summary that quotes an agreement
#: rate has to divide by all of them, not by these.
DECIDED = (AGREED, DISAGREED)

#: gfortran's flags for a corpus of code written to no single standard: fixed
#: source lines past column 72 are common, so is syntax three standards old,
#: and warnings on a thousand-line UMAT are noise this gate cannot act on.
#: ``-J`` is added per build, pointing at that build's own directory, because
#: the transformed source opens with ``use otim6n1`` and the module file has to
#: be written somewhere the same command can read it back.
BASE_FLAGS = ("-ffixed-line-length-132", "-std=legacy", "-O2", "-w")


# ---------------------------------------------------------------------------
# The starting state
# ---------------------------------------------------------------------------
#: The strain increment the probe applies, on component 11 alone. Small enough
#: to stay inside the elastic range of most models in the corpus, large enough
#: that the stress it produces is not the round-off of a zero.
PROBE_STRAIN = 1.0e-4

#: Where the probe puts the material point. A generic point of the unit cube:
#: no coordinate zero, no two equal in magnitude. Sources here divide by all
#: three of those coincidences.
PROBE_COORDS = (0.3, 0.7, 0.5)

PROBE_PROVENANCE = (
    "declared probe, chosen by this offline gate: zero stress, zero state and "
    "a uniaxial strain increment of 1e-4 over one increment of unit time. It "
    "is not read from any deck and is not this source's own loading history. "
    "Only the material constants come from the author"
)


def probe_entry(material: "Material", *, strain: float = PROBE_STRAIN,
                dtime: float = 1.0) -> dict[str, Any]:
    """The declared starting state, shaped like one probe ENTRY record.

    Shaped that way on purpose rather than as a new kind of record: ``write_state``
    already knows how to write an ENTRY, the Abaqus round already drives the
    replay from one, and a second state format would be a second place for the
    two sides of this comparison to disagree about what they were handed.

    Everything in it is stated here and nothing is inferred from the source.
    Zero stress and zero state are a declaration that this is a virgin material
    point, not a claim about what the model's own initial state should be -- a
    model with an SDVINI has one and this gate does not read it, which is one
    of the reasons a row that agrees here still has to go through Abaqus.

    ``DFGRD1`` is made consistent with the strain increment rather than left at
    the identity: a finite-strain source reads the deformation gradient and
    ignores DSTRAN entirely, and handing it an unmoved gradient would ask it to
    report the stress of a body that was never deformed. The two builds would
    then agree on zero and this gate would have proved nothing.
    """
    ntens = max(int(material.ntens), 1)
    nstatv = max(int(material.nstatv), 1)
    increment = [0.0] * ntens
    increment[0] = float(strain)
    stretched = [1.0 + float(strain), 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    return {
        "kind": "entry",
        "tag": "offline_gate",
        "element": 1, "point": 1, "step": 1, "increment": 1, "time": 0.0,
        "NTENS": ntens, "NSTATV": nstatv, "NPROPS": len(material.props),
        "NDI": int(material.ndi), "NSHR": int(material.nshr),
        "DTIME": [float(dtime)],
        "TEMP": [0.0, 0.0],
        "STRESS0": [0.0] * ntens,
        "STATEV0": [0.0] * nstatv,
        "STRAN": [0.0] * ntens,
        "DSTRAN": increment,
        "PROPS": [float(value) for value in material.props],
        "DFGRD0": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "DFGRD1": stretched,
        "DROT": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "COORDS": [*PROBE_COORDS, 1.0],
    }


# ---------------------------------------------------------------------------
# Material constants: found, or declared missing. Never invented.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Material:
    """Constants the author published, and the sentence saying where from."""

    props: tuple[float, ...]
    provenance: str
    ntens: int = 6
    ndi: int = 3
    nshr: int = 3
    nstatv: int = 1
    nstatv_provenance: str = ""
    source: str = ""          # which artefact supplied this: manifest, pairing
    name: str = "MATERIAL"    # becomes CMNAME, and both builds get this one
    #: The pairing's own status and caveat, carried through rather than
    #: dropped. Every material block in the proposals says "not established:
    #: the deck gives values, not names. A reviewer has to say what these
    #: constants mean before any result is published against them." The
    #: constants are the author's, so nothing is invented -- but a reader of
    #: this gate's report saw a deck citation with no sign that the pairing is
    #: unreviewed, and "an LLM may propose; it may not certify" requires the
    #: proposal's hedge to reach the output.
    pairing_status: str = ""
    meaning_caveat: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"props_count": len(self.props), "ntens": self.ntens,
                "ndi": self.ndi, "nshr": self.nshr, "nstatv": self.nstatv,
                "material_provenance": self.provenance,
                "nstatv_provenance": self.nstatv_provenance,
                "material_from": self.source,
                "material_name": self.name,
                "pairing_status": self.pairing_status,
                "meaning_caveat": self.meaning_caveat}


def _floats(values: Any) -> tuple[float, ...]:
    try:
        return tuple(float(value) for value in values or ())
    except (TypeError, ValueError):
        return ()


def material_from_proposal(entry: dict[str, Any]) -> Optional[Material]:
    """The constants a corpus proposal paired to a deck, if it paired any.

    Two things make this return None, and both of them are the same rule: an
    entry with no props, and an entry whose props carry no provenance sentence.
    A bare vector with nothing saying which deck it was read out of is
    indistinguishable from one somebody typed, and this project does not drive
    a model with constants it cannot attribute.
    """
    material = entry.get("material") or {}
    props = _floats(material.get("props"))
    provenance = str(material.get("provenance") or "").strip()
    if not props or not provenance:
        return None
    declared = material.get("nstatv_declared_by_deck")
    if declared:
        nstatv, why = int(declared), f"*DEPVAR in {provenance.split(',')[0]}"
    else:
        # The transform's own inference. Named as an inference, because it is
        # one: it bounds the STATEV the source subscripts, which is not the
        # same statement as the author's *DEPVAR.
        nstatv = int(entry.get("nstatv_inferred") or 0) or 1
        why = "inferred from the source; no *DEPVAR in the paired deck"
    return Material(
        props=props, provenance=provenance,
        ntens=int(entry.get("ntens") or 6), ndi=int(entry.get("ndi") or 3),
        nshr=int(entry.get("nshr") or 3), nstatv=nstatv,
        nstatv_provenance=why, source="corpus pairing",
        name=(str(material.get("name") or "").strip() or "MATERIAL")[:60],
        pairing_status=str(entry.get("status") or ""),
        meaning_caveat=str(material.get("meaning") or ""))


def material_from_manifest(record: dict[str, Any]) -> Optional[Material]:
    """The constants a verification manifest declares, under the same rule."""
    props = _floats(record.get("props"))
    provenance = str(record.get("material_provenance") or "").strip()
    if not props or not provenance:
        return None
    return Material(
        props=props, provenance=provenance,
        ntens=int(record.get("ntens") or 6), ndi=int(record.get("ndi") or 3),
        nshr=int(record.get("nshr") or 3),
        nstatv=int(record.get("nstatv") or 1),
        nstatv_provenance=str(record.get("initial_statev_provenance")
                              or "declared by the verification manifest"),
        source="verification manifest",
        name=(str(record.get("name") or "").strip() or "MATERIAL")[:60],
        pairing_status="declared by a verification manifest")


def proposal_materials(path: Path) -> dict[str, Material]:
    """Constants by source identity, read from the corpus proposals.

    Keyed by the path within the cache, never by the file's name. Eighteen
    UMATs in this corpus share a basename with something else, and the last
    time a batch keyed on one, eighteen sources were driven with another
    project's constants.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = payload if isinstance(payload, list) else payload.get("entries", [])
    found: dict[str, Material] = {}
    for entry in entries:
        material = material_from_proposal(entry)
        if material is not None:
            found[_cache_relative_source(entry)] = material
    return found


def manifest_materials(directory: Path) -> dict[str, Material]:
    """Constants by source identity, read from the verification manifests.

    A manifest names its source by the same cache-relative identity, so the two
    indexes share a key space. Matching on a trailing filename is deliberately
    not attempted: see ``proposal_materials``.
    """
    found: dict[str, Material] = {}
    directory = Path(directory)
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        material = material_from_manifest(record)
        if material is None:
            continue
        identity = str(record.get("source_id") or record.get("source") or "")
        if identity:
            found[identity] = material
    return found


def choose_material(source_id: str, manifests: dict[str, Material],
                    proposals: dict[str, Material]) -> Optional[Material]:
    """The material for one source, or None -- which is a result, not a gap.

    A manifest wins over a pairing when both exist. A manifest is a reviewed
    statement of what a model is made of; a pairing is a scan's proposal that
    still says "needs review" in its own status field.
    """
    return manifests.get(source_id) or proposals.get(source_id)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def original_source(entry: Any, cache: Path) -> Path:
    """Where the untransformed source lives.

    The store records the identity a transform was made from -- "owner__name/
    path/to/u.for" -- and that path, under the cache, is the file. Resolving it
    by basename would pair eighteen of these with the wrong file; resolving it
    from metadata is preferred only when the store wrote down the exact path it
    read, which is a stronger statement than reconstructing one.
    """
    metadata = getattr(entry, "metadata", None) or {}
    for key in ("original_source", "source_path", "original_path"):
        recorded = metadata.get(key)
        if recorded:
            return Path(str(recorded))
    return Path(cache) / str(getattr(entry, "source_id", ""))


def original_is_intact(path: Path, expected_sha256: str) -> tuple[bool, str]:
    """Is the file at ``path`` the one this entry was transformed from?

    Checked rather than assumed because the whole comparison rests on it. If
    the cache has moved on -- the repository was re-acquired, a file was
    rewritten -- then "the original" is a different program, and two builds
    disagreeing about the stress would be reported as a defect in the
    transform when it is nothing of the kind.
    """
    if not Path(path).is_file():
        return False, "the original source is not in the discovery cache"
    if not expected_sha256:
        return True, ""
    actual = file_digest(path)
    if actual != expected_sha256:
        return False, (f"the cached source has changed since it was "
                       f"transformed: sha256 {actual[:12]} where the store "
                       f"recorded {expected_sha256[:12]}")
    return True, ""


# ---------------------------------------------------------------------------
# Scoring, as pure functions. Everything below can be tested without a compiler.
# ---------------------------------------------------------------------------
#: How much of a failed build's log is kept. Enough for the first cascade of a
#: Fortran compile error or a whole linker complaint, short enough that a
#: thousand-line failure does not become the report.
REASON_LIMIT = 1500


def _named_roots(roots: Sequence[Any]) -> list[tuple[str, str]]:
    """``roots`` as (path, name) pairs, longest path first.

    Longest first so that a directory sitting inside another is named as
    itself: the work directory of a run launched inside the store would
    otherwise be half-rewritten to <store> and stop matching.
    """
    pairs = []
    for item in roots:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            path, name = item
        else:
            path, name = item, "<work>"
        text = str(path or "")
        if text and text != "/":
            pairs.append((text, str(name)))
    return sorted(pairs, key=lambda pair: -len(pair[0]))


def portable_text(text: str, roots: Sequence[Any] = ()) -> str:
    """``text`` with this run's directories named rather than spelled out.

    The compiler quotes the absolute path of every file it is handed, so a raw
    log carries the store, the cache and the work directory into a report that
    is committed -- and tools/audit_repository_standards.py fails the build on
    a path under a home or a scratch directory. Naming them keeps the file
    identifiable, which is the part of the message that is about the failure.
    """
    if not text:
        return text
    for path, name in _named_roots(roots):
        text = text.replace(path, name)
    # The shared filter still runs, for the repository, the home directory and
    # the scratch roots that no caller passed.
    return without_machine_paths(text)


def compiler_reason(reason: str, log: str, *, limit: int = REASON_LIMIT,
                    roots: Sequence[Any] = ()) -> str:
    """A build failure, keeping the compiler's own words.

    The compiler's message is the finding. "the replay driver did not link"
    tells a reader nothing they can act on; "Error: Symbol 'kinc' at (1) has no
    IMPLICIT type" tells them the source needs an interface it was never given.
    So the log is kept, not the status line alone.

    The head of the log is kept rather than the tail: gfortran reports in
    source order and the first diagnostic names the statement that actually
    broke, while everything after it is usually a cascade of that one. A link
    failure has no head to lose -- its log is the linker's alone.
    """
    parts = [str(reason or "").strip(), str(log or "").strip()]
    text = portable_text("\n".join(part for part in parts if part), roots)
    if len(text) > limit:
        text = text[:limit].rstrip() + " ... [truncated]"
    return text


#: What the replay was compiled against, said portably. ``build_replay``
#: answers with a filesystem path -- the installation's, or "stub in <the work
#: directory>" when no installation is on PATH -- and this report is committed,
#: where the repository audit fails the build on a path under a home or a
#: scratch directory. Which header was used still has to be recorded: a
#: reference built against an approximation of the header the solver used is an
#: approximation of the reference.
INSTALLED_HEADER = "the Abaqus installation's own aba_param.inc"
STUB_HEADER = "a stub aba_param.inc written by the harness"


def header_note(header: str) -> str:
    """Which aba_param.inc a build used, without naming this machine."""
    text = str(header or "")
    if not text:
        return ""
    return STUB_HEADER if text.startswith("stub") else INSTALLED_HEADER


def _json_safe(value: Any) -> Any:
    """The same document with every non-finite number labelled as a string.

    A NaN in a stress array is real evidence and must survive into the report,
    but `json.dumps` writes it as a bare `NaN` token that is not valid JSON.
    Naming it keeps the artifact readable by anything that reads JSON.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def stress_response(values: Sequence[float]) -> float:
    """The largest FINITE stress component a build produced, in magnitude.

    Finite, because max() over a list containing NaN returns NaN and bool(NaN)
    is True, so a build that returned NaN for every component satisfied the
    "did anything move?" guard and went on to be scored as agreement.
    """
    return max((abs(float(value)) for value in values or ()
                if math.isfinite(float(value))), default=0.0)


def _has_non_finite(values: Any) -> bool:
    """Did this build produce a value that is not a number?

    Tolerates the labelled strings the report writes for non-finite values, so
    a row read back from a previous run is judged the same way as a fresh one.
    """
    for value in values or ():
        try:
            if not math.isfinite(float(value)):
                return True
        except (TypeError, ValueError):
            return True
    return False


def non_finite_count(*histories: Sequence[float]) -> int:
    """How many values across these stresses are not finite."""
    return sum(1 for values in histories for value in values or ()
               if not math.isfinite(float(value)))


def single_record(stress: Sequence[float]) -> dict[str, list]:
    """One replayed call, in the shape ``compare_primal`` reads.

    The replay driver writes stress and tangent and no state, so the state
    history is empty on both sides rather than zero-filled: comparing two
    invented STATEV vectors would report agreement about a thing neither build
    reported.
    """
    return {"STRESS": [float(value) for value in stress or ()], "STATEV": []}


def outcome_for(record: dict[str, Any]) -> tuple[str, str]:
    """Which outcome one entry earned, and the sentence explaining it.

    The order of the tests is the order in which a reader has to know things.
    An entry whose original is not the file it was transformed from is reported
    as that first, whatever else is wrong: every later answer would be about
    two unrelated programs. Material data comes next, because without it
    nothing is built at all. Then the builds, then the run, then the response,
    and only then the comparison.

    ``agreed`` is returned from exactly one place, and only when a comparison
    ran and said so. There is no path here on which a missing result, an empty
    stress or an unresolved comparison becomes agreement.
    """
    if not record.get("original_available", True):
        return ORIGINAL_UNAVAILABLE, str(record.get("original_reason") or "")
    if not record.get("material_provenance"):
        return NEEDS_MATERIAL_DATA, (
            "no published material constants are paired with this source; it "
            "is not run here and none are invented for it")
    # A timeout under load is not a finding about a UMAT, and freezing one as
    # a published claim was worse than losing it: RECONSIDERED did not list the
    # build failures, so every later --resume reproduced it verbatim.
    for key, outcome in (("original_build_reason", ORIGINAL_BUILD_FAILED),
                         ("transformed_build_reason", TRANSFORMED_BUILD_FAILED),
                         ("run_reason", DRIVER_DID_NOT_RUN)):
        built = {"original_build_reason": record.get("built_original"),
                 "transformed_build_reason": record.get("built_transformed"),
                 "run_reason": (record.get("ran_original")
                                and record.get("ran_transformed"))}[key]
        if not built and broke_on_the_machine(record.get(key)):
            return HARNESS_ERROR, (
                f"{str(record.get(key))[:200]} -- a machine-state failure, not "
                f"a statement about this source; a later --resume retries it")
    if not record.get("built_original"):
        return ORIGINAL_BUILD_FAILED, str(record.get("original_build_reason") or "")
    if not record.get("built_transformed"):
        return TRANSFORMED_BUILD_FAILED, str(
            record.get("transformed_build_reason") or "")
    if not record.get("ran_original") or not record.get("ran_transformed"):
        return DRIVER_DID_NOT_RUN, str(record.get("run_reason") or "")
    if record.get("non_finite_components"):
        # WHICH build produced the non-finite value decides what this row is
        # evidence of. Collapsing the three cases into one manufactured a
        # 27-row category whose name asserted a transform defect and which
        # contained no instance of one.
        original_bad = _has_non_finite(record.get("stress_original"))
        transformed_bad = _has_non_finite(record.get("stress_transformed"))
        if original_bad and transformed_bad:
            return BOTH_NON_FINITE, (
                f"both builds returned a non-finite stress from the same "
                f"declared starting state, so this says nothing about the "
                f"transform: the probe drove two programs somewhere neither "
                f"can evaluate. {record['non_finite_components']} components "
                f"affected")
        if original_bad:
            return ORIGINAL_NON_FINITE, (
                "the original build returned a non-finite stress, so there is "
                "no reference to compare the transform against")
        return NON_FINITE_RESPONSE, (
            f"the transformed build returned {record['non_finite_components']} "
            f"non-finite stress components where the original returned finite "
            f"numbers. A comparison against NaN is False, so the worst "
            f"difference would otherwise have read as zero")
    if not record.get("response"):
        return NO_RESPONSE, (
            "both builds returned an all-zero stress for the probe, so they "
            "agree about nothing measurable; the comparison has no power here")
    if record.get("agreed"):
        return AGREED, ""
    return DISAGREED, str(record.get("comparison_reason")
                          or "the two builds did not agree on the stress")


def blocking_note(original: Sequence[str], transformed: Sequence[str]) -> str:
    """What to say about a source that waits for input, or nothing.

    A Fortran PAUSE does not fail a solver, it hangs one: Abaqus sits on a
    terminal read until the job times out and the licence is spent on nothing.
    A batch has to know which sources carry one before it queues them, so the
    statements are reported here even for an entry that agreed.
    """
    counts = []
    if original:
        counts.append(f"{len(original)} in the original")
    if transformed:
        counts.append(f"{len(transformed)} in the transformed source")
    if not counts:
        return ""
    return ("input-waiting statement(s) present: " + ", ".join(counts)
            + " -- an Abaqus run of this source can hang rather than fail")


def summarise(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Counts by outcome, over every entry that was looked at.

    The denominator is the number of entries, full stop. An entry with no
    material data, a build that failed and a driver that produced nothing are
    all in it. That is the only way the agreement count means anything: it is a
    fraction of the store, not a fraction of the rows that happened to work.
    """
    counts = Counter(str(record.get("outcome") or HARNESS_ERROR)
                     for record in records)
    decided = sum(counts[name] for name in DECIDED)
    return {
        "entries": len(records),
        "by_outcome": {name: counts.get(name, 0) for name in OUTCOMES
                       if counts.get(name, 0)},
        "decided": decided,
        "agreed": counts.get(AGREED, 0),
        "disagreed": counts.get(DISAGREED, 0),
        "undecided": len(records) - decided,
        "with_blocking_statements": sum(
            1 for record in records if record.get("blocking_statements")),
        "resolved_components_total": sum(
            int(record.get("resolved_components") or 0) for record in records),
        "unresolved_components_total": sum(
            int(record.get("unresolved_components") or 0) for record in records),
        "non_finite_components_total": sum(
            int(record.get("non_finite_components") or 0) for record in records),
        "rows_on_an_unreviewed_pairing": sum(
            1 for record in records
            if str(record.get("pairing_status") or "") == "proposed_needs_review"),
        "rows_on_a_shared_deck": _shared_deck_rows(records),
        "non_finite_note": (
            "transformed_non_finite is the only one of the three non-finite "
            "outcomes that is evidence against the transform. "
            "both_builds_non_finite says the probe drove two programs "
            "somewhere neither can evaluate"),
        "worst_relative_difference_among_agreeing": max(
            [float(record.get("worst_relative") or 0.0) for record in records
             if record.get("outcome") == AGREED], default=0.0),
    }


def _shared_deck_rows(records: Sequence[dict[str, Any]]) -> int:
    """How many rows took their constants from a deck another row also used.

    Measured, and it is most of the corpus: 25 distinct decks are paired to 158
    transformed sources, one of them to 64 of them. That does not weaken the
    parity claim -- both builds are handed the same constants, whatever they
    are, so "the transformed build computes what the original computes at this
    material point" holds either way. It does mean a row's constants are not
    necessarily the ones ITS author published for THAT source, only ones from a
    deck in the same repository with a matching count. A reader who takes an
    agreement rate as "verified against the author's own material" would be
    over-reading it, and this number is here to stop that.
    """
    used = Counter(str(record.get("material_provenance") or "")
                   for record in records
                   if record.get("material_provenance"))
    return sum(1 for record in records
               if used.get(str(record.get("material_provenance") or ""), 0) > 1)


CAVEAT = (
    "This is an offline stress-parity gate, not Abaqus verification. It "
    "compares the stress two standalone drivers compute from one declared "
    "starting state. It runs no solver, drives no loading history and does "
    "not examine DDSDDE. An agreeing row has earned a place in the Abaqus "
    "queue and nothing more."
)


def format_summary(summary: dict[str, Any]) -> str:
    """The human report. Says what the numbers are and what they are not."""
    lines = [
        f"offline stress-parity gate over {summary['entries']} stored transform(s)",
        f"  decided:   {summary['decided']}"
        f"  (agreed {summary['agreed']}, disagreed {summary['disagreed']})",
        f"  undecided: {summary['undecided']}",
    ]
    for name in OUTCOMES:
        count = summary["by_outcome"].get(name, 0)
        if count:
            lines.append(f"    {name:<28} {count}")
    if summary.get("with_blocking_statements"):
        lines.append(f"  sources carrying an input-waiting statement: "
                     f"{summary['with_blocking_statements']} "
                     f"(these can hang an Abaqus job rather than fail it)")
    worst = summary.get("worst_relative_difference_among_agreeing") or 0.0
    if summary.get("agreed"):
        lines.append(f"  worst relative stress difference among agreeing rows: "
                     f"{worst:.3e}")
    lines.append("")
    lines.append(CAVEAT)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Resuming
# ---------------------------------------------------------------------------
#: Outcomes worth reconsidering when a previous run is resumed. Both are cheap:
#: neither compiled anything, so re-deciding them costs nothing, and both can
#: change without the transform changing -- a reviewer pairs a deck, someone
#: re-acquires the repository the cache lost.
RECONSIDERED = (NEEDS_MATERIAL_DATA, ORIGINAL_UNAVAILABLE, HARNESS_ERROR)

#: Console signatures of a build or run that broke for reasons outside the
#: source: the machine was loaded and a timeout elapsed, or a compiler was
#: killed. Recording one as ORIGINAL_BUILD_FAILED publishes a claim that
#: somebody's UMAT does not build, and every --resume reproduced it verbatim
#: because nothing in the store key changes when the load does.
TIMEOUT_SIGNATURES = ("TimeoutExpired", "TIMEOUT", "timed out", "Killed",
                      "Terminated", "MemoryError")


def broke_on_the_machine(reason: str) -> bool:
    """Did this fail for a reason about the machine rather than the source?"""
    haystack = str(reason or "").lower()
    return any(signature.lower() in haystack for signature in TIMEOUT_SIGNATURES)


def previously_recorded(payload: Any) -> dict[str, dict[str, Any]]:
    """Usable records from an earlier output, by store key.

    Keyed by the store key, which already carries a fingerprint of the
    transform code. A record made before the transform changed therefore has a
    key no current entry has, and cannot be served in place of a rebuild --
    which is the property that makes "re-run everything after a change"
    automatic rather than a thing somebody has to remember.

    A record with no recognised outcome is not usable. A run killed halfway
    through leaves rows like that, and treating one as done would silently
    shrink the denominator of every later report.
    """
    if isinstance(payload, dict):
        records = payload.get("entries") or []
    elif isinstance(payload, list):
        records = payload
    else:
        return {}
    usable: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = str(record.get("key") or "")
        outcome = str(record.get("outcome") or "")
        if key and outcome in OUTCOMES and outcome not in RECONSIDERED:
            usable[key] = record
    return usable


def load_previous(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return previously_recorded(payload)


def partition_for_resume(entries: Sequence[Any], previous: dict[str, dict]
                         ) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split the store into what still has to run and what can be reused.

    Reused records are handed back so they stay in the output. Dropping them
    would leave a resumed run reporting a smaller corpus than the one it
    checked, which is the same lie as dropping a failure.
    """
    todo, reused = [], []
    for entry in entries:
        record = previous.get(str(getattr(entry, "key", "")))
        if record is None:
            todo.append(entry)
        else:
            carried = dict(record)
            carried["reused_from_previous_run"] = True
            reused.append(carried)
    return todo, reused


# ---------------------------------------------------------------------------
# The check itself. Everything from here down touches a compiler.
# ---------------------------------------------------------------------------
@dataclass
class Options:
    """What the gate was told to do, in one object the workers share."""

    cache: Path = DEFAULT_CACHE
    work_root: Path = field(default_factory=Path)
    #: The store's own root. Held only so that a compiler message quoting a
    #: file inside it can name it instead of spelling this machine out.
    store_root: Path = field(default_factory=Path)
    tolerance: float = 1e-10
    near_zero_fraction: float = 1e-8
    strain: float = PROBE_STRAIN
    build_timeout: int = 900
    run_timeout: int = 300
    flags: tuple[str, ...] = BASE_FLAGS


#: Every casing a UMAT in this corpus quotes the Abaqus header with.
HEADER_NAMES = ("ABA_PARAM.INC", "aba_param.inc", "ABA_PARAM.inc", "aba_param.INC")


def install_headers(directory: Path) -> str:
    """Make the Abaqus header resolvable under every name it is included by.

    Concrete failure this exists for: the first real corpus source through this
    gate, AnargyrosKarakalas__UMAT_3D, failed to build with "Error: Can't open
    included file 'ABA_PARAM.INC'". The installation on this machine ships
    ``aba_param.inc`` in lowercase only, and ``build_replay`` writes the
    project's stub only when there is no installation at all -- so on a machine
    that *has* Abaqus, every source that spells the include in capitals was
    being reported as a build failure, which reads as a defect in a source that
    compiles perfectly well for the solver.

    The installation's own header is what gets aliased wherever there is one.
    A reference built against an approximation of the header the solver used is
    an approximation of the reference, and the stub is exactly that: it
    reproduces the implicit REAL*8 default and nothing else.
    """
    from umat_oti.abaqus.replay import abaqus_include_dir
    from umat_oti.corpus.cli import _write_aba_param_stub

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    installed = abaqus_include_dir()
    header = installed / "aba_param.inc" if installed else None
    if header is None or not header.is_file():
        _write_aba_param_stub(directory)
        return STUB_HEADER
    text = header.read_text(errors="replace")
    for name in HEADER_NAMES:
        (directory / name).write_text(text, encoding="utf-8")
    return INSTALLED_HEADER


def read_source(path: Path) -> str:
    """The text of a source, or "" when it cannot be read.

    An unreadable source is an outcome this gate reports a moment later with
    the compiler's own words, so reading it here to look for a PAUSE must not
    be what ends the batch.
    """
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _blocking(path: Path) -> list[str]:
    return list(blocking_statements(read_source(path)))


def check_entry(entry: Any, material: Optional[Material],
                options: Options) -> dict[str, Any]:
    """One stored transform, built both ways and driven from the same state.

    The two builds are compiled into separate directories. They have to be:
    ``build_replay`` writes its driver and its program under the directory it
    is given, and the transformed build writes module files there as well, so
    sharing one directory would have the second build overwrite the first
    program and compare a source with itself.
    """
    roots = ((options.store_root, "<store>"), (options.cache, "<cache>"),
             (options.work_root, "<work>"))
    record: dict[str, Any] = {
        "key": str(getattr(entry, "key", "")),
        "source_id": str(getattr(entry, "source_id", "")),
        "source_sha256": str(getattr(entry, "source_sha256", "")),
        "fingerprint": str(getattr(entry, "fingerprint", "")),
        "material_provenance": "",
        "original_available": True,
        "original_reason": "",
        "built_original": False, "original_build_reason": "",
        "built_transformed": False, "transformed_build_reason": "",
        "ran_original": False, "ran_transformed": False, "run_reason": "",
        "response": False,
        "agreed": False,
        "worst_relative": None,
        "comparison_reason": "",
        "unresolved_components": 0,
        "blocking_statements": {},
        "probe": PROBE_PROVENANCE,
    }

    original = original_source(entry, options.cache)
    intact, why = original_is_intact(original, record["source_sha256"])
    record["original_available"] = intact
    record["original_reason"] = why
    transformed = Path(getattr(entry, "entry_source", ""))

    blocking = {name: found for name, found in
                (("original", _blocking(original) if intact else []),
                 ("transformed", _blocking(transformed)))
                if found}
    record["blocking_statements"] = blocking
    record["blocking_note"] = blocking_note(blocking.get("original", ()),
                                            blocking.get("transformed", ()))

    if intact and material is not None:
        record["material_provenance"] = material.provenance
        record.update(material.as_dict())
        state = probe_entry(material, strain=options.strain)
        record["probe_dstran"] = state["DSTRAN"]
        # Resolved once, for both builds. See the build call below.
        material_name = material.name or "MATERIAL"
        record["cmname"] = material_name

        work = Path(options.work_root) / (record["key"] or "entry")
        sides: dict[str, dict[str, Any]] = {}
        for name, source, extra in (
                ("original", original, ()),
                ("transformed", transformed,
                 compile_order(Path(getattr(entry, "directory", ".")),
                               exclude=transformed))):
            side_dir = work / name
            side_dir.mkdir(parents=True, exist_ok=True)
            install_headers(side_dir)
            write_state(state, side_dir / STATE_FILE)
            # ONE material name for both builds. It becomes CMNAME, and the
            # transformed file is always <stem>_oti, so deriving it from each
            # file's basename gave the original CMNAME='U' and the transformed
            # CMNAME='U_OTI'. Ten sources in this cache branch on CMNAME, so
            # the two sides could take different paths through the same model
            # -- and the comparison would be reporting that difference as a
            # defect in the transform.
            build = build_replay(
                source, side_dir, name=material_name, extra=extra,
                flags=(*options.flags, f"-J{side_dir}"),
                timeout=options.build_timeout)
            sides[name] = {"build": build, "dir": side_dir}
            record[f"built_{name}"] = bool(build.ok)
            if not build.ok:
                record[f"{name}_build_reason"] = compiler_reason(
                    build.reason, build.log, roots=roots)
            record[f"{name}_header"] = header_note(build.header)

        if all(record[f"built_{name}"] for name in ("original", "transformed")):
            stresses: dict[str, list[float]] = {}
            complaints = []
            for name, side in sides.items():
                # Component 0 perturbs nothing: this is the model's own answer
                # to the increment it was handed, which is what parity means.
                stress, complaint = run_replay(
                    side["build"], side["dir"], 0, 0.0,
                    timeout=options.run_timeout)
                stresses[name] = stress
                record[f"ran_{name}"] = bool(stress)
                if complaint:
                    complaints.append(f"{name}: {complaint}")
            record["run_reason"] = compiler_reason(
                "", "\n".join(complaints), roots=roots)
            record["stress_original"] = stresses.get("original", [])
            record["stress_transformed"] = stresses.get("transformed", [])
            record["response"] = bool(
                stress_response(stresses.get("original", ()))
                or stress_response(stresses.get("transformed", ())))
            record["non_finite_components"] = non_finite_count(
                stresses.get("original", ()), stresses.get("transformed", ()))

            if record["ran_original"] and record["ran_transformed"]:
                comparison = compare_primal(
                    [single_record(stresses["original"])],
                    [single_record(stresses["transformed"])],
                    tolerance=options.tolerance,
                    near_zero_fraction=options.near_zero_fraction)
                # The comparison is the authority on all three of these now:
                # it refuses agreement on a non-finite value, on a response
                # that never moved, and across histories of different length.
                record["agreed"] = bool(comparison.agrees)
                record["worst_relative"] = comparison.worst_stress_relative
                record["comparison_reason"] = comparison.reason
                record["unresolved_components"] = comparison.unresolved_components
                record["resolved_components"] = comparison.resolved_components
                record["non_finite_components"] = comparison.non_finite_components
                record["tolerance"] = options.tolerance
                # Recorded on the row so a resumed batch can tell whether a
                # reused verdict was reached under the options now in force.
                record["strain_increment"] = options.strain

    record["outcome"], record["reason"] = outcome_for(record)
    return record


def check_one(entry: Any, material: Optional[Material],
              options: Options) -> dict[str, Any]:
    """``check_entry`` with a fence around it.

    One source that makes the compiler segfault, or a work directory that
    cannot be created, must not take the other entries of a batch down with
    it. The failure is recorded as its own outcome and stays in the
    denominator; it is never quietly absent.
    """
    try:
        return check_entry(entry, material, options)
    except Exception:  # noqa: BLE001 - the batch has to survive one bad source
        # The tail of a traceback, not the head: the exception and the frame
        # that raised it are at the end, and they are the finding.
        detail = portable_text(traceback.format_exc(),
                               ((options.store_root, "<store>"),
                                (options.cache, "<cache>"),
                                (options.work_root, "<work>")))
        return {
            "key": str(getattr(entry, "key", "")),
            "source_id": str(getattr(entry, "source_id", "")),
            "outcome": HARNESS_ERROR,
            "reason": detail[-REASON_LIMIT:],
            "agreed": False, "worst_relative": None,
            "built_original": False, "built_transformed": False,
            "blocking_statements": {},
        }


def run_batch(entries: Sequence[Any], materials: dict[str, Material],
              options: Options, jobs: int = 1) -> list[dict[str, Any]]:
    """Every entry, up to ``jobs`` at a time.

    Threads, not processes. Nearly all of the wall clock here is gfortran and
    the driver running as child processes, which release the interpreter while
    they work; a process pool would add the cost of shipping the store entries
    across a pipe to buy nothing.
    """
    def one(entry: Any) -> dict[str, Any]:
        return check_one(entry, materials.get(str(entry.source_id)), options)

    if jobs <= 1:
        return [one(entry) for entry in entries]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, entries))


def build_report(records: Sequence[dict[str, Any]], store_summary: dict,
                 options: Options) -> dict[str, Any]:
    """The JSON payload, with the caveat attached to the numbers themselves."""
    ordered = sorted(records, key=lambda record: str(record.get("source_id")))
    return {
        "tool": "verify_store_offline",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "what_this_is": CAVEAT,
        "probe": {
            "provenance": PROBE_PROVENANCE,
            "strain_increment": options.strain,
            "coords": list(PROBE_COORDS),
            "initial_stress": "zero", "initial_state": "zero",
        },
        "tolerance": options.tolerance,
        "store": {key: value for key, value in store_summary.items()
                  if key != "root"},
        "summary": summarise(ordered),
        "entries": ordered,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline stress-parity gate over the transform store. "
                    "Not Abaqus verification.")
    parser.add_argument("--store", type=Path, default=None,
                        help="transform store root (default: the store's own)")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE,
                        help="discovery cache holding the original sources")
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--manifests", type=Path, default=DEFAULT_MANIFESTS)
    parser.add_argument("--json", type=Path, default=DEFAULT_OUT,
                        dest="out", help="where to write the report")
    parser.add_argument("--jobs", type=int, default=1,
                        help="entries to check at a time")
    parser.add_argument("--resume", action="store_true",
                        help="reuse decided rows from an existing --json output")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--strain", type=float, default=PROBE_STRAIN)
    parser.add_argument("--build-timeout", type=int, default=900)
    parser.add_argument("--run-timeout", type=int, default=300)
    parser.add_argument("--work", type=Path, default=None,
                        help="where the builds happen (default: a temp dir)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    store = TransformStore(root=args.store)
    entries = store.current_entries()
    if args.limit:
        entries = entries[:args.limit]

    previous = load_previous(args.out) if args.resume else {}
    todo, reused = partition_for_resume(entries, previous)

    work_root = Path(args.work) if args.work else Path(
        tempfile.mkdtemp(prefix="offline_gate_"))
    work_root.mkdir(parents=True, exist_ok=True)
    options = Options(cache=args.cache, work_root=work_root,
                      store_root=store.root,
                      tolerance=args.tolerance, strain=args.strain,
                      build_timeout=args.build_timeout,
                      run_timeout=args.run_timeout)

    materials = dict(proposal_materials(args.proposals))
    materials.update(manifest_materials(args.manifests))

    records = run_batch(todo, materials, options, jobs=max(1, args.jobs))
    report = build_report([*records, *reused], store.summary(), options)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False, because the default emits bare NaN/Infinity, which is
    # not JSON: jq and most non-Python parsers reject the artifact while
    # Python's own json.loads accepts it, so the tests never noticed. Any
    # non-finite value is labelled instead of silently becoming a token no
    # reader can parse.
    args.out.write_text(
        json.dumps(_json_safe(report), indent=1, allow_nan=False) + "\n",
        encoding="utf-8")
    if not args.quiet:
        print(format_summary(report["summary"]))
        if reused:
            print(f"  ({len(reused)} row(s) reused from a previous run)")
        print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
