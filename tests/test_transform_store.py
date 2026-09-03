"""What the transform store has to get right to be worth keeping at all.

The store exists so a batch does not re-transform 199 sources every time
something is re-checked. A cache in a project whose whole subject is whether
the transform is correct is only safe if it can tell when it has gone out of
date, so the tests here weigh most heavily on the two ways an entry stops
being evidence:

* the transform code moved on, so the cached output was made by something that
  no longer exists. The key carries a fingerprint of the transform, so this
  shows up as `get` returning None and the batch rebuilding.
* the entry was addressed by the wrong thing. Identity here is a source's path
  within the discovery cache, never its basename: eighteen UMATs in this corpus
  share a basename with something else, and keying on the filename would serve
  one repository's transform for another repository's source.

Everything is built under tmp_path with an explicit fingerprint, so no test
reads or writes the real store root and none of them depend on the current
contents of the package.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.store import StoredTransform, TransformStore, transform_fingerprint
from umat_oti.store.transform_store import ENTRY_RECORD, INDEX, file_digest

#: Two sources that a basename-keyed store would collide. These are the shape
#: of the real identities: "owner__name/path/within/the/repository".
SOURCE_A = "alice__plasticity/src/umat.for"
SOURCE_B = "bob__viscoelastic/models/umat.for"

ENTRY_TEXT = (
    "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD)\n"
    "      RETURN\n"
    "      END\n"
)


def _transform_output(work: Path, entry_name: str = "umat.for", *,
                      body: str = ENTRY_TEXT,
                      units: tuple[str, ...] = ("oti_core.f90", "oti_umat.f90"),
                      order: bool = True) -> tuple[Path, Path]:
    """A directory shaped like what `run_transformation` leaves in its out dir.

    The support units and compile_order.txt are not decoration: the Abaqus link
    needs every .f90 the transform emitted, so a store that copies the entry
    source alone would hand back something that cannot be built. The order file
    names the entry source last, the way the real one does, because that is
    when it compiles -- which is exactly the trap an entry has to avoid
    recording it as a support unit.
    """
    work.mkdir(parents=True, exist_ok=True)
    entry = work / entry_name
    entry.write_text(body, encoding="utf-8")
    for unit in units:
        (work / unit).write_text(
            f"module {Path(unit).stem}\nend module\n", encoding="utf-8")
    if order:
        (work / "compile_order.txt").write_text(
            "\n".join(tuple(units) + (entry_name,)) + "\n", encoding="utf-8")
    return work, entry


def _store(root: Path, fingerprint: str = "transform-a") -> TransformStore:
    """A store that never touches DEFAULT_ROOT and never digests the package."""
    return TransformStore(root=root, fingerprint=fingerprint)


def _put(store: TransformStore, work: Path, source_id: str,
         sha: str = "sha-of-the-source", **kwargs) -> StoredTransform:
    out_dir, entry = _transform_output(work, **kwargs)
    return store.put(source_id, sha, out_dir, entry,
                     {"transform_success": True, "source": source_id})


# ---- serving what was stored --------------------------------------------
def test_a_stored_transform_is_served_back_for_the_same_source_and_digest(tmp_path):
    """If a hit is not served, the batch re-transforms all 199 every run."""
    store = _store(tmp_path / "store")
    stored = _put(store, tmp_path / "work", SOURCE_A)

    served = store.get(SOURCE_A, "sha-of-the-source")
    assert served is not None
    assert served.key == stored.key
    assert served.source_id == SOURCE_A
    assert served.source_sha256 == "sha-of-the-source"
    assert served.fingerprint == store.fingerprint
    assert served.entry_source.read_text(encoding="utf-8") == ENTRY_TEXT
    # the metadata is the only record of how the transform went; losing it on
    # the round trip would leave a cached entry that cannot be reported on
    assert served.metadata["transform_success"] is True
    assert served.metadata["source"] == SOURCE_A


def test_a_source_that_was_never_stored_is_not_served(tmp_path):
    """A miss must be a miss; a stray hit would attribute one source's tangent
    to another."""
    store = _store(tmp_path / "store")
    _put(store, tmp_path / "work", SOURCE_A)
    assert store.get(SOURCE_B, "sha-of-the-source") is None


# ---- identity is the path, not the filename ------------------------------
def test_two_sources_sharing_a_basename_get_different_keys(tmp_path):
    """Eighteen UMATs here are named the same as something else. Keying on the
    basename would serve one repository's transform for another's source, and
    the verification that followed would be measuring the wrong file."""
    store = _store(tmp_path / "store")
    assert Path(SOURCE_A).name == Path(SOURCE_B).name     # the collision itself
    assert store.key_for(SOURCE_A, "same-sha") != store.key_for(SOURCE_B, "same-sha")

    first = _put(store, tmp_path / "a", SOURCE_A, sha="same-sha")
    second = _put(store, tmp_path / "b", SOURCE_B, sha="same-sha",
                  body="      SUBROUTINE UMAT\n      END\n")

    assert first.directory != second.directory
    served_a = store.get(SOURCE_A, "same-sha")
    served_b = store.get(SOURCE_B, "same-sha")
    assert served_a is not None and served_b is not None
    assert served_a.source_id == SOURCE_A
    assert served_b.source_id == SOURCE_B
    assert served_a.entry_source.read_text(encoding="utf-8") == ENTRY_TEXT
    assert served_b.entry_source.read_text(encoding="utf-8") != ENTRY_TEXT


def test_changing_the_source_bytes_changes_the_key(tmp_path):
    """A source that was edited is a different input. Serving the old transform
    for it would report a tangent for code that is no longer there."""
    store = _store(tmp_path / "store")
    assert store.key_for(SOURCE_A, "sha-one") != store.key_for(SOURCE_A, "sha-two")

    _put(store, tmp_path / "work", SOURCE_A, sha="sha-one")
    assert store.get(SOURCE_A, "sha-one") is not None
    assert store.get(SOURCE_A, "sha-two") is None


def test_the_key_is_stable_across_stores_with_the_same_fingerprint(tmp_path):
    """The address has to be reproducible, or a second process writes a second
    copy of the same entry instead of finding the first."""
    one = _store(tmp_path / "store")
    two = _store(tmp_path / "store")
    assert one.key_for(SOURCE_A, "sha-one") == two.key_for(SOURCE_A, "sha-one")

    _put(one, tmp_path / "work", SOURCE_A, sha="sha-one")
    assert two.get(SOURCE_A, "sha-one") is not None


# ---- the property that makes a transform change re-run the batch ---------
def test_an_entry_written_by_another_transform_is_not_served(tmp_path):
    """This is the whole reason the store is safe to use. If a change to the
    transform still served yesterday's output, a re-run would report agreement
    it never rechecked -- the cache would be certifying itself."""
    root = tmp_path / "store"
    old = _store(root, fingerprint="transform-a")
    written = _put(old, tmp_path / "work", SOURCE_A)

    new = _store(root, fingerprint="transform-b")
    assert new.get(SOURCE_A, "sha-of-the-source") is None
    assert new.key_for(SOURCE_A, "sha-of-the-source") != written.key

    # the bytes are still on disk and still readable by their own key; they are
    # simply no longer evidence about the transform as it now stands
    recovered = new.read(written.key)
    assert recovered is not None
    assert recovered.fingerprint == "transform-a"


def test_a_rebuilt_entry_replaces_the_one_it_supersedes(tmp_path):
    """Re-transforming the same inputs must leave one directory, not two half
    directories whose contents came from different runs."""
    store = _store(tmp_path / "store")
    first = _put(store, tmp_path / "one", SOURCE_A)
    (first.directory / "leftover.f90").write_text("module leftover\nend module\n",
                                                  encoding="utf-8")

    second = _put(store, tmp_path / "two", SOURCE_A,
                  body="      SUBROUTINE UMAT\n      END\n",
                  units=("oti_core.f90",))
    assert second.directory == first.directory
    assert not (second.directory / "leftover.f90").exists()
    assert [p.name for p in second.support_units] == ["oti_core.f90"]
    served = store.get(SOURCE_A, "sha-of-the-source")
    assert served is not None
    assert served.entry_source.read_text(encoding="utf-8") != ENTRY_TEXT


# ---- partitioning ---------------------------------------------------------
def test_stale_and_current_entries_partition_the_entries(tmp_path):
    """A caller decides what to re-run from this split. If the two sides
    overlapped or lost an entry, a source would be rebuilt twice or silently
    dropped from the batch."""
    root = tmp_path / "store"
    old = _store(root, fingerprint="transform-a")
    _put(old, tmp_path / "old", SOURCE_A)

    new = _store(root, fingerprint="transform-b")
    _put(new, tmp_path / "new", SOURCE_B)

    entries = new.entries()
    current = new.current_entries()
    stale = new.stale_entries()

    assert len(entries) == 2
    assert len(current) + len(stale) == len(entries)
    keys = {e.key for e in entries}
    assert {e.key for e in current} | {e.key for e in stale} == keys
    assert not ({e.key for e in current} & {e.key for e in stale})
    assert [e.source_id for e in current] == [SOURCE_B]
    assert [e.source_id for e in stale] == [SOURCE_A]
    assert all(e.fingerprint == new.fingerprint for e in current)
    assert all(e.fingerprint != new.fingerprint for e in stale)


def test_prune_stale_removes_the_stale_and_leaves_the_current(tmp_path):
    """Pruning is destructive and runs unattended. Taking a current entry with
    it would throw away a transform that is still valid and cost the batch a
    rebuild; leaving a stale one would keep dead output around forever."""
    root = tmp_path / "store"
    old = _store(root, fingerprint="transform-a")
    doomed = _put(old, tmp_path / "old", SOURCE_A)

    new = _store(root, fingerprint="transform-b")
    kept = _put(new, tmp_path / "new", SOURCE_B)

    removed = new.prune_stale()

    assert removed == [doomed.key]
    assert not doomed.directory.exists()
    assert kept.directory.is_dir()
    assert kept.entry_source.is_file()
    assert [e.key for e in new.entries()] == [kept.key]
    assert new.stale_entries() == []
    assert new.prune_stale() == []                 # nothing left to remove


# ---- what put() actually copies ------------------------------------------
def test_put_copies_the_support_units_and_records_them(tmp_path):
    """`abaqus user=` compiles the entry source itself, but the OTI support
    units have to be built alongside it. An entry that recorded only the entry
    source would link against nothing and fail on every routine it calls."""
    store = _store(tmp_path / "store")
    # deliberately not in alphabetical order: a module has to be compiled
    # before the units that use it, so the sequence is the transform's to say
    written = ("oti_umat.f90", "oti_core.f90", "oti_math.f90")
    stored = _put(store, tmp_path / "work", SOURCE_A, units=written)

    names = [p.name for p in stored.support_units]
    assert names == list(written)
    for unit in stored.support_units:
        assert unit.is_file()
        assert unit.parent == stored.directory          # copied, not referenced
    # the order file travels with them; a rebuild reads it, not the directory
    assert (stored.directory / "compile_order.txt").is_file()

    served = store.get(SOURCE_A, "sha-of-the-source")
    assert served is not None
    assert [p.name for p in served.support_units] == names
    record = json.loads((stored.directory / ENTRY_RECORD).read_text(encoding="utf-8"))
    assert [Path(p).name for p in record["support_units"]] == names


def test_the_entry_source_is_never_recorded_as_a_support_unit(tmp_path):
    """compile_order.txt names the entry source last, because that is when it
    compiles. Every caller compiles it separately -- `abaqus user=` does, and
    so does the replay driver -- so building it from the support list too
    defines every routine in the file twice and fails the link on all of them.
    """
    store = _store(tmp_path / "store")
    stored = _put(store, tmp_path / "work", SOURCE_A)

    listed = (stored.directory / "compile_order.txt").read_text(encoding="utf-8")
    assert stored.entry_source.name in listed        # the trap is present
    assert stored.entry_source not in stored.support_units
    assert stored.entry_source.name not in [p.name for p in stored.support_units]
    assert stored.entry_source.is_file()             # and it was still copied


def test_a_whole_umat_copy_is_not_mistaken_for_a_support_unit(tmp_path):
    """With no order file the units have to be found by looking, and the
    transform leaves a free-form copy of the whole UMAT beside the support
    modules. Building that copy is the same double-definition link failure by
    another route, so a glob of *.f90 is not good enough."""
    store = _store(tmp_path / "store")
    out_dir, entry = _transform_output(tmp_path / "work", units=("oti_core.f90",),
                                       order=False)
    (out_dir / "umat_transformed.f90").write_text(
        "      SUBROUTINE UMAT\n      END\n", encoding="utf-8")

    stored = store.put(SOURCE_A, "sha-of-the-source", out_dir, entry, {})

    assert [p.name for p in stored.support_units] == ["oti_core.f90"]
    # the copy is still in the directory; it is just not something to build
    assert (stored.directory / "umat_transformed.f90").is_file()


def test_an_entry_whose_files_were_deleted_is_not_served(tmp_path):
    """The store lives outside the repository, on a disk that gets cleaned. An
    entry record that outlived its Fortran would be served as a cache hit and
    the batch would try to verify a file that is not there."""
    store = _store(tmp_path / "store")
    stored = _put(store, tmp_path / "work", SOURCE_A)
    assert stored.exists

    stored.entry_source.unlink()

    assert not stored.exists
    assert store.get(SOURCE_A, "sha-of-the-source") is None
    assert store.read(stored.key) is None
    assert store.entries() == []                   # and it is not counted either


# ---- the index and the summary -------------------------------------------
def test_rebuild_index_writes_counts_that_match_the_entries(tmp_path):
    """The index is what a report reads instead of walking the store. If its
    counts drift from the entries, the paper's numbers describe a store that
    does not exist."""
    root = tmp_path / "store"
    old = _store(root, fingerprint="transform-a")
    _put(old, tmp_path / "old", SOURCE_A)

    new = _store(root, fingerprint="transform-b")
    _put(new, tmp_path / "new", SOURCE_B)

    path = new.rebuild_index()
    assert path == root / INDEX
    payload = json.loads(path.read_text(encoding="utf-8"))

    entries = new.entries()
    assert payload["fingerprint"] == new.fingerprint
    assert payload["count"] == len(entries)
    assert payload["current"] == len(new.current_entries())
    assert len(payload["entries"]) == len(entries)
    assert [e["source_id"] for e in payload["entries"]] == [e.source_id for e in entries]
    assert {e["key"] for e in payload["entries"]} == {e.key for e in entries}


def test_the_index_and_the_summary_agree(tmp_path):
    """Two ways of counting the same store, quoted in different places. They
    disagreeing is how a run reports 199 stored and 158 current from numbers
    that were never taken at the same moment."""
    root = tmp_path / "store"
    old = _store(root, fingerprint="transform-a")
    _put(old, tmp_path / "old", SOURCE_A)

    new = _store(root, fingerprint="transform-b")
    _put(new, tmp_path / "new", SOURCE_B)
    new.rebuild_index()

    payload = json.loads((root / INDEX).read_text(encoding="utf-8"))
    summary = new.summary()

    # The summary carries no root: it goes into published evidence, which must
    # not name the machine it was produced on. The caller already knows the
    # root -- it passed it in.
    assert "root" not in summary
    assert summary["fingerprint"] == payload["fingerprint"]
    assert summary["stored"] == payload["count"]
    assert summary["current"] == payload["current"]
    assert summary["stale"] == payload["count"] - payload["current"]
    assert summary["stored"] == summary["current"] + summary["stale"]

    # and they keep agreeing after the store changes underneath them
    new.prune_stale()
    payload = json.loads((root / INDEX).read_text(encoding="utf-8"))
    summary = new.summary()
    assert (payload["count"], payload["current"]) == (summary["stored"], summary["current"])
    assert summary["stale"] == 0


# ---- the fingerprint of the transform itself ------------------------------
def _package_tree(root: Path) -> Path:
    """A stand-in package, so the assertions do not depend on the real one."""
    package = root / "umat_oti_sample"
    (package / "fortran").mkdir(parents=True)
    (package / "__init__.py").write_text("VERSION = '1'\n", encoding="utf-8")
    (package / "fortran" / "__init__.py").write_text("", encoding="utf-8")
    (package / "fortran" / "scanner.py").write_text("SEED = 'auto'\n", encoding="utf-8")
    return package


def test_transform_fingerprint_is_stable_for_the_same_tree(tmp_path):
    """An unchanged transform must keep its fingerprint. If it wandered, every
    entry would go stale on every run and the store would never serve anything."""
    package = _package_tree(tmp_path)
    first = transform_fingerprint(package)
    assert first == transform_fingerprint(package)

    # compiled bytecode is not the transform; it appears and disappears on its
    # own, and letting it count would invalidate the whole store for nothing
    cache = package / "fortran" / "__pycache__"
    cache.mkdir()
    (cache / "scanner.cpython-311.pyc").write_bytes(b"\x00compiled\x00")
    assert transform_fingerprint(package) == first


def test_transform_fingerprint_changes_when_a_python_file_changes(tmp_path):
    """This is the signal the whole store rests on. A transform that changed
    without changing its fingerprint would leave every cached entry looking
    current, and the re-run would confirm results it never recomputed."""
    package = _package_tree(tmp_path)
    before = transform_fingerprint(package)

    edited = package / "fortran" / "scanner.py"
    edited.write_text("SEED = 'DSTRAN'\n", encoding="utf-8")
    after_edit = transform_fingerprint(package)
    assert after_edit != before

    # a new module is a change too, even though nothing existing was touched
    (package / "fortran" / "emitter.py").write_text("ORDER = 2\n", encoding="utf-8")
    assert transform_fingerprint(package) != after_edit


def test_a_changed_transform_makes_every_stored_entry_stale(tmp_path):
    """The fingerprint and the store, end to end: editing the transform has to
    invalidate entries that were made before the edit, with nobody remembering
    to say so."""
    package = _package_tree(tmp_path)
    root = tmp_path / "store"
    before = TransformStore(root=root, fingerprint=transform_fingerprint(package))
    _put(before, tmp_path / "a", SOURCE_A)
    _put(before, tmp_path / "b", SOURCE_B)
    assert len(before.current_entries()) == 2

    (package / "fortran" / "scanner.py").write_text("SEED = 'auto'  # fixed\n",
                                                    encoding="utf-8")
    after = TransformStore(root=root, fingerprint=transform_fingerprint(package))

    assert after.get(SOURCE_A, "sha-of-the-source") is None
    assert after.get(SOURCE_B, "sha-of-the-source") is None
    assert after.current_entries() == []
    assert len(after.stale_entries()) == 2


def test_a_store_given_no_fingerprint_uses_the_transform_code_itself(tmp_path):
    """The default has to be the real package. A store that fingerprinted
    something else would be stale-blind against the code it is caching."""
    store = TransformStore(root=tmp_path / "store")
    assert store.fingerprint == transform_fingerprint()
    assert store.fingerprint                        # not the empty string


# ---- the digest a caller keys on -----------------------------------------
def test_file_digest_reads_the_bytes_and_reports_nothing_for_a_missing_file(tmp_path):
    """The digest is half the address. Two sources whose bytes differ must not
    share one, and an unreadable source must not quietly borrow the digest of
    whatever was asked for last."""
    one = tmp_path / "umat.for"
    two = tmp_path / "other.for"
    one.write_text(ENTRY_TEXT, encoding="utf-8")
    two.write_text(ENTRY_TEXT, encoding="utf-8")
    assert file_digest(one) == file_digest(two)     # same bytes, same digest

    two.write_text(ENTRY_TEXT + "C  edited\n", encoding="utf-8")
    assert file_digest(one) != file_digest(two)
    assert file_digest(tmp_path / "absent.for") == ""
