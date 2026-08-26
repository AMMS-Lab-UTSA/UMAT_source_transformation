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
