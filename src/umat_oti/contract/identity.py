"""What identifies a UMAT source, and what does not.

A basename does not. In the frozen corpus of 237 store entries, 23 basenames
are shared by more than one source file and they account for 108 of the 237
entries -- ``BodyForce-Growth-2Stages.for`` alone names 26 different files in
26 different places. A consumer keyed on ``Path(source).name`` would silently
collapse 26 distinct materials, each with its own properties and its own
verdict, into whichever one it read last.

Identity here is therefore two things together:

``path``
    The path of the source **within the corpus cache**, repository segment
    first: ``BristolCompositesInstitute__abaci/test/data/umat.f``. It has at
    least one separator, because a bare name is the failure this module
    exists to refuse. All 237 store entries have a unique path.
``sha256``
    The SHA-256 of the source file's bytes. Eight of the 237 entries share a
    digest with another entry -- the same file published twice at two paths --
    so the digest alone is not an identity either. It is what says *this is
    still the file the verdict was reached about*.

Together they are unique across the corpus and stable across re-runs, and
either one alone is not.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

#: A SHA-256 as this contract writes it: 64 lowercase hex characters.
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IdentityError(ValueError):
    """A source identity that cannot distinguish one source from another."""


@dataclass(frozen=True)
class UmatIdentity:
    """The identity of one UMAT source inside the corpus cache."""

    path: str
    sha256: str
    repository: str = ""
    #: The store's own opaque key for the entry, where one exists. Carried
    #: because it is what the producing pipeline files things under; never
    #: used as the identity, because it is opaque and not reproducible from
    #: the source.
    store_key: str = ""

    # -- construction ------------------------------------------------------
    @classmethod
    def of(cls, path: Any, sha256: Any, *, repository: Any = "",
           store_key: Any = "") -> "UmatIdentity":
        text = "" if path is None else str(path)
        if not text.strip():
            raise IdentityError(
                "a UMAT identity needs the path of the source within the "
                "corpus cache; got nothing. A record with no path cannot be "
                "matched to a source, and matching it by anything else means "
                "matching it by basename.")
        normalised = text.replace("\\", "/").strip()
        if normalised.startswith("/"):
            raise IdentityError(
                f"{text!r} is an absolute path. Identity is the path WITHIN "
                f"the corpus cache, so that a record produced on one machine "
                f"identifies the same source on another. Strip the cache root.")
        if posixpath.dirname(normalised) == "":
            raise IdentityError(
                f"{text!r} is a bare basename, which is not an identity. "
                f"23 basenames in the frozen corpus name more than one source "
                f"file -- 'BodyForce-Growth-2Stages.for' names 26 -- so a "
                f"consumer keyed on a basename silently merges materials that "
                f"have different properties and different verdicts. Use the "
                f"path within the cache, repository segment first, for "
                f"example 'BristolCompositesInstitute__abaci/test/data/umat.f'.")
        digest = ("" if sha256 is None else str(sha256)).strip().lower()
        if not SHA256.match(digest):
            raise IdentityError(
                f"{sha256!r} is not a SHA-256 of the source. A path without a "
                f"digest says which file was meant, not which bytes were "
                f"verified -- and the verdict is about the bytes. Expected 64 "
                f"lowercase hex characters.")
        return cls(path=normalised, sha256=digest,
                   repository=str(repository or ""),
                   store_key=str(store_key or ""))

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "UmatIdentity":
        """Identity out of a store-verification row or a contract record."""
        block = record.get("identity")
        if isinstance(block, Mapping):
            return cls.of(block.get("path"), block.get("sha256"),
                          repository=block.get("repository", ""),
                          store_key=block.get("store_key", ""))
        return cls.of(record.get("source"), record.get("source_sha256"),
                      repository=record.get("repository", ""),
                      store_key=record.get("key", ""))

    # -- use ---------------------------------------------------------------
    @property
    def basename(self) -> str:
        """Available for display. Never for matching -- see the module docstring."""
        return posixpath.basename(self.path)

    @property
    def cache_repository(self) -> str:
        """The cache's own first segment, which is not always ``repository``.

        The cache spells a repository ``Owner__name``; the record's
        ``repository`` field spells it ``Owner/name``. They are two renderings
        of one fact and a consumer that compares them directly gets a
        mismatch on every entry.
        """
        return self.path.split("/", 1)[0]

    def same_source_as(self, other: "UmatIdentity") -> bool:
        return self.path == other.path and self.sha256 == other.sha256

    def matches(self, path: Any, sha256: Any) -> bool:
        try:
            return self.same_source_as(UmatIdentity.of(path, sha256))
        except IdentityError:
            return False

    def as_dict(self) -> dict:
        out = {"path": self.path, "sha256": self.sha256}
        if self.repository:
            out["repository"] = self.repository
        if self.store_key:
            out["store_key"] = self.store_key
        return out

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.path}@{self.sha256[:12]}"


def refuse_basename_keying(paths: Any) -> Optional[str]:
    """Report which basenames in ``paths`` name more than one source.

    Returned as a message rather than raised, so a caller can print the
    collision list in its own error. ``None`` when every basename is unique --
    which is a property of the particular set passed in, not of the corpus.
    """
    seen: dict[str, set] = {}
    for path in paths:
        text = str(path).replace("\\", "/")
        seen.setdefault(posixpath.basename(text), set()).add(text)
    clashes = {name: sorted(group) for name, group in seen.items()
               if len(group) > 1}
    if not clashes:
        return None
    worst = max(clashes.items(), key=lambda kv: len(kv[1]))
    return (f"{len(clashes)} basename(s) name more than one source here; "
            f"{worst[0]!r} names {len(worst[1])}. Key on the cache path and "
            f"the source digest, not on the basename.")
