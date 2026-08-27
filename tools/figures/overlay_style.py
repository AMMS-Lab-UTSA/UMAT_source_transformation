"""The overlay idiom: plot the derivative, put the reference on top of it.

An error plot answers "how big is the error". A reader wants to see the
derivative itself, in the units it is measured in, with the independent
reference drawn over it -- agreement is then something you see rather than a
number you have to interpret. That is how these results read best, and the
error numbers belong in the tables, where they can be read exactly.

Small multiples do the rest of the work: one row per quantity, each with its
own y-scale, which is also why no second axis or rescaling trick is needed for
a curve that is three orders of magnitude smaller than its neighbours.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "figures"))
from figure_style import ANNOTATION_PT, PALETTE  # noqa: E402

#: Line for the generated value, open marker for the independent reference.
GENERATED_KW = dict(linewidth=2.4, zorder=3)
REFERENCE_KW = dict(linestyle="none", marker="o", markersize=8.0,
                    markerfacecolor="none", markeredgewidth=1.8, zorder=4)

#: Line styles, so the series survive greyscale and colour-deficient vision
#: without relying on hue.
DASHES = ["-", "--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 2))]

#: How many reference markers to draw. Every point makes a solid band; a
#: regular subset reads as "the reference sits on the line" at a glance.
MARKER_EVERY = 2


def series_colour(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


def draw_overlay(axis, x, generated, reference, colour, label=None,
                 marker_every: int = MARKER_EVERY, style: int = 0):
    """One series: the generated curve, with the reference drawn over it.

    A series with a single point is drawn as a filled dot: a line through one
    point renders as nothing at all, which would silently drop the comparison
    from the figure while the provenance still counted it.
    """
    kw = dict(GENERATED_KW)
    if len(x) < 2:
        kw.update(marker="o", markersize=5.0)
    axis.plot(x, generated, color=colour, label=label,
              linestyle=DASHES[style % len(DASHES)], **kw)
    if reference is not None:
        step = max(1, marker_every) if len(x) > 1 else 1
        axis.plot(x[::step], reference[::step], color=colour, **REFERENCE_KW)


def row_label(axis, text: str) -> None:
    """The big left-hand label that names the row, in a neutral colour.

    Neutral deliberately: colour already means the series, and colouring the
    row label as well invites a reader to look for a mapping that is not there.
    """
    axis.set_ylabel(text, rotation=0, ha="right", va="center", labelpad=14,
                    fontsize=ANNOTATION_PT + 5, color="0.2")


def method_legend(figure, axes, component_labels, colours, *, ncol=None,
                  y=0.005, reference_label="finite difference"):
    """One legend for the whole figure: the series, then what line and marker mean."""
    from matplotlib.lines import Line2D

    handles = [Line2D([], [], color=colour, linewidth=3.2,
                      linestyle=DASHES[i % len(DASHES)], label=label)
               for i, (label, colour) in enumerate(zip(component_labels, colours))]
    handles += [
        Line2D([], [], color="0.15", linewidth=2.4, label="OTI (exact)"),
        Line2D([], [], color="0.15", linestyle="none", marker="o",
               markersize=8, markerfacecolor="none", markeredgewidth=1.8,
               label=reference_label),
    ]
    figure.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, y),
                  ncol=ncol or min(len(handles), 4), frameon=False,
                  fontsize=ANNOTATION_PT, handlelength=2.2,
                  columnspacing=1.4, handletextpad=0.6)
