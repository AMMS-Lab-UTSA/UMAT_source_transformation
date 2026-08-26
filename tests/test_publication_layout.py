"""The size a figure is authored at must be the size it is placed at.

This is the defect that made every plot label in the manuscript print below the
9 pt floor while every generator reported it was above: the plots were authored
at 7.0 inches and placed at 6.20, so every configured point size was silently
multiplied by 0.886. Nothing in the code connected the two numbers, so nothing
could notice.
"""
from __future__ import annotations

import pytest

from umat_oti.publication import (
    BODY_TEXT_PT, CAPTION_PT, FIGURE_WIDTH_IN, MIN_RENDERED_PT,
    STATUS_MEANINGS, STATUS_WORDS, css_pixels_for_point_size,
    printed_point_size, status_word,
)


def test_authoring_at_the_placement_width_is_a_no_op():
    assert printed_point_size(10.0) == pytest.approx(10.0)


def test_the_historical_mismatch_would_be_caught():
    """7.0 authored, 6.20 placed: a 10 pt label reaching the page at 8.9 pt."""
    printed = printed_point_size(10.0, authored_width_in=7.0, placed_width_in=6.2)
    assert printed < MIN_RENDERED_PT
    assert printed == pytest.approx(8.857, abs=1e-3)


def test_the_base_sizes_clear_the_floor():
    for size in (BODY_TEXT_PT, CAPTION_PT):
        assert printed_point_size(size) >= MIN_RENDERED_PT


def test_a_wider_viewport_prints_smaller_text():
    """The relationship the screenshot capture has to obey."""
    narrow = css_pixels_for_point_size(9.0, css_text_px=16)
    wide = css_pixels_for_point_size(12.0, css_text_px=16)
    assert wide < narrow


def test_a_screenshot_viewport_can_be_computed_for_a_target_size():
    viewport = css_pixels_for_point_size(9.0, css_text_px=18)
    # 18 px text in that viewport, placed at the figure width, prints at 9 pt.
    assert 18 / viewport * FIGURE_WIDTH_IN * 72 == pytest.approx(9.0)


def test_zero_or_negative_geometry_is_refused():
    with pytest.raises(ValueError):
        printed_point_size(10.0, authored_width_in=0.0)
    with pytest.raises(ValueError):
        css_pixels_for_point_size(0.0, css_text_px=16)


@pytest.mark.parametrize("outcome,word", sorted(STATUS_WORDS.items()))
def test_every_backend_outcome_maps_to_a_defined_word(outcome, word):
    assert status_word(outcome) == word
    assert word in STATUS_MEANINGS, f"{word} has no meaning defined"


def test_the_required_vocabulary_is_complete():
    required = {"PASS", "PARTIAL", "WITHHELD", "NOT REQUESTED", "UNSUPPORTED",
                "FAILED", "BLOCKED"}
    assert required <= set(STATUS_WORDS.values())


def test_an_undefined_outcome_looks_undefined():
    """It must not be silently mapped to something reassuring."""
    assert status_word("something_new") == "SOMETHING NEW"
    assert "something_new" not in STATUS_WORDS
