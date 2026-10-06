"""Growth-CASE3 (pass22): the Jacobian-matched run took 24 increments, the
transformed run 26. The shared records agree to 1e-14 until t=87.7 and differ
by 1.2e-2 at t=92.7, the increment before the transformed run takes extra
cutbacks. Agreement on shared records of runs whose paths parted proves
nothing (the solver's Newton tolerance sits between them) -- no comparison, the
gate is undecided; a DISAGREEMENT on the shared records stands, because it was
found at times both runs reached from identical earlier increments.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TOOL = Path(__file__).resolve().parents[1] / "tools" / "verify_store_in_abaqus.py"


def _tool():
    spec = importlib.util.spec_from_file_location("verify_tool_for_jm", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_tool_for_jm"] = module
    spec.loader.exec_module(module)
    return module


def _history(times, stress):
    return [{"step": 1, "element": 1, "point": 1, "increment": i + 1, "time": t,
             "STRESS": [stress(t)], "STATEV": [0.0], "DDSDDE": [100.0]}
            for i, t in enumerate(times)]


TIMES = [0.0, 1.0, 2.0, 3.0, 4.0]


def test_the_same_increments_are_compared_record_for_record():
    V = _tool()
    out = V.jacobian_matched_verdict(_history(TIMES, lambda t: 10.0 + t),
                                     _history(TIMES, lambda t: 10.0 + t), tolerance=1e-10,
                                     reference_stiffness=100.0)
    assert out["agrees"] is True and out["comparison"]["agrees"] is True


def test_other_increments_with_agreeing_shared_records_decide_nothing():
    V = _tool()
    transformed = _history(TIMES + [4.5], lambda t: 10.0 + t)       # one extra cutback
    out = V.jacobian_matched_verdict(_history(TIMES, lambda t: 10.0 + t), transformed,
                                     tolerance=1e-10, reference_stiffness=100.0)
    assert "comparison" not in out and "agrees" not in out
    assert "share 5 of 6 records" in out["reason"]
    assert out["shared_records"]["comparison"]["agrees"] is True       # recorded, not claimed
    assert V.control_is_undecided({"established": True}, {"agrees": True}, out)


def test_other_increments_with_a_disagreement_on_the_shared_records_still_disagree():
    V = _tool()
    transformed = _history(TIMES + [4.5], lambda t: 10.0 + t + (0.12 if t == 3.0 else 0.0))
    out = V.jacobian_matched_verdict(_history(TIMES, lambda t: 10.0 + t), transformed,
                                     tolerance=1e-10, reference_stiffness=100.0)
    assert out["agrees"] is False and out["comparison"]["agrees"] is False
    assert "share 5 of 6 records" in out["reason"] and "disagree" in out["reason"]
    assert not V.control_is_undecided({"established": True}, {"agrees": True}, out)


def test_nothing_shared_decides_nothing():
    V = _tool()
    out = V.jacobian_matched_verdict(_history([0.0, 1.0], lambda t: 1.0),
                                     _history([5.0, 6.0], lambda t: 1.0), tolerance=1e-10,
                                     reference_stiffness=100.0)
    assert "agrees" not in out and "comparison" not in out
