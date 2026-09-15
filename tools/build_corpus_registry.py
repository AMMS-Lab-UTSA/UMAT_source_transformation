#!/usr/bin/env python3
"""One record per downloaded artefact, and a report a person can read.

The registry is the denominator. Every file the acquisition brought back is in
it exactly once, whether it transformed, whether it ran, whether it is even a
UMAT -- because a source that quietly stopped being attempted leaves no failing
row to notice, and a summary built from the rows a batch happened to produce
would never show it.

So the denominator is SEEDED FROM THE ACQUISITION INVENTORY and the batches are
joined onto it, never the other way round. Building it from the transform
report instead would have worked -- that report happens to carry all 391 rows
today -- and it would have gone on working silently on the day a run stopped
attempting a source, because a registry built from the attempts cannot show an
attempt that was never made. The inventory is 391 rows; the assertion that the
registry is too lives in
``tests/test_the_registry_is_the_denominator.py::test_the_registry_holds_every_one_of_the_391_discovered_sources``.

Each record carries a terminal state and who has to move next. Four of them are
final and external: nobody published the constants, the file is not a UMAT, it
does not compile as published, a module it needs was never published beside it.
One is final and verified. The rest are unfinished and OURS, named as precisely
as the evidence allows so the cluster a failure belongs to is visible -- because
that is what decides which fix is worth making, and because calling any of them
a terminal state would be relabelling our own limitation as somebody else's.

    tools/build_corpus_registry.py \
        --transform <run>/transform_batch.json \
        --abaqus <run>/results/store_verification.jsonl \
        --json paper_results/corpus/corpus_registry.json \
        --csv  paper_results/corpus/corpus_registry.csv \
        --markdown paper_results/corpus/CORPUS_VERIFICATION.md
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]


def _relative_to_repo(path) -> str:
    """A path as the repository sees it, not as one machine happened to.

    An input that lives outside the repository still has to be NAMED, because
    every number in the report has to be traceable to a file on disk. Falling
    back to the bare filename does not do that: three different verification
    passes wrote a file called ``store_verification.jsonl``, and a report that
    cites one of them by basename cites all three.

    So enough of the tail is kept to identify which file it was --
    ``pass10/results/store_verification.jsonl`` -- and everything at or above
    the home directory is dropped first, so a username can never survive into
    a published field.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO))
    except (ValueError, OSError):
        pass
    parts = [part for part in resolved.parts if part not in ("/", "")]
    try:
        home = [part for part in Path.home().resolve().parts
                if part not in ("/", "")]
    except (OSError, RuntimeError):
        home = []
    if home and parts[:len(home)] == home:
        parts = parts[len(home):]
    if home:
        parts = [part for part in parts if part != home[-1]]
    return "/".join(parts[-3:]) if parts else resolved.name


#: A path under someone's home directory, or under a per-process scratch
#: directory. Either one names the machine a run happened on, and a registry
#: that carries one cannot be reproduced from a clean clone --
#: ``tools/audit_repository_standards.py`` fails the build on it, and this
#: registry has failed on exactly that before.
#:
#: The strings that can carry one are not the obvious ones. They are the
#: compiler's own diagnostics, which name the temporary directory the syntax
#: pass ran in, and they arrive inside ``classification_basis`` and
#: ``compile_defect`` having been copied out of an audit file written on
#: another day. So the check is applied to the SERIALISED payload, after
#: everything has been assembled and immediately before it is written, which
#: is the only place that sees every string that is about to be published.
MACHINE_PATH = re.compile(
    r"(?:/home/[a-z][-a-z0-9_]*|/Users/[A-Za-z][-A-Za-z0-9_]*"
    r"|/tmp/[A-Za-z0-9][-A-Za-z0-9_.]*|/var/folders/[A-Za-z0-9])/")


def refuse_machine_paths(text: str, what: str) -> str:
    """The text, or an exception naming the first machine path in it.

    Scrubbing silently would be worse than failing: a registry that quietly
    dropped part of a compiler diagnostic would still be published, and the
    reader would have no way to know a line had been edited. So this refuses,
    the build stops, and whoever added the field decides what belongs there.
    """
    found = MACHINE_PATH.search(text or "")
    if not found:
        return text
    line = text[:found.start()].count("\n") + 1
    excerpt = text[max(0, found.start() - 60):found.end() + 60]
    raise ValueError(
        f"{what} would publish a machine path at line {line}: ...{excerpt}... "
        f"Every path a reviewer reads must be relative to the repository; "
        f"use _relative_to_repo(), or keep the machine-specific part out of "
        f"the field entirely.")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.abaqus.terminal_states import (EXTERNAL, FROM_STAGE,  # noqa: E402
                                             FULLY_VERIFIED, INTERNAL,
                                             WAITS_FOR_INPUT, Verdict,
                                             from_transform_failure)
from umat_oti.abaqus.terminal_states import kind_of as _shared_kind_of  # noqa: E402


class UntranslatableStage(ValueError):
    """A rung the registry has no corpus verdict for.

    This is an exception and not a default ON PURPOSE. ``from_stage`` answers
    ``not_attempted`` for a name it does not know, which is INTERNAL and reads
    "no batch ever reached this source" -- and three pass11 entries settled at
    ``arguments_diverged_before_the_routine``, a rung the verification tool
    added and the shared table had not been told about. Translated by the
    default they became three sources nobody had tried, filed under this
    project's own column, with the evidence that the difference was in the
    author's own deck sitting unread in the record.

    A registry cannot notice that. The whole point of it is to be the thing
    that notices, so an unknown rung stops the build.
    """


#: Rungs the verification tool emits that ``umat_oti.abaqus.terminal_states``
#: does not yet carry, with the owner each one belongs to. This table is a
#: STOPGAP and says so: the shared module is where these belong, and the
#: consistency check below makes the day they arrive there a no-op rather than
#: a contradiction.
#:
#: ``arguments_diverged_before_the_routine`` is INTERNAL. The two builds were
#: handed arguments that had already parted before the call whose outputs
#: differ -- and the solver computed those arguments from each build's own
#: earlier outputs, on a deck this project generated. It was filed EXTERNAL
#: here once, which put three of this project's primal disagreements in
#: somebody else's column; the shared table now carries it as internal.
#:
#: ``disagreement_not_in_any_recorded_call`` is INTERNAL, and about THIS
#: HARNESS. Every paired call returned bit-identical outputs and the history
#: comparison reported a difference anyway. Whatever that is, it is a defect in
#: how this pipeline compares two histories, and filing it as anything else
#: would be charging somebody else for our own measurement.
LOCAL_STATES: dict[str, str] = {
    "arguments_diverged_before_the_routine": "internal",
    "disagreement_not_in_any_recorded_call": "internal",
}

#: Rungs that translate to themselves, kept beside the shared table so the
#: registry's published vocabulary is the union and nothing is invented at the
#: point of use.
_LOCAL_FROM_STAGE = {state: state for state in LOCAL_STATES}


def kind_of(state: str) -> str:
    """Who has to move next, over the shared vocabulary AND the local one.

    The shared module answers "internal" for any state it has not heard of,
    which is the safe direction; a local entry must agree with it the moment
    the shared table carries the state.
    """
    if state in LOCAL_STATES:
        return LOCAL_STATES[state]
    return _shared_kind_of(state)


def _stage_the_gates_support(row: dict) -> str:
    """The shared rule, so the registry cannot drift from promotion or the GUI."""
    from umat_oti.abaqus.terminal_states import stage_supported_by_gates
    return stage_supported_by_gates(row)


def translate_stage(stage: str, reason: str = "") -> Verdict:
    """The corpus verdict for a batch rung, or a refusal to guess at one."""
    name = str(stage or "")
    if name in FROM_STAGE:
        state = FROM_STAGE[name]
        if name in LOCAL_STATES and _shared_kind_of(state) != LOCAL_STATES[name]:
            raise UntranslatableStage(
                f"{name!r} is {LOCAL_STATES[name]} here and "
                f"{_shared_kind_of(state)} in "
                f"umat_oti.abaqus.terminal_states. Two answers to 'whose move "
                f"is it?' is worse than none; delete the entry in "
                f"LOCAL_STATES once the shared table carries it, or fix "
                f"whichever of the two is wrong.")
        return Verdict(state=state, kind=kind_of(state), reason=reason)
    if name in _LOCAL_FROM_STAGE:
        state = _LOCAL_FROM_STAGE[name]
        return Verdict(state=state, kind=kind_of(state), reason=reason)
    raise UntranslatableStage(
        f"the verification batch settled an entry at {name!r} and this "
        f"registry has no corpus verdict for it. Add it to "
        f"umat_oti.abaqus.terminal_states.FROM_STAGE with the kind it belongs "
        f"to -- external if the answer lies in what somebody published, "
        f"internal if it lies in this repository -- or to LOCAL_STATES in "
        f"{Path(__file__).name} until it can go there. It must NOT be left to "
        f"default: the default is 'not_attempted', which reads as 'no batch "
        f"reached this source' and is internal.")


#: Every state this registry can publish, in one place, so the vocabulary the
#: report prints and the vocabulary it translates into cannot drift.
ALL_EXTERNAL = tuple(EXTERNAL) + (WAITS_FOR_INPUT,) + tuple(
    state for state, kind in LOCAL_STATES.items()
    if kind == "external" and state not in EXTERNAL)
ALL_INTERNAL = tuple(INTERNAL) + tuple(
    state for state, kind in LOCAL_STATES.items()
    if kind == "internal" and state not in INTERNAL)

#: A one-line gloss for every terminal state, read from the page that already
#: has to have one. Imported rather than restated so the report and the
#: interface cannot drift into describing the same state two different ways,
#: and because a table of state names is not a human-readable report.
from umat_oti.app.corpus_tab import GLOSS as _SHARED_GLOSS  # noqa: E402

#: Glosses for the states the shared page does not carry one for. A state
#: printed with an empty "what it means" column is a name, and a table of
#: names is not a human-readable report -- which is the whole reason the
#: glosses are imported rather than restated in the first place.
_LOCAL_GLOSS = {
    "arguments_diverged_before_the_routine":
        "the two builds' histories differ, and the recorded calls say the "
        "arguments had already parted before the call whose outputs differ; "
        "the solver computed them from each build's own earlier outputs, so "
        "where the paths parted is this project's to find",
    "disagreement_not_in_any_recorded_call":
        "every paired call returned bit-identical outputs and the history "
        "comparison reported a difference anyway -- a defect in how this "
        "harness compares two histories, not a finding about the routine",
    "published_stub_no_constitutive_content":
        "the author published the UMAT interface and no constitutive "
        "content: a routine that assigns neither STRESS nor DDSDDE and "
        "makes no call",
}

STATE_MEANS = {**_LOCAL_GLOSS, **_SHARED_GLOSS}

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO.parent / "discovery_cache")

#: The acquisition inventory: one row per discovered source, written by the
#: discovery triage before anything was transformed. This is the denominator.
DEFAULT_INVENTORY = REPO / "paper_results/discovery/discovery_triage.csv"

#: Where the acquisition recorded, per repository, the 40-character commit it
#: read and the licence it read it under. The per-file URL is reconstructed
#: from that commit, which is why ``url_provenance`` says so on every record
#: rather than letting a derived URL pass for a recorded one.
DEFAULT_ACQUISITION = (REPO / "paper_results/corpus/companions.json",
                       REPO / "paper_results/corpus/companions_wave2.json")

#: The offline evidence about what each refused source is. Written by
#: ``--refusal-audit``; read back on every later build so the registry can be
#: rebuilt on a machine with no Fortran compiler and get the same answers.
DEFAULT_AUDIT = REPO / "paper_results/corpus/transform_refusal_audit.json"


