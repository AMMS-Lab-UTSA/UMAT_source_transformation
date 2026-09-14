"""Loading, validating against, and locking the shared JSON schemas.

The schema documents in ``schemas/`` are the NORMATIVE form of the contract.
They are carried byte-for-byte in both repositories -- UMAT_source_transformation
under ``src/umat_oti/contract/schemas/`` and Residual_Assembler under
``schemas/`` -- because a schema that exists only on the producing side is a
description of the producer, not an agreement between two parties.

Two things guard them, and they guard different failures.

``contract_lock.json``
    A SHA-256 of every shared file, recorded beside them. It catches a schema
    edited without the contract version being bumped, *within* one repository.
    Regenerate it in the same commit as the edit -- :func:`write_lock`.

The version handshake (:mod:`.version`)
    Catches the two repositories being at different versions of the contract.
    The lock cannot do this: each repository can only check its own copy.

Neither is a substitute for the other, and a change that alters behaviour
needs the version bumped even when the schema text is untouched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .version import CONTRACT_VERSION, ContractVersionError

__all__ = ["SCHEMA_DIR", "SCHEMA_FILES", "SHARED_FILES", "LOCK_NAME",
           "GENERATION_FILE", "current_transform_generation",
           "load_schema", "validate", "SchemaViolation", "digest_of",
           "compute_lock", "read_lock", "write_lock", "verify_lock",
           "LockMismatch"]

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

#: The schema documents, by the short name a caller asks for.
SCHEMA_FILES: dict = {
    "umat_contract": "umat_contract_v1.schema.json",
    "residual_fixture": "residual_fixture_v1.schema.json",
    "contract_error": "contract_error_v1.schema.json",
}

#: Not a schema: the one place the current transform fingerprint is written
#: down, read by both repositories so that neither hard-codes it separately.
GENERATION_FILE = "transform_generation.json"

LOCK_NAME = "contract_lock.json"

#: Files that must be byte-identical in both repositories.
#:
#: ``tristate.py`` is in the list because the three-state reader is part of
#: the contract, not an implementation detail of one side: a reimplementation
#: of it on the other side is exactly where "null reads as a pass" comes back.
#:
#: ``frames.py`` is in it for the same reason and a sharper one. The five
#: fields that name a row and the arithmetic between records and increments
#: are the contract; two implementations of them are two contracts, and the
#: last time the two ends disagreed about which count was which, a complete
#: 280-record history was refused as "35 of the 280 asked for". Both modules
#: import nothing but the standard library so that the consuming repository
#: can carry them verbatim.
SHARED_FILES: tuple = tuple(SCHEMA_FILES.values()) + (
    GENERATION_FILE, "tristate.py", "frames.py")


class SchemaViolation(ValueError):
    """A document that does not conform to the schema for its version."""


class LockMismatch(RuntimeError):
    """A shared contract file changed without the lock being regenerated."""


def _shared_path(name: str) -> Path:
    """Where a shared file lives in THIS repository.

    The shared documents sit in ``schemas/`` beside the package; the Python
    reader sits in the package itself. The lock names them by basename so that
    the consuming repository, whose layout is its own, can find each one
    wherever it keeps it.
    """
    if name.endswith(".json"):
        return SCHEMA_DIR / name
    return Path(__file__).resolve().parent / name


def current_transform_generation() -> dict:
    """The transform fingerprint this contract's evidence belongs to.

    One place, read by both repositories. A constant hard-coded on each side
    is two constants, and the day they drift the consumer accepts a fixture
    the producer would have refused.
    """
    path = SCHEMA_DIR / GENERATION_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("x-contract-version") != CONTRACT_VERSION:
        raise ContractVersionError(
            f"{path.name} declares contract version "
            f"{document.get('x-contract-version')!r}; this repository speaks "
            f"{CONTRACT_VERSION!r}.")
    fingerprint = str(document.get("transform_fingerprint") or "")
    if not fingerprint:
        raise SchemaViolation(
            f"{path.name} records no transform_fingerprint, so nothing can "
            f"say which fixtures are current. An empty value here would make "
            f"every fingerprint comparison NOT ESTABLISHED and quietly stop "
            f"the check from checking anything.")
    return document


def load_schema(name: str) -> dict:
    """Load one schema document by short name or filename."""
    filename = SCHEMA_FILES.get(name, name)
    path = SCHEMA_DIR / filename
    if not path.is_file():
        raise SchemaViolation(
            f"no schema {name!r}; this contract defines "
            f"{', '.join(sorted(SCHEMA_FILES))}")
    document = json.loads(path.read_text(encoding="utf-8"))
    declared = document.get("x-contract-version")
    if declared != CONTRACT_VERSION:
        raise ContractVersionError(
            f"{path.name} declares contract version {declared!r} but this "
            f"repository speaks {CONTRACT_VERSION!r}. The schema and the code "
            f"that reads it must agree, or a record validated here means "
            f"something else to the consumer that reads it there.")
    return document


def validate(document: Any, schema_name: str, *, where: str = "") -> None:
    """Validate a document, raising :class:`SchemaViolation` with a readable path.

    The default ``jsonschema`` message is one line of context-free text. What
    a reader needs is *which field*, *what it found* and *why the rule is
    there*, so the message is rebuilt from the failure's JSON pointer and the
    schema's own description.
    """
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - environment
        raise SchemaViolation(
            "jsonschema is not installed, so contract documents cannot be "
            "validated. Refusing to report an unvalidated document as valid."
        ) from exc
    schema = load_schema(schema_name)
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if not errors:
        return
    prefix = f"{where}: " if where else ""
    lines = []
    for error in errors[:8]:
        pointer = "/".join(str(p) for p in error.absolute_path) or "(root)"
        why = ""
        if isinstance(error.schema, Mapping):
            why = str(error.schema.get("description") or "")
        lines.append(f"  at {pointer}: {error.message}"
                     + (f"\n      why this rule exists: {why}" if why else ""))
    more = f"\n  ... and {len(errors) - 8} more" if len(errors) > 8 else ""
    raise SchemaViolation(
        f"{prefix}{len(errors)} violation(s) of {schema_name} "
        f"(contract {CONTRACT_VERSION}):\n" + "\n".join(lines) + more)


# ---------------------------------------------------------------------------
# the lock
# ---------------------------------------------------------------------------
def digest_of(path: Any) -> str:
    """SHA-256 of a file's bytes, with newlines normalised.

    Normalised because the two repositories are checked out separately and a
    line-ending difference is not a contract change -- but a byte inside a
    line is.
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def compute_lock(root: Optional[Any] = None,
                 names: Iterable[str] = SHARED_FILES) -> dict:
    """The lock this repository's copies of the shared files would produce."""
    files = {}
    for name in sorted(names):
        path = _shared_path(name) if root is None else Path(root) / name
        if not path.is_file():
            raise LockMismatch(
                f"shared contract file {name!r} is missing from "
                f"{path.parent}. Both repositories carry every shared file; a "
                f"missing one means one side is reading a schema the other "
                f"does not have.")
        files[name] = digest_of(path)
    combined = hashlib.sha256()
    for name in sorted(files):
        combined.update(name.encode("utf-8"))
        combined.update(b"\0")
        combined.update(files[name].encode("ascii"))
    return {"contract_version": CONTRACT_VERSION, "files": files,
            "combined": combined.hexdigest()}


