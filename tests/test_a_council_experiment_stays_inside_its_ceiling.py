"""Ceilings of a council-designed experiment (G4, D-19a rev 2 R3).

The amplitude search and the extension ladder take the council ceiling --
the documented strain/stretch domain, or 0.02 small strain / 0.2 finite --
through ``amplitude_search.capped``, which never exceeds CEILING; with
ceiling = CEILING (every author deck) they behave exactly as before. A
routine-level path beyond a documented strain_max, stretch_max or TEMP is
labelled outside_model_domain and gives no verdict.
"""
import numpy as np
import pytest

from umat_oti.abaqus.amplitude_search import (CEILING, LINEAR_TO_THE_CEILING, capped,
                                              search_amplitude)
from umat_oti.corpus_features.loading_paths import (OUTSIDE_MODEL_DOMAIN, _within_domain,
                                                    model_domain, paths_for)

pytestmark = pytest.mark.unit


def _linear(tried):
    def run(amplitude):
        tried.append(amplitude)
        return True, [{"step": 1, "increment": n, "element": 1, "point": 1, "time": n * 0.1,
                       "STRESS": [amplitude * 1000.0], "STATEV": [0.0]}
                      for n in range(1, 7)], ""
    return run


def test_capped_never_exceeds_the_ceiling_or_CEILING():
    assert capped(0.5, 0.02) == 0.02
    assert capped(0.01, 0.02) == 0.01
    assert capped(3.0) == CEILING and capped(3.0, 7.0) == CEILING


@pytest.mark.parametrize("ceiling", [0.02, 0.2])
def test_a_mocked_search_never_runs_above_the_council_ceiling(ceiling):
    tried: list = []
    result = search_amplitude(_linear(tried), ceiling=ceiling)
    assert max(tried) <= ceiling
    assert result.outcome == LINEAR_TO_THE_CEILING
    assert f"linear to {ceiling:.3g}" in result.summary()


def test_the_author_ceiling_is_unchanged():
    a: list = []
    b: list = []
    one = search_amplitude(_linear(a))
    two = search_amplitude(_linear(b), ceiling=CEILING)
    assert a == b and one.as_dict() == two.as_dict()
    assert "ceiling" not in one.as_dict()


def _entry(**kw):
    base = {"source_id": "someone__repo/umat.f", "family": "plasticity", "ntens": 6,
            "kinematics": "small strain", "props": [200000.0, 0.3, 250.0, 1000.0],
            "source_text": "      SUBROUTINE UMAT(STRESS)\n      END\n",
            "activation_amplitude": 0.01}
    base.update(kw)
    return base


def _stated(value):
    return {"value": value, "where": "paper.pdf p. 3", "quote": "tested up to"}


def test_a_path_beyond_the_documented_strain_is_outside_the_domain():
    entry = _entry(documented_domain={"strain_max": _stated(0.004), "stretch_max": None,
                                      "temperature": None})
    dom = model_domain(entry)
    assert dom["strain_max"] == 0.004 and any("strain_max 0.004" in w for w in dom["witnesses"])
    paths = paths_for(entry)
    outside = [p for p in paths if p.purpose == OUTSIDE_MODEL_DOMAIN]
    inside = [p for p in paths if p.purpose != OUTSIDE_MODEL_DOMAIN]
    assert outside and all("documented" in p.provenance["outside_model_domain"] for p in outside)
    from umat_oti.corpus_features.loading_paths import _peaks
    assert all(_peaks(p)[0] <= 0.004 * (1 + 1e-9) for p in inside)
    assert all(_peaks(p)[0] > 0.004 or p.twin for p in outside)


def test_no_documented_domain_changes_nothing():
    plain = paths_for(_entry())
    empty = paths_for(_entry(documented_domain={"strain_max": None, "stretch_max": None,
                                                "temperature": None}))
    assert [(p.name, p.purpose, len(p.increments)) for p in plain] == \
        [(p.name, p.purpose, len(p.increments)) for p in empty]


def test_temperature_and_stretch_witnesses_relabel_a_path():
    from umat_oti.corpus_features.loading_paths import Increment, LoadingPath
    hot = LoadingPath(name="hot", regime="elastic", kinematics="finite",
                      increments=[Increment(None, ((1.3, 0, 0), (0, 1, 0), (0, 0, 1)),
                                            1.0, 400.0, 10.0)])
    dom = {"stretch_max": 1.2, "temperature": (290.0, 420.0),
           "time_provenance": "", "witnesses": [], "unbounded_branches": []}
    (out,) = _within_domain([hot], dom)
    assert out.purpose == OUTSIDE_MODEL_DOMAIN
    assert "peak stretch 1.3 > 1.2" in out.provenance["outside_model_domain"]
    dom["stretch_max"] = 1.5
    (out,) = _within_domain([hot], dom)
    assert out.purpose != OUTSIDE_MODEL_DOMAIN
    dom["temperature"] = (290.0, 405.0)
    (out,) = _within_domain([hot], dom)
    assert "TEMP 400..410 outside 290..405" in out.provenance["outside_model_domain"]


def test_a_domain_stated_in_words_is_recorded_and_not_enforced():
    words = "per the driver format: 500 increments of -0.001 (up to -0.5)"
    entry = _entry(documented_domain={"strain_max": _stated(words), "stretch_max": None,
                                      "temperature": _stated("room temperature")})
    dom = model_domain(entry)
    assert "strain_max" not in dom and "temperature" not in dom
    assert sum("not a number, not enforced" in w for w in dom["witnesses"]) == 2
    assert [p.purpose for p in paths_for(entry)] == [p.purpose for p in paths_for(_entry())]
