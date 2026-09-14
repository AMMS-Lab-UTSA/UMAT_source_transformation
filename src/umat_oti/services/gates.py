"""The six gates, three-state, and the seventh field beside them.

Why three states and not two
----------------------------
A gate that was never measured is not a gate that failed, and it is certainly
not a gate that held. Collapsing the three into a boolean has cost this project
real money twice: once by reporting "agreement only" for 108 entries that never
ran, and once by publishing 7 not-established where the true figure was 11,
because four records carried the key **absent** rather than null and a
``.get(gate)`` dropped them without the census failing to sum.

So there is no truthiness shortcut anywhere in this module. ``bool(value)`` is
never used to decide a reading. A missing key and a null key are **both**
``not_established`` -- and :attr:`GateReading.raw` keeps which, because they are
different facts:

``absent``
    this batch's schema never asked the question.
``null``
    the run asked and could not answer it.
``no_evidence_block``
    the entry never got far enough to ask any of them.

A tally that merges those three can still be right about the total and wrong
about every reason, so :func:`census` reports all three and checks its own
arithmetic against the denominator before it will return.

The seventh
-----------
``primal_difference_explained_by_a_measured_control`` is written beside the six
and is deliberately not one of them. Where ``primal_agreed`` reads false and the
entry is still at ``verified``, it is because a *control* ran and measured
something: the author declared a variable at single precision, or the model
differs from ITSELF by more than the two builds differ when its own arithmetic
is reordered. The raw comparison flag never moves; the explanation is a second
fact, never an edit to the first.

In pass11 that flag predates the data, so it is absent from every record. This
module therefore reads it where it is written and otherwise *derives* it from
the control blocks the same records already carry
(``primal.explained_by_declared_precision``, ``primal.explained_by_operation_order``,
``association_control``, ``precision_control``) -- recording in
:attr:`GateReading.basis` that it was derived and from what. Deriving from a
measurement that is in the record is reading; inventing one that is not would
be fabrication, and a record with neither the flag nor a control block reads
``not_established``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "GATES",
    "GATE_MEANINGS",
    "SEVENTH",
    "TRUE", "FALSE", "NOT_ESTABLISHED",
    "RAW_TRUE", "RAW_FALSE", "RAW_NULL", "RAW_ABSENT", "RAW_NO_BLOCK",
    "RAW_NOT_ESTABLISHED",
    "GateReading",
    "GateSet",
    "read_gate",
    "read_gates",
    "read_seventh",
    "census",
    "CensusDoesNotSum",
]

#: The six, in the order the batch decides them -- the order the writer uses in
#: ``tools/verify_store_in_abaqus.py``, which is also the order
#: ``umat_oti.app.corpus_view.EVIDENCE_GATES`` shows them in.
GATES: tuple[str, ...] = (
    "abaqus_job_completed",
    "all_requested_outputs_present",
    "complete_history_finite",
    "primal_agreed",
    "derivatives_verified",
    "mechanically_informative",
)

#: The seventh field. Carried beside the six, never counted inside them.
SEVENTH = "primal_difference_explained_by_a_measured_control"

GATE_MEANINGS: dict[str, str] = {
    "abaqus_job_completed":
        "both Abaqus analyses ran to the end, read from the .sta files rather "
        "than from an exit code",
    "all_requested_outputs_present":
        "every increment that was asked for came back, with no gap in either "
        "history",
    "complete_history_finite":
        "nothing anywhere in either history is a NaN or an infinity",
    "primal_agreed":
        "the original and the transformed build agreed on stress and state; "
        "until they do, their derivatives are not comparable quantities",
    "derivatives_verified":
        "the transformed build's derivative matched a finite-difference "
        "reference able to resolve it",
    "mechanically_informative":
        "the experiment the verdict rests on actually exercised the model",
    SEVENTH:
        "where the two builds did not agree to tolerance, whether a control "
        "ran and explained the difference as the model's own conditioning "
        "rather than the transform's",
}

#: The three readings. These are the only values a gate reading may take.
TRUE = "true"
FALSE = "false"
NOT_ESTABLISHED = "not_established"

#: The five raw states underneath them. The last three all read
#: ``not_established`` and are kept apart because they are different facts.
RAW_TRUE = "true"
RAW_FALSE = "false"
RAW_NULL = "null"
RAW_ABSENT = "absent"
RAW_NO_BLOCK = "no_evidence_block"
RAW_NOT_ESTABLISHED = (RAW_NULL, RAW_ABSENT, RAW_NO_BLOCK)

_RAW_WHY = {
    RAW_NULL: "the key is present and holds null: the run asked this question "
              "and could not answer it",
    RAW_ABSENT: "the key is not in the evidence block at all: this batch's "
                "schema did not ask this question",
    RAW_NO_BLOCK: "there is no evidence block: the entry never got far enough "
                  "to ask any of the six",
}


class CensusDoesNotSum(ValueError):
    """A tally whose parts do not add up to its denominator.

    Raised rather than returned. A census that does not sum is not a census
    with a caveat, it is a number that must not be published -- which is
    exactly the failure that put 7 in a paper where the answer was 11.
    """


@dataclass(frozen=True)
class GateReading:
    """One gate, as three states, with the raw state kept underneath."""

    gate: str
    reading: str
    raw: str
    why: str = ""
    #: Where the reading came from, when it was not read directly off the key.
    basis: str = "read from the evidence block"

    @property
    def established(self) -> bool:
        """Whether anything was measured. Never inferred from the reading string."""
        return self.reading in (TRUE, FALSE)

    @property
    def held(self) -> bool:
        """True only for a measured true. Not-established is never a pass."""
        return self.reading == TRUE

    def as_dict(self) -> dict:
        return {"gate": self.gate, "reading": self.reading, "raw": self.raw,
                "established": self.established, "held": self.held,
                "why": self.why, "basis": self.basis,
                "means": GATE_MEANINGS.get(self.gate, "")}


@dataclass
class GateSet:
    """The six readings, the seventh beside them, and what may be claimed."""

    readings: list[GateReading] = field(default_factory=list)
    seventh: Optional[GateReading] = None
    #: The record's own stage word, carried so a reader can see it beside the
    #: gates rather than having to trust that they agree.
    stage: str = ""

    def __getitem__(self, gate: str) -> GateReading:
        for reading in self.readings:
            if reading.gate == gate:
                return reading
        raise KeyError(gate)

    @property
    def all_six_hold(self) -> bool:
        return len(self.readings) == len(GATES) and all(
            r.reading == TRUE for r in self.readings)

    @property
    def nothing_was_measured(self) -> bool:
        return all(not r.established for r in self.readings)

    def what_may_be_claimed(self) -> dict:
        """The claim, decomposed. There is no single number here on purpose."""
        held = [r.gate for r in self.readings if r.reading == TRUE]
        did_not = [r.gate for r in self.readings if r.reading == FALSE]
        never = [r.gate for r in self.readings if r.reading == NOT_ESTABLISHED]
        return {
            "all_six_hold": self.all_six_hold,
            "may_be_called_verified": self.all_six_hold,
            "nothing_was_measured": self.nothing_was_measured,
            "gates_that_hold": held,
            "gates_that_did_not_hold": did_not,
            "gates_never_established": never,
            "stage_the_batch_recorded": self.stage,
            "stage_agrees_with_the_gates": (
                None if not self.stage
                else (self.stage == "verified") == self.all_six_hold),
            "the_seventh": self.seventh.as_dict() if self.seventh else None,
            "note": (
                "a stage of 'verified' beside a gate reading false is not a "
                "contradiction: read the seventh field, which says whether a "
                "control ran and explained the difference."),
        }

    def as_dict(self) -> dict:
        return {
            "gates": [r.as_dict() for r in self.readings],
            "seventh": self.seventh.as_dict() if self.seventh else None,
            "what_may_be_claimed": self.what_may_be_claimed(),
        }


def _raw_state(evidence: Any, gate: str) -> str:
    """The five-state raw reading. No truthiness anywhere in here."""
    if not isinstance(evidence, dict):
        return RAW_NO_BLOCK
    if gate not in evidence:
        return RAW_ABSENT
    value = evidence[gate]
    if value is True:
        return RAW_TRUE
    if value is False:
        return RAW_FALSE
    return RAW_NULL


def read_gate(evidence: Any, gate: str) -> GateReading:
    """One gate's reading from an evidence block."""
    raw = _raw_state(evidence, gate)
    if raw == RAW_TRUE:
        return GateReading(gate, TRUE, raw, "measured and it held")
    if raw == RAW_FALSE:
        return GateReading(gate, FALSE, raw, "measured and it did not hold")
    return GateReading(gate, NOT_ESTABLISHED, raw, _RAW_WHY[raw])


