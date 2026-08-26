"""The Streamlit workbench, driven through streamlit.testing.v1.AppTest.

The point of testing the interface is that the paper shows screenshots of it. A
screenshot is evidence only if the page runs the same backend as the pipeline
and never says "verified" for something that merely compiled, so those are the
properties tested here rather than the layout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.services.workbench import (
    OUTCOMES, PRODUCTS, LoadingHistory, WorkbenchRequest, analyse_source,
    run_workbench,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py"
J2 = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _app(timeout: float = 60.0):
    app = AppTest.from_file(str(APP), default_timeout=timeout)
    return app.run()


def _canonical_request(tmp_path: Path, **overrides) -> WorkbenchRequest:
    defaults = dict(
        name="m3_j2", source_path=J2, ntens=6, nstatv=1, ndi=3, nshr=3,
        props=(200000.0, 0.3, 250.0, 2000.0),
        parameters=(("E", 1), ("nu", 2), ("sy0", 3), ("H", 4)),
        state_names=("EQPLAS",),
        loading=LoadingHistory(dstran_per_increment=(1e-4, 0, 0, 0, 0, 0),
                               n_increments=4, label="test"),
        products=("DSIGMA_DP",))
    defaults.update(overrides)
    return WorkbenchRequest(**defaults)


# 1. the app loads a canonical contract ------------------------------------

def test_app_loads_and_offers_the_example_projects():
    app = _app()
    assert not app.exception
    labels = [option for box in app.selectbox for option in box.options]
    assert "m3_j2" in labels, "the canonical example project is not selectable"


def test_selecting_an_example_shows_its_detected_source_information():
    app = _app()
    app.selectbox(key="source_choice").select("m3_j2").run()
    assert not app.exception
    text = " ".join(str(m.value) for m in app.markdown)
    assert "Helper routines detected" in text


# 2. every derivative-request type can be constructed ----------------------

@pytest.mark.parametrize("product", PRODUCTS)
def test_every_product_can_be_requested(product):
    app = _app()
    app.selectbox(key="source_choice").select("m3_j2").run()
    box = app.checkbox(key=f"product_{product}")
    box.set_value(True).run()
    assert not app.exception
    assert app.checkbox(key=f"product_{product}").value is True


def test_the_request_model_accepts_every_product():
    request = _canonical_request(Path("."), products=PRODUCTS)
    assert request.validate() == []


# 3. missing and inconsistent inputs are rejected --------------------------

def test_inconsistent_dimensions_are_reported():
    request = _canonical_request(Path("."), ntens=6, ndi=3, nshr=2)
    problems = request.validate()
    assert any("NDI + NSHR must equal NTENS" in p for p in problems)


def test_a_parameter_outside_the_property_vector_is_reported():
    request = _canonical_request(Path("."), parameters=(("E", 9),))
    assert any("outside the 4 properties" in p for p in request.validate())


def test_requesting_state_sensitivity_without_state_is_reported():
    request = _canonical_request(Path("."), nstatv=0, products=("DSTATEV_DP",))
    assert any("declares no state variables" in p for p in request.validate())


def test_a_missing_source_file_is_reported():
    request = _canonical_request(Path("."), source_path=Path("/no/such/umat.for"))
    assert any("source file not found" in p for p in request.validate())


def test_validation_reports_every_problem_not_just_the_first():
    request = _canonical_request(Path("."), ntens=6, ndi=1, nshr=1,
                                 props=(), products=())
    assert len(request.validate()) >= 3


# 4 and 5. the real backend, and its failures reaching the interface -------

@pytest.mark.slow
@pytest.mark.fortran
def test_the_backend_runs_and_reports_primal_parity_before_derivatives(tmp_path):
    result = run_workbench(_canonical_request(tmp_path), tmp_path)
    assert result.errors == []
    assert result.primal_parity.get("status") == "succeeded"
    assert result.products["DSIGMA_DP"].status == "verified"
    stages = list(result.stages)
    assert stages.index("primal_parity") < stages.index("derivatives_verified")


def test_a_backend_failure_propagates_instead_of_being_swallowed(tmp_path):
    broken = tmp_path / "broken.for"
    broken.write_text("      SUBROUTINE NOTAUMAT(X)\n      END\n", encoding="utf-8")
    result = run_workbench(
        _canonical_request(tmp_path, source_path=broken, name="broken"), tmp_path)
    blocked = [o for o in result.products.values() if o.status == "blocked"]
    assert blocked, "a source with no UMAT entry must block its products"
    assert all(o.reason for o in blocked), "a blocked product must say why"


# 6. statuses are displayed, and compiled is never verified ----------------

def test_compiled_is_a_distinct_outcome_from_verified():
    from umat_oti.app.workbench_app import OUTCOME_BADGES

    assert "compiled" in OUTCOMES and "verified" in OUTCOMES
    word, meaning = OUTCOME_BADGES["compiled"]
    assert word != OUTCOME_BADGES["verified"][0]
    assert "Nothing verified" in meaning


def test_every_outcome_has_a_badge_and_a_plain_word():
    from umat_oti.app.workbench_app import OUTCOME_BADGES

    for outcome in OUTCOMES:
        word, meaning = OUTCOME_BADGES[outcome]
        # Colour must never be the only signal.
        assert word.strip() and meaning.strip()


def test_not_requested_is_distinct_from_blocked(tmp_path):
    result = run_workbench(
        _canonical_request(tmp_path, products=("DSIGMA_DP",)), tmp_path)
    assert result.products["HIGHER_ORDER_STRESS"].status == "not_requested"
    assert result.products["HIGHER_ORDER_STRESS"].status != "blocked"


# 7. artifacts are downloadable -------------------------------------------

@pytest.mark.slow
@pytest.mark.fortran
def test_artifacts_exist_and_are_readable(tmp_path):
    result = run_workbench(
        _canonical_request(tmp_path, products=("DSIGMA_DP", "DSTATEV_DP")), tmp_path)
    for name in ("transformed_source", "dsigma_csv", "primal_csv",
                 "result_manifest"):
        assert name in result.artifacts, name
        assert Path(result.artifacts[name]).is_file()
    manifest = json.loads(Path(result.artifacts["result_manifest"]).read_text())
    assert manifest["products"]["DSIGMA_DP"]["status"] == "verified"


# 8. no hardcoded result numbers ------------------------------------------

def test_the_interface_contains_no_hardcoded_results():
    """A number baked into the page would survive a run that produced another."""
    import re

    text = (REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py").read_text()
    # Strip the loading presets, whose step sizes are inputs rather than results.
    text = re.sub(r"LOADING_PRESETS.*?\n\}\n", "", text, flags=re.DOTALL)
    suspicious = re.findall(r"\d+\.\d*[eE][+-]?\d+", text)
    assert not suspicious, f"result-like literals in the interface: {suspicious}"
    for word in ("13415", "13420", "verified: 17", "2.48e-08"):
        assert word not in text


def test_the_interface_defines_no_numerical_logic():
    """All numerics live in the service; the page renders what it is given."""
    text = (REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py").read_text()
    for forbidden in ("centered_fd", "np.linalg", "tolerance =", "rel_step",
                      "primal_parity(", "compare("):
        assert forbidden not in text, f"{forbidden} belongs in the service layer"
