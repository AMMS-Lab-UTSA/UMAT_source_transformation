"""A verification record that carries NumPy numbers is written, not lost.

A record built from NumPy arithmetic can carry an int64 (an index, a count).
``json.dumps`` cannot write one, and a six-check run on a synthetic UMAT whose
norm takes absolute values stopped after both Abaqus jobs with "Object of type
int64 is not JSON serializable" and kept no record. The record writer now
writes each NumPy value as the plain value it holds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def verify_store(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "src"))
    monkeypatch.syspath_prepend(str(REPO / "tools"))
    sys.modules.pop("verify_store_in_abaqus", None)
    import verify_store_in_abaqus as module
    assert Path(module.__file__).parent == REPO / "tools"
    return module


def test_numpy_values_in_a_record_are_written_as_plain_values(tmp_path, verify_store):
    record = {"entry": "toy", "worst_at": np.int64(3), "worst": np.float64(2.5e-16),
              "flags": np.array([1, 0]), "passed": np.bool_(True)}
    path = tmp_path / "store_verification.jsonl"
    verify_store.append_record(path, record)
    written = json.loads(path.read_text())
    assert written == {"entry": "toy", "worst_at": 3, "worst": 2.5e-16, "flags": [1, 0], "passed": True}


def test_anything_else_json_cannot_write_is_still_an_error(tmp_path, verify_store):
    with pytest.raises(TypeError, match="object"):
        verify_store.append_record(tmp_path / "x.jsonl", {"bad": object()})
