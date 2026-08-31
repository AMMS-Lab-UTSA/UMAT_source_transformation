"""Fortran literals are atomic tokens; no rewrite may reach inside one.

A real literal -- ``1.d-12``, ``1.0D-6``, ``3.8e-6``, ``1.5E+8``, ``.5d0``,
``2.D0`` -- is a single token even though its characters look like a digit run,
a name, a sign and another digit run. Every rewrite this package performs on
Fortran source text works on characters, so each one is capable of reading a
literal as those pieces. Two defects came from exactly that:

* a promoted variable named ``D`` matched the ``D`` inside ``1.d-12`` and the
  statement was emitted as ``XTOL_OTI = 1.D_OTI-12`` -- gfortran: "Missing
  exponent in real number";
* the integer-to-double promoter read the exponent digits of ``1.0D-6`` as a
  bare integer factor and emitted ``1.0D-6.0D0`` -- not a number.

Neither is about the name ``D``, and neither is about exponents specifically.
Any variable whose name collides with an exponent letter has the same problem
(``D`` against ``1.D-12``, ``E`` against ``1.E-6``), and so does a multi-letter
name against a literal that happens to spell it (``D0`` against ``2.D0``, ``E2``
against ``1.E2``).

The mechanism is positional, not lexical: replace every complete literal with a
placeholder that contains no letter and no digit, run the rewrite against text
in which the literal simply is not spelled out, then put the literals back byte
for byte. It lives here, in the package every rewrite already imports from,
rather than beside one of them -- the first version of it was private to
``umat_oti.transform.helper_lifting``, which left the main source rewrite to
find out about literals on its own, and it did not.

Use :func:`atomic_real_literals` on a text-in/text-out rewrite,
:func:`rewrite_outside_real_literals` for an inline callable, and
:func:`without_real_literals` when identifiers are only being *scanned* and the
scan drives a rename.
"""
from __future__ import annotations

import functools
import re
from typing import Callable, TypeVar

__all__ = [
    "REAL_LITERAL_RE",
    "CHARACTER_LITERAL_RE",
    "mask_real_literals",
    "unmask_real_literals",
    "mask_character_literals",
    "unmask_character_literals",
    "rewrite_outside_real_literals",
    "atomic_real_literals",
    "without_real_literals",
]

#: A complete Fortran real literal, including any D/E exponent and its sign.
#: The leading lookbehind keeps the digits of an identifier (``X2``) and the
#: tail of a longer literal from starting a match of their own.
REAL_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:(?:\d+\.\d*|\.\d+|\d+)[dDeE][+-]?\d+"   # with an exponent
    r"|(?:\d+\.\d*|\.\d+))"                        # plain real
)

#: Private-use code points: not letters, not digits, not ``_``. ``\w`` does not
#: match them and ``\b`` treats them as separators, so no pattern that looks for
#: an identifier or an integer can see into a masked literal, and none of them
#: can be spliced onto a name adjacent to one either.
_MASK_BASE = 0xE000
_CHARACTER_MASK_BASE = 0xE800


def mask_real_literals(text: str) -> tuple[str, list[str]]:
    """Replace every real literal with an inert placeholder."""
    store: list[str] = []

    def capture(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return chr(_MASK_BASE + len(store) - 1)

    return REAL_LITERAL_RE.sub(capture, text), store


def unmask_real_literals(text: str, store: list[str]) -> str:
    """Restore literals masked by :func:`mask_real_literals`."""
    if not store:
        return text
    return "".join(
        store[ord(char) - _MASK_BASE]
        if _MASK_BASE <= ord(char) < _MASK_BASE + len(store) else char
        for char in text
    )


#: A complete character literal, single- or double-quoted, doubled quotes
#: included. Masking these keeps identifier rewrites out of FORMAT strings and
#: error messages, where a name is text and not a reference.
CHARACTER_LITERAL_RE = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")


def mask_character_literals(text: str) -> tuple[str, list[str]]:
    """Replace every character literal with an inert placeholder."""
    store: list[str] = []

    def capture(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return chr(_CHARACTER_MASK_BASE + len(store) - 1)

    return CHARACTER_LITERAL_RE.sub(capture, text), store


def unmask_character_literals(text: str, store: list[str]) -> str:
    """Restore literals masked by :func:`mask_character_literals`."""
    if not store:
        return text
    return "".join(
        store[ord(char) - _CHARACTER_MASK_BASE]
        if _CHARACTER_MASK_BASE <= ord(char) < _CHARACTER_MASK_BASE + len(store) else char
        for char in text
    )


def rewrite_outside_real_literals(text: str, rewrite: Callable[[str], str]) -> str:
    """Run ``rewrite`` over ``text`` with every real literal masked out.

    The literals come back exactly as they were written -- same digits, same
    exponent letter, same case -- because they are restored from the captured
    text rather than re-emitted.
    """
    masked, literals = mask_real_literals(text)
    return unmask_real_literals(rewrite(masked), literals)


_F = TypeVar("_F", bound=Callable[..., str])


def atomic_real_literals(func: _F) -> _F:
    """Decorator form of :func:`rewrite_outside_real_literals`.

    For a rewrite whose first positional argument is the source text and whose
    return value is the rewritten text.
    """

    @functools.wraps(func)
    def wrapper(text: str, *args, **kwargs) -> str:
        return rewrite_outside_real_literals(text, lambda masked: func(masked, *args, **kwargs))

    return wrapper  # type: ignore[return-value]


def without_real_literals(text: str) -> str:
    """``text`` with the real literals blanked out, for scanning only.

    Identifier scans that decide whether a name is *used* need the same
    atomicity as the rewrites they feed: ``1.E1`` is a number, not a mention of
    a variable named ``E1``, and a rename driven by that mention is as wrong as
    a rename applied to it.
    """
    return mask_real_literals(text)[0]
