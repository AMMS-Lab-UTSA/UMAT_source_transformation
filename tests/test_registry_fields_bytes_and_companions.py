"""Registry fields that were silently wrong (Scout, B1 data-quality 2 and 3).

* ``bytes`` was ``len(text.encode())`` of the text decoded with
  ``errors="replace"`` and universal newlines -- not the file size for 115
  rows (CRLF endings, non-UTF-8 bytes);
* ``companion_files`` was cut at 500 characters and ``missing_companions`` at
  300, dropping companions of the longest closures (CriticalSoilModels
  umat.f90, Sanisand-High).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_corpus_registry as reg  # noqa: E402


def test_bytes_is_the_file_size_not_the_decoded_length(tmp_path):
    f = tmp_path / "umat.for"
    data = b"      SUBROUTINE UMAT\r\n! caf\xe9 \xff\r\n      END\r\n"
    f.write_bytes(data)
    decoded = f.read_text(errors="replace")
    assert len(decoded.encode()) != len(data)      # the old value was wrong
    assert reg.source_bytes(f) == f.stat().st_size == len(data)


def test_companion_files_are_not_truncated(tmp_path):
    units = [tmp_path / f"deep/directory/name/companion_{i:03d}.f90" for i in range(60)]
    text = reg.companion_files_text(units, tmp_path)
    assert len(text) > 500
    assert text.split("; ") == [str(u.relative_to(tmp_path)) for u in units]


def test_missing_companions_are_not_truncated():
    missing = [f"module VERY_LONG_MODULE_NAME_{i}" for i in range(40)]
    text = reg.missing_companions_text(missing)
    assert len(text) > 300 and text.split("; ") == missing


def test_the_builder_slices_neither_field_nor_derives_bytes_from_text():
    """No ``record.companion_files/missing_companions = ...[:N]`` and no
    ``record.bytes = len(...)`` anywhere in the registry builder."""
    tree = ast.parse((REPO / "tools/build_corpus_registry.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in (
                    "companion_files", "missing_companions", "bytes"):
                if any(isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)
                       for n in ast.walk(node.value)):
                    offenders.append((target.attr, node.lineno))
                if target.attr == "bytes" and any(
                        isinstance(n, ast.Call) and getattr(n.func, "id", "") == "len"
                        for n in ast.walk(node.value)):
                    offenders.append((target.attr, node.lineno))
    assert offenders == []
