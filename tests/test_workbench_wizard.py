"""The rules a user meets in the four-step interface, without a browser.

These are the rules that decide what may be asked for and when Run may be
pressed. They are tested here rather than through the page so that a change to
the layout cannot quietly change what the interface permits.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.app.wizard import (
    PRODUCT_HELP, PRODUCT_LABELS, STEPS, Requirement, WizardState, step_titles,
)
from umat_oti.services.workbench import PRODUCTS

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ready(**overrides) -> WizardState:
    state = WizardState(
        source_key="m3_j2", source_path=REPO_ROOT / "parameter_sensitivity"
        / "models" / "m3_j2" / "umat.for",
        analysis={"local_solves": [], "dimensions": {"minimum_ntens": 3}},
        ntens=6, ndi=3, nshr=3, nstatv=1,
        props=(210000.0, 0.3, 250.0, 2000.0),
        parameters=(("E", 1), ("nu", 2), ("SIGY0", 3), ("H", 4)),
        state_names=("EQPLAS",), products=("DSIGMA_DP",),
        loading_label="Uniaxial strain, 20 steps of 1e-4 (small strain)")
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


# --- step numbering ------------------------------------------------------ #
def test_the_step_numbers_are_generated_and_cannot_skip():
    """The numbering was typed into heading strings, and a figure showed 1, 3, 4."""
    titles = step_titles()
    assert len(titles) == len(STEPS)
    assert [t.split(".")[0] for t in titles] == ["1", "2", "3", "4"]


def test_every_step_has_a_plain_language_purpose():
    for name, purpose in STEPS:
        assert purpose.endswith("."), f"{name} has no sentence explaining it"
        assert len(purpose.split()) >= 5


# --- labels -------------------------------------------------------------- #
@pytest.mark.parametrize("product", PRODUCTS)
def test_every_product_has_a_human_label_and_an_explanation(product):
    label, api = PRODUCT_LABELS[product]
    assert label != product, f"{product} is shown only by its API name"
    assert api
    assert len(PRODUCT_HELP[product].split()) >= 8


# --- validation ---------------------------------------------------------- #
def test_an_empty_request_says_what_is_missing_rather_than_failing_silently():
    problems = WizardState().blocking_problems()
    assert problems
    assert any("source" in p.lower() for p in problems)
    assert any("PROPS" in p or "propert" in p.lower() for p in problems)


def test_a_complete_request_has_nothing_blocking_it():
    assert _ready().blocking_problems() == []
    assert _ready().furthest_ready_step() == 3


def test_dimensions_that_do_not_add_up_are_refused_with_the_arithmetic():
    problems = _ready(ndi=3, nshr=2).material_problems()
    assert any("NDI + NSHR must equal NTENS" in p for p in problems)
    assert any("3 + 2 = 5" in p for p in problems)


def test_a_source_that_addresses_beyond_ntens_is_refused():
    state = _ready(ntens=2, ndi=1, nshr=1)
    assert any("writes tensor index 3" in p for p in state.material_problems())


def test_a_parameter_pointing_past_the_property_vector_is_refused():
    problems = _ready(parameters=(("E", 9),)).material_problems()
    assert any("PROPS index 9" in p for p in problems)


def test_sensitivities_without_a_differentiated_parameter_are_refused():
    problems = _ready(parameters=()).request_problems()
    assert any("no material constant is marked" in p for p in problems)


def test_state_sensitivities_without_state_are_refused():
    state = _ready(products=("DSTATEV_DP",), nstatv=0, state_names=())
    assert any("declares no state variables" in p
               for p in state.request_problems())


def test_unresolved_helpers_block_the_source_and_say_where_to_look():
    state = _ready(analysis={"missing_symbols": [{"symbol": "KMAT"}],
                             "local_solves": []})
    problems = state.source_problems()
    assert any("KMAT" in p for p in problems)
    assert any("Advanced settings" in p for p in problems)


def test_ambiguous_helpers_block_the_source_and_explain_why_not_guessing():
    state = _ready(analysis={"ambiguous_symbols": ["KMAT"], "local_solves": []})
    assert any("would change the numerics" in p
               for p in state.source_problems())


# --- prerequisites shown before running ---------------------------------- #
def test_an_internal_jacobian_is_refused_before_the_run_when_there_is_no_solve():
    state = _ready(products=("DSIGMA_DP", "INTERNAL_JACOBIAN"))
    requirements = {r.product: r for r in state.requirements()}
    assert "INTERNAL_JACOBIAN" in requirements
    assert requirements["INTERNAL_JACOBIAN"].word == "UNSUPPORTED"
    assert "without a local Newton iteration" in requirements["INTERNAL_JACOBIAN"].reason
    # and the rest of the request still runs
    assert state.supported_products() == ("DSIGMA_DP",)


def test_an_internal_jacobian_is_allowed_when_the_source_has_a_solve():
    state = _ready(products=("INTERNAL_JACOBIAN",),
                   analysis={"local_solves": [{"iteration_variable": "DEQPL"}]})
    assert state.requirements() == []
    assert state.supported_products() == ("INTERNAL_JACOBIAN",)


def test_higher_order_stress_says_why_it_is_unsupported_here():
    state = _ready(products=("HIGHER_ORDER_STRESS",))
    requirement = state.requirements()[0]
    assert requirement.word == "UNSUPPORTED"
    assert "contract pipeline" in requirement.reason


def test_a_requirement_carries_a_reason_not_just_a_word():
    requirement = Requirement("DDSDDE", "unsupported", "because of a reason")
    assert requirement.word == "UNSUPPORTED"
    assert requirement.reason


# --- progressive disclosure --------------------------------------------- #
def test_a_step_is_not_reachable_before_the_one_before_it_is_complete():
    assert WizardState().furthest_ready_step() == 0
    assert _ready(products=(), loading_label="").furthest_ready_step() == 2
    assert _ready(props=()).furthest_ready_step() == 1
