"""The four-step interface, driven through streamlit.testing.v1.AppTest.

The paper shows screenshots of this interface, so a screenshot is evidence only
if the page runs the same backend as the pipeline, never says a product passed
when it merely built, and refuses a request it cannot honour before making the
user wait for a build. Those are the properties tested here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from umat_oti.app.wizard import STEPS, step_titles
from umat_oti.publication.status import STATUS_MEANINGS
from umat_oti.services.workbench import (
    OUTCOMES, PRODUCTS, LoadingHistory, ProductOutcome, WorkbenchRequest,
    WorkbenchResult,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py"
J2 = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _app(timeout: float = 240.0):
    return AppTest.from_file(str(APP), default_timeout=timeout).run()


def _plain(app) -> str:
    """Everything a reader sees, with the styling stripped.

    Captions, info and warning blocks carry as much of the interface's meaning
    as markdown does, and reading only markdown made a test claim a sentence
    was missing when it was rendered as a caption.
    """
    pieces = []
    for group in ("markdown", "caption", "info", "warning", "error", "success"):
        for element in getattr(app, group, []) or []:
            pieces.append(str(element.value))
    return re.sub(r"<[^>]+>", "", " ".join(pieces))


def _button(app, prefix: str):
    for button in app.button:
        if button.label.startswith(prefix):
            return button
    raise AssertionError(f"no button starting {prefix!r}; "
                         f"have {[b.label for b in app.button]}")


def _pick_example(app, name: str = "m3_j2"):
    option = next(o for o in app.selectbox[0].options if o.startswith(name))
    app.selectbox[0].set_value(option).run()
    return app


def _through_analysis(app, name: str = "m3_j2"):
    _pick_example(app, name)
    _button(app, "Analyse this source").click().run()
    return app


def _to_step(app, index: int, name: str = "m3_j2"):
    """Walk the wizard to a step the way a user would."""
    _through_analysis(app, name)
    for _ in range(index):
        label = "Review and run" if app.subheader[0].value.startswith("3.") \
            else "Next"
        _button(app, label).click().run()
    return app


# --------------------------------------------------------------------------- #
# 1. Step numbering and progressive disclosure
# --------------------------------------------------------------------------- #
def test_the_app_opens_on_step_one_with_nothing_else_showing():
    app = _app()
    assert not app.exception
    assert app.subheader[0].value == "1. Source"
    assert len([s.value for s in app.subheader]) == 1, \
        "more than one step is on screen at once"


def test_the_step_numbers_never_skip():
    """A rendered figure showed 1, 3, 4 because a panel was dropped."""
    app = _app()
    chips = _plain(app)
    for title in step_titles():
        assert title in chips, f"the progress indicator is missing {title!r}"


@pytest.mark.parametrize("index,expected",
                         list(enumerate(step_titles())))
def test_each_step_renders_under_its_own_number(index, expected):
    app = _to_step(_app(), index)
    assert app.subheader[0].value == expected


def test_next_is_disabled_until_the_step_is_complete():
    app = _app()
    assert _button(app, "Next").disabled, \
        "the user can advance without choosing a source"
    _through_analysis(app)
    assert not _button(app, "Next").disabled


def test_back_is_offered_from_the_second_step_onwards():
    assert not any(b.label.startswith("←") for b in _app().button)
    app = _to_step(_app(), 1)
    assert _button(app, "←")


# --------------------------------------------------------------------------- #
# 2. Example selection and automatic population
# --------------------------------------------------------------------------- #
def test_the_example_projects_are_selectable_and_described():
    app = _app()
    options = app.selectbox[0].options
    assert any(o.startswith("m3_j2") for o in options)
    described = next(o for o in options if o.startswith("m3_j2"))
    assert "stress components" in described, \
        "an example is offered without saying what it is"


def test_choosing_an_example_fills_the_material_step_from_its_contract():
    app = _to_step(_app(), 1)
    values = {n.label: n.value for n in app.number_input}
    assert values["NTENS"] == 6
    assert values["NSTATV"] == 1
    assert values["NDI"] + values["NSHR"] == values["NTENS"]


def test_the_interface_says_where_a_prefilled_value_came_from():
    app = _to_step(_app(), 1)
    assert "read from the example's contract" in _plain(app)


def test_an_uploaded_file_prefills_nothing_and_says_so():
    app = _app()
    assert "Nothing is prefilled for an uploaded file" in _plain(app)


# --------------------------------------------------------------------------- #
# 3. Request construction and validation
# --------------------------------------------------------------------------- #
def test_products_are_offered_by_a_human_name_with_the_api_name_beside_it():
    app = _to_step(_app(), 2)
    labels = [c.label for c in app.checkbox]
    assert any("Consistent tangent" in label and "DDSDDE" in label
               for label in labels)
    assert any("Stress sensitivity" in label and "DSIGMA_DP" in label
               for label in labels)


@pytest.mark.parametrize("product", PRODUCTS)
def test_every_product_can_be_requested(product):
    app = _to_step(_app(), 2)
    box = app.checkbox(key=f"product_{product}")
    box.set_value(True).run()
    assert not app.exception
    assert app.checkbox(key=f"product_{product}").value is True


def test_an_unsupported_product_is_reported_before_the_run_not_after():
    """A user must not wait for a build to be told the request was impossible."""
    app = _to_step(_app(), 2)
    app.checkbox(key="product_INTERNAL_JACOBIAN").set_value(True).run()
    text = _plain(app)
    assert "UNSUPPORTED" in text
    assert "without a local Newton iteration" in text


def test_the_rest_of_a_partly_unsupported_request_still_runs():
    app = _to_step(_app(), 2)
    app.checkbox(key="product_INTERNAL_JACOBIAN").set_value(True).run()
    assert "The rest of the request can still run" in _plain(app)


def test_run_is_disabled_and_explained_when_the_request_is_incomplete():
    app = _to_step(_app(), 2)
    for product in PRODUCTS:
        app.checkbox(key=f"product_{product}").set_value(False).run()
    assert "No derivative product is selected" in _plain(app) \
        or any("No derivative product is selected" in w.value
               for w in app.warning)


# --------------------------------------------------------------------------- #
# 4. A real execution
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.fortran
def test_a_real_run_reports_its_stages_products_and_artifacts():
    app = _to_step(_app(timeout=900), 3)
    assert "Nothing has been run yet" in " ".join(i.value for i in app.info)
    _button(app, "Run the pipeline").click().run()
    assert not app.exception

    text = _plain(app)
    assert "PASS" in text, "a completed run reports no passing product"
    assert len(app.tabs) >= len(PRODUCTS), "products are not in separate tabs"
    assert app.dataframe, "the pipeline stages are not shown as a table"
    assert len(app.download_button) >= 3, "the run produced no downloads"


@pytest.mark.slow
@pytest.mark.fortran
def test_primal_parity_is_reported_above_the_derivative_products():
    app = _to_step(_app(timeout=900), 3)
    _button(app, "Run the pipeline").click().run()
    text = _plain(app)
    parity = text.find("Do the two builds agree")
    products = text.find("Derivative products")
    assert parity >= 0 and products > parity, \
        "derivatives are presented before the parity they depend on"


# --------------------------------------------------------------------------- #
# 5. How outcomes are rendered, including the ones a happy run never shows
# --------------------------------------------------------------------------- #
#: A page that renders one synthetic outcome. Built as a script because these
#: outcomes are unreachable from a run that succeeds, and they still have to
#: render correctly: a status nobody can reach is a status nobody has checked.
_OUTCOME_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
from umat_oti.app import workbench_app
from umat_oti.services.workbench import PRODUCTS, ProductOutcome, WorkbenchResult

status = {status!r}
result = WorkbenchResult(request={{"name": "synthetic"}}, analysis={{}})
result.stages = {{"transformed": {{"status": "succeeded", "seconds": 0.1}},
                 "derivatives_verified": {{"status": status,
                                          "reason": "a stated reason",
                                          "seconds": 0.2}}}}
result.primal_parity = {{"status": "succeeded", "worst_relative": 1e-16}}
for product in PRODUCTS:
    result.products[product] = ProductOutcome(
        product, status if product == "DSIGMA_DP" else "not_requested",
        "a stated reason" if product == "DSIGMA_DP" else None)
workbench_app.render_results(result)
"""