@dataclass
class Record:
    """One acquired artefact, and everything established about it."""

    source_id: str
    repository: str = ""
    #: Where the file sits inside the acquisition cache, and where it came
    #: from. Held on every record, not only the ones that ran: a classification
    #: nobody can trace back to a commit and a path is an assertion.
    cache_path: str = ""
    acquisition_url: str = ""
    url_provenance: str = ""
    commit: str = ""
    license_spdx: str = ""
    sha256: str = ""
    bytes: Optional[int] = None
    source_form: str = ""
    is_umat: Optional[bool] = None
    entry_interface: str = ""
    entry_routine: str = ""
    entry_line: Optional[int] = None
    #: The line of the author's own file the entry point was read from,
    #: verbatim, and which piece of evidence decided the classification.
    entry_evidence: str = ""
    classification_basis: str = ""
    #: What a source the TRANSFORMER refused turned out to be, decided by
    #: parsing the file rather than by the refusal. See
    #: umat_oti.corpus.entry_routines.classify_refusal.
    refusal_class: str = ""
    refusal_class_confident: Optional[bool] = None
    duplicate_of: str = ""
    companion_files: str = ""
    #: Where the whole file was searched for the two outputs a UMAT exists to
    #: produce, and what was found. Recorded on EVERY record and not only on
    #: the ones it decided, because a reader checking "is this a real UMAT?"
    #: needs the search itself and not the verdict that came out of it.
    writes_stress: Optional[bool] = None
    writes_ddsdde: Optional[bool] = None
    output_calls: Optional[int] = None
    output_first_write: str = ""
    output_first_write_line: Optional[int] = None
    output_search: str = ""
    #: THE SECOND DENOMINATOR. Whether this source is an adequately specified
    #: genuine UMAT -- a file that presents the Abaqus UMAT interface, is a
    #: distinct member of the corpus, builds as published, has everything it
    #: USEs published beside it, and has a constitutive model inside it. The
    #: 391 acquired sources are the first denominator; this is the subset any
    #: verification rate may be quoted against, and ``adequacy_basis`` names
    #: the evidence that excluded a source from it.
    adequately_specified: Optional[bool] = None
    adequacy_basis: str = ""
    #: Why it is outside D2, on the axis that matters: "external" -- somebody
    #: published something that cannot be driven; "duplicate" -- it is a
    #: second copy and its one answer is already counted against the copy that
    #: carries it; "internal" -- a limitation of this project, which must
    #: never appear, because an internal limitation may not shrink a
    #: denominator. A duplicate is deliberately NOT called external: nothing
    #: about it is blocked, and listing it under a heading of external
    #: blockers would inflate how much of the corpus is somebody else's
    #: problem.
    adequacy_kind: str = ""
    terminal_state: str = "not_attempted"
    kind: str = "internal"
    reason: str = ""
    stage: str = ""
    #: Whether any batch produced a row for this source at all. A source the
    #: run never reached is not a source the run refused, and reading the
    #: second as the first invents a refusal nobody recorded.
    attempted: bool = False
    transformed: bool = False
    compiled: Optional[bool] = None
    ntens: Optional[int] = None
    ntens_provenance: str = ""
    element_type: str = ""
    formulation: str = ""
    kinematics: str = ""
    deck: str = ""
    material_provenance: str = ""
    props_count: Optional[int] = None
    nstatv: Optional[int] = None
    activated: Optional[bool] = None
    activation_amplitude: Optional[float] = None
    time_dependent: Optional[bool] = None
    response_character: str = ""
    worst_stress_relative: Optional[float] = None
    worst_state_relative: Optional[float] = None
    primal_increments: Optional[int] = None
    precision_control: Optional[bool] = None
    tangent_states_checked: Optional[int] = None
    tangent_states_agreeing: Optional[int] = None
    worst_tangent_relative: Optional[float] = None
    tangent_plateau: str = ""
    missing_companions: str = ""
    compile_defect: str = ""
    key: str = ""
    seconds: Optional[float] = None
    #: The store fingerprint the verification row was produced against, and
    #: whether that is the fingerprint of the store as it stands now. A stage
    #: recorded against a store that has since been rebuilt is evidence about
    #: a transformed file that no longer exists, and reading it as evidence
    #: about the current one is how a stale verdict becomes a verification.
    verification_fingerprint: str = ""
    verification_is_current: Optional[bool] = None
    #: Which results file the row was read from, named so every number in the
    #: report can be traced to a file on disk.
    verification_source: str = ""
    #: The sha256 of the ACQUIRED file the verification row says it ran, as the
    #: row recorded it, and whether that agrees with the sha256 this registry
    #: computed from the cache. A row that names a different file is not
    #: evidence about this one however well the paths line up.
    verification_sha256: str = ""
    verification_sha256_agrees: Optional[bool] = None
    #: A verification row for this source that was produced against an earlier
    #: store and is therefore about generated Fortran that no longer exists.
    #: Recorded rather than discarded, because a reader comparing this registry
    #: against the raw results file needs to see which rows were set aside and
    #: why -- and because "the file says 44 verified" and "41 sources verified"
    #: have to be reconcilable from what is written down.
    superseded_verification: str = ""
    #: For anything that is not fully_verified: the named reason, with the
    #: evidence behind it. Never "the transformer refused it" on its own.
    not_verified_reason: str = ""
    #: Each of the six evidence gates, as one of five words: ``true``,
    #: ``false``, ``null`` (the key is there and holds nothing), ``absent``
    #: (the key is not there at all) or ``no_evidence_block``.
    #:
    #: A MISSING KEY AND A PRESENT-AND-NULL KEY ARE BOTH "NOT ESTABLISHED",
    #: and a census that counts one and silently drops the other does not add
    #: up to its own denominator. Over the whole results file the
    #: ``mechanically_informative`` gate reads true on 113, false on 22, null
    #: on 7 and is absent on 4 -- 146 rows carrying an evidence block -- and a
    #: count that saw only the null ones reported 142 and reconciled with
    #: nothing.
    gate_abaqus_job_completed: str = ""
    gate_all_requested_outputs_present: str = ""
    gate_complete_history_finite: str = ""
    gate_derivatives_verified: str = ""
    gate_primal_agreed: str = ""
    gate_mechanically_informative: str = ""
    #: Whether every one of the six reads true. This is a STRICTER answer than
    #: the batch's ``verified`` rung, and the two are published side by side
    #: rather than one being chosen: three entries reached the rung with
    #: ``primal_agreed`` false and a written explanation of why the difference
    #: is the model's own conditioning.
    verified_on_every_gate: Optional[bool] = None
    #: Which gates did not read true, and in what way.
    gates_not_true: str = ""
    #: Whether a CONTROL that actually ran explains why ``primal_agreed``
    #: reads false beside a verdict of verified.
    #:
    #: Three values, and the third is the point. ``True``: a control ran and
    #: accounted for the difference. ``False``: a control ran and did NOT --
    #: which is a different answer from never having asked, and leaving it as
    #: None would report a measurement that happened as one that did not.
    #: ``None``: no control was needed, which is every entry whose two builds
    #: agreed.
    #:
    #: Read from ``evidence`` where the batch recorded it. pass11 predates the
    #: flag, so for that file it is DERIVED from the two things the batch did
    #: write -- ``primal.explained_by_declared_precision`` and
    #: ``primal.explained_by_operation_order`` -- and
    #: ``control_flag_provenance`` says which of the two happened, because a
    #: derived field that cannot be told from a recorded one is a field a
    #: reader cannot check.
    primal_difference_explained_by_a_measured_control: Optional[bool] = None
    control_flag_provenance: str = ""
    #: Which control ran, and the number it measured. A verdict that rests on
    #: a control is only as good as the control being visible.
    primal_control: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _rows(path: Optional[Path]) -> list:
    """Every record, one per entry: the last one written.

    The results file is append-only, so a resumed run that re-runs an entry
    appends a second record rather than editing the first. Keeping both would
    put a superseded verdict in the registry beside the one that replaced it.
    """
    if not path or not Path(path).is_file():
        return []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if Path(path).suffix == ".jsonl":
        latest: dict = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            latest[str(record.get("key") or record.get("source") or line)] = record
        return list(latest.values())
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload.get("entries") or payload.get("rows") or []
    return payload or []


def verification_reconciliation(abaqus_report: Optional[Path],
                                store_fingerprint: str) -> dict:
    """Why the results file holds more rows than the store holds entries.

    Two numbers disagreed and a registry that cannot explain its own
    denominator is not evidence, so the arithmetic is written down rather than
    asserted.

    ``pass10/results/store_verification.jsonl`` holds 254 rows for a store of
    240 entries. 240 of those rows carry the fingerprint of the store as it
    stands; the other 14 carry the fingerprint of the store as it stood before
    the re-transform, and are there because the results file is append-only
    and the pass resumed onto the file an earlier pass had been writing. 11 of
    those 14 sources were re-run at the current fingerprint, so both rows exist
    for them; the remaining 3 are no longer in the store at all, because the
    re-transform refused them. 240 + 3 = 243 distinct sources, 254 rows.

    The key cannot collapse them: it is derived from the STORE ENTRY, so the
    same source under two fingerprints has two keys and all 254 are distinct.
    The source sha256 cannot collapse them either, in the other direction: 240
    rows carry only 232 distinct source digests, because several acquired
    files are byte-identical to another acquired file and both transformed.
    The identity is the PATH INSIDE THE CACHE, and the digest is what
    corroborates that the row is about the file this registry read.

    The same append-only leftovers are why the file contains 44 rows at stage
    ``verified`` while the run reported 41 of 240. Three sources verified under
    the old store and verified again under the new one; counting rows counts
    them twice. 41 is the number of store entries that verified, and it is the
    one this registry publishes.
    """
    rows = _rows(abaqus_report)
    if not rows:
        return {}
    current = [r for r in rows if str(r.get("fingerprint") or "") == store_fingerprint]
    stale = [r for r in rows if str(r.get("fingerprint") or "") != store_fingerprint]
    current_sources = {str(r.get("source") or "") for r in current}
    verified_now = {str(r.get("source") or "") for r in current
                    if str(r.get("stage") or "") == "verified"}
    stale_verified = [str(r.get("source") or "") for r in stale
                      if str(r.get("stage") or "") == "verified"]
    return {
        "file": _relative_to_repo(abaqus_report) if abaqus_report else "",
        "store_fingerprint": store_fingerprint,
        "rows_in_the_file": len(rows),
        "rows_at_the_current_store_fingerprint": len(current),
        "rows_at_a_superseded_store_fingerprint": len(stale),
        "distinct_sources_in_the_file": len(
            {str(r.get("source") or "") for r in rows}),
        "distinct_keys_in_the_file": len(
            {str(r.get("key") or "") for r in rows}),
        "distinct_source_digests_at_the_current_fingerprint": len(
            {str(r.get("source_sha256") or "") for r in current}),
        "sources_counted_by_this_registry": len(current_sources),
        "superseded_rows_whose_source_was_rerun": sorted(
            str(r.get("source") or "") for r in stale
            if str(r.get("source") or "") in current_sources),
        "superseded_rows_whose_source_is_no_longer_in_the_store": sorted(
            str(r.get("source") or "") for r in stale
            if str(r.get("source") or "") not in current_sources),
        # The word the FILE carries, kept only so the correction below can be
        # seen. It is not a count of anything verified.
        "rows_whose_file_stage_says_verified": sum(
            1 for r in rows if str(r.get("stage") or "") == "verified"),
        # THE one verified number. A row may say verified while its own
        # evidence carries a gate reading false; the gates decide.
        "store_entries_that_verified": sum(
            1 for r in current
            if _stage_the_gates_support(r) == "verified"),
        "store_entries_that_verified_on_every_gate": sum(
            1 for r in current
            if _stage_the_gates_support(r) == "verified"
            and all(_gate_state(r.get("evidence"), gate) == GATE_TRUE
                    for gate in EVIDENCE_GATES)),
        "rows_demoted_because_their_own_evidence_contradicts_the_word": sorted(
            str(r.get("source") or "") for r in current
            if str(r.get("stage") or "") == "verified"
            and _stage_the_gates_support(r) != "verified"),
        "verified_rows_that_double_count_a_source": sorted(
            name for name in stale_verified if name in verified_now),
        "evidence_gate_census_over_the_whole_file": {
            "denominator": len([r for r in rows
                                if isinstance(r.get("evidence"), dict)]),
            "denominator_is": ("rows in the results file carrying an evidence "
                               "block, at any store fingerprint"),
            "gates": {
                gate: {
                    state: sum(1 for r in rows
                               if isinstance(r.get("evidence"), dict)
                               and _gate_state(r["evidence"], gate) == state)
                    for state in (GATE_TRUE, GATE_FALSE, GATE_NULL, GATE_ABSENT)
                } for gate in EVIDENCE_GATES},
        },
        "there_is_one_verified_number": (
            "store_entries_that_verified. A row may carry the word 'verified' "
            "while its own evidence block holds a gate reading false -- that "
            "happened for thirteen entries, where a control measured WHY the "
            "two builds differ and the harness read the explanation as "
            "agreement. An explanation for a disagreement is not agreement. "
            "The stage is decided by the gates, those entries are at the "
            "INTERNAL rung primal_mismatch_explained, and every one of the "
            "391 sits in exactly one of verified / external / internal. There "
            "is no third number."),
    }


#: The six things a run has to establish before an entry may be called
#: verified, in the order the batch writes them.
EVIDENCE_GATES: tuple[str, ...] = (
    "abaqus_job_completed",
    "all_requested_outputs_present",
    "complete_history_finite",
    "derivatives_verified",
    "primal_agreed",
    "mechanically_informative",
)

