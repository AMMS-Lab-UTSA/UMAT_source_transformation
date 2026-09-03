"""What the store must never hand back, and what it must never lose count of.

Found by adversarial review of the store rather than by using it. Each of
these had the store reporting an entry as current and intact when it was not.

The store exists so a batch can be re-run after a change to the transform and
re-establish what still holds. Every defect here defeats exactly that: an
entry served under a fingerprint that no longer describes the code that made
it is worse than no cache at all.
"""
import json
from pathlib import Path

import pytest

from umat_oti.store.transform_store import (
    ENTRY_RECORD, TransformStore, transform_fingerprint)

SOURCE = "owner__repo/models/umat.for"
DIGEST = "sha-of-the-source"


def _output(directory: Path, entry_name: str = "umat_oti.for",
            units=("master_parameters.f90", "otim6n1.f90"),
            order=None, entry_body: str = "      SUBROUTINE UMAT\n      END\n") -> Path:
    """A transform output directory shaped like the real emitter's."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / entry_name).write_text(entry_body, encoding="utf-8")
    for unit in units:
        (directory / unit).write_text(f"module {Path(unit).stem}\nend module\n",
                                      encoding="utf-8")
    lines = list(order) if order is not None else [*units, entry_name]
    (directory / "compile_order.txt").write_text("\n".join(lines) + "\n",
                                                 encoding="utf-8")
    return directory / entry_name


# ---- the fingerprint has to cover the whole transform --------------------
def _package(root: Path, fortran: str = "      x = 1\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "transform.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    support = root / "oti" / "support"
    support.mkdir(parents=True, exist_ok=True)
    (support / "real_utils.f90").write_text(fortran, encoding="utf-8")
    return root


def test_the_fingerprint_notices_a_change_to_a_fortran_support_unit(tmp_path):
    """The transform copies .f90 support verbatim into every output.

    Fingerprinting only *.py left those invisible: editing real_utils.f90
    changed what every transformed source computes while every cached entry
    stayed current, so the store served derivatives of code that no longer
    existed.
    """
    package = _package(tmp_path / "pkg")
    before = transform_fingerprint(package)
    (package / "oti" / "support" / "real_utils.f90").write_text(
        "      x = 2\n", encoding="utf-8")
    assert transform_fingerprint(package) != before


def test_the_fingerprint_notices_a_change_to_a_python_file(tmp_path):
    package = _package(tmp_path / "pkg")
    before = transform_fingerprint(package)
    (package / "transform.py").write_text("def go():\n    return 2\n", encoding="utf-8")
    assert transform_fingerprint(package) != before


def test_the_fingerprint_is_stable_when_nothing_changed(tmp_path):
    package = _package(tmp_path / "pkg")
    assert transform_fingerprint(package) == transform_fingerprint(package)


def test_the_fingerprint_covers_a_fortran_template(tmp_path):
    package = _package(tmp_path / "pkg")
    before = transform_fingerprint(package)
    (package / "pyoti_templates").mkdir(parents=True, exist_ok=True)
    (package / "pyoti_templates" / "oti.f90").write_text("! t\n", encoding="utf-8")
    assert transform_fingerprint(package) != before


def test_the_real_fingerprint_sees_the_fortran_in_this_package():
    """Guards the glob list against being narrowed back to Python only."""
    import umat_oti

    root = Path(umat_oti.__file__).resolve().parent
    fortran = [p for p in root.rglob("*.f90") if "__pycache__" not in p.parts]
    assert fortran, "no .f90 under the package; this test is no longer meaningful"


# ---- the entry source is a path, not a name -----------------------------
def test_the_entry_is_taken_from_the_path_given_not_its_basename(tmp_path):
    """A stale copy beside the real output must not be picked up instead.

    The emitter can put the transformed file in a subdirectory. Recording it
    by basename resolved to whatever sat at the top level -- in the worst case
    the untransformed source -- and `.exists` then reported True about it.
    """
    out = tmp_path / "out"
    (out).mkdir(parents=True)
    (out / "umat_oti.for").write_text("      STALE COPY\n", encoding="utf-8")
    real = _output(out / "generated", entry_name="umat_oti.for",
                   entry_body="      SUBROUTINE UMAT\n      END\n")

    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    stored = store.put(SOURCE, DIGEST, out, real, metadata={})
    assert stored.entry_source.read_text() != "      STALE COPY\n"
    assert stored.entry_source.parent.name == "generated"


def test_an_entry_source_outside_the_output_is_refused(tmp_path):
    out = _output(tmp_path / "out").parent
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    with pytest.raises(ValueError):
        store.put(SOURCE, DIGEST, out, tmp_path / "elsewhere" / "umat_oti.for",
                  metadata={})


# ---- the support units are the build order, minus the entry --------------
def test_a_support_unit_sharing_a_prefix_with_the_entry_is_kept(tmp_path):
    """The exclusion must not be a substring test on the stem.

    Dropping any unit whose stem contains the entry's stem removed the real
    OTI modules: entry `umat.for` silently lost `umat_oti_module.f90`.
    """
    out = tmp_path / "out"
    entry = _output(out, entry_name="umat.for",
                    units=("umat_oti_module.f90", "otim6n1.f90"))
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    stored = store.put(SOURCE, DIGEST, out, entry, metadata={})
    names = [p.name for p in stored.support_units]
    assert "umat_oti_module.f90" in names
    assert "umat.for" not in names


def test_the_build_order_is_preserved(tmp_path):
    """A module has to be compiled before the code that uses it."""
    out = tmp_path / "out"
    entry = _output(out, units=("a.f90", "b.f90", "c.f90"),
                    order=["c.f90", "a.f90", "b.f90", "umat_oti.for"])
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    stored = store.put(SOURCE, DIGEST, out, entry, metadata={})
    assert [p.name for p in stored.support_units] == ["c.f90", "a.f90", "b.f90"]


def test_a_combined_whole_umat_copy_is_not_a_support_unit(tmp_path):
    """The emitter writes one beside the modules; linking it duplicates
    every routine in the file. With no order file to consult, it has to be
    recognised by its contents rather than by its name."""
    out = tmp_path / "out"
    body = "      SUBROUTINE UMAT\n      END\n"
    entry = _output(out, entry_name="u_oti.for", units=("otim6n1.f90",), order=[])
    (out / "compile_order.txt").unlink()
    (out / "u_oti_combined.f90").write_text(body, encoding="utf-8")
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    stored = store.put(SOURCE, DIGEST, out, entry, metadata={})
    names = [p.name for p in stored.support_units]
    assert "otim6n1.f90" in names
    assert "u_oti_combined.f90" not in names


# ---- put must not report success for nothing ----------------------------
def test_put_refuses_an_output_whose_entry_is_missing(tmp_path):
    """The row was counted transformed while the store counted zero entries."""
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "compile_order.txt").write_text("\n", encoding="utf-8")
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    with pytest.raises(ValueError):
        store.put(SOURCE, DIGEST, out, out / "never_written.for", metadata={})


# ---- a failed transform is not a cached success --------------------------
def test_a_failed_transform_is_not_served_as_cached(tmp_path):
    """Otherwise a batch reports it as already done, forever."""
    out = tmp_path / "out"
    entry = _output(out)
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    store.put(SOURCE, DIGEST, out, entry, metadata={"transform_success": False})
    assert store.get(SOURCE, DIGEST) is None


def test_a_successful_transform_is_served(tmp_path):
    out = tmp_path / "out"
    entry = _output(out)
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    store.put(SOURCE, DIGEST, out, entry, metadata={"transform_success": True})
    assert store.get(SOURCE, DIGEST) is not None


def test_metadata_that_says_nothing_about_success_is_served(tmp_path):
    """Absence of the key is not a failure; only False is."""
    out = tmp_path / "out"
    entry = _output(out)
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    store.put(SOURCE, DIGEST, out, entry, metadata={})
    assert store.get(SOURCE, DIGEST) is not None


# ---- a broken entry is counted, not dropped -----------------------------
def test_an_entry_whose_files_vanished_is_counted_as_broken(tmp_path):
    """Dropping it silently shrinks the denominator with no category.

    The store lives outside the repository on a disk that gets cleaned, so
    this happens; a batch has to be able to say how much of its corpus went
    missing rather than reporting a smaller corpus.
    """
    out = tmp_path / "out"
    entry = _output(out)
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    stored = store.put(SOURCE, DIGEST, out, entry, metadata={})
    stored.entry_source.unlink()

    summary = store.summary()
    assert summary["broken"] == 1
    assert summary["stored"] == 1          # still in the denominator
    assert store.get(SOURCE, DIGEST) is None
    # The index is a snapshot taken when an entry is written; the summary is
    # live. A caller that wants the index to reflect a later deletion asks.
    store.rebuild_index()
    index = json.loads((store.root / "index.json").read_text(encoding="utf-8"))
    assert index["broken"] == 1


# ---- the record must not name this machine ------------------------------
def test_the_summary_does_not_carry_an_absolute_home_path(tmp_path):
    """The summary goes into published evidence, which must not name a machine."""
    store = TransformStore(root=tmp_path / "store", fingerprint="fp")
    summary = store.summary()
    assert "root" not in summary or not str(summary.get("root", "")).startswith(
        str(Path.home()))
