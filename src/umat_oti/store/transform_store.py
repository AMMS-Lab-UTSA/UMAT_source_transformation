"""A cache of transformed sources, keyed by what they were made from.

Every run of the discovery triage transformed each source into a temporary
directory and threw it away. That made three things impossible at once: reusing
a transform, re-testing a batch of them, and telling whether a change to the
transform altered any of them. This keeps them.

An entry is addressed by three things together, because all three change what
the output is:

* which source it came from -- its identity in the cache, not its filename.
  Eighteen UMATs in this corpus share a basename with something else.
* the SHA-256 of that source's bytes.
* a fingerprint of the transform itself.

The third is the one that does the work the user asked for. When any transform
code changes, every fingerprint changes, every cached entry becomes stale, and
a batch re-run rebuilds and re-checks all of them rather than quietly serving
yesterday's output. A cache that cannot tell it is stale is worse than no cache
at all in a project whose whole subject is whether the transform is correct.

Nothing here is committed to the repository. Most of these sources carry no
licence, and a transformed source is a derivative of one; the store lives
outside the tree and the repository keeps only digests and counts.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

#: Where a store lives when nobody says otherwise. Outside the repository, on
#: purpose: see the module docstring on licence.
DEFAULT_ROOT = Path.home() / "softwarex_work" / "transform_store"

#: The file each entry carries describing itself.
ENTRY_RECORD = "entry.json"

#: The index, rewritten whenever an entry is added. It is a convenience for
#: reading the store quickly; the entries themselves remain the truth, and
#: `rebuild_index` regenerates it from them.
INDEX = "index.json"


def _digest_of_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    """The SHA-256 of a file, or "" when it cannot be read."""
    try:
        return _digest_of_bytes(Path(path).read_bytes())
    except OSError:
        return ""


def transform_fingerprint(package_root: Optional[Path] = None) -> str:
    """A digest of the transform code itself.

    Every Python file under the package contributes, in sorted order, name and
    contents both. That is deliberately broad: it will call an entry stale for
    a change that could not have affected it, and the cost of that is a rebuild,
    while the cost of the opposite mistake is a batch that reports agreement it
    never rechecked.
    """
    root = Path(package_root) if package_root is not None else \
        Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()[:16]


#: What the transform writes to say which units to build, and in what order.
#: Module dependencies make the order load-bearing.
COMPILE_ORDER = "compile_order.txt"


def _support_units(directory: Path, entry_source: Path) -> tuple[Path, ...]:
    """The units that must be built alongside the entry source, in order.

    Read from the transform's own compile_order.txt rather than by globbing
    the directory. The transform also emits a combined free-form copy of the
    whole UMAT beside the support modules, and a glob picks that up -- which
    links a second definition of every routine in the file and fails the link
    on all of them at once. The order file names only what belongs in a build,
    and it names it in the sequence a module has to be compiled before its
    users.

    The entry source itself is dropped: it is the last line of the order
    because that is when it compiles, but every caller compiles it separately
    -- `abaqus user=` does, and so does the replay driver's link line.
    """
    listing = Path(directory) / COMPILE_ORDER
    entry = Path(entry_source).resolve()
    if listing.is_file():
        units = []
        for line in listing.read_text(errors="replace").splitlines():
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            candidate = Path(directory) / name
            if candidate.is_file() and candidate.resolve() != entry:
                units.append(candidate)
        return tuple(units)
    # No order file: fall back to the modules, but still never the entry
    # source and never a combined whole-UMAT copy of it.
    stem = entry.stem
    return tuple(sorted(
        path for path in Path(directory).glob("*.f90")
        if path.is_file() and path.resolve() != entry and stem not in path.stem))


@dataclass(frozen=True)
class StoredTransform:
    """One transformed source, and what it was made from."""

    key: str
    #: The source's identity: its path within the discovery cache, which is
    #: what distinguishes two files that share a basename.
    source_id: str
    source_sha256: str
    fingerprint: str
    directory: Path
    entry_source: Path
    support_units: tuple[Path, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["directory"] = str(self.directory)
        record["entry_source"] = str(self.entry_source)
        record["support_units"] = [str(p) for p in self.support_units]
        return record

    @property
    def exists(self) -> bool:
        return Path(self.entry_source).is_file()


class TransformStore:
    """A directory of transformed sources, addressed by their inputs."""

    def __init__(self, root: Optional[Path] = None,
                 fingerprint: Optional[str] = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self._fingerprint = fingerprint or transform_fingerprint()

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def key_for(self, source_id: str, source_sha256: str) -> str:
        """The address of one transform of one source by one transform version."""
        material = f"{source_id}\0{source_sha256}\0{self._fingerprint}"
        return _digest_of_bytes(material.encode("utf-8"))[:24]

    def path_for(self, key: str) -> Path:
        return self.root / key

    # ---- reading ---------------------------------------------------------
    def get(self, source_id: str, source_sha256: str) -> Optional[StoredTransform]:
        """The stored transform for these inputs, if one is present and intact.

        Returns None when the transform code has moved on, which is what makes
        a change to the transform re-run the batch instead of reusing it.
        """
        return self.read(self.key_for(source_id, source_sha256))

    def read(self, key: str) -> Optional[StoredTransform]:
        record_path = self.path_for(key) / ENTRY_RECORD
        if not record_path.is_file():
            return None
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        stored = StoredTransform(
            key=str(record.get("key", key)),
            source_id=str(record.get("source_id", "")),
            source_sha256=str(record.get("source_sha256", "")),
            fingerprint=str(record.get("fingerprint", "")),
            directory=Path(record.get("directory", self.path_for(key))),
            entry_source=Path(record.get("entry_source", "")),
            support_units=tuple(Path(p) for p in record.get("support_units", [])),
            metadata=dict(record.get("metadata", {})),
        )
        return stored if stored.exists else None

    def entries(self) -> list[StoredTransform]:
        """Every intact entry, newest-agnostic, sorted by source identity."""
        found = []
        for child in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            if not child.is_dir():
                continue
            stored = self.read(child.name)
            if stored is not None:
                found.append(stored)
        return sorted(found, key=lambda s: s.source_id)

    def current_entries(self) -> list[StoredTransform]:
        """Entries built by the transform as it stands now."""
        return [e for e in self.entries() if e.fingerprint == self._fingerprint]

    def stale_entries(self) -> list[StoredTransform]:
        """Entries built by some earlier transform, and so no longer evidence."""
        return [e for e in self.entries() if e.fingerprint != self._fingerprint]

    # ---- writing ---------------------------------------------------------
    def put(self, source_id: str, source_sha256: str, out_dir: Path,
            entry_source: Path, metadata: Optional[dict[str, Any]] = None,
            ) -> StoredTransform:
        """Copy a transform output into the store and record what made it."""
        key = self.key_for(source_id, source_sha256)
        target = self.path_for(key)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(Path(out_dir), target)

        entry = target / Path(entry_source).name
        support = _support_units(target, entry)
        stored = StoredTransform(
            key=key, source_id=source_id, source_sha256=source_sha256,
            fingerprint=self._fingerprint, directory=target, entry_source=entry,
            support_units=support, metadata=dict(metadata or {}),
        )
        (target / ENTRY_RECORD).write_text(
            json.dumps(stored.as_dict(), indent=1) + "\n", encoding="utf-8")
        self.rebuild_index()
        return stored

    def discard(self, key: str) -> bool:
        target = self.path_for(key)
        if not target.is_dir():
            return False
        shutil.rmtree(target, ignore_errors=True)
        self.rebuild_index()
        return True

    def prune_stale(self) -> list[str]:
        """Remove entries the current transform did not produce. Returns keys."""
        removed = [entry.key for entry in self.stale_entries()]
        for key in removed:
            shutil.rmtree(self.path_for(key), ignore_errors=True)
        if removed:
            self.rebuild_index()
        return removed

    # ---- the index -------------------------------------------------------
    def rebuild_index(self) -> Path:
        entries = self.entries()
        payload = {
            "fingerprint": self._fingerprint,
            "count": len(entries),
            "current": sum(1 for e in entries if e.fingerprint == self._fingerprint),
            "entries": [e.as_dict() for e in entries],
        }
        path = self.root / INDEX
        path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        return path

    def summary(self) -> dict[str, Any]:
        """Counts a caller can report without reading every entry."""
        entries = self.entries()
        current = [e for e in entries if e.fingerprint == self._fingerprint]
        return {
            "root": str(self.root),
            "fingerprint": self._fingerprint,
            "stored": len(entries),
            "current": len(current),
            "stale": len(entries) - len(current),
        }
