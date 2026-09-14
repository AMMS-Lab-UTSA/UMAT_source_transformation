"""Bringing ``services.contract_adapter``'s output under the shared contract.

:mod:`umat_oti.services.contract_adapter` turns a ``resasm_umat_transform_v2``
document into this project's canonical derivative-request contract. It predates
the shared data contract and answers a different question -- *what derivative
should be generated* rather than *what is true about this UMAT* -- so the two
are related by a bridge rather than merged.

Why the bridge lives here and not in the adapter
------------------------------------------------
``contract_adapter.py`` sits in ``umat_oti.services``, which is transform code:
``umat_oti.pipeline`` reaches ``services.transformation``, and the store's
fingerprint covers the whole subpackage. :mod:`umat_oti.contract` is exempt from
that fingerprint -- it describes what a finished transform is published AS,
never how one is produced.

So an import from the adapter INTO the contract is sound, and the reverse is
not: it would let an edit to the contract change transform-side code while
every stored transform still reported itself current. Editing the adapter at
all has a price that is easy to miss and expensive to pay -- measured here, a
single added constant moved the transform fingerprint from
``b0d27ee53c630500`` to ``26e9d52e60de7e6a``, which would have marked all 237
entries in the frozen store stale and made every fixture-fingerprint
comparison in this contract compare two stale things. The adapter's bytes are
therefore left exactly as they are, and everything the shared contract needs
from it is added on this side of the boundary.

What the bridge adds
--------------------
The one field the adapter's document lacks: which shared contract version a
consumer must speak to read it. Stamped rather than assumed, because a
document with no version forces its reader to guess that the fields mean what
the reader's own version says they mean -- and that guess is how a renamed key
becomes a wrong number three layers away instead of an error at the boundary.
"""
from __future__ import annotations

from typing import Any

from umat_oti.services.contract_adapter import (CANONICAL_SCHEMA_VERSION,
                                                AdaptedContract,
                                                ContractAdaptationError,
                                                adapt_v2_contract)

from .record import Kinematics
from .version import (CONTRACT_VERSION, ContractVersionError,
                      contract_version_of, require_compatible)

__all__ = ["adapt_v2_contract_versioned", "stamp_contract_version",
           "CANONICAL_SCHEMA_VERSION", "ContractAdaptationError",
           "require_adapter_contract_compatible", "FINITE_STRAIN_WORDS"]

#: The adapter's set of kinematics values that need a deformation-gradient
#: seed. Read from the adapter rather than re-spelled, so the contract's word
#: for finite strain and the adapter's set cannot drift into disagreeing about
#: which regime seeds what.
from umat_oti.services.contract_adapter import FINITE_STRAIN as FINITE_STRAIN_WORDS  # noqa: E402


def stamp_contract_version(document: dict) -> dict:
    """Add ``contract_version`` to an adapter document, without overwriting one.

    Refuses to overwrite a version already present: a document that declares
    one was written by something that knew which contract it spoke, and
    silently restamping it would erase a mismatch instead of reporting it.
    """
    if not isinstance(document, dict):
        raise ContractVersionError(
            f"cannot stamp a {type(document).__name__}; a contract document "
            f"is an object")
    declared = document.get("contract_version")
    if declared is not None and str(declared) != CONTRACT_VERSION:
        raise ContractVersionError(
            f"this document already declares contract version {declared!r} "
            f"and this repository speaks {CONTRACT_VERSION!r}. Restamping it "
            f"would erase the mismatch rather than report it.")
    stamped = dict(document)
    stamped["contract_version"] = CONTRACT_VERSION
    return stamped


def adapt_v2_contract_versioned(v2: dict, *, model: str,
                                source_path: str) -> AdaptedContract:
    """:func:`adapt_v2_contract`, with the shared contract version stamped on.

    Everything else the adapter decides -- the seed, the requests, the
    unmapped keys, the notes -- is left exactly as it decided it. This adds
    the version and nothing else.
    """
    adapted = adapt_v2_contract(v2, model=model, source_path=source_path)
    return AdaptedContract(contract=stamp_contract_version(adapted.contract),
                           unmapped=adapted.unmapped, notes=adapted.notes)


def require_adapter_contract_compatible(document: Any, *, speaker: str) -> str:
    """Refuse an adapter document written against an incompatible contract."""
    return require_compatible(contract_version_of(document), speaker=speaker)


def kinematics_agree() -> bool:
    """Whether the adapter and the contract mean the same thing by finite strain.

    Held by ``tests/test_contract_version.py``. The adapter cannot import the
    contract (see the module docstring), so the two carry the word separately
    and this is what stops them drifting.
    """
    return (Kinematics.FINITE in FINITE_STRAIN_WORDS
            and Kinematics.SMALL not in FINITE_STRAIN_WORDS)
