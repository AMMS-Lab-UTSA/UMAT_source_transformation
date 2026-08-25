"""Canonical identity for a UMAT implementation, independent of where it was found.

The same Fortran turns up in several places. Every one of the twelve UMATs under
``UMATs/ICP`` is normalised-identical to a file in the pinned
``jgomezc1/ABAQUS-US`` snapshot -- they differ only in line endings -- and the
same sources also appear in the archived Abaqus campaign and the higher-order
fixtures. Counting each appearance as a separate model would turn one
implementation validated four ways into four implementations, which is the
difference between a real generality claim and an inflated one.

So identity is computed from the code, and everything else hangs off it:

``canonical_source_id``
    what the implementation *is*
``origin``
    where a copy of it was found
``validation_event``
    what was done to it, and in which round

Two normalisations matter and are kept separate. Line endings and trailing
whitespace never change behaviour, so they are always stripped. Comments do not
change behaviour either, but they do distinguish a fork from its parent, so the
comment-free hash is reported alongside rather than instead.

**Paths are deliberately not part of the identity.** The same closure lives at
``UMATs/UMATs/ICP/UMAT_PCO.for`` here and at ``UMATS/UMAT_PCO.for`` upstream;
hashing the layout would make identical code hash differently and defeat the
entire purpose. A multi-file closure is identified by the set of routines it
resolves to and their normalised bodies, which is what actually gets compiled.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

__all__ = [
    "SourceIdentity",
    "normalise_source",
    "strip_comments",
    "content_identity",
    "closure_identity",
    "IdentityRegistry",
]

_FIXED_COMMENT = re.compile(r"^[Cc*dD!]")


def normalise_source(text: str) -> str:
    """Line endings and trailing whitespace removed; nothing else touched.

    These never change what the compiler produces, and they are exactly what
    differs between the local ICP copies and their upstream originals.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n")
             .replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def strip_comments(text: str, *, fixed_form: bool = True) -> str:
    """Normalised source with comment lines and blank lines removed."""
    out: list[str] = []
    for line in normalise_source(text).split("\n"):
        if not line.strip():
            continue
        if fixed_form and _FIXED_COMMENT.match(line):
            continue
        code = line[:72] if fixed_form else line.split("!", 1)[0]
        if code.strip():
            out.append(code.rstrip())
    return "\n".join(out)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceIdentity:
    """What an implementation is, separate from where it was found."""

    canonical_source_id: str
    kind: str
    entry_routine: str
    content_sha256: str
    code_only_sha256: str
    closure_routines: tuple[str, ...] = ()
    closure_size: int = 1

    def as_dict(self) -> dict:
        payload = {
            "canonical_source_id": self.canonical_source_id,
            "identity_kind": self.kind,
            "entry_routine": self.entry_routine,
            "normalised_content_sha256": self.content_sha256,
            "code_only_sha256": self.code_only_sha256,
            "closure_size": self.closure_size,
        }
        if self.closure_routines:
            payload["closure_routines"] = list(self.closure_routines)
        return payload


