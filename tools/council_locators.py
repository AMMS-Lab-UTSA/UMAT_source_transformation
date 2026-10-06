#!/usr/bin/env python3
"""Make the council evidence locators resolvable: set folders without ``#``.

A locator is ``<root>:<path>[#selector]`` and ``#`` is the fragment separator
(``umat_oti.corpus_features.manifest.resolve_locator`` cuts the path at the
first ``#``). The council harness runs name each set's folder ``<key>#A`` /
``<key>#B``, so every council evidence locator named a path that does not
exist: the merge validator reported "does not resolve to a file" for all of
them (Vera D-27, open condition).

This is a POST-PROCESSING step, so no fingerprint-covered code changes:

* every ``<dir>/<key>#<set>`` folder (and its ``.log``) under the given run
  directories is COPIED to ``<dir>/<key>_<set>``; the originals stay as the
  run wrote them; a sha256 map of the copies against the originals is written
  beside the cells;
* the cells' ``evidence`` / ``evidence_all`` are rewritten: the path part uses
  ``_<set>``, and the selector's ``key=<key>#<set>`` becomes
  ``key=<key>&set=<set>`` (the inner files still name the row ``<key>#<set>``);
  no ``#`` remains but the one fragment separator.

    python tools/council_locators.py CELLS.jsonl OUT_CELLS.jsonl RUN_DIR [RUN_DIR ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

#: ``<24 hex key>#<set>`` as a whole path component.
_SET_NAME = re.compile(r"^([0-9a-f]{24})#([A-Za-z0-9]+)(\.log)?$")
#: the same inside a locator path or selector.
_PATH_PART = re.compile(r"/([0-9a-f]{24})#([A-Za-z0-9]+)(?=/|$)")
_SELECTOR_KEY = re.compile(r"key=([0-9a-f]{24})#([A-Za-z0-9]+)")


def safe_name(name: str) -> str:
    """``<key>#A`` -> ``<key>_A`` (and ``<key>#A.log`` -> ``<key>_A.log``)."""
    m = _SET_NAME.match(name)
    return f"{m.group(1)}_{m.group(2)}{m.group(3) or ''}" if m else name


def rewrite_locator(locator: str) -> str:
    """The locator with the set folder and the selector free of ``#``.

    Only the FIRST ``#`` of the result separates path from selector.
    """
    if not isinstance(locator, str) or "#" not in locator:
        return locator
    path = _PATH_PART.sub(lambda m: f"/{m.group(1)}_{m.group(2)}", locator)
    path, sep, selector = path.partition("#")
    selector = _SELECTOR_KEY.sub(lambda m: f"key={m.group(1)}&set={m.group(2)}", selector)
    return path + (f"#{selector}" if sep else "")


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_set_folders(run_dir: Path) -> list[dict]:
    """Copy every ``<key>#<set>`` entry of ``run_dir`` to its ``_`` name."""
    mapping: list[dict] = []
    for entry in sorted(Path(run_dir).iterdir()):
        new = safe_name(entry.name)
        if new == entry.name:
            continue
        target = entry.with_name(new)
        files = [entry] if entry.is_file() else sorted(p for p in entry.rglob("*") if p.is_file())
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)
        for src in files:
            dst = target / src.relative_to(entry) if entry.is_dir() else target
            mapping.append({"from": str(src), "to": str(dst),
                            "sha256": _digest(src), "sha256_copy": _digest(dst)})
    return mapping


def rewrite_cells(cells_in: Path, cells_out: Path) -> int:
    n = 0
    lines = []
    for line in Path(cells_in).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        cell = json.loads(line)
        if cell.get("evidence"):
            cell["evidence"] = rewrite_locator(cell["evidence"])
        if isinstance(cell.get("evidence_all"), list):
            cell["evidence_all"] = [rewrite_locator(e) for e in cell["evidence_all"]]
        lines.append(json.dumps(cell, sort_keys=False))
        n += 1
    Path(cells_out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cells_in", type=Path)
    parser.add_argument("cells_out", type=Path)
    parser.add_argument("run_dirs", type=Path, nargs="+")
    args = parser.parse_args(argv)
    mapping = []
    for run_dir in args.run_dirs:
        mapping += copy_set_folders(run_dir)
    n = rewrite_cells(args.cells_in, args.cells_out)
    side = args.cells_out.with_suffix(".copies.json")
    side.write_text(json.dumps({
        "what_this_is": "copies of the council set folders made by tools/council_locators.py: "
                        "the originals (<key>#<set>) are untouched; sha256 is of the original, "
                        "sha256_copy of the copy (equal)",
        "files": mapping}, indent=1) + "\n", encoding="utf-8")
    bad = [m for m in mapping if m["sha256"] != m["sha256_copy"]]
    print(f"  {n} cells rewritten, {len(mapping)} files copied, {len(bad)} digest mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
