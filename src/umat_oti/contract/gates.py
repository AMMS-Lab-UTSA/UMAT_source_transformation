"""The six evidence gates, and the seventh field that explains a false one.

They are six because each was bought separately.

``abaqus_job_completed``
    Abaqus printed THE ANALYSIS HAS COMPLETED SUCCESSFULLY. That is a
    statement about the solver, not about the routine it called: a job
    completes while its UMAT returns values that are not numbers.
``all_requested_outputs_present``
    Every increment produced every material point it should have. An
    increment short of a point did not produce the state a comparison would
    compare, and a comparison over what is left is a comparison of a
    different experiment.
``complete_history_finite``
    Nothing anywhere in either history is a NaN or an infinity. Distinct from
    the one above and from "no truncation was applied": measured on
    BodyForce-Growth-2Stages.for, where both builds "completed" 35 increments
    and both were non-finite from the third.
``primal_agreed``
    The original build and the converted build produced the same stress and
    state history. This is the RAW comparison and it never moves.
``derivatives_verified``
    The generated derivative was checked against a finite difference and
    agreed. Independent of the primal: a build can reproduce the stress
    exactly and carry a truncated derivative.
``mechanically_informative``
    The experiment the verdict rests on exercised something. A run that
    agreed about a material sitting near its initial state agreed about the
    part every build gets right, and a repair that made a history finite by
    removing the behaviour under test has not verified that behaviour.

And the seventh, which is not a gate but the explanation a false fourth needs::

``primal_difference_explained_by_a_measured_control``
    TRUE where a control ran and explained the disagreement -- the author
    declared a variable at single precision, or the model differs from ITSELF
    by more than the two builds differ when its own arithmetic is reordered.
    FALSE where a control ran and did not explain it. NOT ESTABLISHED where
    no control was needed, which is every entry whose builds agreed, and also
    every entry produced before the field existed.

Reading them
------------
Every one is three-state. :func:`read_gates` returns :class:`Tri`, which has
no ``__bool__``, so ``if gates.primal_agreed:`` is a ``TypeError`` rather than
a null silently passing. There is deliberately **no** single ``passed``
boolean over the seven: a summary field that reduced them to one would delete
the distinctions the six were bought with, and the question "did this verify?"
is answered by the terminal state, which is a separate fact with an owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .tristate import NOT_ESTABLISHED, Tri, all_true, read

__all__ = ["GATES", "SEVENTH", "ALL_FIELDS", "EvidenceGates", "read_gates",
           "GateError"]

#: The six, in the order they are reported. Order is part of the contract:
#: a consumer rendering them as a row must not have to guess it.
GATES: tuple = (
    "abaqus_job_completed",
    "all_requested_outputs_present",
    "complete_history_finite",
    "primal_agreed",
    "derivatives_verified",
    "mechanically_informative",
)

#: The seventh field. Named apart from GATES because it is not a gate: it
#: never makes a verdict better, it says why a false one is still a verdict.
SEVENTH = "primal_difference_explained_by_a_measured_control"

ALL_FIELDS: tuple = GATES + (SEVENTH,)


class GateError(ValueError):
    """An evidence block that would let an unmeasured gate read as a pass."""


@dataclass(frozen=True)
class EvidenceGates:
    """Seven three-state answers about one verification run."""

    abaqus_job_completed: Tri = NOT_ESTABLISHED
    all_requested_outputs_present: Tri = NOT_ESTABLISHED
    complete_history_finite: Tri = NOT_ESTABLISHED
    primal_agreed: Tri = NOT_ESTABLISHED
    derivatives_verified: Tri = NOT_ESTABLISHED
    mechanically_informative: Tri = NOT_ESTABLISHED
    primal_difference_explained_by_a_measured_control: Tri = NOT_ESTABLISHED

    # -- the six -----------------------------------------------------------
    def six(self) -> dict:
        return {name: getattr(self, name) for name in GATES}

    def all_seven(self) -> dict:
        return {name: getattr(self, name) for name in ALL_FIELDS}

    def measured(self) -> tuple:
        return tuple(n for n in GATES if getattr(self, n).is_measured())

    def not_established(self) -> tuple:
        """Which of the six nothing measured. Not the same as which failed."""
        return tuple(n for n in GATES if getattr(self, n).is_not_established())

    def failing(self) -> tuple:
        """Which of the six were measured and did not hold."""
        return tuple(n for n in GATES if getattr(self, n).is_false())

    def conjunction(self) -> Tri:
        """All six as one three-state answer, keeping the third state.

        FALSE if any was measured false. NOT ESTABLISHED if any was never
        measured. TRUE only if all six were measured and all six held. This
        is a *derived view* and not a field in the record: it is offered so a
        consumer does not write its own, and it never replaces the six.
        """
        return all_true(*(getattr(self, n) for n in GATES))

    def primal_settled(self) -> Tri:
        """The primal AFTER the control, which is the chain a verdict rests on.

        :meth:`conjunction` stays RAW on purpose -- the raw comparison never
        moves, and a reader asking "did the two builds produce the same
        numbers?" must get the same answer forever. This answers the different
        question the verdict actually rests on: "is the difference between
        them accounted for?"

        TRUE where the builds agreed, or where they disagreed and a control
        measured the reason. FALSE where they disagreed and a control ran and
        did not. NOT ESTABLISHED where they disagreed and nothing says whether
        a control explained it -- which is not a pass, and is the branch that
        keeps an unexplained disagreement out of a verification claim.
        """
        seventh = self.primal_difference_explained_by_a_measured_control
        if self.primal_agreed.is_true():
            return Tri(True, "the two builds agreed")
        if self.primal_agreed.is_not_established():
            return Tri(None, "nothing compared the two builds")
        if seventh.is_true():
            return Tri(True, seventh.why or "a measured control explained the "
                                            "difference between the builds")
        if seventh.is_false():
            return Tri(False, seventh.why or "a control ran and did not "
                                             "explain the difference")
        return Tri(None, "the two builds disagreed and this record does not "
                         "say whether a measured control explained it; an "
                         "unexplained disagreement is not a verification")

    def settled(self) -> Tri:
        """The six, with the primal taken after its control. Three-state."""
        others = tuple(getattr(self, n) for n in GATES if n != "primal_agreed")
        return all_true(self.primal_settled(), *others)

    # -- the seventh's own rule -------------------------------------------
    def seventh_is_consistent(self) -> tuple:
        """Whether the seventh field is a legal answer beside ``primal_agreed``.

        Returns ``(ok, reason)``. The rule: where the primal AGREED, no
        control was needed, so the seventh must be NOT ESTABLISHED -- a
        ``true`` there would be claiming a control explained a difference
        there was none of. Where the primal DISAGREED the seventh may be any
        of the three: true (a control ran and explained it), false (a control
        ran and did not), not-established (no control ran, or the record
        predates the field).
        """
        seventh = self.primal_difference_explained_by_a_measured_control
        if self.primal_agreed.is_true() and seventh.is_measured():
            return (False,
                    f"{SEVENTH} is {seventh.spelling()} while primal_agreed "
                    f"is true. No control is needed where the two builds "
                    f"agreed, so there is no difference for a control to "
                    f"explain; this field must be null there.")
        return (True, "")

    def as_dict(self) -> dict:
        return {name: getattr(self, name).state for name in ALL_FIELDS}

    def describe(self) -> str:
        parts = [f"{n}={getattr(self, n).spelling()}" for n in ALL_FIELDS]
        return "; ".join(parts)


def read_gates(record: Mapping[str, Any]) -> EvidenceGates:
    """Read the seven out of a store row or a contract record.

    ``mechanically_informative`` exists twice in a store row: as a boolean in
    ``evidence`` and as ``{"informative": ..., "reason": ...}`` at the top
    level. The evidence boolean is the gate; the top-level block carries the
    reason, and it is read only to attach that reason -- never to supply the
    answer, because a block that says ``informative`` while ``evidence`` says
    null would be the top-level block overruling the gate.
    """
    evidence = record.get("evidence")
    if evidence is not None and not isinstance(evidence, Mapping):
        raise GateError(
            f"'evidence' must be an object of the seven gate fields or absent; "
            f"found {type(evidence).__name__}. A non-object here cannot be "
            f"read three-state and would collapse to truthiness.")
    values = {}
    for name in ALL_FIELDS:
        values[name] = read(
            evidence, name,
            why=("no evidence block was written for this entry"
                 if evidence is None else ""))
    if values["primal_agreed"].is_false() and values[SEVENTH].is_not_established():
        values[SEVENTH] = _seventh_from_the_controls(record)
    informative = record.get("mechanically_informative")
    if isinstance(informative, Mapping) and \
            values["mechanically_informative"].is_measured():
        reason = str(informative.get("reason") or "")
        if reason:
            values["mechanically_informative"] = Tri(
                values["mechanically_informative"].state, reason)
    return EvidenceGates(**values)


def _seventh_from_the_controls(record: Mapping[str, Any]) -> Tri:
    """Recover the seventh field from a record written before it existed.

    This is a READ, not an invention. ``tools/verify_store_in_abaqus.py`` now
    writes ``primal_difference_explained_by_a_measured_control`` into the
    evidence block; runs made before it did recorded the same fact in two
    other places, and this reads those rather than leaving the gate blank:

    ``primal.explained_by_declared_precision``
        the precision control reproduced the original once the author's own
        declared precision was honoured.
    ``primal.explained_by_operation_order``
        the model differs from ITSELF by at least as much as the two builds
        differ, when the same source is compiled so that the same mathematics
        is computed in a different order.

    It matters. In the frozen 237-entry store, 13 entries reached
    ``fully_verified`` with ``primal_agreed`` measured FALSE; every one of
    those verdicts rests on a control having explained the difference, and
    without this the contract would carry 13 verified entries whose evidence
    block says a gate failed and says nothing about why.

    Where neither flag is set and a control nevertheless RAN, the answer is
    FALSE -- a control was measured and did not explain it. Where no control
    ran at all the answer stays NOT ESTABLISHED, because nothing measured it.
    Nothing here ever produces TRUE from an absence.
    """
    primal = record.get("primal")
    primal = primal if isinstance(primal, Mapping) else {}
    if primal.get("explained_by_declared_precision") is True:
        return Tri(True, "primal.explained_by_declared_precision: the "
                         "precision control reproduced the original once the "
                         "author's own declared precision was honoured")
    if primal.get("explained_by_operation_order") is True:
        return Tri(True, "primal.explained_by_operation_order: this model "
                         "differs from itself by at least as much when its "
                         "own arithmetic is reordered")
    ran = [name for name in ("precision_control", "association_control")
           if isinstance(record.get(name), Mapping)
           and record[name].get("ran") is True]
    if ran:
        return Tri(False, f"{' and '.join(ran)} ran and did not explain the "
                          f"difference")
    return Tri(None, "no control is recorded for this entry, so whether the "
                     "difference has a measured explanation is not "
                     "established -- it is not absent-and-therefore-none")
