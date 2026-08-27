"""One place that decides how large a figure is on the page.

Every configured point size in a plot is multiplied by the ratio of the width
it was authored at to the width it is placed at. The two were different -- the
plots were authored at 7.0 inches and placed at 6.20 -- so every label was
printed at 88.6% of its configured size and the whole set fell below the 9 pt
floor while every generator reported that it was above it.

Authoring at the placement width removes the multiplication entirely: a size
configured here is the size that reaches the page.
"""

from __future__ import annotations

#: The width every main-text figure is authored at AND placed at. Changing this
#: changes both, so they cannot drift apart again.
FIGURE_WIDTH_IN = 6.2

#: A figure taller than this cannot share a page with its caption.
MAX_FIGURE_HEIGHT_IN = 8.2

#: The floor every rendered glyph in a figure must clear.
MIN_RENDERED_PT = 9.0

#: Base sizes for plot text. A 2x2 grid at FIGURE_WIDTH_IN gives each panel
#: about three inches, so the type can be much larger than a four-across strip
#: allowed -- and it needs to be: at 9 pt in a 1.5 inch panel nothing reads.
#: These are the sizes as printed, since figures are authored at the width
#: they are placed at.
BODY_TEXT_PT = 13.0
CAPTION_PT = 12.0

#: The interface's smallest text, in CSS pixels. Streamlit's own label tier is
#: 14 px, which prints below the floor at any usable viewport, so the interface
#: raises every tier to at least this.
GUI_MIN_TEXT_PX = 17

#: The viewport a publication screenshot is captured at. Narrower than the
#: laptop widths the interface must remain usable at, because the two are
#: different questions: this one is "how large does this text print", and that
#: one is "does anything overflow".
SCREENSHOT_VIEWPORT_PX = 820

#: Viewports the interface must remain usable at, without horizontal scrolling.
SUPPORTED_VIEWPORTS: tuple[tuple[int, int], ...] = ((1366, 768), (1440, 900))


def printed_point_size(configured_pt: float, authored_width_in: float = FIGURE_WIDTH_IN,
                       placed_width_in: float = FIGURE_WIDTH_IN) -> float:
    """What a configured size actually measures once the figure is placed."""
    if authored_width_in <= 0:
        raise ValueError("a figure cannot be authored at zero width")
    return configured_pt * placed_width_in / authored_width_in


def css_pixels_for_point_size(target_pt: float, css_text_px: float,
                              placed_width_in: float = FIGURE_WIDTH_IN) -> float:
    """The widest viewport whose text still prints at ``target_pt``.

    A screenshot's printed text size is set by how much of the figure's width
    one CSS pixel occupies, never by the capture resolution: capturing at a
    higher device scale makes text sharper, not bigger.
    """
    if target_pt <= 0:
        raise ValueError("a target point size must be positive")
    return css_text_px * placed_width_in * 72.0 / target_pt
