"""Three of the four activation indicators were reading a key that is never there.

A UMAT call produces two probe records. The RESULT record carries what the
routine computed -- STRESS, STATEV, DDSDDE. The ENTRY record carries what it
was given -- STRAN, DSTRAN, PROPS, DFGRD0, DFGRD1 -- and it is attached to the
result under ``"entry"``, because a finite difference has to replay the
increment from the state it began in.

``record["STRAN"]`` is therefore absent from every real history this project
has ever produced. Measured on ``abuganza__UMAT_anisotropic_damage`` over nine
increments of a path that reverses:

* departure from linearity: "too few increments carry both stress and strain";
* residual after reversal: "no increment came back near the starting strain";
* response character: ``unknown_state_semantics`` -- "no strain was recorded
  to compare against".

Only the two indicators that need no strain ever fired, so the adaptive search
was choosing an amplitude on half its evidence, and every regime classification
was made without knowing where the strain had been.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.activation import (detect_activation,  # noqa: E402
                                        increment_of, strain_at)
from umat_oti.abaqus.state_regime import response_character  # noqa: E402


def probe_record(stress, statev, stran, dstran):
    """A result record shaped the way the probe actually writes one."""
    return {"kind": "result", "STRESS": list(stress), "STATEV": list(statev),
            "DDSDDE": [1.0] * 36,
            "entry": {"kind": "entry", "STRAN": list(stran),
                      "DSTRAN": list(dstran), "STRESS0": [0.0] * 6,
                      "STATEV0": list(statev)}}


def test_the_strain_comes_out_of_the_entry_record():
    record = probe_record([1.0] * 6, [0.0], [0.01] * 6, [0.002] * 6)
    assert record.get("STRAN") is None, "the fixture is shaped like a real one"
    assert strain_at(record) == [0.012] * 6
    assert increment_of(record) == [0.002] * 6


def test_a_flat_record_is_still_read():
    """A hand-written fixture that puts STRAN at the top level is taken as
    given, so the unit tests written against that shape keep meaning what they
    meant."""
    assert strain_at({"STRAN": [0.01] * 6}) == [0.01] * 6


def test_departure_from_linearity_can_now_see_the_strain():
    """Stress that falls away from the line the first increment set."""
    strains = [i * 1e-3 for i in range(1, 7)]
    linear = [2e5 * e for e in strains]
    bent = linear[:3] + [value * 0.5 for value in linear[3:]]
    records = [probe_record([s] + [0.0] * 5, [0.0], [e - 1e-3] + [0.0] * 5,
                            [1e-3] + [0.0] * 5)
               for s, e in zip(bent, strains)]
    found = detect_activation(records)
    indicator = next(i for i in found.indicators
                     if i.name == "departure_from_linearity")
    assert indicator.fired, indicator.detail
    assert "too few increments" not in indicator.detail


def test_a_reversal_that_leaves_stress_behind_is_now_visible():
    """Out to 3e-3 and back to zero, with stress left over."""
    path = [(1e-3, 2e2), (2e-3, 4e2), (3e-3, 6e2), (2e-3, 4e2), (1e-3, 2e2),
            (0.0, 1e2)]
    records = [probe_record([s] + [0.0] * 5, [0.0], [e] + [0.0] * 5,
                            [0.0] * 6) for e, s in path]
    found = detect_activation(records, reversal_at=3)
    indicator = next(i for i in found.indicators
                     if i.name == "residual_after_reversal")
    assert indicator.fired, indicator.detail
    assert indicator.magnitude > 0.1


def test_the_response_character_can_now_be_decided():
    """It used to answer unknown_state_semantics on every real history."""
    path = [(0.0, 0.0), (1e-3, 2e2), (2e-3, 4e2), (1e-3, 2e2), (0.0, 0.0)]
    records = [probe_record([s] + [0.0] * 5, [1.0 + e], [e] + [0.0] * 5,
                            [0.0] * 6) for e, s in path]
    character, why = response_character(records)
    assert character != "unknown_state_semantics", why
    assert "no strain was recorded" not in why
