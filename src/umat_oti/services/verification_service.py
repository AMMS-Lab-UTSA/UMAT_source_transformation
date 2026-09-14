"""VerificationService: the full ladder, the six gates, and the seventh.

This is the module that makes the architecture requirement true. The verdict
rule lives here and nowhere else: no screen holds a tolerance, no screen counts
gates, and no screen decides that a record may be called verified. The CLI and
the GUI both call :meth:`VerificationService.verify_record` and render what
comes back.

Three rules are enforced rather than documented:

*Unknown is never verified.* A gate that was not measured reads
``not_established``, which is not a pass. :meth:`ladder` reports a rung that was
never reached as ``not_run`` -- an explicit state string, never an absence.

*No summary number hides a distinction.* :meth:`summarise` returns the count at
stage ``verified`` and the count true on all six **separately**, because in
pass11 those are 55 and 42 and a single headline would have to be wrong about
one of them. The thirteen records in between are reported as their own figure
with the seventh field's reading for each.

*Every claim is traceable.* Each rung carries the internal stage name it was
mapped from and the record keys it was read out of.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ._support import REPO_ROOT, read_jsonl
from .gates import (
    FALSE, GATES, NOT_ESTABLISHED, SEVENTH, TRUE, GateSet, census, read_gates,
)
from .results import Provenance, ServiceResult, repo_commit
from umat_oti.jobs.records import utc_now
from umat_oti.jobs.stages import (
    STAGES, STATE_FAILED, STATE_NOT_RUN, STATE_REFUSED, STATE_SUCCEEDED,
    label_for_internal,
)

__all__ = ["LadderRung", "VerificationVerdict", "CorpusSummary",
           "VerificationService"]

SERVICE = "verification"

#: For each displayed stage, the record keys that say whether it happened.
#: A rung with no witness in the record reports ``not_run`` rather than being
#: assumed from the rungs around it.
_WITNESSES: dict[str, tuple[str, ...]] = {
    "analyze_umat": ("entry_classification", "source_form", "source_sha256"),
    "find_material_data": ("material_block", "material_provenance",
                           "searched_for_material_data"),
    "build_experiment": ("manifest", "deck", "deck_digest", "formulation"),
    "search_activation": ("discovery", "activation_on_the_frozen_run"),
    "run_original": ("original", "support"),
    "run_transformed": ("transformed",),
    "compare_histories": ("primal", "history_grouping"),
    "verify_derivatives": ("tangent", "coverage"),
    "create_regression": (),
}

#: Where a rung has a gate that decides it, the gate decides it -- not the
#: presence of a block in the record. The tangent block exists whether or not
#: the tangent agreed, and the primal block exists whether or not the two
#: builds matched, so "the record carries this key" is evidence that the rung
#: RAN and is no evidence at all that it passed.
_GOVERNING_GATE: dict[str, str] = {
    "run_original": "abaqus_job_completed",
    "run_transformed": "abaqus_job_completed",
    "search_activation": "mechanically_informative",
    "compare_histories": "primal_agreed",
    "verify_derivatives": "derivatives_verified",
}


@dataclass
class LadderRung:
    """One rung of the displayed ladder for one record."""

    key: str
    label: str
    state: str
    internal: str = ""
    detail: str = ""
    witnesses: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "state": self.state,
                "internal": self.internal, "detail": self.detail,
                "witnesses": list(self.witnesses)}


@dataclass
class VerificationVerdict:
    """What one record establishes, decomposed."""

    key: str
    source_id: str
    stage: str
    stage_label: Optional[str]
    gates: GateSet
    ladder: list[LadderRung] = field(default_factory=list)
    reason: str = ""
    evidence_paths: dict[str, str] = field(default_factory=dict)

    @property
    def may_be_called_verified(self) -> bool:
        """All six measured and all six true. The stage word does not decide this."""
        return self.gates.all_six_hold

    def as_dict(self) -> dict:
        claim = self.gates.what_may_be_claimed()
        return {
            "key": self.key, "source_id": self.source_id,
            "stage": self.stage, "stage_label": self.stage_label,
            "may_be_called_verified": self.may_be_called_verified,
            "ladder": [r.as_dict() for r in self.ladder],
            "reason": self.reason,
            **self.gates.as_dict(),
            "what_may_be_claimed": claim,
        }


@dataclass
class CorpusSummary:
    """Counts over a whole results file, with nothing collapsed."""

    records: int = 0
    unreadable: int = 0
    at_stage_verified: int = 0
    true_on_all_six: int = 0
    verified_but_not_all_six: list[dict] = field(default_factory=list)
    all_six_but_not_stage_verified: list[str] = field(default_factory=list)
    stage_counts: dict[str, int] = field(default_factory=dict)
    gate_census: list[dict] = field(default_factory=list)
    seventh_census: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "records": self.records,
            "unreadable": self.unreadable,
            "at_stage_verified": self.at_stage_verified,
            "true_on_all_six": self.true_on_all_six,
            "verified_but_not_all_six_count":
                len(self.verified_but_not_all_six),
            "verified_but_not_all_six": list(self.verified_but_not_all_six),
            "all_six_but_not_stage_verified":
                list(self.all_six_but_not_stage_verified),
            "stage_counts": dict(self.stage_counts),
            "gate_census": list(self.gate_census),
            "seventh_census": dict(self.seventh_census),
            "why_two_numbers": (
                "'at stage verified' and 'true on all six gates' are reported "
                "separately because they are different counts. An entry may be "
                "at stage verified with primal_agreed false, where a measured "
                "control explained the difference; the seventh field says "
                "which. One headline number would have to be wrong about one "
                "of them."),
        }


class VerificationService:
    """The ladder and the gates, for every front end."""

    def __init__(self, *, repo_root: Path = REPO_ROOT) -> None:
        self.repo_root = Path(repo_root)

    def _provenance(self, **inputs) -> Provenance:
        commit, dirty = repo_commit(self.repo_root)
        return Provenance(commit=commit, commit_dirty=dirty,
                          generated_at=utc_now(), inputs=inputs)

    # -- one record --------------------------------------------------------

    def ladder(self, record: dict) -> list[LadderRung]:
        """The nine displayed rungs for one record.

        A rung whose witnesses are all absent from the record reports
        ``not_run``. It is never inferred from a later rung having happened:
        the record is what there is, and a rung with nothing behind it in the
        record is a rung this service cannot speak for.
        """
        stage = str(record.get("stage") or "")
        stopped_at = label_for_internal(stage)
        gates = read_gates(record)
        rungs: list[LadderRung] = []
        reached_stop = False

        for stage_def in STAGES:
            witnesses = [name for name in _WITNESSES[stage_def.key]
                         if record.get(name) is not None]
            state = STATE_NOT_RUN
            detail = ""
            internal = ""

            if stopped_at["mapped"] and stopped_at["key"] == stage_def.key:
                internal = stage
                reached_stop = True
                if stage == "verified":
                    state = STATE_SUCCEEDED
                    detail = "this is the rung the entry reached and passed"
                elif stage in ("manifest_refused", "needs_material_data",
                               "experiment_not_generated"):
                    state = STATE_REFUSED
                    detail = (f"the run stopped here and declined to go on: "
                              f"{record.get('reason') or stage}")
                else:
                    state = STATE_FAILED
                    detail = str(record.get("reason") or stage)
            elif reached_stop and stage == "verified":
                # The batch's ladder ends at "verified". Freezing a fixture is
                # a separate step (tools/export_residual_fixture.py) and this
                # record is simply silent about it -- which is not the same
                # thing as the run having stopped before it.
                state = STATE_NOT_RUN
                detail = ("this record is a verification result and does not "
                          "record whether a fixture was frozen; freezing is a "
                          "separate step and is reported by "
                          "ResidualAssemblyService, not inferred here")
            elif reached_stop:
                state = STATE_NOT_RUN
                detail = ("the run stopped at an earlier rung, so this one "
                          "never ran")
            elif witnesses:
                state = STATE_SUCCEEDED
                detail = (f"the record carries {', '.join(witnesses)}, which "
                          f"this rung writes")
            else:
                detail = ("nothing in the record witnesses this rung, so it "
                          "is reported as not run rather than assumed from "
                          "the rungs around it")

            rungs.append(LadderRung(key=stage_def.key, label=stage_def.label,
                                    state=state, internal=internal,
                                    detail=detail, witnesses=witnesses))

        for rung in rungs:
            gate_name = _GOVERNING_GATE.get(rung.key)
            if gate_name is None or rung.internal or rung.state != STATE_SUCCEEDED:
                continue
            gate = gates[gate_name]
            if gate.reading == FALSE:
                rung.state = STATE_FAILED
                rung.detail = f"{gate_name} was measured and did not hold"
                if rung.key == "compare_histories":
                    seventh = gates.seventh
                    rung.detail += (
                        f". The seventh field reads {seventh.reading!r}: "
                        f"{seventh.why}")
            elif gate.reading == NOT_ESTABLISHED:
                rung.state = STATE_NOT_RUN
                rung.detail = gate.why
        return rungs

    def verify_record(self, record: dict) -> ServiceResult:
        """The full verdict for one store-verification record."""
        result = ServiceResult(
            service=SERVICE, outcome="read",
            provenance=self._provenance(key=record.get("key")))
        gates = read_gates(record)
        verdict = VerificationVerdict(
            key=str(record.get("key") or ""),
            source_id=str(record.get("source") or ""),
            stage=str(record.get("stage") or ""),
            stage_label=label_for_internal(record.get("stage"))["label"],
            gates=gates,
            ladder=self.ladder(record),
            reason=str(record.get("reason") or ""))
        result.data = verdict
        result.outcome = ("verified" if verdict.may_be_called_verified
                          else "not_verified")
        if verdict.stage == "verified" and not verdict.may_be_called_verified:
            seventh = gates.seventh
            result.add(
                "verified_with_a_gate_reading_false",
                f"this entry is at stage 'verified' and is not true on all six "
                f"gates. The seventh field reads {seventh.reading!r}: "
                f"{seventh.why}. That is a chain, not a contradiction, and it "
                f"must be shown as one.",
                where=verdict.key, severity="warning")
        return result

    # -- a whole file ------------------------------------------------------

    def summarise(self, results_path: Path) -> ServiceResult:
        """Counts over a results file, with every distinction kept."""
        results_path = Path(results_path)
        result = ServiceResult(
            service=SERVICE, outcome="summarised",
            provenance=self._provenance(results=str(results_path)))
        if not results_path.is_file():
            result.add("results_file_missing",
                       f"{results_path} does not exist; there is nothing to "
                       f"summarise, which is not the same as a corpus in which "
                       f"nothing verified", where=str(results_path))
            result.outcome = "no_results_file"
            return result

        records, unreadable = [], 0
        for row in read_jsonl(results_path):
            if "unparseable" in row:
                unreadable += 1
                continue
            records.append(row)

        summary = CorpusSummary(records=len(records) + unreadable,
                                unreadable=unreadable)
        seventh_counts = {TRUE: 0, FALSE: 0, NOT_ESTABLISHED: 0}
        for record in records:
            stage = str(record.get("stage") or "")
            summary.stage_counts[stage] = summary.stage_counts.get(stage, 0) + 1
            gates = read_gates(record)
            seventh_counts[gates.seventh.reading] += 1
            if stage == "verified":
                summary.at_stage_verified += 1
            if gates.all_six_hold:
                summary.true_on_all_six += 1
                if stage != "verified":
                    summary.all_six_but_not_stage_verified.append(
                        str(record.get("key") or ""))
            elif stage == "verified":
                summary.verified_but_not_all_six.append({
                    "key": str(record.get("key") or ""),
                    "source": str(record.get("source") or ""),
                    "gates_that_did_not_hold":
                        [r.gate for r in gates.readings if r.reading == FALSE],
                    "gates_never_established":
                        [r.gate for r in gates.readings
                         if r.reading == NOT_ESTABLISHED],
                    SEVENTH: gates.seventh.as_dict(),
                })
        summary.gate_census = [census(records, gate) for gate in GATES]
        summary.seventh_census = dict(seventh_counts)
        result.data = summary
        result.evidence_paths["results"] = str(results_path)
        if unreadable:
            result.add("unreadable_records",
                       f"{unreadable} line(s) would not parse; they are in the "
                       f"record count and in no other figure",
                       severity="warning")
        return result
