"""Under --jobs, every console result line of verify_store names its own entry.

pass17.log (corpus_run/pass17.log, lines 1019-1029) printed

    [237/238] theysy__mml_subroutine_public/MML_U3/MML_U3.FOR
        incomplete_or_corrupt_source  the unmodified source does not compile
        with Abaqus's own compile line: thealanjason__umat_...

The record in store_verification.jsonl was right; the console was not. The
"[i/N] source" header is printed when an entry STARTS and the bare result line
when it FINISHES, and under a thread pool a slow entry finishes after faster
ones have printed their headers, so its result lands under someone else's.

The test makes the first entry slow and the second fast, runs two workers,
and asserts that every result line carries the source it belongs to.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"


@pytest.fixture()
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "src"))
    monkeypatch.syspath_prepend(str(TOOLS))
    sys.modules.pop("verify_store_in_abaqus", None)
    import verify_store_in_abaqus as module
    assert Path(module.__file__).parent == TOOLS
    return module


def test_a_slow_entrys_result_is_printed_under_its_own_name(tool, tmp_path,
                                                          monkeypatch, capsys):
    fast_done = threading.Event()

    def verify_one(stored, *args, **kwargs):
        if stored.source_id == "slow__repo/a.f":
            # Finish only after the fast entry has started AND finished, so
            # its header is the last one on the console when this prints.
            fast_done.wait(timeout=10)
            return {"key": stored.key, "source": stored.source_id,
                    "stage": "incomplete_or_corrupt_source",
                    "reason": "slow__repo/a.f(3): error"}
        fast_done.set()
        return {"key": stored.key, "source": stored.source_id,
                "stage": "verified", "reason": "fine"}

    monkeypatch.setattr(tool, "verify_one", verify_one)
    monkeypatch.setattr(tool, "append_record", lambda *a, **k: None)
    entries = [SimpleNamespace(key="k1", source_id="slow__repo/a.f",
                               directory=str(tmp_path)),
               SimpleNamespace(key="k2", source_id="fast__repo/b.f",
                               directory=str(tmp_path))]

    tool.run_batch(entries, {}, {}, tmp_path, tmp_path,
                   tmp_path / "r.jsonl", timeout=1, jobs=2)

    out = capsys.readouterr().out.splitlines()
    results = [line for line in out if "->" in line]
    assert len(results) == 2, out
    for line in results:
        if "incomplete_or_corrupt_source" in line:
            assert "slow__repo/a.f" in line.split("->")[0], line
        if "verified" in line:
            assert "fast__repo/b.f" in line.split("->")[0], line
    # and no stage is printed on a line that names no entry
    assert not [line for line in out if line.startswith("    ")
                and ("verified" in line or "incomplete" in line)], out
