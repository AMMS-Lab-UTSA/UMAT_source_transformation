"""Three answers, not two: true, false, and not-established.

This module is SHARED VERBATIM between UMAT_source_transformation and
Residual_Assembler. It imports nothing but the standard library so that the
consuming repository can carry a byte-identical copy rather than a
reimplementation, and a digest test in each repository fails if the two drift.

Why it exists
-------------
Every gate in this system has three possible answers and only two of them are
a verdict. "The tangent was verified", "the tangent was checked and did not
agree" and "nothing ever measured the tangent" are three different facts, and
the third is the one that gets lost. It gets lost in exactly one way::

    if record["evidence"]["derivatives_verified"]:      # WRONG
        ...

because a missing key raises, and a *null* key -- which is what a pipeline
writes when it did not measure something -- is falsy, so an unmeasured gate
reads identically to a measured failure. That direction of error is the safe
one. The unsafe one is the mirror image::

    if record.get("derivatives_verified") is not False:  # WRONG, and worse
        ...

which reads "not established" as a pass. A schema or a reader that lets a null
read as a pass is the worst defect this system can ship, because the output is
a verification claim about a material nobody verified.

So :class:`Tri` has **no** ``__bool__``. ``if tri:`` is a ``TypeError`` with a
message telling the reader which of the three questions they meant to ask. The
only ways to get a plain bool out are :meth:`Tri.is_true`, :meth:`Tri.is_false`
and :meth:`Tri.is_not_established`, each of which names one of the three.

A missing key and a null key are the SAME answer
------------------------------------------------
:func:`read` takes the mapping and the key rather than the value, so that
``{"gate": None}`` and ``{}`` both produce :data:`NOT_ESTABLISHED`. A reader
that pulled the value out first would have already collapsed the distinction
before it got here.
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["Tri", "TRUE", "FALSE", "NOT_ESTABLISHED", "read", "read_path",
           "TristateError", "all_true", "as_json"]

#: How the three states are spelled when a contract record is serialised.
#: ``null`` is the wire form of NOT_ESTABLISHED; so is the key being absent.
TRUE_JSON = True
FALSE_JSON = False
NOT_ESTABLISHED_JSON = None


class TristateError(TypeError):
    """A three-state answer was used as if it were a two-state one."""


class Tri:
    """One of exactly three answers. Deliberately not truthy."""

    __slots__ = ("_state", "_why")

    _SPELLINGS = {True: "true", False: "false", None: "not-established"}

    def __init__(self, state: Any, why: str = "") -> None:
        if state not in (True, False, None) or isinstance(state, int) \
                and not isinstance(state, bool):
            raise TristateError(
                f"a three-state answer is True, False or None; got "
                f"{state!r} ({type(state).__name__}). Numbers and strings are "
                f"refused here on purpose: '0', 'false' and 'no' are all "
                f"truthy strings in Python and each one has silently passed a "
                f"gate somewhere.")
        self._state = state
        self._why = str(why or "")

    # -- construction ------------------------------------------------------
    @classmethod
    def of(cls, value: Any, why: str = "") -> "Tri":
        """Wrap a raw JSON value. ``None`` is NOT ESTABLISHED, never a pass."""
        return cls(value, why)

    # -- the three questions, each asked by name ---------------------------
    def is_true(self) -> bool:
        """This was measured and it held."""
        return self._state is True

    def is_false(self) -> bool:
        """This was measured and it did not hold."""
        return self._state is False

    def is_not_established(self) -> bool:
        """Nothing measured this. It is not a pass and it is not a failure."""
        return self._state is None

    def is_measured(self) -> bool:
        """Something measured this, whichever way it came out."""
        return self._state is not None

    # -- accessors ---------------------------------------------------------
    @property
    def state(self) -> Any:
        """The raw ``True`` / ``False`` / ``None``, for serialising only."""
        return self._state

    @property
    def why(self) -> str:
        return self._why

    def spelling(self) -> str:
        return self._SPELLINGS[self._state]

    # -- the guard ---------------------------------------------------------
    def __bool__(self) -> bool:
        raise TristateError(
            f"a three-state answer ({self.spelling()}) was used where Python "
            f"wanted a yes-or-no. That is how 'nobody measured this' becomes "
            f"'this passed'. Ask the question you mean: .is_true() for 'it "
            f"was measured and held', .is_false() for 'it was measured and "
            f"did not hold', .is_not_established() for 'nothing measured "
            f"it'.")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Tri):
            return self._state is other._state
        return NotImplemented

    def __hash__(self) -> int:
        return hash((Tri, self._state))

    def __repr__(self) -> str:
        why = f", why={self._why!r}" if self._why else ""
        return f"Tri({self.spelling()}{why})"


TRUE = Tri(True)
FALSE = Tri(False)
NOT_ESTABLISHED = Tri(None)


def read(mapping: Any, key: str, why: str = "") -> Tri:
    """Read one three-state field out of a mapping.

    Takes the mapping and the key, not the value, precisely so that an absent
    key and a null value produce the same answer. A non-mapping (including
    ``None``, which is what a whole absent block looks like) is NOT
    ESTABLISHED rather than an error: "the block this gate lives in was never
    written" is a perfectly good instance of nothing having measured it.
    """
    if not isinstance(mapping, Mapping):
        return Tri(None, why or f"no block to read {key!r} from")
    if key not in mapping:
        return Tri(None, why or f"{key!r} is absent")
    value = mapping[key]
    if value is None:
        return Tri(None, why or f"{key!r} is null")
    if not isinstance(value, bool):
        raise TristateError(
            f"{key!r} must be true, false or null in a contract record; found "
            f"{value!r} ({type(value).__name__}). A non-boolean here is how a "
            f"gate acquires a truthy string.")
    return Tri(value, why)


def read_path(root: Any, *keys: str, why: str = "") -> Tri:
    """:func:`read` through a chain of blocks, any of which may be missing."""
    if not keys:
        raise TristateError("read_path needs at least one key")
    node: Any = root
    for key in keys[:-1]:
        if not isinstance(node, Mapping):
            return Tri(None, why or f"{'.'.join(keys)} has no block {key!r}")
        node = node.get(key)
    return read(node, keys[-1], why)


def all_true(*tris: Tri) -> Tri:
    """Conjunction that keeps the third state.

    Any FALSE makes the answer FALSE -- a measured failure is a failure
    whatever else is unknown. Otherwise any NOT ESTABLISHED makes the answer
    NOT ESTABLISHED, because a conjunction containing an unmeasured term has
    not been established either. Only all-true is TRUE.
    """
    if any(t.is_false() for t in tris):
        return FALSE
    if any(t.is_not_established() for t in tris):
        return NOT_ESTABLISHED
    return TRUE


def as_json(tri: Tri) -> Any:
    """The wire form: ``true`` / ``false`` / ``null``."""
    return tri.state
