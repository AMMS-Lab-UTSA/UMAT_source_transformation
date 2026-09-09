"""The loading is searched for, not chosen.

A verification driven at a strain the model answers elastically tests the part
of a UMAT that every build gets right: the stress is linear, the tangent is the
elastic one, the state never moves. A converted routine that is wrong about
yielding, damage, hardening or rate dependence agrees perfectly there.

So the driver runs the ORIGINAL material, asks whether anything happened, and
raises the amplitude until something does -- then narrows the bracket, because
the states worth checking a tangent at are the ones either side of a
transition.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.activation import (LINEARITY_TOLERANCE,  # noqa: E402
                                        detect_activation)
from umat_oti.abaqus.amplitude_search import (ACTIVATED,  # noqa: E402
                                              LEFT_ITS_DOMAIN,
                                              LINEAR_TO_THE_CEILING,
                                              STOPPED_CONVERGING,
                                              search_amplitude)
from umat_oti.abaqus.manifest import TEST_PURPOSE, family  # noqa: E402


def elastic_plastic(amplitude, yield_at, increments=10):
    """A material that yields at a known strain."""
    records = []
    for step in range(1, increments + 1):
        strain = amplitude * step / increments
        plastic = max(0.0, strain - yield_at)
        records.append({
            "STRESS": [2e5 * (strain - plastic)] + [0.0] * 5,
            "STRAN": [strain] + [0.0] * 5,
            "STATEV": [plastic],
            "DDSDDE": [2e5 if plastic == 0 else 2e3] + [0.0] * 35})
    return records


# ---- what counts as the material doing something -------------------------
def test_a_moved_state_variable_is_activation():
    activation = detect_activation(elastic_plastic(1e-2, 2e-3))
    assert activation.activated
    assert "state_change" in activation.fired


def test_a_changed_tangent_is_activation():
    """The indicator that matters most for a derivative claim: a tangent that
    never moves is one whose verification says nothing about the material."""
    assert "tangent_change" in detect_activation(
        elastic_plastic(1e-2, 2e-3)).fired


def test_a_purely_elastic_history_is_not_activation():
    activation = detect_activation(elastic_plastic(1e-4, 1.0))
    assert not activation.activated
    assert "elastic branch only" in activation.summary()


def test_a_material_with_no_state_is_not_penalised_for_it():
    """Absence of state variables is not absence of activation."""
    records = [{"STRESS": [i * 1.0], "STRAN": [i * 1e-4], "STATEV": []}
               for i in range(1, 5)]
    state = next(i for i in detect_activation(records).indicators
                 if i.name == "state_change")
    assert not state.fired and "declares no state variables" in state.detail


def test_what_cannot_be_measured_is_named_rather_than_assumed_absent():
    """Dissipated energy, a PNEWDT cutback and which branch executed are not
    visible in a material-point probe. Silence about them must not read as
    'no activation'."""
    activation = detect_activation(elastic_plastic(1e-2, 2e-3))
    joined = " ".join(activation.not_measured)
    assert "ALLPD" in joined and "PNEWDT" in joined and "branch" in joined


# ---- the search ----------------------------------------------------------
def test_the_search_brackets_the_transition():
    result = search_amplitude(
        lambda a: (True, elastic_plastic(a, 2e-3), ""))
    assert result.outcome == ACTIVATED
    low, high = result.bracket
    assert low <= 2e-3 <= high * 1.5
    assert high / max(low, 1e-30) < 1.5, "the bracket should be narrowed"


def test_a_linear_material_is_reported_as_linear_not_as_a_failure():
    """For a linear elastic material there is nothing to activate, and that
    is the right answer rather than a failure to try harder."""
    result = search_amplitude(lambda a: (True, elastic_plastic(a, 1e9), ""))
    assert result.outcome == LINEAR_TO_THE_CEILING
    assert "not a failure" in result.summary()


def test_non_convergence_bounds_the_search_and_is_reported():
    result = search_amplitude(
        lambda a: (a <= 1e-3, elastic_plastic(a, 1e9) if a <= 1e-3 else [],
                   "" if a <= 1e-3 else "the increment did not converge"))
    assert result.outcome == STOPPED_CONVERGING
    assert result.amplitude <= 1e-3


def test_a_runaway_stress_stops_the_search():
    """Before Abaqus has to say so."""
    def run(amplitude):
        records = elastic_plastic(amplitude, 1e9)
        if amplitude > 1e-3:
            for record in records:
                record["STRESS"] = [1e30] + [0.0] * 5
        return True, records, ""
    assert search_amplitude(run).outcome in (LEFT_ITS_DOMAIN, ACTIVATED)


def test_the_search_never_runs_the_converted_build():
    """A loading chosen with the conversion in view would be a loading chosen
    to agree. The callback is given an amplitude and nothing else."""
    import inspect

    signature = inspect.signature(search_amplitude)
    assert "run" in signature.parameters
    assert "transformed" not in signature.parameters


def test_every_attempt_is_kept():
    """The escalation is the evidence for where the transition is."""
    result = search_amplitude(lambda a: (True, elastic_plastic(a, 2e-3), ""))
    assert len(result.attempts) >= 3
    assert all("amplitude" in a.as_dict() for a in result.attempts)


# ---- the family of tests -------------------------------------------------
def test_each_named_test_says_what_it_is_for():
    for name in TEST_PURPOSE:
        assert family(name, 0.005)
        assert TEST_PURPOSE[name]


def test_the_basis_family_drives_every_tangent_column():
    """A column of DDSDDE that no loading drives is a column no comparison
    can say anything about."""
    segments = family("elastic_basis", 0.005)
    assert len(segments) == 6
    for component, segment in enumerate(segments):
        assert segment.strain[component] != 0
        assert all(v == 0 for i, v in enumerate(segment.strain) if i != component)


def test_monotonic_covers_both_signs():
    """A model with different tensile and compressive responses shows it
    only here."""
    names = {s.name for s in family("monotonic", 0.005)}
    assert names == {"uniaxial", "compression"}


def test_hydrostatic_changes_pressure_and_no_shear():
    """A path that never changes the pressure never reaches a
    pressure-dependent surface."""
    segment, = family("hydrostatic", 0.005)
    assert segment.strain[:3] == (0.005, 0.005, 0.005)
    assert segment.strain[3:] == (0.0, 0.0, 0.0)


def test_load_unload_returns_the_whole_of_the_loading():
    out, back = family("load_unload", 0.005)
    assert [a + b for a, b in zip(out.strain, back.strain)] == [0.0] * 6


def test_cyclic_crosses_zero():
    """Kinematic hardening is invisible to a monotonic path and to a single
    unloading."""
    segments = family("cyclic", 0.005)
    assert any(s.strain[0] < 0 for s in segments)
    assert len(segments) >= 4


def test_an_unknown_test_is_refused_by_name():
    import pytest

    with pytest.raises(ValueError, match="not a test this generator knows"):
        family("teleportation", 0.005)
