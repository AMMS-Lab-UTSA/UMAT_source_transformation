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
import re
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


#: What counts as transform code. The Fortran matters as much as the Python:
#: the transform copies its OTI support units verbatim into every output and
#: generates from Fortran templates, so a change to one of those changes what
#: every transformed source computes. Fingerprinting only *.py left them
#: invisible, and the store went on serving derivatives of code that no longer
#: existed while reporting every entry as current.
FINGERPRINTED = ("*.py", "*.f90", "*.f", "*.for", "*.inc")


def transform_fingerprint(package_root: Optional[Path] = None) -> str:
    """A digest of the transform code itself.

    Every file under the package whose suffix is in :data:`FINGERPRINTED`
    contributes, name and contents both, in one order sorted by path relative
    to the root -- not grouped by suffix, or the digest would depend on the
    order the globs happened to run in.

    Deliberately broad: it will call an entry stale for a change that could not
    have affected it, and the cost of that is a rebuild, while the cost of the
    opposite mistake is a batch reporting agreement it never rechecked.
    """
    root = Path(package_root) if package_root is not None else \
        Path(__file__).resolve().parents[1]
    seen: dict[str, Path] = {}
    for pattern in FINGERPRINTED:
        for path in root.rglob(pattern):
            if "__pycache__" in path.parts or not path.is_file():
                continue
            seen[str(path.relative_to(root))] = path
    digest = hashlib.sha256()
    for relative in sorted(seen):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(seen[relative].read_bytes())
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
        if units:
            return tuple(units)
    # No usable order file. Fall back to the modules, and recognise a whole-UMAT
    # copy by the routine it DECLARES.
    #
    # Two weaker rules were tried and both were wrong. Excluding any unit whose
    # stem contains the entry's stem dropped the real OTI modules, because an
    # entry named `umat.for` sits inside `umat_oti_module.f90`. Comparing bytes
    # against the entry missed it entirely, because the copy the transform
    # leaves is a free-form translation of the fixed-form entry, not a copy of
    # it. What the two do share is the subprogram they define, and defining it
    # twice is the link failure being avoided.
    declared = _declared_subprograms(entry)
    units = []
    for path in sorted(Path(directory).glob("*.f90")):
        if not path.is_file() or path.resolve() == entry:
            continue
        if declared and _declared_subprograms(path) & declared:
            continue
        units.append(path)
    return tuple(units)


_SUBPROGRAM = re.compile(
    r"^[^!cC*]{0,10}?\b(?:SUBROUTINE|FUNCTION)\s+(\w+)", re.IGNORECASE)