def read_gates(record: Any) -> GateSet:
    """The six readings and the seventh, from one store-verification record."""
    if not isinstance(record, dict):
        record = {}
    evidence = record.get("evidence")
    readings = [read_gate(evidence, gate) for gate in GATES]
    return GateSet(readings=readings,
                   seventh=read_seventh(record),
                   stage=str(record.get("stage") or ""))


def read_seventh(record: Any) -> GateReading:
    """The seventh field: written where the pass wrote it, derived where not.

    The derivation reads only measurements already in the record. It never
    concludes "explained" from the absence of a control.
    """
    if not isinstance(record, dict):
        record = {}
    evidence = record.get("evidence")
    raw = _raw_state(evidence, SEVENTH)
    if raw == RAW_TRUE:
        return GateReading(SEVENTH, TRUE, raw,
                           "a control ran and explained the difference")
    if raw == RAW_FALSE:
        return GateReading(SEVENTH, FALSE, raw,
                           "a control ran and did not explain the difference")
    if raw == RAW_NULL:
        return GateReading(
            SEVENTH, NOT_ESTABLISHED, raw,
            "the flag is present and null, which this pass writes where no "
            "control was needed")

    # The flag was not written by this pass. Derive it from the control blocks
    # the record carries, and say that is what happened.
    derived = "derived from the control blocks in this record; the flag key "\
              "was not written by the pass that produced it"
    primal = record.get("primal") if isinstance(record.get("primal"), dict) else {}
    primal_gate = read_gate(evidence, "primal_agreed")

    if primal_gate.reading == TRUE:
        return GateReading(
            SEVENTH, NOT_ESTABLISHED, raw,
            "no control was needed: the two builds agreed to tolerance",
            basis=derived)
    if primal_gate.reading == NOT_ESTABLISHED:
        return GateReading(
            SEVENTH, NOT_ESTABLISHED, raw,
            "the entry never reached the primal comparison, so there was "
            "nothing for a control to explain",
            basis=derived)

    if primal.get("explained_by_declared_precision") is True:
        return GateReading(
            SEVENTH, TRUE, raw,
            "a precision control ran: the author declared a variable at single "
            "precision, and that accounts for the difference",
            basis=derived)
    if primal.get("explained_by_operation_order") is True:
        return GateReading(
            SEVENTH, TRUE, raw,
            "an association control ran: this model differs from itself by at "
            "least as much when its own arithmetic is reordered, so the "
            "difference is the model's conditioning and not the transform's",
            basis=derived)
    ran = [name for name in ("association_control", "precision_control")
           if isinstance(record.get(name), dict)]
    if ran:
        return GateReading(
            SEVENTH, FALSE, raw,
            f"a control ran ({', '.join(ran)}) and did not explain the "
            f"difference; measured-and-refuted is not the same answer as "
            f"not-measured",
            basis=derived)
    return GateReading(
        SEVENTH, NOT_ESTABLISHED, raw,
        "the two builds did not agree and no control is recorded, so nothing "
        "is known about why",
        basis=derived)