@pytest.mark.parametrize("status,word", [
    ("failed", "FAILED"),
    ("unresolved", "WITHHELD"),
    ("partial", "PARTIAL"),
    ("blocked", "BLOCKED"),
    ("unsupported", "UNSUPPORTED"),
    ("compiled", "BLOCKED"),
])
def test_a_non_passing_outcome_shows_its_word_and_its_reason(status, word):
    """Every one of these is unreachable from a happy run, and must still read."""
    script = _OUTCOME_SCRIPT.format(src=str(REPO_ROOT / "src"), status=status)
    app = AppTest.from_string(script, default_timeout=90).run()
    assert not app.exception, app.exception
    text = _plain(app)
    assert word in text, f"{status} did not render as {word}"
    assert "a stated reason" in text or STATUS_MEANINGS[word][:24] in text


def test_no_outcome_is_carried_by_colour_alone():
    from umat_oti.app.workbench_app import BADGE_CLASS
    from umat_oti.publication.status import STATUS_WORDS

    for word in set(STATUS_WORDS.values()):
        assert word in STATUS_MEANINGS, f"{word} has no words explaining it"
    assert set(BADGE_CLASS) <= set(STATUS_MEANINGS), \
        "a badge style exists for a word with no meaning"


def test_building_is_never_reported_as_verification():
    from umat_oti.publication.status import status_word
    assert status_word("compiled") == "BLOCKED"
    assert "not verification" in STATUS_MEANINGS["BLOCKED"]


