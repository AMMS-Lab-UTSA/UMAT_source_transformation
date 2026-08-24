"""Stage outcome vocabulary for the UMAT-OTI pipeline.

The point of having five outcomes rather than a boolean is that "it did not
produce a result" has several distinct causes, and collapsing them destroys the
information a reader needs most:

``succeeded``
    The stage ran and produced its declared outputs.
``failed``
    The stage ran and could not produce them. Something is wrong here.
``not_requested``
    The contract never asked for this. Nothing is wrong; there is simply no
    result, and there must never be a fabricated one.
``unsupported``
    The contract asked, but this input is outside what the pipeline can handle
    (an unparsed Fortran construct, a formulation with no seed strategy). The
    limitation is ours and is named.
``blocked_by_external_dependency``
    The contract asked and the pipeline can do it, but something outside the
    repository is missing -- Abaqus, a licence, a compiler, a network. Nothing
    about the science is settled either way.

A stage that is not ``succeeded`` must carry a reason. That is enforced in
:class:`~umat_oti.pipeline.manifest.StageRecord`, not left to discipline.

The cardinal rule of this module: **a missing value is never zero and never a
pass.** :func:`require` exists so that reaching for absent data raises instead
of silently defaulting.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, TypeVar

T = TypeVar("T")


class StageStatus(str, Enum):
    """Why a stage did or did not produce a result."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_REQUESTED = "not_requested"
    UNSUPPORTED = "unsupported"
    BLOCKED_BY_EXTERNAL_DEPENDENCY = "blocked_by_external_dependency"

    @property
    def produced_outputs(self) -> bool:
        return self is StageStatus.SUCCEEDED

    @property
    def is_problem(self) -> bool:
        """Did something go wrong, as opposed to nothing being asked for?"""
        return self in (StageStatus.FAILED, StageStatus.UNSUPPORTED)

    @property
    def requires_reason(self) -> bool:
        return self is not StageStatus.SUCCEEDED


#: Statuses that let dependent stages run.
RUNNABLE_DOWNSTREAM = frozenset({StageStatus.SUCCEEDED})


class MissingData(KeyError):
    """Raised instead of defaulting when required data is absent.

    Defaulting a missing measurement to zero is how an unrun stage becomes a
    published number. This exception is the alternative.
    """


def require(mapping: Mapping[str, Any], key: str, *, context: str) -> Any:
    """Fetch ``key`` or raise. Never returns a default.

    >>> require({"a": 1}, "a", context="demo")
    1
    >>> require({}, "a", context="demo")
    Traceback (most recent call last):
    umat_oti.pipeline.status.MissingData: ...
    """
    if key not in mapping:
        raise MissingData(
            f"{context}: required value {key!r} is absent. It has no default: a "
            f"missing measurement must stay missing rather than become zero."
        )
    value = mapping[key]
    if value is None:
        raise MissingData(
            f"{context}: required value {key!r} is None. Record it as null with a "
            f"reason, or produce it -- do not substitute a number."
        )
    return value


def unavailable(reason: str) -> dict[str, Any]:
    """A null-with-a-reason placeholder for a value that could not be measured.

    Use this wherever a schema wants a number that does not exist. It keeps the
    field present and machine-readable while making the absence explicit.
    """
    return {"value": None, "unavailable_reason": reason}
