"""B20 rule H5: the Jacobian-matched control and the transformed run are paired on the same increment.

Growth-CASE3: the control converged in a 5.0 increment where the transformed run took a 1.25 cutback that starts at
the same time; pairing on the start time alone compared them and reported a 1.6e-2 "disagreement".
"""
import sys
from pathlib import Path

import pytest

from umat_oti.abaqus.compare import align_by_time, record_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

pytestmark = pytest.mark.unit


def rec(time, dtime, stress=100.0, point=1):
    return {"step": 1, "element": 1, "point": point, "increment": 1, "time": time,
            "STRESS": [stress, 0.0, 0.0, 0.0, 0.0, 0.0], "STATEV": [1.0],
            "DDSDDE": [1.0] * 36, "entry": {"DTIME": [dtime]}}


def test_the_default_pairing_is_the_old_one():
    left = [rec(0.0, 1.0), rec(1.0, 5.0)]
    right = [rec(0.0, 1.0), rec(1.0, 1.25)]
    a, b, note = align_by_time(left, right)
    assert len(a) == len(b) == 2 and "increment size" not in note


def test_equal_start_times_and_different_increments_pair_nothing_by_increment():
    # PLANTED ERROR: a 5.0 increment against a 1.25 increment that start together
    left = [rec(0.0, 1.0), rec(1.0, 5.0)]
    right = [rec(0.0, 1.0), rec(1.0, 1.25)]
    a, b, note = align_by_time(left, right, by_increment=True)
    assert len(a) == len(b) == 1 and a[0]["time"] == 0.0
    assert "increment size" in note


def test_equal_increments_pair_as_before():
    left = [rec(0.0, 1.0), rec(1.0, 5.0)]
    right = [rec(0.0, 1.0), rec(1.0, 5.0)]
    a, b, note = align_by_time(left, right, by_increment=True)
    assert len(a) == 2 and note == ""


def test_a_record_with_no_increment_size_is_keyed_as_before():
    plain = {"step": 1, "element": 1, "point": 1, "time": 0.5}
    assert record_key(plain, by_increment=False) == record_key(plain, by_increment=True)[:4]
    assert record_key(plain)[4] is None


def test_the_control_verdict_is_not_decided_when_the_increments_differ():
    import verify_store_in_abaqus as V
    control = [rec(0.0, 1.0, 100.0), rec(1.0, 5.0, 100.0), rec(6.0, 1.0, 100.0)]
    transformed = [rec(0.0, 1.0, 100.0), rec(1.0, 1.25, 77.0), rec(2.25, 1.0, 100.0)]
    out = V.jacobian_matched_verdict(control, transformed, tolerance=1e-10,
                                     reference_stiffness=1.0)
    # the shared record agrees; the 5.0 vs 1.25 pair is not compared, so no disagreement is manufactured
    assert "agrees" not in out or out["agrees"] is not False
    assert "did not walk the same increments" in out["reason"]
