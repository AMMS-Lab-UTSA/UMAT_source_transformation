"""An envelope is not a verdict.

``ServiceResult.ok`` means the call succeeded. It is true of every entry a
service managed to look at -- INCLUDING every entry it looked at and refused.
Reading it as the answer offered all 237 corpus materials to the Residual
Assembler as verified when 42 are true on all six gates and 55 reached a
verified terminal state. A boolean that is true 237 times out of 237 is not a
filter; it is the absence of one.

The two facts, and why they cannot share a shape
------------------------------------------------
``call_succeeded``
    Did the service run to completion? A plain ``bool``. A verification that
    ran perfectly and found the derivatives wrong has ``call_succeeded=True``.
``verdict``
    What is true of the SUBJECT the call looked at. A :class:`Tri`, which has
    no ``__bool__``, so ``if envelope.verdict:`` is a ``TypeError`` rather
    than an answer.

Different names and different types, deliberately. The names alone would not
be enough: the failure being prevented is a reader reaching for whichever
field looks like success, and two booleans side by side are two things that
look alike. One of them not being usable as a condition at all is what makes
the confusion impossible rather than merely discouraged.

:func:`verdict_of` will not read ``ok`` as a verdict at any cost. A payload
carrying ``ok`` and no verdict is refused by name, because that is precisely
the shape that was misread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .tristate import NOT_ESTABLISHED, Tri

__all__ = ["CallEnvelope", "EnvelopeError", "verdict_of", "SUCCESS_FIELD",
           "VERDICT_FIELD", "FORBIDDEN_AS_A_VERDICT"]

#: What this contract calls the two fields. Never ``ok`` for either: the word
#: is already spoken for by ``ServiceResult`` and means the other thing.
SUCCESS_FIELD = "call_succeeded"
VERDICT_FIELD = "verdict"

#: Field names that must never be read as a verdict about the subject, with
#: what each of them actually means. Refused by name rather than ignored, so
#: that a payload shaped like the one that was misread fails loudly.
FORBIDDEN_AS_A_VERDICT: dict = {
    "ok": "ServiceResult.ok: whether the service RAN. True of every entry a "
          "service managed to look at, including the ones it refuses.",
    "success": "whether the call succeeded, not what it found",
    "passed": "ambiguous between the call and the subject; say which",
    "status": "a service's own word for what happened, not a verdict",
}


class EnvelopeError(ValueError):
    """A result envelope whose success could be mistaken for its verdict."""


@dataclass(frozen=True)
class CallEnvelope:
    """One call, and separately what it found.

    ``verdict`` is three-state on purpose. A call that succeeded and measured
    nothing about its subject gets NOT ESTABLISHED, which is neither a pass
    nor a refusal, and is the honest answer for every entry a pipeline looked
    at without finishing.
    """

    service: str
    call_succeeded: bool
    subject: str = ""
    verdict: Tri = NOT_ESTABLISHED
    #: Why the verdict is what it is, in words a reader can act on.
    verdict_reason: str = ""
    #: The service's own short word for what the CALL did -- never a verdict.
    outcome: str = ""
    problems: tuple = ()
    data: Any = None
    evidence_paths: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.call_succeeded, bool):
            raise EnvelopeError(
                f"{SUCCESS_FIELD} must be a plain bool -- the call either ran "
                f"or it did not, and that question has two answers. Got "
                f"{self.call_succeeded!r}.")
        if not isinstance(self.verdict, Tri):
            raise EnvelopeError(
                f"{VERDICT_FIELD} must be a three-state answer, not "
                f"{type(self.verdict).__name__}. A bool here would be a second "
                f"field that looks exactly like {SUCCESS_FIELD}, and telling "
                f"them apart by name alone is what failed: 237 entries whose "
                f"call succeeded were offered as 237 verified materials.")
        if self.call_succeeded is False and self.verdict.is_measured():
            raise EnvelopeError(
                f"the call did not succeed, so nothing it would have measured "
                f"about {self.subject or 'the subject'} was measured. A "
                f"verdict of {self.verdict.spelling()} beside "
                f"{SUCCESS_FIELD}=False is a claim made by a call that did not "
                f"finish.")

    @property
    def ran(self) -> bool:
        """Alias for readability. Still the CALL, never the subject."""
        return self.call_succeeded

    def as_dict(self) -> dict:
        return {"service": self.service,
                SUCCESS_FIELD: self.call_succeeded,
                "subject": self.subject,
                VERDICT_FIELD: self.verdict.state,
                "verdict_reason": self.verdict_reason,
                "outcome": self.outcome,
                "problems": list(self.problems),
                "evidence_paths": dict(self.evidence_paths)}

    def describe(self) -> str:
        return (f"{self.service}: the call "
                f"{'succeeded' if self.call_succeeded else 'did not run'}; "
                f"the verdict about {self.subject or 'its subject'} is "
                f"{self.verdict.spelling()}"
                + (f" ({self.verdict_reason})" if self.verdict_reason else ""))

    @classmethod
    def from_service_result(cls, payload: Mapping[str, Any], *,
                            verdict: Tri, verdict_reason: str = "",
                            subject: str = "") -> "CallEnvelope":
        """Wrap a ``umat-oti/service-result/1`` payload, verdict supplied apart.

        The verdict is a REQUIRED argument and is never taken from the
        payload. There is nothing in a service result that answers it: ``ok``
        is the call, ``outcome`` is the service's word for what the call did,
        and ``data`` is typed per service. Requiring the caller to pass it is
        what stops one of those being pressed into service as the answer.
        """
        if not isinstance(payload, Mapping):
            raise EnvelopeError(f"a service result must be an object; got "
                                f"{type(payload).__name__}")
        return cls(service=str(payload.get("service") or ""),
                   call_succeeded=bool(payload.get("ok", False)),
                   subject=subject, verdict=verdict,
                   verdict_reason=verdict_reason,
                   outcome=str(payload.get("outcome") or ""),
                   problems=tuple(payload.get("problems") or ()),
                   evidence_paths=dict(payload.get("evidence_paths") or {}))


def verdict_of(payload: Mapping[str, Any]) -> Tri:
    """The verdict a payload states, refusing to accept a call-success for one.

    A payload carrying ``ok`` and nothing named as a verdict is refused by
    name. Falling back to ``ok`` there is the exact misreading this module
    exists to prevent, and silently answering NOT ESTABLISHED instead would
    hide it: the caller asked a question this payload does not answer, and
    they need to be told that rather than handed a shrug.
    """
    if not isinstance(payload, Mapping):
        raise EnvelopeError(f"expected an object; got {type(payload).__name__}")
    if VERDICT_FIELD in payload:
        value = payload[VERDICT_FIELD]
        if value is None or isinstance(value, bool):
            return Tri(value)
        raise EnvelopeError(
            f"{VERDICT_FIELD} must be true, false or null; got {value!r}")
    present = [name for name in FORBIDDEN_AS_A_VERDICT if name in payload]
    if present:
        raise EnvelopeError(
            f"this payload states no {VERDICT_FIELD!r}. It carries "
            f"{', '.join(repr(n) for n in present)}, and none of those is one: "
            + "; ".join(f"{n} is {FORBIDDEN_AS_A_VERDICT[n]}" for n in present)
            + f". Reading one of them as the answer offered 237 corpus "
              f"materials as verified when 42 are true on all six gates. "
              f"Supply the verdict explicitly.")
    raise EnvelopeError(
        f"this payload states no {VERDICT_FIELD!r} and carries nothing that "
        f"could be mistaken for one. Supply the verdict explicitly.")