def census(records, gate: str) -> dict:
    """Count one gate across records, with the arithmetic checked.

    Raises :class:`CensusDoesNotSum` rather than returning a tally whose parts
    do not add up to the number of records it was given.
    """
    rows = list(records)
    counts = {RAW_TRUE: 0, RAW_FALSE: 0, RAW_NULL: 0, RAW_ABSENT: 0,
              RAW_NO_BLOCK: 0}
    for row in rows:
        evidence = row.get("evidence") if isinstance(row, dict) else None
        state = _raw_state(evidence, gate)
        # .get rather than direct indexing, and the total below is summed from
        # the five known buckets only. A state this function does not know
        # about therefore falls out of the total and trips the sum check,
        # instead of raising a KeyError that says nothing about the count or
        # -- worse -- being folded into a neighbouring bucket.
        counts[state] = counts.get(state, 0) + 1
    not_established = (counts[RAW_NULL] + counts[RAW_ABSENT]
                       + counts[RAW_NO_BLOCK])
    total = counts[RAW_TRUE] + counts[RAW_FALSE] + not_established
    if total != len(rows):
        unaccounted = {state: number for state, number in counts.items()
                       if state not in (RAW_TRUE, RAW_FALSE, *RAW_NOT_ESTABLISHED)}
        raise CensusDoesNotSum(
            f"the tally for {gate!r} adds to {total} over {len(rows)} records; "
            f"a count that does not sum to its own denominator must not be "
            f"published"
            + (f". Unaccounted for: {unaccounted}" if unaccounted else ""))
    return {
        "gate": gate,
        "denominator": len(rows),
        "true": counts[RAW_TRUE],
        "false": counts[RAW_FALSE],
        "not_established_present_but_null": counts[RAW_NULL],
        "not_established_key_absent": counts[RAW_ABSENT],
        "not_established_no_evidence_block": counts[RAW_NO_BLOCK],
        "not_established_total": not_established,
        "sums_to": total,
        "a_missing_key_and_a_null_key_are_both": NOT_ESTABLISHED,
    }