def content_identity(path: Path, *, entry_routine: str = "UMAT") -> SourceIdentity:
    """Identity of a single-file source: normalised content plus its entry."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    fixed = Path(path).suffix.lower() in {".for", ".f", ".f77"}
    content = _sha(normalise_source(text))
    code_only = _sha(strip_comments(text, fixed_form=fixed))
    return SourceIdentity(
        canonical_source_id=_sha(f"single:{entry_routine.upper()}:{content}")[:32],
        kind="single_file", entry_routine=entry_routine.upper(),
        content_sha256=content, code_only_sha256=code_only)


def closure_identity(graph, *, entry_routine: str = "UMAT") -> SourceIdentity:
    """Identity of a multi-file source: the routine set that actually compiles.

    Built from ``(routine name, normalised body)`` pairs over the whole resolved
    closure, sorted. Layout plays no part, so the same closure assembled from a
    different directory tree -- or from an upstream repository rather than a
    local copy -- yields the same identity.
    """
    entries: list[str] = []
    bodies: list[str] = []
    for name in sorted(graph.resolved):
        definition = graph.resolved[name]
        text = definition.path.read_text(encoding="utf-8", errors="replace")
        lines = normalise_source(text).split("\n")
        body = "\n".join(lines[definition.start_line - 1:definition.end_line])
        fixed = definition.fixed_form
        entries.append(f"{name}:{_sha(normalise_source(body))}")
        bodies.append(strip_comments(body, fixed_form=fixed))
    joined = "\n".join(entries)
    code_only = _sha("\n".join(bodies))
    if len(graph.resolved) <= 1:
        return content_identity(graph.entry_path, entry_routine=entry_routine)
    return SourceIdentity(
        canonical_source_id=_sha(f"closure:{entry_routine.upper()}:{joined}")[:32],
        kind="dependency_closure", entry_routine=entry_routine.upper(),
        content_sha256=_sha(joined), code_only_sha256=code_only,
        closure_routines=tuple(sorted(graph.resolved)),
        closure_size=len(graph.resolved))


@dataclass
class IdentityRegistry:
    """Every appearance of every implementation, grouped by what it is."""

    by_id: dict[str, dict] = field(default_factory=dict)

    def record(self, identity: SourceIdentity, *, origin: str, label: str,
               validation_event: Optional[str] = None,
               constitutive_model: Optional[str] = None,
               source_structure: Optional[str] = None,
               execution_environment: Optional[str] = None,
               upstream_repository: Optional[str] = None,
               verified: Optional[bool] = None) -> None:
        entry = self.by_id.setdefault(identity.canonical_source_id, {
            **identity.as_dict(),
            "labels": [], "origins": [], "validation_events": [],
            "constitutive_models": [], "source_structures": [],
            "upstream_repositories": [], "verified_by": [],
        })
        for key, value in (("labels", label), ("origins", origin),
                           ("constitutive_models", constitutive_model),
                           ("source_structures", source_structure),
                           ("upstream_repositories", upstream_repository)):
            if value and value not in entry[key]:
                entry[key].append(value)
        if validation_event:
            record = {"event": validation_event, "label": label, "origin": origin}
            if execution_environment:
                record["execution_environment"] = execution_environment
            if verified is not None:
                record["verified"] = verified
            entry["validation_events"].append(record)
            if verified and validation_event not in entry["verified_by"]:
                entry["verified_by"].append(validation_event)

    def counts(self, *, raw_discovered: int) -> dict:
        """The numbers a generality claim is allowed to use."""
        unique = len(self.by_id)
        closures = {e["canonical_source_id"] for e in self.by_id.values()
                    if e["identity_kind"] == "dependency_closure"}
        models = {m for e in self.by_id.values() for m in e["constitutive_models"]}
        repositories = {r for e in self.by_id.values()
                        for r in e["upstream_repositories"]}
        verified = sum(1 for e in self.by_id.values() if e["verified_by"])
        duplicated = sum(1 for e in self.by_id.values() if len(e["origins"]) > 1)
        # "Verified" alone hides what did the verifying. Paired agreement inside
        # Abaqus and a derivative checked against centred differences are both
        # validation, and they are not the same claim, so the breakdown travels
        # with the total.
        per_event: dict[str, int] = {}
        for entry in self.by_id.values():
            for event in entry["verified_by"]:
                per_event[event] = per_event.get(event, 0) + 1
        events: dict[str, int] = {}
        for entry in self.by_id.values():
            for record in entry["validation_events"]:
                events[record["event"]] = events.get(record["event"], 0) + 1
        return {
            "raw_discovered_files": raw_discovered,
            "content_deduplicated_sources": unique,
            "unique_dependency_closures": len(closures),
            "unique_constitutive_models": len(models),
            "independent_upstream_repositories": len(repositories),
            "verified_unique_sources": verified,
            "verified_unique_sources_by_event": dict(sorted(per_event.items())),
            "validation_events_by_kind": dict(sorted(events.items())),
            "sources_found_at_more_than_one_origin": duplicated,
            "note": ("content_deduplicated_sources counts implementations, not "
                     "appearances. A source found both locally and upstream is "
                     "one source with two origins and however many validation "
                     "events were run against it."),
        }

    def as_dict(self, *, raw_discovered: int) -> dict:
        return {
            "counts": self.counts(raw_discovered=raw_discovered),
            "sources": {k: v for k, v in sorted(self.by_id.items())},
        }