def test_every_backend_outcome_can_be_displayed():
    from umat_oti.publication.status import STATUS_WORDS
    missing = [o for o in OUTCOMES if o not in STATUS_WORDS]
    assert not missing, f"the interface cannot display: {missing}"


# --------------------------------------------------------------------------- #
# 6. The request the interface builds is the canonical one
# --------------------------------------------------------------------------- #
def test_the_interface_builds_the_same_request_object_as_the_cli():
    from umat_oti.app.workbench_app import _build_request
    from umat_oti.app.wizard import WizardState

    state = WizardState(
        source_key="m3_j2", source_path=J2,
        analysis={"local_solves": []}, ntens=6, ndi=3, nshr=3, nstatv=1,
        props=(210000.0, 0.3, 250.0, 2000.0),
        parameters=(("E", 1),), state_names=("EQPLAS",),
        products=("DSIGMA_DP",),
        loading_label="Uniaxial strain, 20 steps of 1e-4 (small strain)")
    request = _build_request(state)
    assert isinstance(request, WorkbenchRequest)
    assert request.validate() == []
    assert isinstance(request.loading, LoadingHistory)
    assert request.loading.provenance, "the loading history records no source"


def test_no_result_number_is_written_into_the_page():
    """The page must not carry a value that did not come from a run."""
    source = APP.read_text(encoding="utf-8")
    for suspicious in ("2.639e-16", "2.48e-08", "13947", "13980",
                       "verified\", \"PASS"):
        assert suspicious not in source, f"{suspicious!r} is hardcoded in the page"


# --------------------------------------------------------------------------- #
# 7. Regressions the redesign introduced, and their guards
# --------------------------------------------------------------------------- #
def test_the_parity_sentence_actually_carries_its_number():
    """The funnel records worst_relative_difference; a shorter name printed nothing."""
    script = _OUTCOME_SCRIPT.format(src=str(REPO_ROOT / "src"), status="verified")
    script = script.replace(
        '{"status": "succeeded", "worst_relative": 1e-16}',
        '{"status": "succeeded", "worst_relative_difference": 2.639e-16}')
    app = AppTest.from_string(script, default_timeout=90).run()
    assert not app.exception, app.exception
    assert "2.639e-16" in _plain(app), \
        "primal parity claims agreement without saying how close"


def test_the_result_carries_the_stage_it_reached():
    """`getattr(result, 'furthest_stage', None)` was always None."""
    from umat_oti.services.workbench import WorkbenchResult

    result = WorkbenchResult(request={}, analysis={})
    assert hasattr(result, "furthest_stage")
    result.furthest_stage = "derivatives_verified"
    assert result.as_dict()["furthest_stage"] == "derivatives_verified"


def test_a_built_but_unverified_product_is_distinguishable_from_a_blocked_one():
    """Both print BLOCKED, so the reason has to carry the difference."""
    from umat_oti.publication.status import STATUS_MEANINGS, status_word

    assert status_word("compiled") == status_word("blocked") == "BLOCKED"
    assert "not verification" in STATUS_MEANINGS["BLOCKED"]

    script = _OUTCOME_SCRIPT.format(src=str(REPO_ROOT / "src"), status="compiled")
    script = script.replace('"a stated reason"',
                            '"the run stopped before the comparison. '
                            'Compiling is not verification."')
    app = AppTest.from_string(script, default_timeout=90).run()
    text = _plain(app)
    assert "Compiling is not verification" in text


def test_the_pipeline_table_shows_every_stage_it_was_given():
    """A table that scrolls inside itself photographs as a run that stopped."""
    import inspect

    from umat_oti.app import workbench_app

    source = inspect.getsource(workbench_app._pipeline_table)
    assert "height=" in source, \
        "the stage table has no explicit height, so it will scroll internally"