#: The five states a gate can be in. The last three all mean "not
#: established", and they are kept apart because they have different causes: a
#: key holding null is a question the run asked and could not answer, a key
#: that is not there at all is a question that batch's schema did not ask, and
#: no evidence block is a run that never got far enough to ask any of them.
GATE_TRUE, GATE_FALSE = "true", "false"
GATE_NULL, GATE_ABSENT, GATE_NO_BLOCK = "null", "absent", "no_evidence_block"
GATE_NOT_ESTABLISHED = (GATE_NULL, GATE_ABSENT, GATE_NO_BLOCK)


def _gate_state(evidence, gate: str) -> str:
    """What one gate reads, distinguishing missing from present-and-null."""
    if not isinstance(evidence, dict):
        return GATE_NO_BLOCK
    if gate not in evidence:
        return GATE_ABSENT
    value = evidence[gate]
    if value is True:
        return GATE_TRUE
    if value is False:
        return GATE_FALSE
    return GATE_NULL


#: The key the verification tool writes for the control chain, once it writes
#: it. Named rather than spelled out at each use so the recorded field and the
#: derived one cannot come to be spelled differently.
CONTROL_GATE = "primal_difference_explained_by_a_measured_control"


def _control_explanation(row: dict) -> tuple:
    """Does a measured control explain this entry's primal difference?

    Returns the flag, where the flag came from, and what the control measured.

    The flag is READ where the batch recorded it and DERIVED where it did not,
    and the difference is reported rather than smoothed over. A registry that
    silently derived a field the batch is supposed to write would go on
    reporting the derivation long after the batch started disagreeing with it.
    """
    evidence = row.get("evidence")
    primal = row.get("primal") or {}
    precision = row.get("precision_control") or {}
    association = row.get("association_control") or {}
    if isinstance(evidence, dict) and CONTROL_GATE in evidence:
        recorded = evidence[CONTROL_GATE]
        flag = recorded if isinstance(recorded, bool) else None
        where = f"read from evidence.{CONTROL_GATE}"
    elif primal.get("explained_by_declared_precision") is True:
        flag, where = True, "derived from primal.explained_by_declared_precision"
    elif primal.get("explained_by_operation_order") is True:
        flag, where = True, "derived from primal.explained_by_operation_order"
    elif precision or association:
        # A control was run and did not account for it. NOT None: not-measured
        # and measured-and-refuted are different answers.
        flag, where = False, ("derived: a control ran and did not account for "
                              "the difference")
    elif primal.get("agrees") is True:
        flag, where = None, "no control was needed: the two builds agreed"
    else:
        flag, where = None, "no control is recorded for this entry"

    detail = ""
    if primal.get("explained_by_declared_precision") is True:
        detail = str(precision.get("reason") or "")[:400]
    elif primal.get("explained_by_operation_order") is True:
        own = primal.get("own_sensitivity")
        mine = primal.get("worst_stress_relative")
        detail = (
            f"the two builds differ by {mine:.3e} and this model differs from "
            f"itself by {own:.3e} under {association.get('how') or 'reordering'}"
            if isinstance(own, float) and isinstance(mine, float) else
            str(association.get("reason") or "")[:400])
    elif flag is False:
        detail = (str(primal.get("own_sensitivity_unmeasured") or "")
                  or str(association.get("reason") or "")
                  or str(precision.get("reason") or ""))[:400]
    return flag, where, detail


