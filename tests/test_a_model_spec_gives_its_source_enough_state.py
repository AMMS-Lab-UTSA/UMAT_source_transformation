"""Every higher-order model gives its source at least the state slots it addresses.

UMAT_PCL writes its back stress into STATEV(10:13) (``DO K1=10,2*NTENS+5``),
and its model and example contract gave NSTATV=9: the source wrote past the
driver's array and the run finished anyway. The size is read from the source
(``infer_minimum_dimensions``) and checked for every model, and
``build_model_artifacts`` refuses a model that is too small.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from umat_oti.validation.actual_umat_higher_order_generic import MODELS, state_size_problem

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.mark.parametrize("key", sorted(MODELS))
def test_the_model_gives_the_source_enough_state(key):
    spec = MODELS[key]
    if not (REPO / spec.source).is_file():
        pytest.skip(f"{spec.source} is not shipped")
    assert state_size_problem(spec, REPO) == ""
    contract = json.loads((REPO / spec.config).read_text())
    assert contract.get("nstatv", spec.nstatv) >= spec.nstatv


def test_an_undersized_state_is_caught():
    spec = dataclasses.replace(MODELS["UMAT_PCL"], nstatv=9)
    problem = state_size_problem(spec, REPO)
    assert "NSTATV=9" in problem and "13" in problem
