"""A Kelvin-Voigt solid is linear in the strain at every amplitude.

So the amplitude search reports ``linear_to_the_ceiling`` -- "nothing here to
activate" -- about a material whose whole subject is time. Measured on
``irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for``, whose stiffness
carries ``eta/(E*dtime)``: six runs from 1e-4 to 1 strain, every one linear,
every one at the same DTIME.

Raising the strain does not make time pass. So the same path is walked again
over a different step time, and stopped for a while at the end of it. Same
targets, same increments -- so increment k of one run is at the same strain as
increment k of the other, and a difference between their stresses is rate
dependence and can be nothing else.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.manifest import (at_rate, hold,  # noqa: E402
                                      uniaxial)
from umat_oti.abaqus.rate_search import (RATE_FACTOR,  # noqa: E402
                                         compare_rates, probe_time,
                                         relaxation_during)


def path(stresses, strains=None):
    strains = strains or [0.001 * (i + 1) for i in range(len(stresses))]
    return [{"STRESS": [s] + [0.0] * 5, "STRAN": [e] + [0.0] * 5}
            for s, e in zip(stresses, strains)]


ELASTIC = [1e6, 2e6, 3e6, 4e6]


def test_the_same_stress_at_two_rates_is_not_rate_dependence():
    difference, _ = compare_rates(path(ELASTIC), path(ELASTIC))
    assert difference == 0.0


def test_a_stiffer_answer_at_a_higher_rate_is_rate_dependence():
    faster = [value * 1.2 for value in ELASTIC]
    difference, where = compare_rates(path(ELASTIC), path(faster))
    assert difference > 0.1
    assert where[0] in (1, 2, 3, 4)


def test_stress_moving_while_the_strain_is_held_is_relaxation():
    # four loading increments, then four at constant strain
    records = path(ELASTIC + [4e6, 3.4e6, 3.0e6, 2.8e6],
                   [0.001, 0.002, 0.003, 0.004] + [0.004] * 4)
    assert relaxation_during(records, 4) > 0.2


def test_a_hold_keeps_the_strain_and_lengthens_the_time():
    pull = uniaxial(0.01, 10)
    held = hold(pull, period=10.0, increments=5)
    assert held.strain == pull.strain
    assert held.period == 10.0
    assert "held" in held.description


def test_a_rate_change_keeps_the_strain_and_the_increments():
    pull = uniaxial(0.01, 10)
    fast = at_rate(pull, RATE_FACTOR)
    assert fast.strain == pull.strain
    assert fast.increments == pull.increments
    assert fast.period == pull.period * RATE_FACTOR


def test_a_time_dependent_material_says_so_and_says_why():
    slow = path(ELASTIC + [4e6, 3.0e6, 2.5e6], [0.001, 0.002, 0.003, 0.004]
                + [0.004] * 3)
    fast = path([value * 1.5 for value in ELASTIC])
    finding = probe_time(lambda: (True, slow, ""), lambda: (True, fast, ""),
                         hold_from=4)
    assert finding.time_dependent
    assert finding.rate_dependent and finding.relaxed
    assert "raising the strain does not make time pass" in finding.reason


def test_a_rate_independent_material_says_that_too():
    finding = probe_time(lambda: (True, path(ELASTIC), ""),
                         lambda: (True, path(ELASTIC), ""), hold_from=None)
    assert not finding.time_dependent
    assert "nothing here depends on time" in finding.reason


def test_a_run_that_did_not_produce_a_history_decides_nothing():
    finding = probe_time(lambda: (False, [], "the job did not complete"),
                         lambda: (True, path(ELASTIC), ""))
    assert not finding.ran
    assert not finding.time_dependent
    assert "nothing can be said" in finding.reason


# ---------------------------------------------------------------------------
# and a state variable is not a plastic strain because it moved
# ---------------------------------------------------------------------------
from umat_oti.abaqus.activation import detect_activation  # noqa: E402


def _driven(strains, states, stresses=None):
    stresses = stresses or [2e5 * e for e in strains]
    return [{"STRAN": [e] + [0.0] * 5, "DSTRAN": [e] + [0.0] * 5,
             "STRESS": [s] + [0.0] * 5, "STATEV": list(q)}
            for e, s, q in zip(strains, stresses, states)]


RAMP = [0.0, 1e-4, 2e-4, 3e-4, 4e-4, 5e-4]


def test_a_state_that_follows_the_strain_is_not_activation():
    """The tissue UMATs: SDVINI sets ten state variables to 1.0 and the routine
    then tracks the deformation in them. Every one moves at any amplitude, so
    the search stopped at its FIRST -- 1e-4 -- and the finite difference there
    is pure noise."""
    stretch = [[1.0 + e] for e in RAMP]
    found = detect_activation(_driven(RAMP, stretch))
    assert not found.activated
    indicator = next(i for i in found.indicators if i.name == "state_change")
    assert indicator.magnitude > 0.0, "it did move, and that is recorded"
    assert "proportion to the strain" in indicator.detail


def test_a_state_that_starts_growing_partway_along_is_activation():
    """A plastic strain is zero until the yield surface is reached. Its
    movement per unit strain is therefore not the same at every increment --
    it changes by everything."""
    plastic = [[0.0], [0.0], [0.0], [1e-5], [1e-4], [3e-4]]
    found = detect_activation(_driven(RAMP, plastic))
    assert found.activated
    indicator = next(i for i in found.indicators if i.name == "state_change")
    assert indicator.fired
    assert "does not explain" in indicator.detail


def test_a_state_that_never_moves_is_not_activation():
    found = detect_activation(_driven(RAMP, [[1.0]] * len(RAMP)))
    assert not found.activated
    assert next(i for i in found.indicators
                if i.name == "state_change").detail == "no state variable moved"