def _declared_subprograms(path: Path) -> set[str]:
    """The subprogram names a Fortran file defines, upper-cased.

    Enough to tell a support module from a second copy of the UMAT: two files
    that define the same subprogram cannot both be in one link.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return set()
    names = set()
    for line in text.splitlines():
        if line[:1] in "cC*!":
            continue
        match = _SUBPROGRAM.match(line)
        if match:
            names.add(match.group(1).upper())
    return names


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
        """The stored transform for these inputs, if one is usable.

        Returns None when the transform code has moved on, which is what makes
        a change to the transform re-run the batch instead of reusing it, and
        None for an entry that records a transform which failed: otherwise a
        batch reads it back as already done and reports it as cached for as
        long as the store lives.
        """
        stored = self.read(self.key_for(source_id, source_sha256))
        if stored is None:
            return None
        if stored.metadata.get("transform_success") is False:
            return None
        return stored

    def read(self, key: str) -> Optional[StoredTransform]:
        """The entry at ``key``, or None when it is absent or its files are gone.

        Use :meth:`record` when the count matters: an entry whose files were
        cleaned off the disk underneath the store is *broken*, not absent, and
        dropping it here is how a denominator quietly shrinks.
        """
        stored = self.record(key)
        return stored if stored is not None and stored.exists else None

    def record(self, key: str) -> Optional[StoredTransform]:
        """What the store says about ``key``, whether or not its files survive."""
        record_path = self.path_for(key) / ENTRY_RECORD
        if not record_path.is_file():
            return None
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return StoredTransform(
            key=str(record.get("key", key)),
            source_id=str(record.get("source_id", "")),
            source_sha256=str(record.get("source_sha256", "")),
            fingerprint=str(record.get("fingerprint", "")),
            directory=Path(record.get("directory", self.path_for(key))),
            entry_source=Path(record.get("entry_source", "")),
            support_units=tuple(Path(p) for p in record.get("support_units", [])),
            metadata=dict(record.get("metadata", {})),
        )

    def all_records(self) -> list[StoredTransform]:
        """Every entry the store has written, intact or not.

        This is the denominator. The store lives outside the repository on a
        disk that gets cleaned, so entries do lose their files, and a batch has
        to be able to say how much of its corpus went missing rather than
        reporting a smaller corpus.
        """
        found = []
        for child in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            if not child.is_dir():
                continue
            stored = self.record(child.name)
            if stored is not None:
                found.append(stored)
        return sorted(found, key=lambda s: s.source_id)

    def broken_entries(self) -> list[StoredTransform]:
        """Entries the store recorded whose files are no longer on disk."""
        return [e for e in self.all_records() if not e.exists]

    def entries(self) -> list[StoredTransform]:
        """Every intact entry, sorted by source identity."""
        return [e for e in self.all_records() if e.exists]

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
        """Copy a transform output into the store and record what made it.

        ``entry_source`` is located by its path within ``out_dir``, not by its
        basename. The emitter may write the transformed file into a
        subdirectory, and taking the name alone resolved to whatever sat at the
        top level -- in the worst case a stale untransformed copy -- which then
        reported itself as present.

        Raises ValueError when the entry is not under ``out_dir`` or is not
        there after the copy. A store entry that records a file which does not
        exist is counted as a transform by its caller while the store counts
        nothing, and the two numbers then disagree with no way to tell which
        is wrong.
        """
        out_dir = Path(out_dir).resolve()
        entry_path = Path(entry_source).resolve()
        try:
            relative = entry_path.relative_to(out_dir)
        except ValueError:
            raise ValueError(
                f"the entry source {entry_path} is not inside the transform "
                f"output {out_dir}, so the store cannot address it") from None
        if not entry_path.is_file():
            raise ValueError(
                f"the transform named {entry_path} as its output but no such "
                f"file exists, so there is nothing to store")

        key = self.key_for(source_id, source_sha256)
        target = self.path_for(key)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(out_dir, target)

        entry = target / relative
        if not entry.is_file():
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError(
                f"the entry source did not survive the copy into the store: "
                f"{relative}")
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
        records = self.all_records()
        payload = {
            "fingerprint": self._fingerprint,
            "count": len(records),
            "current": sum(1 for e in records
                           if e.exists and e.fingerprint == self._fingerprint),
            "stale": sum(1 for e in records
                         if e.exists and e.fingerprint != self._fingerprint),
            "broken": sum(1 for e in records if not e.exists),
            "entries": [e.as_dict() for e in records],
        }
        path = self.root / INDEX
        path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        return path

    def summary(self) -> dict[str, Any]:
        """Counts a caller can report, with nothing dropped from the total.

        ``stored`` is every entry the store has written, so
        ``current + stale + broken == stored`` always. A broken entry -- one
        whose files were cleaned off the disk -- used to be dropped from
        ``entries`` and therefore from the total, which shrank the denominator
        with no category to account for it.

        The root is deliberately absent: this goes into published evidence,
        which must not name the machine it was produced on.
        """
        records = self.all_records()
        broken = [e for e in records if not e.exists]
        intact = [e for e in records if e.exists]
        current = [e for e in intact if e.fingerprint == self._fingerprint]
        return {
            "fingerprint": self._fingerprint,
            "stored": len(records),
            "current": len(current),
            "stale": len(intact) - len(current),
            "broken": len(broken),
        }
