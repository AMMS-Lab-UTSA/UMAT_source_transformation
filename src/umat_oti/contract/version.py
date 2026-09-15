"""What version of the shared data contract this repository speaks.

Two repositories exchange records here: UMAT_source_transformation produces
them and Residual_Assembler consumes them. Until now the exchange was a set of
JSON keys each side read out of the other's files, which meant a key renamed on
one side surfaced on the other as a ``KeyError`` three frames deep, or -- worse
-- as a ``.get()`` returning ``None`` and a wrong number carried forward.

So the exchange is versioned, and both sides say which version they speak.

Semantics of the three numbers
------------------------------
``MAJOR``
    A **breaking change**: any change that could make a reader that speaks the
    previous version read a record wrongly rather than fail on it. Removing a
    field, renaming one, narrowing a type, changing the meaning of a value,
    adding a new required field, adding a member to an enumeration a consumer
    switches on exhaustively, or changing which of the seven evidence gates
    exist. A MAJOR bump is a refusal: a consumer at 1.x must not attempt to
    read a 2.x record, because the failure mode of trying is a wrong number
    and not an exception.
``MINOR``
    A field added that an older reader may ignore without being misled, or an
    error code added to a namespace that is documented as open. A consumer at
    1.1 reads a 1.2 record; a consumer at 1.2 reading a 1.1 record must treat
    every 1.2-only field as NOT ESTABLISHED, never as absent-means-false.
``PATCH``
    Documentation, wording of a message, a tightened validation that refuses
    records the previous version should already have refused.

What is deliberately NOT a breaking change: the *contents* of a corpus run.
Records at the same contract version may disagree about a material; that is
data, not schema.
"""
from __future__ import annotations

from typing import NamedTuple

#: The version this repository speaks. Bump per the rules in the module
#: docstring, and regenerate ``schemas/contract_lock.json`` in the same commit.
#:
#: 2.0.0, and MAJOR because this contract's own rule says so rather than
#: because anything was deleted. Four changes, every one of which an older
#: reader could MISREAD rather than fail on:
#:
#: * ``terminalState.state`` gained ``arguments_diverged_before_the_routine``
#:   (EXTERNAL) and ``disagreement_not_in_any_recorded_call`` (INTERNAL). A
#:   consumer switching on the enum exhaustively would fall through on both,
#:   and the fall-through was ``not_attempted`` -- INTERNAL, "the run never
#:   happened" -- for three entries that ran and whose arguments diverged,
#:   which is an external fact about somebody's file.
#: * A history row is named by five fields, not two. ``element``, ``point``
#:   and ``step`` became required.
#: * A fixture carries five counts, and ``records_carried`` /
#:   ``increments_carried`` / ``material_points_per_increment`` became
#:   required. A 1.0.0 reader took one count and would read a 280-record
#:   history as 280 increments.
#: * The result envelope separates ``call_succeeded`` from ``verdict``.
#: 3.0.0, MAJOR, for two changes an older reader would MISREAD rather than
#: fail on:
#:
#: * ``terminalState.state`` gained ``primal_mismatch_explained`` (INTERNAL).
#:   A primal comparison that failed and that a measured control accounts for
#:   used to travel as ``fully_verified`` with the primal gate rewritten to
#:   true; thirteen entries crossed the boundary that way. A 2.x reader has no
#:   word for the state and would fall through.
#: * ``arguments_diverged_before_the_routine`` changed owner, EXTERNAL to
#:   INTERNAL, and its error code moved from ``external.`` to ``internal.``.
#:   The arguments that parted were computed by the solver from each build's
#:   own earlier outputs on this project's deck; a 2.x reader would book three
#:   of this project's primal disagreements against somebody else's file.
CONTRACT_VERSION = "3.0.0"

#: The name this repository answers to in a handshake message.
SPEAKER = "UMAT_source_transformation"


class ContractVersionError(RuntimeError):
    """The two ends of the contract do not speak compatible versions.

    Raised instead of letting the mismatch surface downstream as a missing key
    or a silently-absent field. The message names both versions, both
    speakers, and what specifically is incompatible.
    """


class Version(NamedTuple):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.major}.{self.minor}.{self.patch}"


def parse(text: object) -> Version:
    """Parse ``MAJOR.MINOR.PATCH``; refuse anything else by name.

    A version is not optional and not inferable. ``None``, ``""`` and a
    two-part ``"1.0"`` are all refused rather than padded, because a record
    that does not say which contract it was written against is a record whose
    fields cannot be trusted to mean what this reader thinks they mean.
    """
    if text is None:
        raise ContractVersionError(
            "this record declares no contract version. A record with no "
            "version cannot be read safely: the reader would be guessing "
            f"that its fields mean what {CONTRACT_VERSION} says they mean. "
            f"Producers must write 'contract_version': '{CONTRACT_VERSION}'.")
    parts = str(text).split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ContractVersionError(
            f"{text!r} is not a contract version. Expected three integers "
            f"'MAJOR.MINOR.PATCH', for example {CONTRACT_VERSION!r}.")
    return Version(*(int(p) for p in parts))


def require_compatible(theirs: object, *, speaker: str,
                       ours: str = CONTRACT_VERSION) -> str:
    """Refuse, loudly and in one place, a version this reader cannot read.

    Returns a note describing what the reader must treat as NOT ESTABLISHED
    when the far end is older than this one -- the empty string when the two
    are the same version.
    """
    mine = parse(ours)
    yours = parse(theirs)
    if yours.major != mine.major:
        raise ContractVersionError(
            f"contract version mismatch: {speaker} speaks {yours}, this "
            f"repository ({SPEAKER}) speaks {mine}. A major-version "
            f"difference is a BREAKING change -- fields have been removed, "
            f"renamed, retyped or given a new meaning -- so reading this "
            f"record would not fail, it would produce wrong numbers. "
            f"Refusing. Upgrade whichever end is behind, or pin both to "
            f"the same major version.")
    if yours.minor > mine.minor:
        raise ContractVersionError(
            f"contract version mismatch: {speaker} speaks {yours}, newer "
            f"than this repository's {mine}. The record may carry required "
            f"structure this reader has never heard of, and this reader "
            f"cannot tell 'a field I do not know about' from 'a field that "
            f"is absent'. Refusing rather than reading it partially. "
            f"Upgrade {SPEAKER} to at least {yours.major}.{yours.minor}.")
    if yours.minor < mine.minor:
        return (
            f"{speaker} speaks {yours}, older than this repository's {mine}. "
            f"Every field added between {yours.major}.{yours.minor} and "
            f"{mine.major}.{mine.minor} is NOT ESTABLISHED in this record -- "
            f"it is not absent-and-therefore-false.")
    return ""


def handshake() -> dict:
    """What this repository publishes about the contract it speaks."""
    return {"speaker": SPEAKER, "contract_version": CONTRACT_VERSION}


def contract_version_of(document: object) -> str:
    """The contract version a document declares, or refuse to guess one."""
    if not isinstance(document, dict):
        raise ContractVersionError(
            f"a contract document must be an object; got "
            f"{type(document).__name__}, which declares no version at all")
    declared = document.get("contract_version")
    if declared is None:
        raise ContractVersionError(
            f"this document declares no 'contract_version'. It may predate "
            f"the shared contract, in which case the fields it does carry "
            f"cannot be assumed to mean what {CONTRACT_VERSION} says they "
            f"mean. Refusing to read it as though they do.")
    return str(parse(declared))