def census(rows: list, key, denominator_name: str) -> dict:
    """A count that proves its own arithmetic or refuses to be published.

    Every census in this registry has to sum to a denominator it states. The
    rule is here rather than at each call site because the failure it prevents
    is silent: a count taken over "records where the key is present and null"
    drops the records where the key is ABSENT, comes out four short of its own
    population, and reads perfectly well.
    """
    counts: dict[str, int] = {}
    for row in rows:
        value = str(key(row))
        counts[value] = counts.get(value, 0) + 1
    total = sum(counts.values())
    if total != len(rows):
        raise ValueError(
            f"a census over {denominator_name} counted {total} of "
            f"{len(rows)}: {counts}. A census that does not sum to its own "
            f"denominator is a finding about the data, not a number to "
            f"publish.")
    return {"denominator": len(rows),
            "denominator_is": denominator_name,
            "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "sums_to_the_denominator": True}


def _fingerprint_latest(rows: list, store_fingerprint: str) -> list:
    """One row per source: the newest one that is about the CURRENT store.

    An append-only results file accumulates rows across passes, and a pass
    that resumed from a previous one carries rows from before the store was
    rebuilt. Taking the last row per source would let a stale row win simply
    by having been appended later. So a row whose fingerprint matches the
    store the registry is being built for always beats one that does not, and
    only where a source has no matching row at all does the stale one survive
    -- kept so the registry can say what it was and why it does not count,
    rather than reporting silence.
    """
    if not store_fingerprint:
        return rows
    current: dict = {}
    stale: dict = {}
    for row in rows:
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        if str(row.get("fingerprint") or "") == store_fingerprint:
            current[source_id] = row
        else:
            stale[source_id] = row
    return list(current.values()) + [row for source_id, row in stale.items()
                                     if source_id not in current]


# ---------------------------------------------------------------------------
# The denominator, and where each of its entries came from
# ---------------------------------------------------------------------------
def inventory(path: Optional[Path]) -> list:
    """Every source the acquisition discovered, in the order it recorded them.

    The discovery triage writes one row per discovered source before anything
    is transformed, so it is the only artefact in the chain that cannot have
    been shortened by a batch that skipped something. A CSV and not a line
    split: blocker columns hold embedded newlines, and the 391-row file is 856
    lines long because of them.
    """
    if not path or not Path(path).is_file():
        return []
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with Path(path).open(newline="", encoding="utf-8") as handle:
            return [str(row.get("source") or "").strip()
                    for row in csv.DictReader(handle)
                    if str(row.get("source") or "").strip()]
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else (
        payload.get("rows") or payload.get("sources") or [])
    return [str(row if isinstance(row, str) else
                (row.get("source") or row.get("source_id") or "")).strip()
            for row in rows]


def acquisition_provenance(paths=DEFAULT_ACQUISITION) -> dict:
    """Per repository: the commit it was read at, and under which licence.

    The acquisition pinned every repository to a 40-character commit and wrote
    a URL beside each file it fetched. Those URLs are for the COMPANION files,
    not for the UMAT sources, so the per-source URL here is reconstructed from
    the repository's commit and the file's path inside the cache. That is a
    derivation, and ``url_provenance`` says so on every record: a derived URL
    presented as a recorded one is a small lie that a reader cannot detect.

    The owner/repo slug is taken from a recorded URL wherever the acquisition
    left one -- 134 of the 136 repositories the corpus draws on -- and falls
    back to splitting the cache directory name at its first ``__``. That rule
    is not guessed: it agrees with the recorded slug on all 134.
    """
    found: dict[str, dict] = {}
    for path in paths or ():
        if not Path(path).is_file():
            continue
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            continue
        for entry in payload.get("repositories") or []:
            name = str(entry.get("repository") or "")
            if not name or name in found:
                continue
            slug = ""
            for fetched in entry.get("fetched") or []:
                match = re.match(r"https://github\.com/([^/]+/[^/]+)/blob/",
                                 str(fetched.get("url") or ""))
                if match:
                    slug = match.group(1)
                    break
            found[name] = {
                "commit": str(entry.get("commit") or ""),
                "slug": slug or name.replace("__", "/", 1),
                "slug_provenance": ("recorded in an acquisition URL" if slug
                                    else "derived from the cache directory name"),
                "license_spdx": str(entry.get("license_spdx") or ""),
            }
    return found


def _acquisition_url(source_id: str, provenance: dict) -> tuple:
    """The URL this file was acquired from, and how that URL was arrived at."""
    repo_dir = source_id.split("/", 1)[0]
    rest = source_id.split("/", 1)[1] if "/" in source_id else ""
    entry = (provenance or {}).get(repo_dir)
    if not entry or not entry.get("commit"):
        return "", "no commit was recorded for this repository"
    quoted = "/".join(quote(part) for part in rest.split("/"))
    return (f"https://github.com/{entry['slug']}/blob/{entry['commit']}/{quoted}",
            f"reconstructed from the commit the acquisition pinned "
            f"({entry['commit'][:12]}), whose owner/repo was "
            f"{entry['slug_provenance']}")


def _line_identity(path: Path) -> str:
    """A digest of the file's lines, ignoring how they were newline-terminated.

    Only trailing whitespace and the CR of a CRLF are removed. Nothing that
    changes a COLUMN is touched, because in fixed-form Fortran a column carries
    meaning: collapsing runs of spaces made a file whose continuation markers
    sit in column 9 -- which no compiler accepts -- come out identical to one
    whose markers sit in column 6, and quietly filed a corrupt source as a
    duplicate of a working one.
    """
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in text.replace("\r\n", "\n")
             .replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def duplicate_map(cache: Optional[Path], source_ids) -> dict:
    """Which acquired sources are second copies, and of what.

    The first source_id in sort order is the one kept; the rest name it. Two
    files that are line-for-line identical carry one answer between them, and
    counting that answer twice inflates every rate computed from the corpus.
    """
    if not cache or not Path(cache).is_dir():
        return {}
    groups: dict = defaultdict(list)
    for source_id in source_ids:
        path = Path(cache) / source_id
        if path.is_file():
            groups[_line_identity(path)].append(source_id)
    duplicates: dict[str, str] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        canonical = sorted(members)[0]
        for member in sorted(members)[1:]:
            duplicates[member] = canonical
    return duplicates


# ---------------------------------------------------------------------------
# Does the author's own text build? Asked offline, without Abaqus.
# ---------------------------------------------------------------------------
#: ifort diagnostics that mean the compiler could not PARSE the text it was
#: given. They are the only ones this audit will call a defect in the file,
#: because a missing module cannot make a parser find ``&`` where an
#: identifier belongs, and cannot put an ENDDO where no DO was opened. Every
#: semantic diagnostic -- an undeclared name, a kind parameter that is not
#: constant, an argument of the wrong type -- is exactly what an unresolved
#: USE produces, so none of them may be read as the file's fault.
SYNTAX_DIAGNOSTICS = frozenset((
    "5082",   # syntax error
    "5078",   # unrecognised token
    "5118",   # first statement may not be a continuation
    "5143",   # missing mandatory item
    "5144",   # invalid attribute
    "5149",   # illegal character in the statement label field
    "5192",   # invalid statement
    "5195",   # continuation character illegal in this column in fixed form
    "5276",   # unbalanced parentheses
    "5274",
    "5287",
    "6099",   # ENDDO with no DO
    "6236",   # specification statement in the executable section
    "6317",   # ENDIF with no IF THEN
    "6343",   # invalid statement after a logical IF
    "6418",   # this name has already been assigned a data type
    "6222",   # IMPLICIT positioned wrongly in the scoping unit
    "6818",   # the statement after CONTAINS is not a procedure
))

#: The include the corpus writes as ``INCLUDE 'ABA_PARAM.INC'``. Its real
#: contents are read from the Abaqus installation when there is one, because a
#: stub that omits ``implicit real*8(a-h,o-z)`` changes the type of every
#: dummy argument and turns working files into type-mismatch errors.
ABA_PARAM_FALLBACK = ("      implicit real*8(a-h,o-z)\n"
                      "      parameter (nprecd=2)\n")
ABA_PARAM_SPELLINGS = ("ABA_PARAM.INC", "aba_param.inc", "ABA_PARAM.inc",
                       "Aba_param.inc", "aba_param.INC", "ABA_PARAM_DP.INC",
                       "aba_param_dp.inc")

#: Modules the compiler provides. ``resolve`` reports them as missing because
#: nothing in the repository defines them, which is true and irrelevant.
INTRINSIC_MODULES = frozenset((
    "iso_fortran_env", "iso_c_binding", "ieee_arithmetic", "ieee_exceptions",
    "ieee_features", "omp_lib", "omp_lib_kinds", "mpi", "mpi_f08", "openacc",
))

_INCLUDE = re.compile(r"^[^!'\"\n]*?\binclude\s*['\"]([^'\"]+)['\"]",
                      re.IGNORECASE | re.MULTILINE)


def _fortran_compiler() -> str:
    """A front end that reports diagnostic NUMBERS, or nothing.

    gfortran is not a substitute. Its diagnostics carry no numbers, so a
    syntax error cannot be told apart from an unresolved USE, and this audit
    would have to guess which of the two it was looking at. It returns "" and
    every verdict from the audit comes back unsettled, which is the honest
    answer for a machine that cannot ask the question.
    """
    for candidate in ("ifort", "ifx"):
        found = shutil.which(candidate)
        if found:
            return found
    for root in sorted(Path("/opt/intel/oneapi/compiler").glob("*/linux/bin*"),
                       reverse=True):
        for candidate in ("intel64/ifort", "ifort", "ifx"):
            if (root / candidate).is_file():
                return str(root / candidate)
    return ""


def _abaqus_header_dir() -> Optional[Path]:
    """Abaqus's own include directory, if this machine has one.

    Reading a header file off the disk is not running Abaqus: no process is
    started and no licence token is drawn.
    """
    for root in sorted(Path("/usr/SIMULIA").glob("*/*/linux_a64/code/include"),
                       reverse=True):
        if root.is_dir():
            return root
    return None


def _compile_once(source: Path, form: str, companions, include_dirs,
                  shims: dict, preprocess: bool, compiler: str) -> dict:
    """One ifort syntax pass over the author's file and its companions."""
    import subprocess
    import tempfile

    header_dir = _abaqus_header_dir()
    aba_param = ABA_PARAM_FALLBACK
    if header_dir and (header_dir / "aba_param.inc").is_file():
        aba_param = (header_dir / "aba_param.inc").read_text(errors="replace")
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        for name in ABA_PARAM_SPELLINGS:
            (scratch / name).write_text(aba_param, encoding="utf-8")
        for header in (header_dir.glob("*.hdr") if header_dir else ()):
            shutil.copyfile(header, scratch / header.name)
        for wanted, present in shims.items():
            try:
                shutil.copyfile(present, scratch / wanted)
            except OSError:
                pass
        suffix = ".f90" if form == "free" else ".f"
        units = []
        for index, companion in enumerate(companions):
            target = scratch / f"companion{index:02d}{suffix}"
            shutil.copyfile(companion, target)
            units.append(str(target))
        probe = scratch / f"probe{suffix}"
        shutil.copyfile(source, probe)
        units.append(str(probe))
        command = [compiler, "-syntax-only",
                   "-free" if form == "free" else "-fixed",
                   "-extend-source", "132", "-module", str(scratch),
                   "-I", str(scratch)]
        if header_dir:
            command += ["-I", str(header_dir)]
        if preprocess:
            command.append("-fpp")
        for directory in include_dirs:
            command += ["-I", str(directory)]
        command += units
        try:
            done = subprocess.run(command, capture_output=True, text=True,
                                  cwd=str(scratch), timeout=300)
        except Exception:                          # noqa: BLE001
            return {"ran": False, "ok": False, "own": []}
        output = ((done.stderr or "") + (done.stdout or "")).replace(
            str(scratch), "<probe>")
        # Diagnostics against the author's own file, and against the Abaqus
        # header AS THIS FILE INCLUDES IT -- a second IMPLICIT inside
        # aba_param.inc is caused by the source putting IMPLICIT NONE above
        # the INCLUDE, so it belongs to the source. Diagnostics against a
        # companion unit are that companion's and are left out.
        own = [{"line": int(line), "code": code, "message": message.strip(),
                "in": "the published source" if unit == "probe"
                      else "Abaqus's own aba_param.inc, as this source "
                           "includes it"}
               for unit, line, code, message in re.findall(
                   r"<probe>/(probe|ABA_PARAM\.INC|aba_param\.inc)"
                   r"[^(]*\((\d+)\): error #(\d+): ([^\n]*)", output)]
        return {"ran": True, "ok": done.returncode == 0, "own": own,
                "output": output[:4000]}


def offline_syntax_audit(cache: Path, source_ids, *, compiler: str = "") -> dict:
    """Whether each source builds as its author published it, decided offline.

    No Abaqus process is started. The file is handed to ifort with
    ``-syntax-only``, with the companions the repository does publish compiled
    ahead of it, with Abaqus's own ``aba_param.inc`` on the include path, and
    with both source forms tried -- because reading a free-form file as fixed
    produces a page of illegal-character diagnostics that say nothing about
    the file.

    Three outcomes, and the difference between them is the whole point:

    ``text_rejected`` true
        the parser could not read the author's text, under either form, with
        a diagnostic that no absent module could have caused.
    ``text_rejected`` false
        it compiled.
    ``text_rejected`` None
        it did not compile, but every diagnostic is one an unresolved USE
        would also produce. The audit has not settled anything, and says so.
    """
    from umat_oti.abaqus.companions import repository_files, resolve
    from umat_oti.fortran.normalize import detect_source_form

    compiler = compiler or _fortran_compiler()
    audited: dict[str, dict] = {}
    for source_id in source_ids:
        source = Path(cache) / source_id
        if not source.is_file():
            continue
        repo = Path(cache) / source_id.split("/", 1)[0]
        text = source.read_text(errors="replace")
        found = resolve(source, repository_files(source, cache))
        missing = [f"module {name}" for name in found.missing_modules
                   if name.lower() not in INTRINSIC_MODULES]
        missing += [f"include {name}" for name in found.missing_includes]
        directories = [source.parent, repo]
        directories += [d for d in sorted(repo.rglob("*")) if d.is_dir()][:60]
        shims: dict[str, Path] = {}
        for wanted in sorted(set(_INCLUDE.findall(text))):
            base = Path(wanted).name
            if base.lower().startswith("aba_param") or base.lower().endswith(".hdr"):
                continue
            if any((d / wanted).is_file() or (d / base).is_file()
                   for d in directories):
                continue
            elsewhere = [f for d in directories for f in d.iterdir()
                         if f.is_file() and f.name.lower() == base.lower()]
            if elsewhere:
                # Published, but spelled in another case. A case-only mismatch
                # is a property of the filesystem it is unpacked on, not a
                # file the author failed to publish.
                shims[base] = elsewhere[0]
            else:
                missing.append(f"include {wanted}")
        record = {"missing_externals": sorted(set(missing)),
                  "companions": [str(Path(c).relative_to(cache))
                                 for c in found.order],
                  "compiler": Path(compiler).name if compiler else ""}
        if not compiler:
            record.update(compiles=None, text_rejected=None, evidence="",
                          basis="no compiler that reports diagnostic numbers "
                                "was available, so nothing was asked")
            audited[source_id] = record
            continue
        preprocess = bool(re.search(r"^\s*#\s*(include|if|define)", text,
                                    re.MULTILINE))
        primary = detect_source_form(source, text)
        other = "free" if primary == "fixed" else "fixed"
        first = _compile_once(source, primary, found.order, directories, shims,
                              preprocess, compiler)
        second = ({"ran": False, "ok": False, "own": []} if first["ok"]
                  else _compile_once(source, other, found.order, directories,
                                     shims, preprocess, compiler))
        compiles = bool(first["ok"] or second["ok"])
        syntax = [] if compiles else [d for d in first["own"]
                                      if d["code"] in SYNTAX_DIAGNOSTICS]
        if compiles:
            rejected, evidence, basis = False, "", (
                f"ifort -syntax-only accepted the published text as "
                f"{primary if first['ok'] else other} form")
        elif syntax:
            first_defect = syntax[0]
            rejected = True
            evidence = (f"{first_defect['in']}, line {first_defect['line']}: "
                        f"{first_defect['message'][:200]}")
            basis = (f"ifort rejected the published text with "
                     f"{len(syntax)} parse diagnostic(s) under {primary} form")
        else:
            rejected, evidence = None, ""
            basis = ("the offline compile failed, but every diagnostic is one "
                     "an unresolved USE or INCLUDE would also produce, so it "
                     "settles nothing about the file")
        record.update(compiles=compiles, text_rejected=rejected,
                      evidence=evidence, basis=basis, source_form=primary)
        audited[source_id] = record
    return audited


def build(transform_report: Optional[Path], abaqus_report: Optional[Path],
          cache: Optional[Path], *, compile_check: bool = False,
          inventory_ids=None, provenance: Optional[dict] = None,
          audit: Optional[dict] = None, store_fingerprint: str = "") -> list:
    """Every acquired artefact, its terminal state, and the evidence for it.

    ``inventory_ids`` is the denominator and is seeded first, so a source the
    transform batch never produced a row for still gets a record -- as
    ``not_attempted``, which is an absence of a verdict and has to stay
    visible. A source that appears in a batch but not in the inventory is also
    kept, because dropping it would hide a disagreement between two artefacts
    that are supposed to describe the same corpus.
    """
    records: dict[str, Record] = {}

    def _seed(source_id: str) -> Record:
        record = records.get(source_id)
        if record is None:
            record = Record(
                source_id=source_id,
                repository=source_id.split("/")[0].replace("__", "/", 1),
                cache_path=source_id)
            if provenance:
                entry = provenance.get(source_id.split("/", 1)[0]) or {}
                record.commit = str(entry.get("commit") or "")
                record.license_spdx = str(entry.get("license_spdx") or "")
                url, why = _acquisition_url(source_id, provenance)
                record.acquisition_url, record.url_provenance = url, why
            records[source_id] = record
        return record

    for source_id in (inventory_ids or ()):
        if str(source_id).strip():
            _seed(str(source_id).strip())

    payload = json.loads(transform_report.read_text(encoding="utf-8")) \
        if transform_report and Path(transform_report).is_file() else {}
    for row in payload.get("rows", []):
        source_id = str(row.get("source") or row.get("source_id") or "")
        if not source_id:
            continue
        record = _seed(source_id)
        record.ntens = row.get("ntens")
        record.ntens_provenance = str(row.get("ntens_provenance") or "")
        record.kinematics = str(row.get("kinematics") or "")
        record.key = str(row.get("key") or "")
        outcome = str(row.get("outcome") or "")
        record.attempted = True
        record.transformed = outcome in ("transformed", "cached")
        record.compiled = row.get("compiled")
        if not record.transformed:
            record.reason = str(row.get("reason") or "")[:500]
    for row in payload.get("failures", []):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        record = _seed(source_id)
        record.attempted = True
        record.transformed = False
        record.reason = str(row.get("reason") or "")[:500]

    # What the file itself is, asked of the file rather than of the transform.
    duplicates = duplicate_map(cache, sorted(records)) if cache else {}
    if cache and Path(cache).is_dir():
        from umat_oti.abaqus.companions import repository_files, resolve
        from umat_oti.corpus.entry_routines import (classify, classify_refusal,
                                                    umat_outputs_written)
        from umat_oti.store.transform_store import file_digest

        for record in records.values():
            source = Path(cache) / record.source_id
            if not source.is_file():
                record.classification_basis = (
                    "the acquisition inventory names this source but the "
                    "cache does not hold it")
                continue
            text = source.read_text(errors="replace")
            record.bytes = len(text.encode())
            record.sha256 = file_digest(source)
            record.duplicate_of = duplicates.get(record.source_id, "")

            found = classify(text, path=source)
            # Where the file was searched for a stress or tangent update, and
            # what was found. Done for every acquired source, not only the
            # refused ones: a file that presents the UMAT interface and
            # assigns neither output anywhere is a template whoever wrote it
            # published, and that is a fact worth carrying whether or not the
            # transformer ever reached it.
            outputs = umat_outputs_written(text, form=found.source_form,
                                           path=source)
            record.writes_stress = outputs.writes_stress
            record.writes_ddsdde = outputs.writes_ddsdde
            record.output_calls = outputs.calls
            record.output_first_write = outputs.first_write
            record.output_first_write_line = outputs.first_write_line or None
            record.output_search = outputs.where_it_searched
            record.source_form = found.source_form
            record.entry_interface = found.entry_interface
            record.entry_routine = found.entry_routine
            record.entry_line = found.entry_line or None
            record.entry_evidence = found.entry_text

            resolution = resolve(source, repository_files(source, cache))
            record.companion_files = "; ".join(
                str(Path(unit).relative_to(cache))
                for unit in resolution.order)[:500]
            evidence = (audit or {}).get(record.source_id) or {}
            missing = evidence.get("missing_externals")
            if missing is None:
                missing = ([f"module {n}" for n in resolution.missing_modules
                            if n.lower() not in INTRINSIC_MODULES]
                           + [f"include {n}" for n in resolution.missing_includes])
            record.missing_companions = "; ".join(missing)[:300]

            verdict = classify_refusal(
                found, duplicate_of=record.duplicate_of,
                missing_externals=tuple(missing),
                text_rejected=evidence.get("text_rejected"),
                compiler_evidence=str(evidence.get("evidence") or ""),
                outputs=outputs)
            # The refusal class answers "the transformer refused this -- what
            # was it?", so it is only recorded where there was a refusal. What
            # the file IS is recorded either way, because a transformed file
            # whose entry point is a UEL is just as wrong to count as a UMAT.
            if record.attempted and not record.transformed:
                record.refusal_class = verdict.refusal_class
                record.refusal_class_confident = verdict.confident
            record.is_umat = verdict.is_umat
            record.classification_basis = "; ".join(
                part for part in (verdict.basis,
                                  str(evidence.get("basis") or "")) if part)[:600]
            if verdict.evidence:
                record.entry_evidence = verdict.evidence

    # What Abaqus made of the ones that got that far. This overrides the
    # transform's verdict, because it is later and it is about a real run --
    # but only where it is about the SAME transformed file. A verification row
    # carries the fingerprint of the store it ran against; the store was
    # rebuilt, and a row from before that rebuild describes a transformed file
    # that no longer exists. pass9 is 250 rows, every one of them at
    # fingerprint ff94800b1884bcc0, against a store that is now
    # 668e7e64c1371b47. Joining those on source_id alone would have reported
    # 67 sources as verified on evidence about different generated Fortran.
    verification_file = _relative_to_repo(abaqus_report) if abaqus_report else ""
    for row in _fingerprint_latest(_rows(abaqus_report), store_fingerprint):
        source_id = str(row.get("source") or "")
        if not source_id:
            continue
        record = _seed(source_id)
        record.verification_source = verification_file
        record.verification_fingerprint = str(row.get("fingerprint") or "")
        record.verification_is_current = (
            None if not store_fingerprint or not record.verification_fingerprint
            else record.verification_fingerprint == store_fingerprint)
        if record.verification_is_current is False:
            # Not a verdict about the entry that is in the store now. The row
            # is kept -- its fingerprint and its stage are recorded -- but it
            # decides nothing, and the record stays at whatever the transform
            # established, which for a stored entry is "no batch has reached
            # it at this fingerprint yet".
            record.superseded_verification = (
                f"a verification row for this source reached "
                f"`{row.get('stage')}` against store fingerprint "
                f"{record.verification_fingerprint}, and the store is now "
                f"{store_fingerprint}; that row is evidence about generated "
                f"Fortran that has since been rebuilt, so it decides nothing "
                f"here")
            record.verification_fingerprint = ""
            continue
        record.verification_sha256 = str(row.get("source_sha256") or "")
        evidence = row.get("evidence")
        states = {gate: _gate_state(evidence, gate) for gate in EVIDENCE_GATES}
        for gate, state in states.items():
            setattr(record, f"gate_{gate}", state)
        record.verified_on_every_gate = all(
            state == GATE_TRUE for state in states.values())
        record.gates_not_true = "; ".join(
            f"{gate}={state}" for gate, state in states.items()
            if state != GATE_TRUE)[:400]
        (record.primal_difference_explained_by_a_measured_control,
         record.control_flag_provenance,
         record.primal_control) = _control_explanation(row)
        record.key = str(row.get("key") or record.key)
        record.stage = _stage_the_gates_support(row)
        verdict = translate_stage(record.stage,
                                  str(row.get("reason") or "")[:500])
        record.terminal_state, record.kind = verdict.state, verdict.kind
        record.reason = verdict.reason
        record.transformed = True
        record.element_type = str(row.get("element_type") or "")
        record.ntens = row.get("ntens", record.ntens)
        record.kinematics = str(row.get("kinematics") or record.kinematics)
        record.deck = str(row.get("deck") or "")
        record.material_provenance = str(row.get("material_provenance") or "")
        record.props_count = row.get("props_count")
        record.nstatv = row.get("nstatv")
        formulation = row.get("formulation") or {}
        record.formulation = str(formulation.get("family") or "")
        discovery = row.get("discovery") or {}
        record.activation_amplitude = discovery.get("chosen_amplitude")
        record.activated = (discovery.get("outcome") == "activated"
                            if discovery.get("ran") else None)
        record.time_dependent = (discovery.get("time") or {}).get("time_dependent")
        primal = row.get("primal") or {}
        record.worst_stress_relative = primal.get("worst_stress_relative")
        record.worst_state_relative = primal.get("worst_state_relative")
        record.primal_increments = primal.get("increments")
        record.precision_control = (row.get("precision_control") or {}).get("agrees")
        tangent = row.get("tangent") or {}
        record.tangent_states_checked = tangent.get("states_checked")
        record.tangent_states_agreeing = tangent.get("states_agreeing")
        record.response_character = str(tangent.get("response_character") or "")
        comparison = tangent.get("comparison") or {}
        record.worst_tangent_relative = comparison.get("best_relative")
        stable = comparison.get("stable_range") or []
        record.tangent_plateau = (f"{min(stable):g}..{max(stable):g}"
                                  if len(stable) == 2 else "")
        classification = row.get("entry_classification") or {}
        if classification:
            record.is_umat = classification.get("kind") == "umat"
            record.entry_interface = str(
                classification.get("entry_interface") or record.entry_interface)
        diagnosis = row.get("original_diagnosis") or {}
        if diagnosis:
            record.compile_defect = "; ".join(
                (diagnosis.get("compile") or {}).get("defects") or [])[:300]
        record.seconds = row.get("seconds")

    # Everything Abaqus never saw. Its terminal state comes from what the file
    # is: a transform refusal is ours unless the file is one nobody could have
    # transformed, and the compile check is what tells those apart.
    for record in records.values():
        if record.stage:
            continue
        if record.is_umat is False:
            record.terminal_state, record.kind = "not_a_umat", "external"
            continue
        if record.transformed or not record.attempted:
            # It converted and the batch has not reached it, or no batch
            # produced a row for it at all. Not a verdict -- an absence of one,
            # and an absence that has to stay visible.
            record.terminal_state, record.kind = "not_attempted", "internal"
            continue
        # A transform refusal is NEVER what decides this. What the file is
        # decides it, and what the file is was read out of the file, so the
        # three inputs below all come from the refusal classification and the
        # refusal text is carried along only as the reason.
        #
        # `compiles` is False ONLY where the classification says the text is
        # rejected. An offline compile that merely failed is not the same
        # claim: six genuine UMATs failed it because a module they USE could
        # not be built here, and passing that through as compiles=False filed
        # all six as `incomplete_or_corrupt_source` -- an external verdict on
        # somebody's repository, resting on a gap in this probe.
        compiles = (audit or {}).get(record.source_id, {}).get("compiles")
        if compiles is None and compile_check and cache \
                and (Path(cache) / record.source_id).is_file():
            compiles = _compiles(Path(cache) / record.source_id, record)
        if record.refusal_class == "incomplete_or_corrupt_source":
            compiles = False
        elif record.refusal_class:
            compiles = True if compiles else None
        # A file that presents the UMAT interface and publishes no
        # constitutive model is EXTERNAL, and it is the one refusal class
        # ``from_transform_failure`` has no parameter for. Left to it, both
        # published stubs came back ``transform_refused`` -- INTERNAL, glossed
        # "the transform could not convert it, our work" -- when there is no
        # model to convert: matmodlab2's umat_stub.f90 is 16 logical lines
        # that assign neither STRESS nor DDSDDE and make no CALL, and the
        # ufc-fem-kernel adapter is 9 whose body is a PRINT.
        #
        # Only where the classification is CONFIDENT. An unsettled read of the
        # file leaves the verdict where it was, which keeps the error in the
        # direction that overstates this project's own unfinished work.
        if record.refusal_class == "published_stub_no_constitutive_content" \
                and record.refusal_class_confident:
            verdict = translate_stage(record.refusal_class, record.reason)
        else:
            verdict = from_transform_failure(
                record.reason, compiles=compiles,
                companions_missing=(record.refusal_class ==
                                    "missing_external_dependency"),
                is_umat=(record.is_umat if record.refusal_class
                         else _is_a_umat(cache, record.source_id)))
        record.terminal_state, record.kind = verdict.state, verdict.kind

    for record in records.values():
        if record.verification_sha256 and record.sha256:
            record.verification_sha256_agrees = (
                record.verification_sha256 == record.sha256)
        (record.adequately_specified, record.adequacy_basis,
         record.adequacy_kind) = _adequacy(record)
        if record.terminal_state != FULLY_VERIFIED:
            record.not_verified_reason = _why_not_verified(record)
    return sorted(records.values(), key=lambda r: r.source_id)


#: The terminal states that say the source itself cannot be driven, because of
#: something nobody published. Each is already classified external in
#: umat_oti.abaqus.terminal_states; they are listed again here because this is
#: the rule that decides the SECOND DENOMINATOR, and a denominator whose
#: membership rule lives somewhere else is a denominator nobody can check.
NOT_ADEQUATELY_SPECIFIED_STATES = (
    "incomplete_or_corrupt_source",
    "external_dependency_unavailable",
    "missing_material_data",
    WAITS_FOR_INPUT,
)


def _adequacy(record: Record) -> tuple:
    """Is this an adequately specified genuine UMAT, and if not, whose fault?

    THE SECOND DENOMINATOR. The first is the 391 sources the acquisition
    brought back; this is the subset a verification rate may honestly be
    quoted against. Every exclusion below is a fact about somebody's published
    repository, and every one of them names the evidence that established it.

    NOTHING INTERNAL MAY SHRINK THIS SET. A source this project's transformer
    could not convert, whose deck this project could not generate, whose
    experiment this project could not make informative, stays inside it and
    counts against us -- that is the whole point of separating the two
    denominators rather than quoting one number. The assertion is
    ``tests/test_the_two_denominators_stay_apart.py``.
    """
    if not record.sha256:
        return (None, "the acquisition inventory names this source but the "
                      "cache does not hold it, so nothing about it was "
                      "established by parsing", "internal")
    if record.is_umat is False:
        return (False, ("this file's Abaqus entry point is not a UMAT: "
                        + (record.classification_basis
                           or record.entry_evidence))[:600], "external")
    if record.duplicate_of:
        return (False, (f"line-for-line identical to {record.duplicate_of}, "
                        f"which carries the same answer; counting both would "
                        f"count one source twice"), "duplicate")
    if (record.entry_interface == "UMAT" and record.output_calls == 0
            and record.writes_stress is False and record.writes_ddsdde is False):
        return (False, ("this file presents the Abaqus UMAT interface and "
                        "publishes no constitutive model inside it: "
                        + record.output_search
                        + " -- nothing was assigned and no CALL was made")[:600],
                "external")
    if record.terminal_state in NOT_ADEQUATELY_SPECIFIED_STATES:
        return (False, (f"{record.terminal_state}: "
                        + (record.reason or record.classification_basis
                           or record.missing_companions
                           or record.compile_defect))[:600], "external")
    basis = (f"presents the Abaqus UMAT interface at line {record.entry_line}"
             if record.entry_line else "presents the Abaqus UMAT interface")
    if record.output_first_write:
        basis += (f", and assigns an output at line "
                  f"{record.output_first_write_line}: "
                  f"{record.output_first_write}")
    return (True, (basis + "; nothing external excludes it")[:600], "")


def _why_not_verified(record: Record) -> str:
    """The NAMED reason this source is not verified, with its evidence.

    Never "the transformer refused it": that is an answer about the
    transformer. Where the transform is what stopped it, the reason names the
    transformer's own diagnostic AND the parse that established the file is a
    whole UMAT, so a reader can see that the work is this project's.
    """
    parts = [f"terminal state `{record.terminal_state}` "
             f"({record.kind}; "
             f"{'somebody else' if record.kind == 'external' else 'this project'}"
             f" has to move next)"]
    if record.terminal_state == "not_attempted":
        parts.append("no batch has produced a row for this source at the "
                     "current store fingerprint; this is an absence of a "
                     "verdict, not a verdict")
    if record.superseded_verification:
        parts.append(record.superseded_verification)
    if record.reason:
        parts.append(f"recorded reason: {record.reason}")
    for label, value in (("classification", record.classification_basis),
                         ("missing beside it", record.missing_companions),
                         ("compile defect", record.compile_defect),
                         ("output search", record.output_search)):
        if value:
            parts.append(f"{label}: {value}")
            break
    return "; ".join(parts)[:900]


def _is_a_umat(cache: Optional[Path], source_id: str) -> Optional[bool]:
    """What this file presents to Abaqus, by parsing rather than by name.

    Asked of sources the transform refused, because a file whose entry point
    is a UEL was never this transformer's to convert and its refusal says
    nothing about the transformer.
    """
    if not cache or not source_id:
        return None
    path = Path(cache) / source_id
    if not path.is_file():
        return None
    try:
        from umat_oti.corpus.entry_routines import classify
        found = classify(path.read_text(errors="replace"), path=path)
    except Exception:                              # noqa: BLE001 - advisory
        return None
    # A file that parses as nothing may be a helper, or may be a file whose
    # text is too damaged to parse. Saying "not a UMAT" about the second is an
    # external verdict resting on no evidence, so an unreadable file gets no
    # answer here and the compile check gives it one.
    from umat_oti.corpus.entry_routines import NO_PROGRAM_UNIT
    if found.kind == NO_PROGRAM_UNIT:
        return None
    return bool(found.is_umat)


def _compiles(source: Path, record: Record) -> Optional[bool]:
    """Does the author's own file build with Abaqus's compile line?"""
    try:
        from umat_oti.abaqus.companions import repository_files, resolve
        from umat_oti.abaqus.support import compile_one
        import tempfile

        found = resolve(source, repository_files(source, source.parents[-2]))
        with tempfile.TemporaryDirectory() as scratch:
            check = compile_one(source, Path(scratch), form=record.source_form,
                                extra_sources=found.order)
        if check.ok:
            return True
        if check.missing_dependencies:
            record.missing_companions = (record.missing_companions
                                         or "; ".join(check.missing_dependencies))
            return None
        record.compile_defect = "; ".join(check.defects)[:300]
        # False only when the compiler rejected the TEXT. Anything else is a
        # compile that did not settle the question, and None says so.
        return False if check.source_is_malformed else None
    except Exception:                              # noqa: BLE001
        return None


def _refused_sources(transform_report: Optional[Path]) -> list:
    """The sources the transform batch refused, from the batch's own report."""
    if not transform_report or not Path(transform_report).is_file():
        return []
    payload = json.loads(Path(transform_report).read_text(encoding="utf-8"))
    refused = [str(row.get("source") or "")
               for row in payload.get("failures") or []]
    refused += [str(row.get("source") or "") for row in payload.get("rows") or []
                if str(row.get("outcome") or "") not in ("transformed", "cached")]
    return sorted({name for name in refused if name})


def summarise(records: list) -> dict:
    umats = [r for r in records if r.is_umat is not False]
    verified = [r for r in records if r.terminal_state == FULLY_VERIFIED]
    by_state = Counter(r.terminal_state for r in records)
    by_kind = Counter(r.kind for r in records)
    clusters = defaultdict(list)
    for record in records:
        if record.kind == "internal":
            clusters[record.terminal_state].append(record.source_id)
    refused = [r for r in records if r.refusal_class]
    by_refusal = Counter(r.refusal_class for r in refused)

    # THE TWO DENOMINATORS, kept apart and both named. Quoting a rate without
    # saying which of them it is against is the failure this block exists to
    # prevent, so neither is ever computed as a bare percentage here: the
    # numerator and the denominator are both published and the reader divides.
    adequate = [r for r in records if r.adequately_specified]
    excluded = [r for r in records if r.adequately_specified is False]
    unknown = [r for r in records if r.adequately_specified is None]
    internal_exclusions = sorted(r.source_id for r in excluded
                                 if r.adequacy_kind not in ("external",
                                                            "duplicate"))
    return {
        "acquired": len(records),
        "genuine_umats": len(umats),
        "adequately_specified_genuine_umats": len(adequate),
        "denominators": {
            "acquired_sources": {
                "count": len(records),
                "means": "every artefact the acquisition brought back, one "
                         "record each, seeded from the discovery inventory",
                "verified": len([r for r in verified
                                 if True]),
            },
            "adequately_specified_genuine_umats": {
                "count": len(adequate),
                "means": "the subset that presents the Abaqus UMAT interface, "
                         "is a distinct member of the corpus, has a "
                         "constitutive model inside it, builds as published, "
                         "has everything it USEs published beside it, and has "
                         "material constants published for it",
                "verified": len([r for r in verified if r.adequately_specified]),
                "excluded": len(excluded),
                "excluded_for_an_internal_reason": internal_exclusions,
                "unknown": [r.source_id for r in unknown],
            },
        },
        "adequacy_exclusions_by_kind": dict(
            Counter(r.adequacy_kind or "external" for r in excluded)),
        "fully_verified": len(verified),
        "fully_verified_and_adequately_specified": len(
            [r for r in verified if r.adequately_specified]),
        "verified_on_every_gate": len(
            [r for r in verified if r.verified_on_every_gate]),
        "verified_on_every_gate_and_adequately_specified": len(
            [r for r in verified
             if r.verified_on_every_gate and r.adequately_specified]),
        "reached_the_verified_rung_but_failed_a_gate": sorted(
            f"{r.source_id} ({r.gates_not_true})" for r in verified
            if not r.verified_on_every_gate),
        # The same set again, split by whether a control that RAN accounts for
        # the gate that reads false. The two numbers are published side by
        # side and neither replaces the other: an entry whose primal
        # comparison failed and whose control explained it is not the same
        # thing as one that agreed outright, and it is not the same thing as
        # one nobody measured either.
        "verified_rung_with_a_gate_explained_by_a_measured_control": sorted(
            f"{r.source_id} ({r.gates_not_true}; {r.primal_control})"
            for r in verified
            if not r.verified_on_every_gate
            and r.primal_difference_explained_by_a_measured_control is True),
        "verified_rung_with_a_gate_no_control_explains": sorted(
            f"{r.source_id} ({r.gates_not_true}; {r.control_flag_provenance})"
            for r in verified
            if not r.verified_on_every_gate
            and r.primal_difference_explained_by_a_measured_control is not True),
        "evidence_gate_census": gate_census(records),
        # Every other count this registry publishes, put through the same
        # proof. Each states the population it was taken over and each raises
        # rather than being published if it does not sum to it -- so a
        # classification that quietly stopped covering some of its records
        # stops the build instead of appearing as a table that is four short.
        "censuses": {
            "terminal_state": census(
                records, lambda r: r.terminal_state, "acquired sources (D1)"),
            "whose_move_it_is": census(
                records, lambda r: r.kind, "acquired sources (D1)"),
            "adequately_specified": census(
                records, lambda r: str(r.adequately_specified),
                "acquired sources (D1)"),
            "why_excluded_from_d2": census(
                excluded, lambda r: r.adequacy_kind or "external",
                "sources excluded from D2"),
            "what_the_refused_files_are": census(
                refused, lambda r: r.refusal_class,
                "sources the transformer refused"),
            "entry_interface": census(
                records, lambda r: r.entry_interface or "none",
                "acquired sources (D1)"),
            "transformed": census(
                records, lambda r: str(r.transformed), "acquired sources (D1)"),
            "compiled": census(
                records, lambda r: str(r.compiled), "acquired sources (D1)"),
        },
        "verification_rows_at_a_stale_fingerprint": sorted(
            r.source_id for r in records if r.verification_is_current is False),
        "records_with_no_named_reason": sorted(
            r.source_id for r in records
            if r.terminal_state != FULLY_VERIFIED and not r.not_verified_reason),
        "transform_refused": len(refused),
        "refusals_by_class": dict(sorted(by_refusal.items(),
                                         key=lambda kv: -kv[1])),
        "refusals_not_confidently_classified": sorted(
            r.source_id for r in refused if r.refusal_class_confident is False),
        "refusals_with_no_entry_evidence": sorted(
            r.source_id for r in refused if not r.entry_evidence),
        "duplicate_sources": sorted(
            f"{r.source_id} == {r.duplicate_of}"
            for r in records if r.duplicate_of),
        "records_without_an_acquisition_url": sorted(
            r.source_id for r in records if not r.acquisition_url),
        "by_terminal_state": dict(sorted(by_state.items(), key=lambda kv: -kv[1])),
        "by_kind": dict(by_kind),
        "external_total": sum(by_state[s] for s in ALL_EXTERNAL),
        "internal_total": sum(by_state[s] for s in ALL_INTERNAL),
        "internal_clusters": {state: len(names)
                              for state, names in sorted(
                                  clusters.items(), key=lambda kv: -len(kv[1]))},
        "verified_sources": [r.source_id for r in verified],
    }


def _pct(numerator: int, denominator: int, name: str) -> str:
    """A percentage that names its denominator, or nothing at all.

    A rate quoted without saying what it is a rate OF is the single most
    misleading thing this report could print, so the denominator is written
    into the string itself and there is no way to ask for one without it.
    """
    if not denominator:
        return f"{numerator} of 0 {name}"
    return (f"{numerator} of {denominator} {name} -- "
            f"{100.0 * numerator / denominator:.1f}% of {name}")


def gate_census(records: list) -> dict:
    """Each of the six gates, over the entries a verification row reached.

    Four states per gate, and they are published separately because three of
    them mean "not established" for three different reasons. The census is
    taken over the entries that HAVE an evidence block, which is the only
    population the question can be asked of, and that denominator is stated
    beside every count.
    """
    with_block = [r for r in records
                  if r.gate_abaqus_job_completed
                  and r.gate_abaqus_job_completed != GATE_NO_BLOCK]
    out: dict = {
        "denominator": len(with_block),
        "denominator_is": ("entries whose verification row at the current "
                           "store fingerprint carries an evidence block"),
        "a_missing_key_and_a_null_key_are_both": "not established",
        "gates": {},
    }
    for gate in EVIDENCE_GATES:
        counted = census(with_block, lambda r, g=gate: getattr(r, f"gate_{g}"),
                         out["denominator_is"])
        counts = counted["counts"]
        out["gates"][gate] = {
            "true": counts.get(GATE_TRUE, 0),
            "false": counts.get(GATE_FALSE, 0),
            "not_established_present_but_null": counts.get(GATE_NULL, 0),
            "not_established_key_absent": counts.get(GATE_ABSENT, 0),
            "not_established_total": sum(counts.get(state, 0)
                                         for state in GATE_NOT_ESTABLISHED),
            "sums_to": counted["denominator"],
        }
    return out


def markdown(records: list, summary: dict) -> str:
    inputs = summary.get("inputs") or {}
    denominators = summary.get("denominators") or {}
    acquired = summary["acquired"]
    adequate = summary.get("adequately_specified_genuine_umats", 0)
    verified = summary["fully_verified"]
    verified_adequate = summary.get("fully_verified_and_adequately_specified",
                                    verified)
    gated = summary.get("verified_on_every_gate", verified)
    gated_adequate = summary.get(
        "verified_on_every_gate_and_adequately_specified", gated)

    basenames = Counter(r.source_id.rsplit("/", 1)[-1].lower()
                        for r in records)
    worst, worst_count = (basenames.most_common(1) or [("", 0)])[0]
    shared = sum(count for count in basenames.values() if count > 1)

    lines = [
        "# Corpus verification",
        "",
        "Every acquired source has a record here, and each one is named by "
        "its path inside the acquisition cache -- never by its basename. "
        f"{shared} of the {acquired} share a basename with at least one "
        f"other source, and {worst_count} of them are called `{worst}`. A "
        "registry keyed on the basename would hold one row where the corpus "
        "holds " + str(worst_count) + " files.",
        "",
        "## Where every number below comes from",
        "",
        "| input | file |",
        "| --- | --- |",
    ]
    for label, key in (("acquisition inventory (the denominator)",
                        "inventory_path"),
                       ("transform report", "transform_report"),
                       ("Abaqus verification results", "verification_results"),
                       ("offline compile evidence", "refusal_audit"),
                       ("acquisition cache", "discovery_cache")):
        value = inputs.get(key) or (summary.get("inventory") or {}).get("path", "")
        if value:
            lines.append(f"| {label} | `{value}` |")
    if inputs.get("store_fingerprint"):
        lines += ["", f"The transform store this registry describes is at "
                      f"fingerprint `{inputs['store_fingerprint']}`. A "
                      f"verification row carries the fingerprint of the store "
                      f"it ran against; a row from before the store was "
                      f"rebuilt is evidence about a transformed file that no "
                      f"longer exists, and none of those is read as a verdict "
                      f"about the entry that is in the store now."]

    inputs = summary.get("inputs") or {}
    lines += [
        "",
        "## How to regenerate every number in this report",
        "",
        "```",
        "UMAT_OTI_DISCOVERY_CACHE=<the acquisition cache> \\",
        "python tools/build_corpus_registry.py \\",
        # The files THIS report was built from, not an example of the shape
        # they take. A regeneration recipe naming a different run is a recipe
        # that reproduces different numbers, and it named pass10's for as long
        # as the table four lines above named pass11's.
        f"    --transform <run>/{Path(inputs.get('transform_report') or '').name or 'transform_batch.json'} \\",
        f"    --abaqus <run>/{'/'.join(str(inputs.get('verification_results') or '').split('/')[-3:]) or 'results/store_verification.jsonl'} \\",
        f"    --store-fingerprint {inputs.get('store_fingerprint') or ''} \\",
        "    --audit-refusals",
        "```",
        "",
        "`--audit-refusals` re-runs the offline `ifort -syntax-only` pass over "
        "every source the transformer refused and rewrites "
        "`paper_results/corpus/transform_refusal_audit.json`. It is needed "
        "whenever the set of refused sources changes and not otherwise; "
        "without it the recorded evidence is read back, so the registry "
        "rebuilds to the same answers on a machine with no Fortran compiler. "
        "**No Abaqus process is started by any of this and no licence token "
        "is drawn.** The store fingerprint is read from the transform report "
        "unless `--store-fingerprint` overrides it.",
        "",
        "## Two denominators, and which is which",
        "",
        "There are two populations in this report and they are never pooled. "
        "Every rate below says which one it is a rate of.",
        "",
        f"**D1 -- {acquired} acquired sources.** Everything the acquisition "
        "brought back, whatever it turned out to be. This is the honest "
        "denominator for \"what happened to the corpus we collected\".",
        "",
        f"**D2 -- {adequate} adequately specified genuine UMATs.** The subset "
        "of D1 that presents the Abaqus UMAT interface, is a distinct member "
        "of the corpus rather than a second copy of another one, has a "
        "constitutive model inside it, builds as its author published it, has "
        "everything it USEs or INCLUDEs published beside it, and has material "
        "constants published somewhere in its repository. This is the honest "
        "denominator for \"what happened to the UMATs that could be driven at "
        "all\".",
        "",
        "**Nothing internal may shrink D2.** Every exclusion from it is a "
        "fact about somebody else's published repository, and each one names "
        "the evidence that established it. "
        "Nothing this project failed to do removes a source from D2: a source "
        "whose transform this project refused, whose deck this project could "
        "not generate, whose experiment this project could not make "
        "informative, all stay in D2 and count against us. That is why there "
        "are two denominators rather than one number.",
        "",
        "| | reached the `verified` rung | verified on every gate | "
        "denominator |",
        "| --- | ---: | ---: | ---: |",
        f"| D1 acquired sources | {verified} | {gated} | {acquired} |",
        f"| D2 adequately specified genuine UMATs | {verified_adequate} | "
        f"{gated_adequate} | {adequate} |",
        "",
        "**Verified on every gate is the stricter number and it is the one to "
        "quote.** The two columns differ by the "
        f"{verified - gated} entr{'y' if verified - gated == 1 else 'ies'} "
        "that reached the batch's `verified` rung with one of the six "
        "evidence gates not reading true; they are named below.",
        "",
        f"* {_pct(gated, acquired, 'acquired sources (D1)')}",
        f"* {_pct(gated_adequate, adequate, 'adequately specified genuine UMATs (D2)')}",
        "",
        "Against the looser rung instead:",
        "",
        f"* {_pct(verified, acquired, 'acquired sources (D1)')}",
        f"* {_pct(verified_adequate, adequate, 'adequately specified genuine UMATs (D2)')}",
        "",
        "No figure above may be quoted without the words after it. They are "
        "answers to different questions and the larger one is not the better "
        "one.",
        "",
        "`fully_verified` means the source transformed and compiled, Abaqus "
        "ran the ORIGINAL, Abaqus ran the CONVERTED build on the same deck, "
        "their stress and state histories agreed over the whole path, and the "
        "OTI tangent agreed with a finite difference of the original at "
        "several states along it. Compiling is not working, running is not "
        "verified, and unknown is never verified.",
        "",
        "## Finished, and unfinished",
        "",
        "Over D1, the "
        f"{acquired} acquired sources. The three lines are never added "
        "together into a completion figure: pooling what somebody else "
        "published with what this project has not finished would be a claim "
        "about the corpus made out of facts about the pipeline.",
        "",
        "| | entries in D1 |",
        "| --- | ---: |",
        f"| reached the `verified` rung | "
        f"{summary['by_kind'].get('verified', 0)} |",
        f"| blocked outside this repository | {summary['external_total']} |",
        f"| work remaining here | {summary['internal_total']} |",
        "",
        f"Of the {summary['by_kind'].get('verified', 0)} on the first line, "
        f"{gated} read true on all six evidence gates. The rung and the gates "
        f"are different questions and this table asks the rung's, because it "
        f"is the one whose three lines partition D1.",
    ]

    excluded_internal = (denominators.get(
        "adequately_specified_genuine_umats") or {}).get(
            "excluded_for_an_internal_reason") or []
    unknown = (denominators.get("adequately_specified_genuine_umats")
               or {}).get("unknown") or []
    if excluded_internal:
        lines += ["", f"**{len(excluded_internal)} source(s) were excluded "
                      f"from D2 for a reason that is NOT external.** That is "
                      f"a defect in this report, not a result: " +
                  ", ".join(f"`{name}`" for name in excluded_internal[:10])]
    if unknown:
        lines += ["", f"{len(unknown)} source(s) could not be placed in or "
                      f"out of D2 because the acquisition cache does not hold "
                      f"the file. They are counted in D1, excluded from D2's "
                      f"numerator and denominator both, and named here: " +
                  ", ".join(f"`{name}`" for name in unknown[:10])]

    lines += [
        "",
        "## What excluded a source from D2",
        "",
        "| reason | external or internal | sources |",
        "| --- | --- | ---: |",
    ]
    reasons: dict = defaultdict(list)
    for record in records:
        if record.adequately_specified is False:
            head = record.adequacy_basis.split(":")[0].strip()
            if head.startswith("line-for-line identical to"):
                # One row, not one per source it is a copy of: the reader is
                # being told how many sources are second copies, and naming
                # each original here would turn a census into a list.
                head = "line-for-line identical to another acquired source"
            reasons[(head[:70], record.adequacy_kind or "external")].append(
                record.source_id)
    for (head, kind), names in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        mark = {"external": "**EXTERNAL**",
                "duplicate": "neither -- a second copy",
                }.get(kind, "**INTERNAL**")
        lines.append(f"| {head} | {mark} | {len(names)} |")
    lines += ["",
              "A second copy is not an external blocker and is not counted as "
              "one: nothing about it is blocked, its one answer is already "
              "counted against the copy that carries it, and filing it under "
              "\"somebody else's problem\" would inflate how much of the "
              "corpus is."]

    # A source can be excluded from D2 for an external reason and still sit at
    # an INTERNAL terminal state, because the two vocabularies are not the
    # same size. Saying so is the point: a reader who found the contradiction
    # themselves would be right to distrust everything around it.
    mismatched = [r for r in records
                  if r.adequately_specified is False
                  and r.adequacy_kind == "external"
                  and r.kind == "internal"]
    mismatched.sort(key=lambda r: r.source_id)
    if mismatched:
        lines += [
            "",
            "### Where a terminal state and its cause disagree",
            "",
            f"{len(mismatched)} source(s) are excluded from D2 for a reason "
            "that is EXTERNAL while their terminal state is INTERNAL. That is "
            "not a contradiction being hidden, it is a vocabulary that is one "
            "word short: `umat_oti.abaqus.terminal_states` has no state for "
            "\"the author published a template\", and the nearest existing "
            "one, `incomplete_or_corrupt_source`, is glossed \"the file does "
            "not compile as published\" -- which is false of a template, since "
            "a template compiles. Rather than borrow a state that would make "
            "the interface say something untrue, these are left at the state "
            "the transform gave them, which is INTERNAL. That overstates this "
            "project's own unfinished work and understates nobody else's, "
            "which is the only direction the error may go. Adding a state for "
            "it is a change to a module this registry does not own.",
            "",
        ]
        for record in mismatched:
            lines.append(f"* `{record.source_id}` -- terminal state "
                         f"`{record.terminal_state}` (INTERNAL); excluded from "
                         f"D2 because {record.adequacy_basis[:200]}")

    lines += [
        "",
        "## Every terminal state, and whose move it is",
        "",
        "EXTERNAL means the answer lies in what somebody published and no "
        "further engineering here changes it. INTERNAL means the answer lies "
        "in this repository and the work is ours. Where it was not clear "
        "which of the two a state is, it is INTERNAL -- overstating this "
        "project's own unfinished work rather than the corpus's "
        "incompleteness is the only direction the error may go.",
        "",
        "| terminal state | external or internal | what it means | of D1 | of D2 |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    in_d2 = Counter(r.terminal_state for r in records if r.adequately_specified)
    for state, count in summary["by_terminal_state"].items():
        kind = kind_of(state)
        mark = ("VERIFIED" if kind == "verified"
                else "**EXTERNAL**" if kind == "external" else "**INTERNAL**")
        lines.append(f"| `{state}` | {mark} | {STATE_MEANS.get(state, '')} | "
                     f"{count} | {in_d2.get(state, 0)} |")
    lines += ["", f"D1 column sums to {acquired}; D2 column sums to "
                  f"{sum(in_d2.values())}."]

    lines += ["", "## What is left here, by cluster", "",
              "Each of these is a limitation of this pipeline, not of the "
              "corpus. Largest first, because that is the order they are "
              "worth fixing in.", "",
              "| cluster | sources in D1 | of which in D2 |",
              "| --- | ---: | ---: |"]
    for state, count in summary["internal_clusters"].items():
        lines.append(f"| `{state}` | {count} | {in_d2.get(state, 0)} |")

    if summary.get("transform_refused"):
        lines += ["", "## What the transformer refused, and what those files are",
                  "",
                  f"{summary['transform_refused']} sources were refused by the "
                  "transformer. A REFUSAL IS A FACT ABOUT THE TRANSFORMER and "
                  "never about the file. Each of these was then classified by "
                  "parsing the file itself -- its Abaqus entry point read out "
                  "of the source text, its lines matched against every other "
                  "acquired source, an offline `ifort -syntax-only` pass over "
                  "the author's own text, the companion resolution, and a "
                  "search of the whole file for an assignment to STRESS or "
                  "DDSDDE. The classification below rests on that evidence and "
                  "never on the refusal.", "",
                  "| what the file is | external or internal | sources |",
                  "| --- | --- | ---: |"]
        for name, count in summary.get("refusals_by_class", {}).items():
            mark = {"genuine_umat": "**INTERNAL**",
                    "duplicate_of_another_source":
                        "neither -- a second copy",
                    }.get(name, "**EXTERNAL**")
            lines.append(f"| `{name}` | {mark} | {count} |")
        lines += ["",
                  "`published_stub_no_constitutive_content` is EXTERNAL as a "
                  "cause AND as a terminal state. A file that presents the "
                  "UMAT interface and assigns neither STRESS nor DDSDDE "
                  "anywhere is not a model this project failed to convert -- "
                  "there is nothing there to convert. It used to come back "
                  "`transform_refused`, which is INTERNAL and glossed \"the "
                  "transform could not convert it, our work\", because "
                  "`from_transform_failure` has no parameter for this class; "
                  "the registry now routes it, and only where the "
                  "classification is confident."]
        unsure = summary.get("refusals_not_confidently_classified") or []
        lines += ["",
                  f"{len(unsure)} of them are held at `genuine_umat` because "
                  "the offline compile did not settle whether the published "
                  "text builds. That is the safe direction: it counts the work "
                  "as ours."]

    recon = summary.get("verification_file_reconciliation") or {}
    if recon:
        lines += [
            "", "## Why the results file holds more rows than the store holds "
                "entries",
            "",
            "The results file is append-only and this pass resumed onto the "
            "file an earlier pass had been writing, so it carries rows from "
            "before the transform store was rebuilt. A row count over that "
            "file is not a census of the store, and the two places this shows "
            "up are reconciled here rather than asserted.",
            "",
            "| | count |",
            "| --- | ---: |",
            f"| rows in `{recon.get('file', '')}` | "
            f"{recon.get('rows_in_the_file', 0)} |",
            f"| of those, at the current store fingerprint "
            f"`{recon.get('store_fingerprint', '')}` | "
            f"{recon.get('rows_at_the_current_store_fingerprint', 0)} |",
            f"| of those, at a superseded store fingerprint | "
            f"{recon.get('rows_at_a_superseded_store_fingerprint', 0)} |",
            f"| distinct sources named in the file | "
            f"{recon.get('distinct_sources_in_the_file', 0)} |",
            f"| distinct row keys in the file | "
            f"{recon.get('distinct_keys_in_the_file', 0)} |",
            f"| **sources this registry counts** | "
            f"**{recon.get('sources_counted_by_this_registry', 0)}** |",
            "",
            "The row key cannot collapse the duplicates: it is derived from "
            "the STORE ENTRY, so the same source under two fingerprints has "
            "two keys and every row key in the file is distinct. The source "
            "digest cannot collapse them either, in the other direction: the "
            f"{recon.get('rows_at_the_current_store_fingerprint', 0)} current "
            f"rows carry only "
            f"{recon.get('distinct_source_digests_at_the_current_fingerprint', 0)} "
            "distinct source digests, because several acquired files are "
            "byte-identical to another acquired file and both transformed. "
            "**The identity is the path inside the acquisition cache**, and "
            "the digest is what corroborates that a row is about the file "
            "this registry read.",
            "",
            f"{len(recon.get('superseded_rows_whose_source_was_rerun') or [])} "
            "of the superseded rows are for sources that were re-run at the "
            "current fingerprint, so the current row is used and the old one "
            "is set aside. The remaining "
            f"{len(recon.get('superseded_rows_whose_source_is_no_longer_in_the_store') or [])} "
            "are for sources that are no longer in the store at all, because "
            "the re-transform refused them; whatever rung they reached under "
            "the old store, it is evidence about generated Fortran that no "
            "longer exists:",
            "",
        ]
        for name in (recon.get(
                "superseded_rows_whose_source_is_no_longer_in_the_store") or []):
            lines.append(f"* `{name}`")

        double = recon.get("verified_rows_that_double_count_a_source") or []
        verified = recon.get("store_entries_that_verified", 0)
        file_word = recon.get("rows_whose_file_stage_says_verified", 0)
        demoted = recon.get(
            "rows_demoted_because_their_own_evidence_contradicts_the_word") or []
        lines += [
            "",
            "### One verified number",
            "",
            f"**{verified}** store entries are verified: every one of the six "
            f"evidence gates reads true. That is the only number this registry "
            f"calls verified, and every one of the 391 sources sits in exactly "
            f"one of verified, external or internal.",
            "",
            f"The results file carries the word `verified` on {file_word} rows. "
            f"{len(demoted)} of those rows hold a gate reading FALSE in their "
            f"own evidence block, so the word is not what their evidence says. "
            f"A control measured why the two builds differ and the harness read "
            f"that explanation as agreement. An explanation for a disagreement "
            f"is not agreement: they are at the internal rung "
            f"`primal_mismatch_explained`, counted there and nowhere else.",
            "",
        ]
        for name in demoted:
            lines.append(f"* `{name}`")
        lines.append("")

        gates = (summary.get("evidence_gate_census") or {})
        if gates.get("gates"):
            lines += [
                "",
                "### The six evidence gates, and what 'not established' covers",
                "",
                "A gate can read true, read false, be present and hold "
                "nothing, or not be there at all. **The last two both mean "
                "not established**, and they are counted separately because "
                "they have different causes: a key holding null is a question "
                "the run asked and could not answer, and a key that is not "
                "there is a question that batch's schema never asked. A "
                "census that counts one and drops the other comes out short "
                "of its own denominator and still reads perfectly well.",
                "",
                f"Denominator: {gates['denominator']} "
                f"{gates['denominator_is']}. Every row below sums to it.",
                "",
                "| gate | true | false | null | key absent | not established |"
                " sums to |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
            for gate, counts in gates["gates"].items():
                lines.append(
                    f"| `{gate}` | {counts['true']} | {counts['false']} | "
                    f"{counts['not_established_present_but_null']} | "
                    f"{counts['not_established_key_absent']} | "
                    f"{counts['not_established_total']} | {counts['sums_to']} |")

            whole = (recon.get(
                "evidence_gate_census_over_the_whole_file") or {})
            if whole.get("gates"):
                mech = whole["gates"].get("mechanically_informative") or {}
                here = gates["gates"].get("mechanically_informative") or {}
                lines += [
                    "",
                    "The same census over a different denominator gives a "
                    "different answer, and that is the whole reason the "
                    "denominator has to be stated. Over "
                    f"{whole['denominator']} {whole['denominator_is']}, "
                    f"`mechanically_informative` reads true on "
                    f"{mech.get('true', 0)}, false on {mech.get('false', 0)}, "
                    f"null on {mech.get('null', 0)} and is absent on "
                    f"{mech.get('absent', 0)} -- so "
                    f"{mech.get('null', 0) + mech.get('absent', 0)} are not "
                    f"established. Over the "
                    f"{gates['denominator']} entries in the store now it is "
                    f"absent on {here.get('not_established_key_absent', 0)} "
                    f"and null on "
                    f"{here.get('not_established_present_but_null', 0)}, so "
                    f"{here.get('not_established_total', 0)} are not "
                    f"established. **Both are right and neither means "
                    f"anything without the denominator beside it.**"
                    + (" The absent key belongs to the superseded rows: it "
                       "is a question the earlier batch's schema did not "
                       "ask, not a question this run failed to answer."
                       if mech.get("absent", 0) else
                       " No row in this file is missing the key: every row "
                       "was written by one batch against one store, so the "
                       "two censuses coincide. A key that is ABSENT and a "
                       "key that is PRESENT AND NULL are still counted "
                       "apart, because they are different answers -- a "
                       "question that was never asked and a question that "
                       "was asked and not answered -- and a census that "
                       "pooled them would stop adding up the moment a "
                       "resumed pass put both kinds of row in one file "
                       "again."),
                ]

    stale = summary.get("verification_rows_at_a_stale_fingerprint") or []
    if stale:
        lines += ["", "### Sources left with no verdict at this fingerprint",
                  "",
                  f"{len(stale)} source(s) have a verification row only at a "
                  f"superseded fingerprint -- the same ones listed above. None "
                  f"is counted as verified. Each is recorded at whatever the "
                  f"transform established for it at this fingerprint, which "
                  f"is an absence of a verdict and not the same as a verdict, "
                  f"and each one's record carries the superseded row's rung so "
                  f"the two files can be reconciled by a reader."]

    lines += ["", "## Every source that is not verified, and why",
              "",
              "One row per source, with the NAMED reason and the evidence "
              "behind it. \"The transformer refused it\" is never a reason "
              "here: it is an answer about the transformer.",
              "",
              "| source | terminal state | external/internal | in D2 | reason |",
              "| --- | --- | --- | :-: | --- |"]
    for record in records:
        if record.terminal_state == FULLY_VERIFIED:
            continue
        kind = ("EXTERNAL" if record.kind == "external" else "INTERNAL")
        member = "yes" if record.adequately_specified else "no"
        reason = record.not_verified_reason.replace("|", "/")[:400]
        lines.append(f"| `{record.source_id}` | `{record.terminal_state}` | "
                     f"{kind} | {member} | {reason} |")

    lines += ["", "## Every source that reached the `verified` rung", "",
              "`all six gates` says whether every evidence gate read true. "
              "Where it does not, the gate that did not is named: the entry "
              "is one the batch accepted with a written explanation, and an "
              "explanation is not the same thing as the gate reading true.",
              "",
              "| source | all six gates | element | worst primal | "
              "worst tangent | states |",
              "| --- | --- | --- | ---: | ---: | --- |"]
    for record in records:
        if record.terminal_state != FULLY_VERIFIED:
            continue
        gate_note = ("yes" if record.verified_on_every_gate
                     else f"**no** -- {record.gates_not_true}")
        primal = ("" if record.worst_stress_relative is None
                  else f"{record.worst_stress_relative:.2e}")
        tangent = ("" if record.worst_tangent_relative is None
                   else f"{record.worst_tangent_relative:.2e}")
        states = ("" if record.tangent_states_checked is None
                  else f"{record.tangent_states_agreeing}/"
                       f"{record.tangent_states_checked}")
        lines.append(f"| `{record.source_id}` | {gate_note} | "
                     f"{record.element_type} | {primal} | {tangent} | "
                     f"{states} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transform", type=Path, required=True)
    parser.add_argument("--abaqus", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--json", dest="json_path", type=Path,
                        default=REPO / "paper_results/corpus/corpus_registry.json")
    parser.add_argument("--csv", dest="csv_path", type=Path,
                        default=REPO / "paper_results/corpus/corpus_registry.csv")
    parser.add_argument("--markdown", type=Path,
                        default=REPO / "paper_results/corpus/CORPUS_VERIFICATION.md")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY,
                        help="the acquisition inventory, one row per "
                             "discovered source. This is the denominator: the "
                             "registry is seeded from it and the batches are "
                             "joined onto it, so a source no batch produced a "
                             "row for still gets a record")
    parser.add_argument("--acquisition", type=Path, action="append",
                        dest="acquisition", default=None,
                        help="acquisition manifests carrying the commit each "
                             "repository was read at (default: the two "
                             "companion manifests)")
    parser.add_argument("--refusal-audit", type=Path, default=DEFAULT_AUDIT,
                        help="offline evidence about what each refused source "
                             "is; read if present, rewritten by --audit-refusals")
    parser.add_argument("--audit-refusals", action="store_true",
                        help="compile every refused source offline with "
                             "ifort -syntax-only and write the evidence to "
                             "--refusal-audit. No Abaqus process is started "
                             "and no licence token is drawn")
    parser.add_argument("--store-fingerprint", default="",
                        help="the transform-store fingerprint the registry is "
                             "being built for. A verification row carries the "
                             "fingerprint of the store it ran against, and a "
                             "row from before the store was rebuilt is "
                             "evidence about a transformed file that no "
                             "longer exists. Defaults to the fingerprint the "
                             "--transform report records")
    parser.add_argument("--compile-check", action="store_true",
                        help="compile every unreached source with Abaqus's own "
                             "compile line, so a transform refusal on a file "
                             "that does not build is recorded as the file's "
                             "problem rather than as ours")
    args = parser.parse_args(argv)

    inventory_ids = inventory(args.inventory)
    provenance = acquisition_provenance(args.acquisition or DEFAULT_ACQUISITION)

    audit: dict = {}
    if args.refusal_audit and Path(args.refusal_audit).is_file():
        audit = json.loads(Path(args.refusal_audit).read_text(
            encoding="utf-8")).get("sources") or {}
    if args.audit_refusals:
        refused = _refused_sources(args.transform)
        print(f"  auditing {len(refused)} refused sources offline "
              f"(ifort -syntax-only; no Abaqus)", flush=True)
        audit = offline_syntax_audit(args.cache_dir, refused)
        Path(args.refusal_audit).parent.mkdir(parents=True, exist_ok=True)
        Path(args.refusal_audit).write_text(json.dumps({
            "schema": "umat-oti/transform-refusal-audit/1",
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "what_this_is": (
                "for each source the transformer refused: whether the author's "
                "own text is accepted by ifort -syntax-only, what it USEs or "
                "INCLUDEs that was never published beside it, and which "
                "companion units the repository does publish. No Abaqus "
                "process was started. A refusal is not evidence for any of "
                "these; this file is."),
            "sources": audit}, indent=1) + "\n", encoding="utf-8")
        print(f"  wrote {args.refusal_audit}")

    fingerprint = args.store_fingerprint
    if not fingerprint and args.transform and Path(args.transform).is_file():
        fingerprint = str(json.loads(Path(args.transform).read_text(
            encoding="utf-8")).get("fingerprint") or "")

    records = build(args.transform, args.abaqus, args.cache_dir,
                    compile_check=args.compile_check,
                    inventory_ids=inventory_ids, provenance=provenance,
                    audit=audit, store_fingerprint=fingerprint)
    summary = summarise(records)
    summary["verification_file_reconciliation"] = verification_reconciliation(
        args.abaqus, fingerprint)
    summary["inputs"] = {
        # Every number in the report has to be traceable to a file on disk
        # that the report names. These are those files, as the repository
        # sees them -- never as one machine happened to.
        "transform_report": _relative_to_repo(args.transform),
        "verification_results": (_relative_to_repo(args.abaqus)
                                 if args.abaqus else ""),
        "store_fingerprint": fingerprint,
        "refusal_audit": _relative_to_repo(args.refusal_audit),
        "discovery_cache": _relative_to_repo(args.cache_dir),
    }
    summary["inventory"] = {
        # Relative to the repository where possible: the audit fails the
        # build on an absolute home path, and a registry that records where
        # one machine happened to keep its checkout is not provenance.
        "path": _relative_to_repo(args.inventory),
        "discovered_sources": len(inventory_ids),
        "in_the_registry": len(records),
        "in_a_batch_but_not_the_inventory": sorted(
            {r.source_id for r in records} - set(inventory_ids)),
        "in_the_inventory_but_in_no_batch": sorted(
            set(inventory_ids) - {r.source_id for r in records}),
    }

    payload = {
        "schema": "umat-oti/corpus-registry/1",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "what_counts_as_verified": (
            "only fully_verified, and it is reached by a source that "
            "transformed, compiled, ran in Abaqus as the original, ran as the "
            "converted build on the same deck, agreed with itself over the "
            "whole stress and state history, and whose OTI tangent agreed with "
            "a finite difference of the original at several smooth states"),
        "terminal_states": {
            "verified": [FULLY_VERIFIED],
            "external": list(ALL_EXTERNAL),
            "internal": list(ALL_INTERNAL),
        },
        "summary": summary,
        "records": [r.as_dict() for r in records],
    }
    import io
    rows = io.StringIO()
    # LF, not the CRLF csv writes by default: the row text is checked for
    # machine paths and written through write_text like the other two
    # artefacts, and a file whose line endings change on every rebuild shows
    # up as a diff that is about nothing.
    writer = csv.DictWriter(rows, fieldnames=list(records[0].as_dict())
                            if records else ["source_id"],
                            lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record.as_dict())

    for path, text in ((args.json_path, json.dumps(payload, indent=1) + "\n"),
                       (args.markdown, markdown(records, summary)),
                       (args.csv_path, rows.getvalue())):
        refuse_machine_paths(text, _relative_to_repo(path))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8", newline="")

    print(f"  {summary['acquired']} artefacts, {summary['genuine_umats']} UMATs, "
          f"{summary['fully_verified']} fully verified")
    if summary.get("refusals_by_class"):
        print(f"  {summary['transform_refused']} refused by the transformer; "
              f"what those files are:")
        for name, count in summary["refusals_by_class"].items():
            print(f"    {name:<34} {count:>4}")
    for state, count in summary["by_terminal_state"].items():
        print(f"    {state:<34} {count:>4}  ({kind_of(state)})")
    print(f"  wrote {args.json_path}")
    print(f"  wrote {args.csv_path}")
    print(f"  wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
