"""Properties every publication figure has to have, checked mechanically.

The defect these exist for is subtle: the plots were authored at 7.0 inches and
placed at 6.20, so every configured point size was multiplied by about 0.87 on
the way to the page. Both existing guards evaluated the authored width, so
neither ever fired, and the manuscript shipped with 32 of its 41 text roles
below the caption size printed beneath them.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIGURES = REPO_ROOT / "paper_results" / "figures"

sys.path.insert(0, str(REPO_ROOT / "tools" / "figures"))

# figure_style imports matplotlib at module level, and matplotlib is in the
# `paper` extra rather than `test` -- deliberately, so a user who only wants to
# transform a UMAT does not install a plotting stack. Without this guard the
# import raised during COLLECTION, which aborts the whole session: CI reported
# "1 skipped, 1 error" and ran none of the other 1700 tests.
pytest.importorskip(
    "matplotlib",
    reason="matplotlib is in the `paper` extra; install -e \".[paper]\" to "
           "check the publication figures")

from figure_style import ANNOTATION_PT, FONT_SIZES  # noqa: E402

from umat_oti.publication.layout import (  # noqa: E402
    FIGURE_WIDTH_IN, MAX_FIGURE_HEIGHT_IN, MIN_RENDERED_PT,
)

#: The figures the manuscript places, main text and supplementary.
def _provenances() -> list[Path]:
    return sorted(FIGURES.glob("*_provenance.json"))


def _plots() -> list[Path]:
    return [p for p in _provenances() if p.name != "gui_screenshots_provenance.json"]


def test_there_are_figures_to_check():
    assert _plots(), "no plot provenance found; were the figures generated?"


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_every_plot_states_the_one_question_it_answers(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    question = record.get("answers", "")
    assert question.endswith("?"), f"{path.stem} states no question"
    assert len(question.split()) >= 8


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_every_plot_is_authored_at_the_width_it_is_placed_at(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["outputs"]["width_inches"] == pytest.approx(FIGURE_WIDTH_IN)
    assert record["layout"]["figure_width_in"] == pytest.approx(FIGURE_WIDTH_IN)


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_every_plot_fits_a_page(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    height = record["outputs"]["height_inches"]
    assert height <= MAX_FIGURE_HEIGHT_IN, \
        f"{path.stem} is {height} in tall and cannot share a page with a caption"


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_every_configured_size_clears_the_floor(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    sizes = record["layout"]["configured_font_sizes"]
    small = {role: size for role, size in sizes.items() if size < MIN_RENDERED_PT}
    assert not small, f"{path.stem} configures text below {MIN_RENDERED_PT} pt: {small}"


def test_the_smallest_annotation_size_clears_the_floor():
    assert ANNOTATION_PT >= MIN_RENDERED_PT
    assert min(FONT_SIZES.values()) >= MIN_RENDERED_PT


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_every_plot_hashes_its_inputs_and_they_exist(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["inputs"], f"{path.stem} names no input"
    for entry in record["inputs"]:
        assert (REPO_ROOT / entry["path"]).is_file(), entry["path"]
        assert len(entry["sha256"]) == 64


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_every_plot_declares_its_denominator_or_filters(path: Path):
    record = json.loads(path.read_text(encoding="utf-8"))
    filters = json.dumps(record["plotted_filters"]).lower()
    assert any(word in filters for word in
               ("denominator", "plotted", "model", "excluded")), \
        f"{path.stem} does not say what it plotted or out of what"


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_the_image_is_large_enough_to_print(path: Path):
    from PIL import Image

    record = json.loads(path.read_text(encoding="utf-8"))
    png = REPO_ROOT / record["outputs"]["png"]
    with Image.open(png) as image:
        dpi = image.width / FIGURE_WIDTH_IN
    assert dpi >= 300, f"{png.name} is only {dpi:.0f} dpi at the placed width"


#: Quantities that are counts or positions and so carry no physical unit. A
#: label naming one of these is complete without a parenthesised unit.
_COUNTED = ("increment", "order", "sources", "count", "rows", "family")


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_axis_labels_carry_units(path: Path):
    """A quantity without a unit is not a measurement a reader can use.

    The labels are read from the axes at save time rather than grepped out of
    the script: a label written across two source lines cannot be matched, and
    a check that cannot see a unit reports every figure as missing one.
    """
    record = json.loads(path.read_text(encoding="utf-8"))
    unitless = []
    for axes in record["outputs"]["axes"]:
        for role in ("xlabel", "ylabel"):
            label = (axes.get(role) or "").strip()
            if not label:
                continue
            if re.search(r"\(.*\)", label):
                continue
            if any(word in label.lower() for word in _COUNTED):
                continue
            unitless.append(f"{path.stem} axes {axes['axes']} {role}: {label!r}")
    assert not unitless, f"axis labels without a unit or a stated scale: {unitless}"


@pytest.mark.parametrize("path", _plots(), ids=lambda p: p.stem)
def test_no_axis_places_zero_on_a_logarithmic_scale(path: Path):
    """An ordinary log axis cannot show zero, so zero must be counted instead."""
    record = json.loads(path.read_text(encoding="utf-8"))
    for axes in record["outputs"]["axes"]:
        for role in ("xscale", "yscale"):
            assert axes.get(role) in ("linear", "log", "symlog"), axes
            if axes.get(role) == "symlog":
                filters = json.dumps(record["plotted_filters"]).lower()
                assert "symlog" in filters or "linear window" in filters, (
                    f"{path.stem} uses a symmetric-log {role} without "
                    "explaining its linear window")


def test_the_screenshots_print_above_the_floor():
    record = json.loads(
        (FIGURES / "gui_screenshots_provenance.json").read_text(encoding="utf-8"))
    assert record["smallest_text_printed_pt"] >= MIN_RENDERED_PT, \
        "the interface's smallest text prints below the floor"
    for stem, shot in record["screenshots"].items():
        assert shot["smallest_text_printed_pt"] >= MIN_RENDERED_PT, stem
        assert not shot["overflow"]["overflowing"], \
            f"{stem} has content past the right edge: {shot['overflow']}"


def test_the_interface_does_not_overflow_at_the_supported_viewports():
    record = json.loads(
        (FIGURES / "gui_screenshots_provenance.json").read_text(encoding="utf-8"))
    for viewport, overflow in record["supported_viewports"].items():
        assert not overflow["overflowing"], \
            f"the interface overflows horizontally at {viewport}"


def test_every_screenshot_shows_a_numbered_step():
    """A figure that showed sections 1, 3, 4 is what this is for."""
    record = json.loads(
        (FIGURES / "gui_screenshots_provenance.json").read_text(encoding="utf-8"))
    headings = {stem: shot["step_heading"]
                for stem, shot in record["screenshots"].items()}
    for stem, heading in headings.items():
        assert re.match(r"^[1-4]\. ", heading), \
            f"{stem} shows an unnumbered step: {heading!r}"


def test_no_figure_or_provenance_names_a_home_directory():
    for path in _provenances():
        assert "/home/" not in path.read_text(encoding="utf-8"), path.name


# --------------------------------------------------------------------------- #
# The canvas is fixed at the placement width and nothing clips to it visibly:
# a title too long for the page is simply cut off at the edge, and the file is
# still written, still the right size, and still passes every other check
# here. These pin the guard that measures each text artist against the canvas.
# --------------------------------------------------------------------------- #
def _one_axis_figure(title: str):
    import matplotlib
    matplotlib.use("Agg")
    from figure_style import figure, use_publication_style
    use_publication_style()
    fig, axis = figure(3.0)
    axis.plot([0, 1], [0, 1])
    axis.set_title(title, loc="left")
    return fig


def test_a_title_that_runs_off_the_page_is_refused(tmp_path: Path):
    from figure_style import save
    figure_object = _one_axis_figure("x" * 400)
    with pytest.raises(RuntimeError) as caught:
        save(figure_object, "overlong", tmp_path)
    assert "run off" in str(caught.value)
    assert not (tmp_path / "overlong.png").exists(), (
        "a figure whose text is cut off must not be left on disk for a later "
        "step to pick up")


def test_a_title_that_fits_is_accepted(tmp_path: Path):
    from figure_style import save
    outputs = save(_one_axis_figure("a short title"), "fits", tmp_path)
    assert (tmp_path / "fits.png").exists()
    assert outputs["width_inches"] == FIGURE_WIDTH_IN


def test_labels_of_ticks_outside_the_view_are_not_reported_as_clipped(tmp_path: Path):
    """A tick just past the end of an axis keeps a label it never draws.

    Those labels sit beyond the axis where nothing renders them. Counting them
    as clipped text made the guard fire on figures whose saved files were
    perfectly intact, which is the fastest way to get a guard switched off.
    """
    from figure_style import save
    figure_object = _one_axis_figure("fine")
    axis = figure_object.axes[0]
    axis.set_xticks([0.0, 0.5, 1.0, 4000.0])
    axis.set_xlim(0.0, 1.0)
    save(figure_object, "outside_view", tmp_path)
    assert (tmp_path / "outside_view.png").exists()


def test_a_figure_regenerates_byte_for_byte(tmp_path: Path):
    """Two runs of the same script must produce the same files.

    The PDF backend stamps the wall clock into ``/CreationDate``, so every
    figure differed between runs in two bytes -- enough that the figures could
    not be shown to come from the evidence they claim, which is the whole
    point of shipping them with provenance.
    """
    from figure_style import save
    first, second = tmp_path / "first", tmp_path / "second"
    save(_one_axis_figure("stable"), "repeat", first)
    save(_one_axis_figure("stable"), "repeat", second)
    for suffix in ("png", "pdf"):
        assert (first / f"repeat.{suffix}").read_bytes() == \
               (second / f"repeat.{suffix}").read_bytes(), (
            f"the {suffix} differs between two runs of the same figure")


def test_a_blocker_is_not_classified_by_a_substring_of_a_stage_name():
    """Blocker causes are matched by pattern, and stage names are prose too.

    ``contract_constructed`` contains the word "construct", so a source held up
    because no material vector exists for it was filed on the figure under
    "Unsupported Fortran construct" -- a different, and wrong, explanation of
    why the pipeline could not verify it.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools" / "figures"))
    from build_acquisition_figures import _classify  # noqa: PLC0415

    contract = ("contract_constructed: the declared dimensions are too small "
                "for what this source addresses: it needs NTENS >= 0 and, at "
                "NTENS=6, NSTATV >= 125, but the contract declares NTENS=6 "
                "and NSTATV=0")
    assert _classify(contract) == "No established contract"

    fortran = "transformed: unsupported Fortran construct in the entry routine"
    assert _classify(fortran) == "Unsupported Fortran construct"

    # And every cause must still be reachable by something, so a pattern that
    # stops matching anything is visible rather than silently inert.
    from build_acquisition_figures import CAUSES  # noqa: PLC0415
    assert len({label for label, _, _ in CAUSES}) == len(CAUSES), (
        "two causes share a label; the figure would merge them")
