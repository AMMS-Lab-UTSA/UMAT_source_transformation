"""The feature runner resolves its output directories, so a relative --out works.

A newcomer following the docs ran ``tools/run_corpus_features.py --out ../x``
and every cell came back not_attempted with "original routine did not build":
the relative path was handed to compilers running in other directories. The
result looked like a fact about the source.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "tools" / "run_corpus_features.py"


@pytest.mark.unit
def test_out_and_work_are_resolved_before_use():
    tree = ast.parse(RUNNER.read_text())
    assigned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            assigned[node.targets[0].id] = ast.unparse(node.value)
    assert assigned["out"].endswith(".resolve()"), assigned["out"]
    assert "resolve()" in assigned["work"], assigned["work"]
