"""What the interface needs to show about a corpus, as data rather than widgets.

The rule this module exists to keep is the one the workbench service keeps: the
interface a user drives and the pipeline a paper cites run the same code. So
nothing here renders anything and nothing here computes a verdict. It reads the
artefacts the batch wrote -- the results file, the transform report, the job
directories -- and returns them in one declared shape, so that a Streamlit tab,
a test and a report generator all see the same thing.

Everything a reader of the interface is entitled to ask is answerable from
here: which UMATs were acquired, what was inferred about each one and from
where, what is missing, which experiment was generated, what Abaqus did with
it, where the deck and the logs are, what the two builds computed, where the
material activated, whether the finite difference converged, and which
component of which tangent disagreed.

Two things it deliberately does NOT do. It does not decide anything the batch
did not already decide -- a verdict rendered differently in the interface than
in the evidence is a second opinion nobody can cite. And it does not read the
sources: the corpus is not redistributable, and the interface shows paths,
digests and provenance rather than text.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from umat_oti.abaqus.terminal_states import (EXTERNAL, INTERNAL,  # noqa: F401
                                             FULLY_VERIFIED, from_stage,
                                             kind_of)

#: The file the batch appends a record to as each entry settles. Read rather
#: than the summary JSON, because it exists while the run is still going and
#: is what makes live progress possible without asking the run anything.
RESULTS_FILE = "store_verification.jsonl"

#: The version of the shape this module returns. A front end pinned to it can
#: refuse to render something it does not understand instead of showing a
#: blank panel.
SCHEMA = "umat-oti/corpus-view/1"


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _latest(rows: list) -> list:
    """One record per entry: the last one written.

    The results file is append-only, and a resumed run that re-runs an entry
    appends a second record for it rather than editing the first. Counting
    both reports 254 outcomes for a 253-entry batch and, worse, counts a
    superseded verdict beside the one that replaced it.
    """
    seen: dict = {}
    for row in rows:
        key = str(row.get("key") or row.get("source") or id(row))
        seen[key] = row
    return list(seen.values())


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# where a piece of evidence lives in a record
# ---------------------------------------------------------------------------
#: Fields the batch writes at the top of a record when the verification ran,
#: and inside ``discovery`` when the search settled them and the verification
#: never got that far. Read from both, top level first, because a panel that
#: looks in one place shows a blank and a blank reads as "not measured" when
#: the measurement is there under another key.
#:
#: Measured on pass9: of 250 records, NONE carries ``failure_mechanism``,
#: ``segment_repair``, ``coverage_given_up``, ``safe_loading_reconstructed`` or
#: ``discovery_usable_prefix`` at the top, and 139 carry all five inside
#: ``discovery``. What was being hidden: 139 usable prefixes, 30 named failure
#: mechanisms, 23 repaired segments, 13 experiments that gave up coverage and 7
#: loadings rebuilt inside the part a run had proved safe.
EITHER_LEVEL = (
    "complete_finite_verification_run",
    "discovery_usable_prefix",
    "safe_loading_reconstructed",
    "failure_mechanism",
    "segment_repair",
    "coverage_given_up",
    "history_grouping",
    "time_scale_coverage",
    "activation_on_the_frozen_run",
    "mechanically_informative",
    "primal_signature",
    "searched_for_material_data",
    "safety_distance",
)


def field_anywhere(row: dict, name: str) -> Any:
    """One recorded field, from wherever in the record the batch put it.

    Top level wins, then ``discovery`` -- but only for the names in
    :data:`EITHER_LEVEL`. Falling back into ``discovery`` for anything at all
    would let an unrelated key of the same name inside the search's own
    bookkeeping stand in for a field the verification never recorded, and a
    borrowed value is worse than a missing one: it reads as measured.

    Nothing is derived and nothing is defaulted. A field absent from both
    comes back as ``None``, which is "never recorded" and is shown as that
    rather than as a false.
    """
    value = row.get(name)
    if value is not None:
        return value
    if name not in EITHER_LEVEL:
        return None
    inner = row.get("discovery")
    if isinstance(inner, dict):
        return inner.get(name)
    return None


#: The gates a verdict rests on, in the order the batch decides them, with what
#: each one measures and which part of the record carries it. Written out
#: because "verified" is a word and these six are the measurements under it:
#: Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement about
#: the solver, not about the constitutive routine it called.
EVIDENCE_GATES = (
    ("abaqus_job_completed",
     "the solver reached the end of the deck it was given",
     "original.sta / transformed.sta"),
    ("all_requested_outputs_present",
     "every increment produced every material point it was asked for -- an "
     "increment short of a point did not produce the state a comparison "
     "would compare",
     "history_grouping[side].first_incomplete_increment"),
    ("complete_history_finite",
     "no NaN and no infinity anywhere in either history, which a job Abaqus "
     "calls successful can still be full of",
     "history_grouping[side].first_non_finite_material_point"),
    ("primal_agreed",
     "the original and the converted build computed the same stress and the "
     "same state at every increment they both walked",
     "primal"),
    ("derivatives_verified",
     "the converted build's tangent matched a centred difference of the "
     "ORIGINAL, over a plateau of step sizes rather than at one step",
     "tangent.states[].comparison"),
    ("mechanically_informative",
     "the material did something over the run that was verified, and the run "
     "was long enough to reach the time scale the source declares -- "
     "agreement about a material sitting still is agreement about the part "
     "every build gets right",
     "mechanically_informative / time_scale_coverage"),
)

#: What :data:`EVIDENCE_GATES` names, per history, in the grouping the batch
#: writes. Shown as a table rather than a JSON blob because the two sides have
#: to be read against each other: a transformed history two increments shorter
#: than the original is the finding.
HISTORY_FIELDS = ("raw_output_records", "complete_increments",
                  "material_points_per_increment",
                  "first_incomplete_increment",
                  "first_non_finite_material_point")

#: What a gate with no recorded measurement is called. Distinct from "no" on
#: purpose: a step whose result was never established is not a step that
#: failed, and reporting it as one invents a failure the batch did not record.
NOT_MEASURED = "not measured"


def _said(value: Any) -> str:
    """One recorded value as a phrase, with absence said rather than blank."""
    if value is None:
        return "--"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def what_the_batch_recorded_after(row: dict, gate: str) -> str:
    """What else the record says about a gate that did not pass.

    A disagreement is not yet a verdict, and the batch says so in the record
    rather than in a log: it re-runs the ORIGINAL with the author's own
    declared precision widened, and where that does not settle it, with the
    same mathematics reassociated. Either can end with the entry at
    ``verified`` while ``evidence.primal_agreed`` stays the false the raw
    comparison measured -- those are two different claims and both are kept.

    On pass9 that is 17 entries reaching ``verified`` with
    ``evidence.primal_agreed`` false. A page that showed the gate alone would
    read as a contradiction; one that showed only the verdict would hide that
    the raw builds differ. Both are shown, and the sentence between them is
    the batch's own, quoted rather than composed here.
    """
    if gate != "primal_agreed":
        return ""
    primal = row.get("primal") or {}
    control = row.get("precision_control") or {}
    association = row.get("association_control") or {}
    if primal.get("explained_by_declared_precision"):
        return ("the raw comparison disagreed, and the batch recorded the "
                "difference as the author's own declared precision: "
                + str(control.get("reason") or row.get("reason") or ""))
    if association:
        return ("the raw comparison disagreed, and the batch put the model "
                "against itself compiled with the same mathematics "
                "reassociated: " + str(row.get("reason") or ""))
    if control:
        return ("the raw comparison disagreed and a precision control was "
                "run; it is recorded under precision_control")
    return ""


def evidence_rows(row: dict) -> list:
    """The six gates, each with what it measures and what was measured.

    Nothing here decides anything: the batch wrote ``evidence`` and this puts
    it beside the sentence that says what each entry of it means, so a reader
    can see which of the six a verdict rests on and which of them nobody
    measured.
    """
    measured = row.get("evidence") or {}
    rows = []
    for name, what, where in EVIDENCE_GATES:
        value = measured.get(name)
        rows.append({
            "gate": name.replace("_", " "),
            "field": name,
            # The same three words every other finding on the page uses. Two
            # vocabularies for one concept is how a reader ends up wondering
            # whether "not measured" here and "not established" there are
            # different things. They are not.
            "holds": three_state(value),
            "established": value is not None,
            "measured": NOT_MEASURED if value is None else _said(value),
            "passed": None if value is None else bool(value),
            "what it measures": what,
            "read from": where,
            "and then": (what_the_batch_recorded_after(row, name)
                         if value is False else ""),
        })
    return rows


# ---------------------------------------------------------------------------
# three states, and why there have to be three
# ---------------------------------------------------------------------------
#: What a recorded finding is called when the record holds ``null`` for it.
#: A step whose result was never established is not a step that passed and it
#: is not a step that failed: it is a hole in the evidence. Rendering a null
#: as either invents a measurement nobody made, and a null shown as a pass is
#: the worst thing this interface can do -- so the three are three strings
#: that cannot be mistaken for one another on a page.
NOT_ESTABLISHED = "not established"
HELD = "yes"
DID_NOT_HOLD = "no"


def three_state(value: Any) -> str:
    """One recorded finding as exactly one of three words.

    ``None`` is :data:`NOT_ESTABLISHED` and nothing else. There is deliberately
    no default and no truthiness shortcut that would let an absent measurement
    fall through to "no": "nobody measured it" and "it was measured and it
    failed" are different findings and a reader is entitled to both.
    """
    if value is None:
        return NOT_ESTABLISHED
    return HELD if bool(value) else DID_NOT_HOLD


def finding(name: str, value: Any, reason: str = "", *,
            magnitude: Any = None, about: str = "") -> dict:
    """One finding as a row: what it is, whether it holds, and why.

    ``established`` is carried beside ``holds`` so a table can be read without
    parsing a word, and so a caller cannot collapse the three states back into
    two by treating the string as a boolean.
    """
    return {
        "finding": name,
        "holds": three_state(value),
        "established": value is not None,
        "recorded": value,
        "what it is about": about,
        "magnitude": magnitude,
        "why": reason,
    }


# ---------------------------------------------------------------------------
# the experiment that was PLANNED, as opposed to what the search had to do
# ---------------------------------------------------------------------------
def planned_experiment(row: dict) -> dict:
    """Why this source was driven the way it was, in the record's own words.

    Distinct from :func:`experiment_settlement`, which is what the amplitude
    search had to do to get a run that finishes. This is the decision before
    that: which family of behaviour the source was read as, what criterion an
    experiment for that family has to meet, and which lines of the source
    settled it. A page that shows only the loading path shows what was driven
    and not why, and "why" is the part a reader has to be able to disagree
    with.

    An entry whose ``experiment`` block is empty -- 5 of the 38 pass10 records
    that carry one -- is reported as not established rather than as a blank,
    because a blank reads as "there was nothing to say".
    """
    plan = row.get("experiment")
    if not isinstance(plan, dict) or not plan:
        return {
            "recorded": False,
            "family": NOT_ESTABLISHED,
            "driven by": NOT_ESTABLISHED,
            "the criterion this experiment must meet": NOT_ESTABLISHED,
            "what the experiment is required to do": NOT_ESTABLISHED,
            "why this source was driven this way": NOT_ESTABLISHED,
            "the source lines that settled it": [],
            "notes this family carries": [],
            "what stopped one being planned": "",
            "warnings": [],
        }
    family = plan.get("family") if isinstance(plan.get("family"), dict) else {}
    return {
        "recorded": True,
        "family": str(family.get("name") or "") or NOT_ESTABLISHED,
        "driven by": str(family.get("driver") or "") or NOT_ESTABLISHED,
        "the criterion this experiment must meet":
            str(plan.get("criterion") or "") or NOT_ESTABLISHED,
        "what the experiment is required to do":
            str(plan.get("requirement") or "") or NOT_ESTABLISHED,
        "why this source was driven this way":
            str(plan.get("reason") or "") or NOT_ESTABLISHED,
        # Quoted, not summarised: these are the lines of the source that
        # decided the family, and a reader who cannot see them cannot check
        # the decision.
        "the source lines that settled it": list(family.get("evidence") or ()),
        "notes this family carries": list(family.get("notes") or ()),
        "what stopped one being planned": str(plan.get("refusal") or ""),
        "warnings": list(plan.get("warnings") or ()),
    }


def coverage_rows(row: dict) -> list:
    """The family's own criteria, each as a finding with three states.

    ``met`` is the record's, unedited. ``met=null`` means NOT MEASURED and is
    rendered as such: on pass10 one criterion reads "no increment in this run
    applied a direct strain with no shear, so the coupling has nothing to show
    up in", and showing that as a met criterion would claim a coupling was
    exercised when the experiment never presented it.
    """
    rows = []
    for entry in row.get("coverage") or ():
        if not isinstance(entry, dict):
            continue
        rows.append(finding(
            str(entry.get("name") or "an unnamed criterion"),
            entry.get("met"),
            str(entry.get("reason") or ""),
            magnitude=entry.get("magnitude"),
            about="a criterion of the family this source was read as"))
    return rows


# ---------------------------------------------------------------------------
# objectivity: two different facts that must not be merged
# ---------------------------------------------------------------------------
#: The two claims the objectivity block holds, kept apart on purpose.
#:
#: ``agreed`` is about THE TRANSFORM: the converted build and the original,
#: run on the same path presented in a rotated frame, computed the same thing.
#: ``objective`` is about THE MODEL: the author's own response to a rotated
#: path is the unrotated response rotated, which is what objectivity means.
#:
#: They are independent, and on pass10 they are measured to differ. The
#: NeoHookean entry verified with ``agreed=true`` and ``objective=false``, the
#: author's own response missing Q sigma Q^T by 9.02 relative -- so a page
#: that merged them into one tick would report the transform's success as the
#: model's correctness and hide a finding about the published source.
OBJECTIVITY_CLAIMS = (
    ("agreed",
     "the converted build agrees with the original on a rotated path",
     "the transform: whether converting the source changed what it computes "
     "in a rotated frame",
     "worst_stress_relative"),
    ("objective",
     "the author's own response to a rotated path is Q sigma Q^T",
     "the model: whether the published source is frame indifferent, which is "
     "a property of what its author wrote and not of this pipeline",
     "objectivity_worst_relative"),
)


def objectivity_rows(row: dict) -> list:
    """The objectivity block as two findings, never as one.

    Returns two rows always -- one per claim in :data:`OBJECTIVITY_CLAIMS` --
    so that a record which measured one and not the other shows a measurement
    beside a "not established" rather than a single word covering both.
    """
    block = row.get("objectivity")
    block = block if isinstance(block, dict) else {}
    reasons = {"agreed": str(block.get("reason") or ""),
               "objective": str(block.get("objectivity_reason")
                                or block.get("reason") or "")}
    rows = []
    for name, what, about, magnitude in OBJECTIVITY_CLAIMS:
        value = block.get(name)
        rows.append(finding(what, value,
                            reasons[name] if value is not None else
                            ("no rotated-frame comparison was run for this "
                             "entry" if not block else
                             "this run recorded no measurement of it"),
                            magnitude=block.get(magnitude),
                            about=about))
    return rows


def objectivity_detail(row: dict) -> dict:
    """Everything else the objectivity block carries, named.

    The rotation itself is here because "in a rotated frame" is not checkable
    until the frame is on the page: it is the nine entries of Q, row major.
    """
    block = row.get("objectivity")
    if not isinstance(block, dict) or not block:
        return {"ran": three_state(None),
                "why": "this run carries no objectivity block at all, so "
                       "neither claim was established"}
    return {
        "ran": three_state(block.get("ran")),
        "the rotation Q, row major": list(block.get("rotation") or ()),
        "components compared": block.get("compared_components"),
        "worst stress difference, converted against original":
            block.get("worst_stress_relative"),
        "worst state difference, converted against original":
            block.get("worst_state_relative"),
        "worst departure from Q sigma Q^T in the author's own response":
            block.get("objectivity_worst_relative"),
        "the original's own job": block.get("original"),
        "the converted build's own job": block.get("transformed"),
    }


# ---------------------------------------------------------------------------
# did the material do anything, and does the response fit the problem
# ---------------------------------------------------------------------------
def informativeness_row(row: dict) -> dict:
    """Whether the run a verdict rests on exercised the material at all.

    Three states, and the middle one is the point: 3 of the 10 pass10 entries
    that reached ``verified`` carry no informativeness measurement at all.
    Agreement about a material sitting still is agreement about the part every
    build gets right, and "nobody measured whether it sat still" is not the
    same claim as "it did something".
    """
    block = field_anywhere(row, "mechanically_informative")
    block = block if isinstance(block, dict) else {}
    measured = row.get("evidence") or {}
    recorded = measured.get("mechanically_informative")
    value = block.get("informative") if "informative" in block else recorded
    # Three different absences, and saying the wrong one is its own dishonesty.
    # 108 of the 254 pass10 entries never reached a run at all, and telling
    # those "this run predates the informativeness gate" invents a run.
    if not measured:
        absent = ("nothing ran for this entry, so there was no run over which "
                  "the material could have done anything")
    elif recorded is None:
        absent = ("this run predates the informativeness gate, so whether the "
                  "material did anything over it was never measured")
    else:
        absent = ""
    return finding(
        "the material did something over the run that was verified",
        value,
        str(block.get("reason") or "") or absent,
        about="whether there is any behaviour under the agreement")


def plausibility_rows(row: dict) -> list:
    """Each plausibility check as its own finding.

    A peak stress is plausible against the scales the problem supplies or it
    is not, and the record keeps one check per scale. Summed into a single
    "plausible" they would hide which scale the response failed against.
    """
    block = row.get("response_plausibility")
    block = block if isinstance(block, dict) else {}
    rows = []
    for check in block.get("checks") or ():
        if not isinstance(check, dict):
            continue
        rows.append(finding(
            str(check.get("name") or "an unnamed check"),
            check.get("plausible"),
            str(check.get("detail") or ""),
            magnitude=check.get("measured"),
            about=f"measured against {check.get('against')}"))
    return rows


def plausibility_overall(row: dict) -> dict:
    block = row.get("response_plausibility")
    block = block if isinstance(block, dict) else {}
    return finding("the response fits the scales this problem supplies",
                   block.get("plausible") if block else None,
                   "" if block else "no plausibility check is recorded for "
                                    "this entry",
                   about="the response as a whole")


def time_scale_row(row: dict) -> dict:
    """Whether the experiment ran long enough for the clock the source keeps.

    ``enough`` is three-state for the same reason everything else here is: a
    source that declares no time scale of its own is not a source whose
    experiment was too short, and the record says which of those it is.
    """
    block = field_anywhere(row, "time_scale_coverage")
    block = block if isinstance(block, dict) else {}
    scale = block.get("scale") if isinstance(block.get("scale"), dict) else {}
    row_out = finding(
        "the experiment reached the time scale the source declares",
        block.get("enough") if block else None,
        str(block.get("reason") or "") or
        "no time-scale measurement is recorded for this entry",
        magnitude=block.get("fraction"),
        about="how long the run was against the source's own clock")
    row_out["the source declares a time scale"] = three_state(
        scale.get("declared") if scale else None)
    row_out["that scale"] = scale.get("name") or ""
    row_out["its value"] = scale.get("value")
    row_out["the experiment's total time"] = block.get("total_time")
    row_out["reaches the heuristic"] = three_state(
        block.get("reaches_heuristic") if block else None)
    return row_out


def signature_rows(row: dict) -> list:
    """Each hypothesis about a primal disagreement, with its own status.

    A stage is not a diagnosis. The record keeps hypotheses, and each one
    carries whether it was confirmed, refuted, or still needs evidence -- and
    ``confirmed_root_cause`` is null on every hypothesis that is not settled.
    A page that showed the list without the status would read as a set of
    conclusions.
    """
    block = field_anywhere(row, "primal_signature")
    block = block if isinstance(block, dict) else {}
    rows = []
    for entry in block.get("hypotheses") or ():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("confirmation_status") or "") or NOT_ESTABLISHED
        cause = entry.get("confirmed_root_cause")
        rows.append({
            "hypothesis": entry.get("hypothesis"),
            "what it claims": entry.get("claim"),
            "confirmation status": status,
            "confirmed root cause":
                NOT_ESTABLISHED if cause is None else str(cause),
            "what would confirm it": entry.get("what_would_confirm"),
            "what would refute it": entry.get("what_would_refute"),
            "supporting evidence": [
                e.get("statement") for e in entry.get("supporting_evidence") or ()
                if isinstance(e, dict)],
            "contradicting evidence": [
                e.get("statement") for e in
                entry.get("contradicting_evidence") or ()
                if isinstance(e, dict)],
            "reproduced": three_state(entry.get("reproduction")),
        })
    return rows


def material_search_row(row: dict) -> dict:
    """Where constants were looked for, as a finding rather than a blank.

    "Nobody published what this material is made of" is a claim until it names
    the files it read; this carries the scan's own account beside a three-state
    answer to whether anything was found.
    """
    searched = field_anywhere(row, "searched_for_material_data")
    searched = searched if isinstance(searched, dict) else {}
    provenance = str(row.get("material_provenance") or "")
    # True where a deck published them, False where a scan ran and found
    # none, and None where no scan is recorded at all -- which is "nobody
    # looked here", not "there is nothing to find".
    found = True if provenance else (False if searched else None)
    out = finding("constants for this source were found",
                  found,
                  _where_constants_were_looked_for(row),
                  about="what the pairing scan read")
    out["repository scanned"] = searched.get("repository") or NOT_ESTABLISHED
    out["decks read"] = searched.get("decks_scanned")
    out["what the scan found"] = searched.get("evidence") or ""
    return out


# ---------------------------------------------------------------------------
# what the six gates say about the stage, and what may be claimed
# ---------------------------------------------------------------------------
def gate_tally(row: dict) -> dict:
    """The six gates split three ways: held, did not hold, never established."""
    measured = row.get("evidence") or {}
    held, broke, unestablished = [], [], []
    for name, _what, _where in EVIDENCE_GATES:
        value = measured.get(name)
        (unestablished if value is None else held if value else broke).append(name)
    return {"held": held, "did not hold": broke,
            "never established": unestablished}


def what_may_be_claimed(row: dict) -> dict:
    """What this entry may honestly be called, and which gate decides it.

    The batch's own terminal state is carried unedited -- a verdict rendered
    differently here than in the evidence is a second opinion nobody can cite.
    What is added is the qualification the six gates make necessary, because
    ``fully_verified`` is one word and the six are the measurements under it.

    The rule this function exists to keep: the page does not call an entry
    verified where ``mechanically_informative`` is false or was never
    established. On pass10, 3 of the 10 entries at ``verified`` carry no
    informativeness measurement at all -- agreement with nothing established
    about whether the material did anything. That is a real result and it is
    not a verification of the material's behaviour, so it is not shown as one.
    """
    stage = str(row.get("stage") or "")
    state = from_stage(stage, str(row.get("reason") or "")).state
    tally = gate_tally(row)
    measured = row.get("evidence") or {}
    informative = measured.get("mechanically_informative")

    qualifier = ""
    if informative is None:
        qualifier = "informativeness not established"
    elif informative is False:
        qualifier = "the material did nothing over this run"
    elif tally["never established"]:
        qualifier = (", ".join(n.replace("_", " ")
                               for n in tally["never established"])
                     + " not established")
    elif tally["did not hold"]:
        qualifier = ", ".join(n.replace("_", " ") + " did not hold"
                              for n in tally["did not hold"])

    complete = not tally["never established"] and not tally["did not hold"]
    # 108 of the 254 pass10 entries never reached a run at all, and telling
    # those "agreement only" would report an agreement that never happened.
    # Nothing measured is its own answer and it is said as one.
    nothing_measured = len(tally["never established"]) == len(EVIDENCE_GATES)
    if complete:
        claim = "verified: all six gates were measured and all six hold"
    elif nothing_measured:
        claim = ("nothing was measured: this entry never reached a run the "
                 "six gates could be measured on, so none of them holds and "
                 "none of them failed")
    elif informative is False:
        claim = ("the material did nothing over this run. Agreement about a "
                 "material sitting still is agreement about the part every "
                 "build gets right, so this is not a verification of its "
                 "behaviour")
    elif tally["did not hold"]:
        claim = ("not complete on the six gates: "
                 + ", ".join(n + " did not hold" for n in tally["did not hold"]))
        if tally["never established"]:
            claim += ("; " + ", ".join(tally["never established"])
                      + " never established")
    else:
        # Every gate that was measured holds, and at least one was not.
        claim = (", ".join(tally["never established"])
                 + " never established, so nothing here may be called a "
                 "verification -- the gates that were measured hold, and a "
                 "gate nobody measured is not a gate that passed")

    followups = {name: what_the_batch_recorded_after(row, name)
                 for name in tally["did not hold"]}

    # Findings the record keeps that the six gates do not cover. They are
    # listed apart rather than folded into the claim, because they are about
    # different things: the gates are about whether this pipeline verified
    # the conversion, and these are about the source somebody published.
    # Measured on pass10: the NeoHookean entry passes all six gates and its
    # author's own response misses Q sigma Q^T by 9.02 relative. A headline
    # that carried only the six would be true and would still hide that.
    outside = []
    for row_out in objectivity_rows(row):
        if row_out["holds"] == DID_NOT_HOLD:
            outside.append(f"{row_out['finding']}: no -- {row_out['why']}")
    for row_out in coverage_rows(row):
        if row_out["holds"] == DID_NOT_HOLD:
            outside.append(f"the criterion {row_out['finding']!r} was not "
                           f"met: {row_out['why']}")
        elif not row_out["established"]:
            outside.append(f"the criterion {row_out['finding']!r} was "
                           f"{NOT_ESTABLISHED}: {row_out['why']}")

    return {
        "the batch's terminal state": state,
        "the stage the batch reached": stage,
        # The batch's word with the gates' qualification attached, so a bare
        # "verified" cannot stand anywhere on the page over an entry whose
        # informativeness nobody measured.
        "qualified state": f"{state} ({qualifier})" if qualifier else state,
        "what may be claimed": claim,
        # The machine-readable form of the rule, so a caller does not have to
        # parse prose to honour it: TRUE only when all six were measured and
        # all six hold. Anything else, and this entry is not to be presented
        # as a verification of the material's behaviour.
        "may be called verified": complete,
        "nothing was measured": nothing_measured,
        "all six gates hold": complete,
        "gates that hold": tally["held"],
        "gates that did not hold": tally["did not hold"],
        "gates never established": tally["never established"],
        "what the batch recorded after a gate that did not hold":
            {k: v for k, v in followups.items() if v},
        "findings outside the six gates": outside,
    }


def history_rows(row: dict) -> list:
    """How each history grouped into increments and material points.

    Three rows where there are three: the original, the converted build, and
    the run the amplitude search itself walked. The last is there because a
    record that never reached a verification still has one history in it, and
    a panel that shows nothing for such an entry is hiding the only thing
    measured about it.
    """
    grouping = field_anywhere(row, "history_grouping") or {}
    sides: list = []
    if isinstance(grouping, dict):
        for side in ("original", "transformed"):
            payload = grouping.get(side)
            if isinstance(payload, dict):
                sides.append((side, payload))
    prefix = field_anywhere(row, "discovery_usable_prefix")
    if isinstance(prefix, dict):
        sides.append(("discovery (the search's own run)", prefix))
    rows = []
    for side, payload in sides:
        entry = {"history": side, "complete": _said(payload.get("complete"))}
        for name in HISTORY_FIELDS:
            entry[name.replace("_", " ")] = _said(payload.get(name))
        entry["total increments"] = _said(payload.get("total_increments"))
        rows.append(entry)
    return rows


def loading_rows(row: dict) -> list:
    """The loading path the experiment walked, segment by segment.

    Off the manifest that was RUN, not off the discovery summary: the summary
    says what amplitude the search chose and the manifest says what was
    actually driven, including the hold a rate probe added and the segments a
    repair shortened or dropped. A page that shows only the amplitude cannot
    show that the reversal is gone.
    """
    manifest = row.get("manifest") or {}
    rows = []
    for segment in manifest.get("loading") or ():
        if not isinstance(segment, dict):
            continue
        rows.append({
            "segment": segment.get("name"),
            "what it does": segment.get("description"),
            "strain": segment.get("strain"),
            "increments": segment.get("increments"),
            "step time": segment.get("period"),
            "held": segment.get("held") or "--",
            "body force": segment.get("body_force") or "--",
        })
    return rows


def experiment_settlement(row: dict) -> dict:
    """What the search had to do to get an experiment that runs whole.

    A verdict that rests on a repaired experiment is a verdict about the
    repaired experiment. Every part of that repair is named here: how far the
    model walked before it left its domain, what was rebuilt inside the part
    it proved safe, which mechanism stopped it, which segment was shortened or
    dropped, and what the experiment therefore stopped exercising.
    """
    return {name: field_anywhere(row, name) for name in (
        "complete_finite_verification_run",
        "discovery_usable_prefix",
        "safe_loading_reconstructed",
        "failure_mechanism",
        "segment_repair",
        "coverage_given_up",
        "time_scale_coverage",
        "activation_on_the_frozen_run",
        "mechanically_informative",
    )}


@dataclass(frozen=True)
class Requirement:
    """One thing an entry needs before it can be run, and whether it has it."""

    name: str
    satisfied: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "satisfied": self.satisfied,
                "detail": self.detail}


@dataclass
class EntryView:
    """One corpus artefact, as much as is known about it, in one shape."""

    source_id: str
    repository: str = ""
    key: str = ""
    stage: str = ""
    terminal_state: str = ""
    kind: str = ""
    reason: str = ""
    is_umat: Optional[bool] = None
    #: What the manifest said: element, tensor shape, kinematics, constants.
    manifest: dict = field(default_factory=dict)
    #: How the formulation was decided and by which witnesses.
    formulation: dict = field(default_factory=dict)
    #: What the loading search did, including the time probes.
    discovery: dict = field(default_factory=dict)
    #: Per job: completed, increments, warnings, and where its files are.
    jobs: dict = field(default_factory=dict)
    primal: dict = field(default_factory=dict)
    tangent: dict = field(default_factory=dict)
    truncation: dict = field(default_factory=dict)
    precision_control: dict = field(default_factory=dict)
    #: The model against itself, compiled so the same mathematics is computed
    #: in a different order. Run when a precision control did not settle a
    #: disagreement, and recorded whether or not it did.
    association_control: dict = field(default_factory=dict)
    requirements: list = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    seconds: Optional[float] = None
    #: The six gates a verdict rests on, each with what it measures and
    #: whether it was measured. See :data:`EVIDENCE_GATES`.
    evidence: list = field(default_factory=list)
    #: How each history grouped into increments and material points, and
    #: where the first incomplete increment and the first value that is not a
    #: number are. See :func:`history_rows`.
    history: list = field(default_factory=list)
    #: What the search had to do to get an experiment that runs whole, and
    #: what the experiment therefore stopped exercising.
    experiment: dict = field(default_factory=dict)
    #: What the pairing scan read while looking for material constants.
    material_search: dict = field(default_factory=dict)
    #: What kind of disagreement a primal disagreement is, where one was
    #: classified. A stage is not a diagnosis.
    primal_signature: dict = field(default_factory=dict)
    #: The manifest the batch actually ran: constants, tensor split, loading
    #: segments, step ladder, tolerances and outputs. Distinct from
    #: :attr:`manifest`, which is what was INFERRED about the source. A
    #: regression replays this one, so a reader has to be able to see it.
    run_manifest: dict = field(default_factory=dict)
    #: The loading path, segment by segment. See :func:`loading_rows`.
    loading: list = field(default_factory=list)
    #: The experiment that was PLANNED and why -- the family the source was
    #: read as, the criterion, and the source lines that settled it. Distinct
    #: from :attr:`experiment`, which is what the search had to DO to get a
    #: run that finishes. See :func:`planned_experiment`.
    planned_experiment: dict = field(default_factory=dict)
    #: The family's own criteria as findings, each three-state. See
    #: :func:`coverage_rows`.
    coverage: list = field(default_factory=list)
    #: Two findings, never one: whether the converted build agreed with the
    #: original on a rotated path (the transform), and whether the author's
    #: own response is Q sigma Q^T (the model). See :func:`objectivity_rows`.
    objectivity: list = field(default_factory=list)
    #: The rest of the objectivity block, the rotation included.
    objectivity_detail: dict = field(default_factory=dict)
    #: Whether the material did anything over the run that was verified.
    informativeness: dict = field(default_factory=dict)
    #: Whether the response fits the scales the problem supplies, per check.
    plausibility: list = field(default_factory=list)
    #: The same, as the record's own overall answer.
    plausibility_overall: dict = field(default_factory=dict)
    #: How long the run was against the source's own declared clock.
    time_scale: dict = field(default_factory=dict)
    #: Each hypothesis about a primal disagreement, with its own confirmation
    #: status. See :func:`signature_rows`.
    signature: list = field(default_factory=list)
    #: Where constants were looked for, as a three-state finding.
    material_search_finding: dict = field(default_factory=dict)
    #: What may honestly be claimed about this entry, and which gate decides
    #: it. See :func:`verdict`.
    verdict: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        record = {name: getattr(self, name) for name in
                  ("source_id", "repository", "key", "stage", "terminal_state",
                   "kind", "reason", "is_umat", "manifest", "formulation",
                   "discovery", "jobs", "primal", "tangent", "truncation",
                   "precision_control", "association_control",
                   "artifacts", "seconds", "evidence",
                   "history", "experiment", "material_search",
                   "primal_signature", "run_manifest", "loading",
                   "planned_experiment", "coverage", "objectivity",
                   "objectivity_detail", "informativeness", "plausibility",
                   "plausibility_overall", "time_scale", "signature",
                   "material_search_finding", "verdict")}
        record["requirements"] = [r.as_dict() for r in self.requirements]
        return record


def _requirements(row: dict) -> list:
    """What this entry needed, and which of it was there.

    Written as questions with an answer each rather than as a single "ready"
    flag, because "not ready" is not a thing a user can act on and "no deck in
    this repository publishes constants for it" is.
    """
    manifest_refusals = row.get("refusals") or []
    material = str(row.get("material_provenance") or "")
    deck = str(row.get("deck") or "")
    formulation = row.get("formulation") or {}
    companions = ((row.get("original_diagnosis") or {}).get("companions") or {})
    missing_units = list(companions.get("missing_modules") or []) + \
        list(companions.get("missing_includes") or [])
    return [
        Requirement("a UMAT interface", row.get("stage") != "not_a_umat",
                    str(row.get("reason") or "")
                    if row.get("stage") == "not_a_umat" else ""),
        Requirement("published material constants", bool(material),
                    material or _where_constants_were_looked_for(row)),
        Requirement("a paired deck", bool(deck), deck),
        Requirement("a formulation this harness can drive",
                    bool(formulation.get("element")),
                    str(formulation.get("reason") or "")),
        Requirement("every companion source", not missing_units,
                    ", ".join(missing_units)),
        Requirement("a manifest with nothing missing", not manifest_refusals,
                    "; ".join(str(r) for r in manifest_refusals)),
        # The one a verdict actually rests on. Abaqus printing THE ANALYSIS
        # HAS COMPLETED SUCCESSFULLY is a statement about the solver; this is
        # about the routine it called.
        Requirement("an analysis finite from end to end",
                    bool(field_anywhere(
                        row, "complete_finite_verification_run")),
                    _how_the_experiment_was_settled(row)),
        # Agreement about a material that did nothing is agreement about the
        # part every build gets right, so it is a requirement of its own
        # rather than a footnote under the tangent.
        Requirement("an experiment the material did something in",
                    (row.get("evidence") or {}).get(
                        "mechanically_informative") is not False,
                    _what_the_experiment_exercised(row)),
    ]


def _how_the_experiment_was_settled(row: dict) -> str:
    """What the discovery had to do to get an experiment that runs whole.

    Named rather than summarised, because "not ready" is not something a
    reader can act on and "the model will not be driven backwards, so the
    reversal was dropped and this experiment no longer exercises it" is.
    """
    grouping = (field_anywhere(row, "history_grouping") or {}).get(
        "original") or {}
    if field_anywhere(row, "complete_finite_verification_run"):
        said = (f"{grouping.get('complete_increments', '?')} complete "
                f"increment(s) at "
                f"{grouping.get('material_points_per_increment', '?')} "
                f"material points each, every one finite")
        given_up = str(field_anywhere(row, "coverage_given_up") or "")
        return f"{said}; {given_up}" if given_up else said
    mechanism = (field_anywhere(row, "failure_mechanism") or {}).get("kind") or ""
    repair = str(field_anywhere(row, "segment_repair") or "")
    prefix = field_anywhere(row, "discovery_usable_prefix") or {}
    said = (f"{prefix.get('complete_increments', 0)} complete increment(s) of "
            f"{prefix.get('total_increments', '?')} before it left its domain")
    where = (prefix.get("first_non_finite_material_point") or {})
    if where:
        said += (f"; the first value that was not a number is element "
                 f"{where.get('element')} point {where.get('point')} at "
                 f"increment {where.get('increment')}")
    if mechanism:
        said += f"; the failure is {mechanism.replace('_', ' ')}"
    rebuilt = field_anywhere(row, "safe_loading_reconstructed") or {}
    if rebuilt:
        said += (f"; the loading was rebuilt at "
                 f"{rebuilt.get('amplitude')}, {rebuilt.get('fraction')} of "
                 f"the part the run proved safe")
    return f"{said}; {repair}" if repair else said


def _what_the_experiment_exercised(row: dict) -> str:
    """Whether the run a verdict rests on exercised anything, and how that
    was measured -- the indicators read off the frozen run, and whether the
    experiment was long enough for the time scale the source declares."""
    informative = field_anywhere(row, "mechanically_informative")
    if isinstance(informative, dict) and informative.get("reason"):
        return str(informative["reason"])
    activation = field_anywhere(row, "activation_on_the_frozen_run") or {}
    coverage = field_anywhere(row, "time_scale_coverage") or {}
    said = [str(activation.get("summary") or ""), str(coverage.get("reason") or "")]
    said = [part for part in said if part]
    if said:
        return "; ".join(said)
    if (row.get("evidence") or {}).get("mechanically_informative") is None:
        return ("this run predates the informativeness gate, so whether the "
                "material did anything over it was never measured")
    return str(row.get("reason") or "")


def _where_constants_were_looked_for(row: dict) -> str:
    """What the search for material constants actually read.

    "No deck publishes constants for this source" is a claim until it names
    a file. The verification records the pairing scan's own account -- the
    repository, how many decks were read, how many constants the source's
    PROPS references reach -- so the panel shows that rather than a sentence
    a reader cannot check.
    """
    searched = field_anywhere(row, "searched_for_material_data") or {}
    if not searched:
        return str(row.get("reason") or
                   "no deck in this repository publishes constants matching "
                   "this source")
    where = str(searched.get("repository") or "this source's repository")
    count = int(searched.get("decks_scanned") or 0)
    evidence = str(searched.get("evidence") or "")
    if not count:
        return (f"{where} contains no .inp file at all, and no document in "
                f"it carries a material block naming this routine")
    said = f"read {count} .inp file(s) in {where}"
    if evidence:
        said += f": {evidence}"
    return said


def _artifacts(row: dict, work_dir: Optional[Path]) -> dict:
    """Where the files this entry produced are, named rather than embedded."""
    key = str(row.get("key") or "")
    if not work_dir or not key:
        return {}
    root = Path(work_dir) / key
    found: dict = {"work_dir": str(root)}
    for job in ("original", "transformed", "control"):
        directory = root / job if job != "control" else root / "precision_control"
        if not directory.is_dir():
            continue
        found[job] = {
            "directory": str(directory),
            "deck": str(directory / f"{job}.inp"),
            "status_file": str(directory / f"{job}.sta"),
            "message_file": str(directory / f"{job}.msg"),
            "data_file": str(directory / f"{job}.dat"),
            "probe": str(directory / f"{job}_probe.txt"),
            "history": str(directory / f"{job}_history.json"),
        }
    if (root / "discovery").is_dir():
        found["discovery_dir"] = str(root / "discovery")
    if (root / "replay").is_dir():
        found["replay_dir"] = str(root / "replay")
    return found


def entry_view(row: dict, work_dir: Optional[Path] = None) -> EntryView:
    """One results row in the shape the interface reads."""
    stage = str(row.get("stage") or "")
    verdict = from_stage(stage, str(row.get("reason") or ""))
    return EntryView(
        source_id=str(row.get("source") or ""),
        repository=str(row.get("repository") or ""),
        key=str(row.get("key") or ""),
        stage=stage,
        terminal_state=verdict.state,
        kind=verdict.kind,
        reason=str(row.get("reason") or ""),
        is_umat=None if stage == "not_a_umat" else True,
        manifest={
            "element_type": row.get("element_type"),
            "ntens": row.get("ntens"),
            "kinematics": row.get("kinematics"),
            "kinematics_provenance": row.get("kinematics_provenance"),
            "kinematics_note": row.get("kinematics_note"),
            "props_count": row.get("props_count"),
            "nstatv": row.get("nstatv"),
            "unsymmetric": row.get("unsymmetric"),
            "material_block": row.get("material_block"),
            "material_provenance": row.get("material_provenance"),
            "searched_for_material_data": field_anywhere(
                row, "searched_for_material_data"),
            # How the experiment was settled on, and what it cost. A reader
            # has to be able to see that a verdict rests on an analysis that
            # was finite throughout, which segment (if any) the model would
            # not walk, and what the experiment therefore stopped exercising.
            "discovery_usable_prefix": field_anywhere(
                row, "discovery_usable_prefix"),
            "safe_loading_reconstructed": field_anywhere(
                row, "safe_loading_reconstructed"),
            "complete_finite_verification_run": field_anywhere(
                row, "complete_finite_verification_run"),
            "failure_mechanism": field_anywhere(row, "failure_mechanism"),
            "segment_repair": field_anywhere(row, "segment_repair"),
            "coverage_given_up": field_anywhere(row, "coverage_given_up"),
            "safety_distance": field_anywhere(row, "safety_distance"),
            "history_grouping": field_anywhere(row, "history_grouping"),
            "time_scale_coverage": field_anywhere(row, "time_scale_coverage"),
            "evidence": row.get("evidence"),
            "deck": row.get("deck"),
            "deck_digest": row.get("deck_digest"),
            "source_form": row.get("source_form"),
            "source_form_note": row.get("source_form_note"),
        },
        formulation=dict(row.get("formulation") or {}),
        discovery=dict(row.get("discovery") or {}),
        jobs={name: dict(row.get(name) or {})
              for name in ("original", "transformed", "support")
              if row.get(name)},
        primal=dict(row.get("primal") or {}),
        tangent=dict(row.get("tangent") or {}),
        truncation=dict(row.get("truncation") or {}),
        precision_control=dict(row.get("precision_control") or {}),
        association_control=dict(row.get("association_control") or {}),
        requirements=_requirements(row),
        artifacts=_artifacts(row, work_dir),
        seconds=row.get("seconds"),
        evidence=evidence_rows(row),
        history=history_rows(row),
        experiment=experiment_settlement(row),
        material_search=dict(
            field_anywhere(row, "searched_for_material_data") or {}),
        primal_signature=dict(field_anywhere(row, "primal_signature") or {}),
        run_manifest=dict(row.get("manifest") or {}),
        loading=loading_rows(row),
        planned_experiment=planned_experiment(row),
        coverage=coverage_rows(row),
        objectivity=objectivity_rows(row),
        objectivity_detail=objectivity_detail(row),
        informativeness=informativeness_row(row),
        plausibility=plausibility_rows(row),
        plausibility_overall=plausibility_overall(row),
        time_scale=time_scale_row(row),
        signature=signature_rows(row),
        material_search_finding=material_search_row(row),
        verdict=what_may_be_claimed(row),
    )


@dataclass
class RunView:
    """A whole verification run: its entries, its counts and whether it is done."""

    schema: str = SCHEMA
    results_dir: str = ""
    work_dir: str = ""
    entries: list = field(default_factory=list)
    finished: bool = False
    attempted: int = 0
    expected: Optional[int] = None

    @property
    def by_terminal_state(self) -> dict:
        counts: dict = {}
        for entry in self.entries:
            counts[entry.terminal_state] = counts.get(entry.terminal_state, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    @property
    def by_kind(self) -> dict:
        counts = {"verified": 0, "external": 0, "internal": 0}
        for entry in self.entries:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return counts

    def verified(self) -> list:
        return [e for e in self.entries if e.terminal_state == FULLY_VERIFIED]

    def as_dict(self) -> dict:
        return {"schema": self.schema, "results_dir": self.results_dir,
                "work_dir": self.work_dir, "finished": self.finished,
                "attempted": self.attempted, "expected": self.expected,
                "by_terminal_state": self.by_terminal_state,
                "by_kind": self.by_kind,
                "entries": [e.as_dict() for e in self.entries]}


def load_run(results_dir: Path, work_dir: Optional[Path] = None) -> RunView:
    """Every entry a run has settled so far, whether or not it has finished.

    Reads the append-only record, so calling it while a batch is running gives
    live progress without asking the batch anything -- which is what lets an
    interface show a job list that fills in.
    """
    results_dir = Path(results_dir)
    rows = _latest(_read_jsonl(results_dir / RESULTS_FILE))
    summary = _read_json(results_dir / "store_verification.json")
    finished = bool(isinstance(summary, dict) and summary.get("summary"))
    expected = None
    if isinstance(summary, dict):
        expected = (summary.get("summary") or {}).get("attempted")
    view = RunView(results_dir=str(results_dir),
                   work_dir=str(work_dir or ""), finished=finished,
                   attempted=len(rows), expected=expected)
    view.entries = [entry_view(row, work_dir) for row in rows]
    return view


def histories(work_dir: Path, key: str) -> dict:
    """The original, converted and control stress histories, for plotting.

    Returned as parallel series keyed by what they are, with the increment
    numbers beside them, so a caller can draw them against each other without
    knowing anything about the probe's format.
    """
    root = Path(work_dir) / key
    series: dict = {}
    for name, directory in (("original", root / "original"),
                            ("transformed", root / "transformed"),
                            ("control", root / "precision_control")):
        job = "control" if name == "control" else name
        payload = _read_json(directory / f"{job}_history.json")
        if not isinstance(payload, list) or not payload:
            continue
        from umat_oti.abaqus.activation import strain_at

        series[name] = {
            "increment": [record.get("increment") for record in payload],
            "time": [record.get("time") for record in payload],
            "stress": [list(record.get("STRESS") or ()) for record in payload],
            "strain": [strain_at(record) for record in payload],
            "state": [list(record.get("STATEV") or ()) for record in payload],
        }
    return series


def job_log(work_dir: Path, key: str, job: str, *,
            limit: int = 20000) -> dict:
    """What Abaqus wrote for one job, for a reader looking at a failure.

    The status, message and data files, trimmed. Named separately rather than
    concatenated: which file a diagnostic came from is part of reading it.
    """
    directory = Path(work_dir) / key / (
        "precision_control" if job == "control" else job)
    found: dict = {"directory": str(directory), "files": {}}
    for suffix in (".sta", ".msg", ".dat", ".log"):
        path = directory / f"{job}{suffix}"
        if path.is_file():
            try:
                found["files"][suffix] = path.read_text(
                    errors="replace")[-limit:]
            except OSError as error:               # pragma: no cover
                found["files"][suffix] = f"could not be read: {error}"
    return found


def deck_text(work_dir: Path, key: str, job: str = "original") -> str:
    """The generated .inp both builds were driven by."""
    path = Path(work_dir) / key / job / f"{job}.inp"
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def fd_plateau(entry: EntryView, state: int = 0, *,
               against: str = "comparison") -> list:
    """The finite-difference sweep at one state, step by step.

    One step size cannot separate a truncation error from a cancellation one:
    both shrink the error for a while and then grow it, and a single number
    taken anywhere on that curve is indistinguishable from a number taken at
    the one step where two different tangents happen to cross. What settles it
    is the PLATEAU -- a run of step sizes over which the error stops moving --
    so each row carries whether it is inside the stable range the batch
    recorded, and which step was the best.

    ``against`` picks which sweep: the converted build's tangent against a
    difference of the original (``comparison``, the one a verdict rests on),
    the author's own DDSDDE against the same difference
    (``against_the_authors_tangent``), or the reference's difference against
    itself (``the_references_own_error``).
    """
    states = (entry.tangent or {}).get("states") or []
    if not 0 <= state < len(states):
        return []
    comparison = (states[state] or {}).get(against) or {}
    stable = list(comparison.get("stable_range") or ())
    best = comparison.get("best_step")
    rows = []
    for point in comparison.get("sweep") or ():
        step = point.get("step")
        inside = None
        if len(stable) == 2 and step is not None:
            try:
                inside = float(stable[0]) <= float(step) <= float(stable[1])
            except (TypeError, ValueError):       # pragma: no cover
                inside = None
        rows.append({"step": step,
                     "relative": point.get("relative"),
                     "absolute": point.get("absolute"),
                     "frobenius": point.get("frobenius"),
                     "on the plateau": inside,
                     "best step": best is not None and step == best})
    return rows


def componentwise_errors(entry: EntryView, state: int = 0, *,
                         work_dir: Optional[Path] = None) -> list:
    """Entry by entry, the DDSDDE the original returned against the converted
    build's, at one state.

    "The tangent disagreed by 3e-4" is a number; "DDSDDE(4,4) disagreed by
    3e-4 and every other entry agreed to 1e-12" is a finding, and only the
    second tells anybody which term of the constitutive law to open.

    The record carries norms, not matrices, so the matrices are read off the
    two probe histories on disk at the record the tangent was measured at.
    What a difference here means is worth being exact about: it is the
    AUTHOR'S own DDSDDE against the derivative the converted build extracted,
    which is the pair the record summarises as
    ``against_the_authors_tangent``. A verdict rests on ``comparison`` --
    the converted build's derivative against a centred difference of the
    original's STRESS -- so a large number in this table is a statement about
    the author's tangent, not about the transformation.

    Empty when the histories are not on disk, which is the honest answer: an
    interface that invents a table here would be showing a difference nobody
    computed.
    """
    states = (entry.tangent or {}).get("states") or []
    if not 0 <= state < len(states) or not work_dir or not entry.key:
        return []
    index = (states[state] or {}).get("record_index")
    if not isinstance(index, int):
        return []
    root = Path(work_dir) / entry.key
    original = _read_json(root / "original" / "original_history.json")
    converted = _read_json(root / "transformed" / "transformed_history.json")
    if not isinstance(original, list) or not isinstance(converted, list):
        return []
    if not 0 <= index < len(original) or not 0 <= index < len(converted):
        return []
    left = list((original[index] or {}).get("DDSDDE") or ())
    right = list((converted[index] or {}).get("DDSDDE") or ())
    size = int(entry.manifest.get("ntens") or 0)
    if not left or len(left) != len(right) or size <= 0:
        return []
    if len(left) < size * size:
        return []
    largest = max((abs(float(v)) for v in left[:size * size]), default=0.0)
    rows = []
    for i in range(size):
        for j in range(size):
            a, b = float(left[i * size + j]), float(right[i * size + j])
            difference = abs(a - b)
            scale = max(abs(a), abs(b))
            rows.append({
                "entry": f"DDSDDE({i + 1},{j + 1})",
                "the author's own": a,
                "the converted build's": b,
                "absolute": difference,
                # Relative to the entry itself where the entry carries any of
                # the response, and left unscored where it does not: a
                # component eight orders below the largest holds each build's
                # rounding and nothing else, and dividing by it manufactures a
                # disagreement out of round-off.
                "relative": (difference / scale
                             if scale > largest * 1e-8 and scale > 0 else None),
            })
    rows.sort(key=lambda r: (r["relative"] is None, -(r["relative"] or 0.0),
                             -r["absolute"]))
    return rows


#: Every claim the interface makes about an entry, and where the thing behind
#: it is. A panel that shows a number without saying which file it came out of
#: is asking to be believed; this is what makes a screenshot checkable.
EVIDENCE_LOCATIONS = (
    ("the manifest that was run", "manifest", "original/original.inp"),
    ("where the material constants came from", "manifest.material_provenance",
     ""),
    ("what was read while looking for constants",
     "searched_for_material_data", ""),
    ("the loading history the experiment walked", "manifest.loading",
     "original/original.inp"),
    ("why this source was driven this way at all", "experiment", ""),
    ("the family's own criteria, met and not met", "coverage", ""),
    ("what the search did to arrive at it", "discovery", "discovery"),
    ("what Abaqus did with it", "original / transformed",
     "original/original.sta"),
    ("what the routine wrote at every material point", "history_grouping",
     "original/original_history.json"),
    ("whether the material did anything", "mechanically_informative", ""),
    ("how long the experiment ran against the source's own clock",
     "time_scale_coverage", ""),
    ("whether the response fits the scales the problem supplies",
     "response_plausibility", ""),
    ("whether converting the source changed what it computes in a rotated "
     "frame", "objectivity.agreed", "objectivity"),
    ("whether the author's own response is Q sigma Q^T",
     "objectivity.objective", "objectivity"),
    ("the two builds' stress and state, compared", "primal",
     "transformed/transformed_history.json"),
    ("what kind of disagreement it is", "primal_signature", ""),
    ("the tangent against a difference of the original",
     "tangent.states[].comparison", "replay"),
    ("the author's own DDSDDE against the same difference",
     "tangent.states[].against_the_authors_tangent",
     "transformed/transformed_history.json"),
    ("what the arithmetic alone would have cost", "precision_control",
     "precision_control"),
    ("how far this model moves when its own arithmetic is reordered",
     "association_control", "association_control"),
    ("where a derivative was dropped on the way to the stress", "truncation",
     ""),
)


def evidence_paths(entry: EntryView) -> list:
    """For every claim on the page, the field and the file behind it.

    ``on disk`` is ``""`` where the claim rests on the record alone, and a
    path under this entry's work directory otherwise. ``present`` says whether
    that file is actually there, so a reader can tell a claim whose evidence
    was cleaned up from one whose evidence is sitting next to it.
    """
    root = entry.artifacts.get("work_dir") or ""
    rows = []
    for what, field_name, relative in EVIDENCE_LOCATIONS:
        path = str(Path(root) / relative) if (root and relative) else ""
        rows.append({
            "what the page claims": what,
            "field in the record": field_name,
            "on disk": path,
            "present": Path(path).exists() if path else None,
        })
    return rows


# ---------------------------------------------------------------------------
# starting a run from the interface
# ---------------------------------------------------------------------------
#: The two modes the corpus is run in, and what each means. Named here because
#: the interface offers them as buttons and a button with an unexplained name
#: is how a user starts the wrong one.
MODES = {
    "discovery": ("infer what is missing, generate an experiment, search for "
                  "an amplitude and a rate that make the material do "
                  "something, and choose the states to differentiate at"),
    "regression": ("re-run the frozen manifests, decks, states and step sizes "
                   "of everything that has verified before, and fail if any of "
                   "it stops verifying"),
}


@dataclass
class RunHandle:
    """A batch started from the interface, and where to watch it."""

    mode: str
    results_dir: str
    work_dir: str
    command: list = field(default_factory=list)
    pid: Optional[int] = None
    started: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {"mode": self.mode, "results_dir": self.results_dir,
                "work_dir": self.work_dir, "command": list(self.command),
                "pid": self.pid, "started": self.started, "reason": self.reason}


def run_command(mode: str, results_dir: Path, work_dir: Path, *,
                only: str = "", limit: int = 0, jobs: int = 1,
                baseline: Optional[Path] = None,
                repo_root: Optional[Path] = None) -> list:
    """The exact command a run would be, so the interface can show it first.

    Separated from starting it because a user is entitled to see what a button
    will do, and because a test can then check the command without running
    Abaqus.
    """
    if mode not in MODES:
        raise ValueError(f"{mode!r} is not a mode; known: {', '.join(MODES)}")
    root = Path(repo_root or Path(__file__).resolve().parents[3])
    command = [sys.executable, str(root / "tools" / "verify_store_in_abaqus.py"),
               "--work-dir", str(work_dir), "--results-dir", str(results_dir),
               "--jobs", str(max(1, int(jobs)))]
    if mode == "regression":
        command += ["--mode", "regression", "--no-discovery"]
        if baseline is not None:
            command += ["--baseline", str(baseline)]
    if only:
        command += ["--only", only]
    if limit:
        command += ["--limit", str(int(limit))]
    return command


def start_run(mode: str, results_dir: Path, work_dir: Path, **options) -> RunHandle:
    """Start a batch in the background and hand back where to watch it.

    Detached on purpose: an Abaqus corpus round is hours, and an interface that
    blocks on it is an interface nobody can use to watch it. Progress comes
    from :func:`load_run` reading the record the batch appends to.
    """
    command = run_command(mode, results_dir, work_dir, **options)
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    handle = RunHandle(mode=mode, results_dir=str(results_dir),
                       work_dir=str(work_dir), command=command)
    log = Path(results_dir) / f"{mode}.log"
    try:
        with open(log, "wb") as stream:
            process = subprocess.Popen(
                command, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(Path(command[1]).resolve().parents[1]),
                env=dict(os.environ))
        handle.pid, handle.started = process.pid, True
    except OSError as error:
        handle.reason = f"{type(error).__name__}: {error}"
    return handle


def progress(results_dir: Path) -> dict:
    """How far a run has got, cheap enough to poll."""
    view = load_run(results_dir)
    return {"attempted": view.attempted, "expected": view.expected,
            "finished": view.finished, "by_kind": view.by_kind,
            "by_terminal_state": view.by_terminal_state,
            "latest": [e.source_id for e in view.entries[-5:]]}