def read_lock(root: Optional[Any] = None) -> dict:
    path = (SCHEMA_DIR.parent / LOCK_NAME) if root is None \
        else Path(root) / LOCK_NAME
    if not path.is_file():
        raise LockMismatch(
            f"{path} is missing. The lock is what catches a shared contract "
            f"file edited without the version being bumped; without it that "
            f"change is invisible until a consumer reads a record wrongly.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_lock(root: Optional[Any] = None) -> dict:
    """Regenerate the lock. Run this in the same commit as a schema edit."""
    lock = compute_lock(root)
    path = (SCHEMA_DIR.parent / LOCK_NAME) if root is None \
        else Path(root) / LOCK_NAME
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return lock


def verify_lock(root: Optional[Any] = None) -> None:
    """Refuse a shared file that changed without the lock being regenerated."""
    recorded = read_lock(root)
    actual = compute_lock(root)
    if recorded.get("contract_version") != actual["contract_version"]:
        raise LockMismatch(
            f"the lock records contract version "
            f"{recorded.get('contract_version')!r} and this repository speaks "
            f"{actual['contract_version']!r}. Regenerate the lock in the same "
            f"commit as the version bump.")
    changed = [name for name in actual["files"]
               if recorded.get("files", {}).get(name) != actual["files"][name]]
    gone = [name for name in recorded.get("files", {})
            if name not in actual["files"]]
    if changed or gone:
        raise LockMismatch(
            f"shared contract file(s) changed without the lock being "
            f"regenerated: {', '.join(sorted(changed + gone))}. Either this "
            f"is a contract change -- in which case bump the version in "
            f"umat_oti/contract/version.py and in every schema's "
            f"'x-contract-version', regenerate the lock, and tell the other "
            f"repository -- or it is an accident. Both repositories carry "
            f"these files byte-for-byte, and an edit on one side that the "
            f"other never sees is how the two ends stop meaning the same "
            f"thing by the same key.")
