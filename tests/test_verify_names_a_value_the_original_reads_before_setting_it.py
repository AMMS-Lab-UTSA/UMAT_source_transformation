"""``umat-oti verify`` says when the original reads a value it never set.

The gate leaves an output the init probe finds undefined out of the stress
comparison, so the verdict can be green while the original has undefined
behaviour. The command prints a paragraph that names the variable and line (from
the transform report) and the outputs (from the init probe).
"""
import json

from umat_oti.app.verify_command import undefined_behaviour_note


def _store(tmp_path, findings):
    entry = tmp_path / "store" / "abc"
    entry.mkdir(parents=True)
    (entry / "transform_report.json").write_text(json.dumps(
        {"reads_before_assignment": {"findings": findings}}))
    return tmp_path / "store"


def test_both_sources_are_named(tmp_path):
    store = _store(tmp_path, [{"name": "DEP", "line": 41, "lines": [41]}])
    record = {"undefined_outputs": ["STATEV(8)"],
              "undefined_in_original": {"pair": "ifort -init=zero / -init=huge"}}
    note = undefined_behaviour_note(record, store)
    assert "DEP (line 41)" in note and "STATEV(8) differs" in note
    assert "ifort -init=zero / -init=huge" in note and "left out of the stress comparison" in note


def test_nothing_is_said_when_there_is_nothing(tmp_path):
    store = _store(tmp_path, [])
    assert undefined_behaviour_note({"undefined_outputs": []}, store) == ""


def test_the_transform_finding_alone_is_reported(tmp_path):
    store = _store(tmp_path, [{"name": "X", "line": 12, "lines": [12, 30]}, {"name": "N", "line": 5}])
    note = undefined_behaviour_note({}, store)
    assert "X (line 12, 30), N (line 5)" in note and "each at zero" in note
    assert "init probe" not in note


def test_a_state_slot_the_routine_reads_back_is_said_to_feed_the_computation(tmp_path):
    store = _store(tmp_path, [{"name": "DEP", "line": 9, "lines": [9]}])
    source = tmp_path / "umat.f"
    source.write_text("      SUBROUTINE UMAT(STATEV)\n"
                      "      DIMENSION STATEV(2)\n"
                      "C     STATEV(2) = EPSB\n"
                      "      EPSB = STATEV(2)\n"
                      "      PHI = 2.0D0*EPSB\n"
                      "      IF (PHI .GT. 1.0D0) DEP = PHI\n"
                      "      STATEV(1) = PHI\n"
                      "      STATEV(2) = STATEV(2) + DEP\n"
                      "      END\n")
    record = {"undefined_outputs": ["STATEV(2)"], "undefined_in_original": {"pair": "p"}}
    note = undefined_behaviour_note(record, store, source)
    assert "reads it back on line 4 (EPSB = ... STATEV(2)), which is used on lines 5, 6" not in note
    assert "reads it back on line 4 (EPSB = ... STATEV(2)), which is used on line 5" in note
    assert "enters the computation through EPSB" in note
    assert "reads it back" not in undefined_behaviour_note(
        {"undefined_outputs": ["STATEV(1)"]}, store, source)
