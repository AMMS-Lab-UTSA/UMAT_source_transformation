"""Canonical OTI imaginary-direction enumeration.

Single source of truth shared by the OTI module generator (which names the type
members and builds the multiplication tables) and the derivative extraction in
the source transform. The ordering is *nbases-independent* ("graded by largest
basis index, then lexicographic"), which has two properties the rest of the
pipeline relies on:

* ``fulldir(idx, order)`` needs no ``nbases`` argument (matching the upstream
  pyoti ``get_fulldir`` contract that ``fmod_writer.py`` calls).
* The first ``ndir_order(nbases, order)`` directions of a given order are exactly
  the multisets over bases ``1..nbases``. So the writer's
  ``for j in range(ndir_order(nbases, order))`` loop and the flat ``GETIM`` index
  line up with this enumeration.

For order 1 this reduces to ``fulldir(j, 1) == (j + 1,)``, identical to the old
first-order shim, so existing first-order modules are unchanged byte-for-byte.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations_with_replacement
from math import comb, factorial
from typing import Iterator, Sequence

# Must match umat_oti/oti/support/fmod_writer.py `valid_chars` exactly: '0'..'9' then 'A'..'Z'.
# A basis index b (1-indexed) is rendered as VALID_CHARS[b]; member names are
# "E" followed by the rendered bases, e.g. E1, E2 (order 1), E11, E12, E22 (order 2).
# Bases 1..35 use that single-character alphabet (so every module of up to 35
# directions keeps the names upstream gives it); base 36 and above are written
# "_<decimal>_" by :func:`basis_token`, so the alphabet does not bound the
# number of directions.
VALID_CHARS = [chr(i) for i in range(48, 58)] + [chr(i) for i in range(65, 91)]

#: Largest basis index the generator can represent. The pyoti-compatible helper
#: in :mod:`umat_oti.oti.module_generator` hands directions to the vendored
#: writer as ``numpy.uint16`` arrays (the upstream pyoti basis type), so a basis
#: above 65535 cannot be expressed. Far below this, the coefficient count of the
#: generated module is the binding limit; see
#: :data:`umat_oti.oti.module_generator.DEFAULT_MAX_COEFFICIENTS`.
MAX_BASIS_INDEX = 65535

#: Fortran 2008 limit on the length of a name (Clause 3.2.2).
FORTRAN_MAX_NAME_LENGTH = 63


def ndir_order(nbases: int, order: int) -> int:
    """Number of imaginary directions of exactly ``order`` over ``nbases`` bases."""
    if order == 0:
        return 1
    return comb(nbases + order - 1, order)


def ndir_total(nbases: int, order: int) -> int:
    """Total imaginary directions up to ``order`` (including the order-0 real part)."""
    return sum(ndir_order(nbases, k) for k in range(order + 1))


def _gen_dirs(order: int) -> Iterator[tuple[int, ...]]:
    """Yield size-``order`` multisets (sorted, 1-indexed bases) in the canonical
    nbases-independent order: grouped by largest basis index, lexicographic within."""
    if order == 0:
        yield ()
        return
    maxbase = 1
    while True:
        for rest in combinations_with_replacement(range(1, maxbase + 1), order - 1):
            yield tuple(sorted(rest + (maxbase,)))
        maxbase += 1


class _OrderEnumeration:
    """Memoised prefix of :func:`_gen_dirs` for one order, with its inverse.

    :func:`fulldir` and :func:`dir_index` used to restart the enumeration on
    every call, which is linear in the index; the module writer calls them once
    per direction and once per pair of directions in the multiplication table,
    so generation was quadratic-to-cubic in the direction count. The prefix
    here is the same enumeration, extended on demand, so every answer is the
    one the scan would give.
    """

    __slots__ = ("_source", "directions", "index")

    def __init__(self, order: int) -> None:
        self.directions: list[tuple[int, ...]] = []
        self.index: dict[tuple[int, ...], int] = {}
        self._source = _gen_dirs(order)

    def extend_to(self, count: int) -> None:
        while len(self.directions) < count:
            direction = next(self._source)
            self.index[direction] = len(self.directions)
            self.directions.append(direction)


_ENUMERATIONS: dict[int, _OrderEnumeration] = {}


def _enumeration(order: int) -> _OrderEnumeration:
    enumeration = _ENUMERATIONS.get(order)
    if enumeration is None:
        enumeration = _ENUMERATIONS[order] = _OrderEnumeration(order)
    return enumeration


def fulldir(idx: int, order: int) -> tuple[int, ...]:
    """The ``idx``-th (0-based) imaginary direction of the given ``order``."""
    if idx < 0:
        raise IndexError(f"direction index {idx} out of range for order {order}")
    if order == 0:
        if idx == 0:
            return ()
        raise IndexError(f"direction index {idx} out of range for order {order}")
    enumeration = _enumeration(order)
    enumeration.extend_to(idx + 1)
    return enumeration.directions[idx]


def dir_index(multiset: Sequence[int]) -> int:
    """Inverse of :func:`fulldir`: the within-order index of a multiset of bases."""
    target = tuple(sorted(multiset))
    order = len(target)
    if order == 0:
        return 0
    if target[0] < 1:
        raise ValueError(f"multiset {multiset} not found in order-{order} enumeration")
    enumeration = _enumeration(order)
    # Every multiset whose largest basis is at most target[-1] precedes the
    # first one with a larger basis, and there are ndir_order(target[-1], order)
    # of them.
    enumeration.extend_to(ndir_order(target[-1], order))
    try:
        return enumeration.index[target]
    except KeyError:
        raise ValueError(f"multiset {multiset} not found in order-{order} enumeration") from None


def flat_index(nbases: int, order: int, idx: int) -> int:
    """Flat 1-based GETIM index of within-order direction ``idx`` of ``order``.

    GETIM lays members out as: 0 -> real, then all order-1 directions, then all
    order-2 directions, etc., each block sized ``ndir_order(nbases, k)``.
    """
    return sum(ndir_order(nbases, k) for k in range(1, order)) + idx + 1


def member_name(multiset: Sequence[int]) -> str:
    """Fortran member name for a direction, e.g. (1, 2) -> 'E12'."""
    return "E" + "".join(basis_token(base) for base in multiset)


def basis_token(base: int) -> str:
    """Preserve upstream names and delimit larger basis indices uniquely.

    Bases 0..35 are the upstream single characters ('0'-'9', 'A'-'Z'), so a
    module of up to 35 directions is named exactly as upstream names it. Base 36
    and above become ``_<decimal>_``: a character of the alphabet is never an
    underscore and a decimal run is closed by one, so a name such as ``E1_36_``
    reads back to one multiset only, and no larger base can collide with a pair
    of smaller ones (``E36`` is bases 3 and 6; base 36 is ``E_36_``).
    """
    if base < 0:
        raise ValueError(f"basis index must be nonnegative, got {base}")
    return VALID_CHARS[base] if base < len(VALID_CHARS) else f"_{base}_"


def max_member_name_length(nbases: int, order: int) -> int:
    """Length of the longest member name of a module over ``nbases`` up to ``order``.

    The longest name repeats the token of the largest basis ``order`` times.
    """
    if nbases < 1 or order < 1:
        return 1
    return 1 + order * len(basis_token(nbases))


def deriv_factor(multiset: Sequence[int]) -> int:
    """Factor converting a stored OTI imaginary coefficient to the true partial
    derivative: ``derivative = coefficient * prod(multiplicity!)``.

    OTI stores the Taylor coefficient (derivative divided by the multiplicities'
    factorials), so e.g. the e_i^2 member holds ``f_ii / 2`` and the mixed e_i e_j
    member holds ``f_ij`` directly.
    """
    factor = 1
    for multiplicity in Counter(multiset).values():
        factor *= factorial(multiplicity)
    return factor


def imaginary_directions(nbases: int, order: int) -> list[dict]:
    """All imaginary directions for ``(nbases, order)`` as dicts with keys:
    ``order``, ``idx`` (within-order), ``bases`` (1-indexed tuple), ``name``
    (Fortran member), ``flat`` (GETIM index), ``factor`` (derivative factor)."""
    out: list[dict] = []
    for k in range(1, order + 1):
        for idx in range(ndir_order(nbases, k)):
            bases = fulldir(idx, k)
            out.append(
                {
                    "order": k,
                    "idx": idx,
                    "bases": bases,
                    "name": member_name(bases),
                    "flat": flat_index(nbases, k, idx),
                    "factor": deriv_factor(bases),
                }
            )
    return out
