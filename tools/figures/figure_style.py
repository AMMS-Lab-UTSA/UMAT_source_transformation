"""Shared plotting style for the publication figures.

Two rules decide everything here.

The first is that a figure is authored at the width it is placed at. Otherwise
every configured point size is silently multiplied on the way to the page: the
plots were authored at 7.0 inches and placed at 6.20, and `savefig.bbox="tight"`
grew the canvas further, so labels configured at 10 pt printed between 8.6 and
8.8 pt while every generator reported that they were above the floor. Tight
bounding boxes are therefore off, and the layout engine is asked to fit the
content inside the declared size instead of the size being asked to grow.

The second is that nothing is carried by colour alone: every series differs in
marker and line style as well as hue, and the palette stays legible under the
common colour deficiencies.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.text as mtext  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.publication.layout import (  # noqa: E402
    BODY_TEXT_PT, CAPTION_PT, FIGURE_WIDTH_IN, MAX_FIGURE_HEIGHT_IN,
    MIN_RENDERED_PT,
)

#: Okabe-Ito, which stays distinguishable under the common colour deficiencies.
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#E69F00", "#56B4E9", "#000000")

#: Series must differ in shape too: colour alone fails in greyscale print.
MARKERS = ("o", "s", "^", "D", "v", "P", "X")
LINESTYLES = ("-", "--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 2)))

#: Every configured size, so a test can assert the smallest one clears the
#: floor rather than trusting that somebody checked.
FONT_SIZES: dict[str, float] = {
    "font.size": BODY_TEXT_PT,
    "axes.titlesize": BODY_TEXT_PT + 2.0,
    "axes.labelsize": BODY_TEXT_PT,
    "xtick.labelsize": CAPTION_PT,
    "ytick.labelsize": CAPTION_PT,
    "legend.fontsize": CAPTION_PT,
    "figure.titlesize": BODY_TEXT_PT + 3.0,
}

#: The smallest size any annotation added by a figure script may use. Below
#: this a note prints under the caption it sits beside.
ANNOTATION_PT = CAPTION_PT + 0.5


def use_publication_style() -> None:
    plt.rcParams.update({
        **FONT_SIZES,
        "figure.dpi": 100,
        "savefig.dpi": 400,
        "legend.frameon": False,
        "axes.grid": True,
        "grid.alpha": 0.18,
        "grid.linewidth": 0.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        # Heavier strokes to match the larger type: a 1.6 pt line under 13 pt
        # text reads as a hairline.
        "lines.linewidth": 2.2,
        "lines.markersize": 7.5,
        "figure.constrained_layout.use": True,
        # Not "tight": a tight bounding box grows the canvas past the declared
        # figsize, which is exactly how the authored width drifted away from
        # the placed width.
        "savefig.bbox": None,
        "savefig.pad_inches": 0.0,
    })


def figure(height_in: float, width_in: float = FIGURE_WIDTH_IN):
    """A figure of the exact size it will be placed at."""
    if height_in > MAX_FIGURE_HEIGHT_IN:
        raise ValueError(
            f"a figure {height_in:.2f} in tall cannot share a page with its "
            f"caption; the limit is {MAX_FIGURE_HEIGHT_IN} in")
    return plt.subplots(figsize=(width_in, height_in))


def page_title(figure_object, text: str) -> None:
    """Title anchored to the page, not to the axes.

    ``set_title(loc="left")`` anchors at the left edge of the axes box, and a
    chart whose categories are named on the y axis has that box pushed well to
    the right -- so the title starts a third of the way across the page and
    runs off the other side. Anchoring to the figure gives it the full width.

    No explicit ``y``: constrained layout reserves vertical space for a
    suptitle it positions itself, and setting the coordinate by hand opts out
    of that, leaving the title sitting on top of the first row of the chart.
    """
    figure_object.suptitle(text, x=0.014, ha="left",
                           fontsize=FONT_SIZES["axes.titlesize"] + 1)


def commit() -> str:
    try:
        done = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return done.stdout.strip() if done.returncode == 0 else "unavailable"


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _overflowing_text(figure_object) -> list[str]:
    """Every text artist drawn wholly or partly outside the canvas.

    The canvas is fixed at the placement width and nothing clips to it
    visibly: a title too long for the page is simply cut off at the edge, and
    the file is still written, still the right size, and still passes every
    other check. Only comparing each artist's extent against the figure finds
    it.
    """
    # Draw first, and with the figure's own dpi. Text has no laid-out position
    # until something draws it, and the renderer savefig leaves behind is at
    # the save dpi while ``figure.bbox`` is at the figure dpi -- measuring one
    # against the other scales every extent by their ratio and reports text
    # that fits comfortably as running off the page.
    # Twice: constrained layout reserves room for decorations from what the
    # previous draw measured, so the first pass still has the axes at their
    # default box and every long tick label hanging off the left edge. The
    # second pass settles them, and measuring after only one reports those
    # labels as clipped when the saved file shows them sitting comfortably.
    figure_object.canvas.draw()
    figure_object.canvas.draw()
    renderer = figure_object.canvas.get_renderer()
    canvas = figure_object.bbox

    # Ticks just outside the view keep their label objects, positioned past
    # the end of the axis where they are never drawn. They are not clipped
    # text, so they must not be reported as such.
    unshown = set()
    for axes in figure_object.axes:
        for axis in (axes.xaxis, axes.yaxis):
            low, high = sorted(axis.get_view_interval())
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if not low <= tick.get_loc() <= high:
                    unshown.update((id(tick.label1), id(tick.label2)))

    offenders = []
    for text in figure_object.findobj(mtext.Text):
        if id(text) in unshown:
            continue
        if not text.get_visible() or not text.get_text().strip():
            continue
        try:
            extent = text.get_window_extent(renderer=renderer)
        except (RuntimeError, ValueError):
            continue
        if extent.width == 0 or extent.height == 0:
            continue
        # A pixel of slack: glyph extents and the canvas edge routinely differ
        # by less than one device pixel without anything being cut off.
        over = max(canvas.x0 - extent.x0, extent.x1 - canvas.x1,
                   canvas.y0 - extent.y0, extent.y1 - canvas.y1)
        if over > 1.0:
            flat = " ".join(text.get_text().split())
            offenders.append(f"{over:6.1f} px beyond the canvas: {flat!r}")
    return offenders


def save(figure_object, stem: str, out_dir: Path) -> dict[str, Any]:
    """Write PNG and PDF at the declared size, and check that size held."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    declared = float(figure_object.get_figwidth())
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    # Checked before the files are written, so a clipped figure is never left
    # on disk for a later step to pick up.
    overflowing = _overflowing_text(figure_object)
    if overflowing:
        plt.close(figure_object)
        raise RuntimeError(
            f"{stem}: {len(overflowing)} text object(s) run off the "
            f"{declared:.2f} in canvas and would be cut off in the saved "
            f"file:\n  " + "\n  ".join(overflowing))
    figure_object.savefig(png)
    # The PDF backend stamps the wall-clock time into /CreationDate, so two
    # runs of the same script produced two different files and the figures
    # could not be shown to regenerate identically. Dropping the field is
    # enough: the generation time is already recorded, to the second and
    # against the inputs it was generated from, in the provenance sidecar.
    figure_object.savefig(pdf, metadata={"CreationDate": None})
    height = float(figure_object.get_figheight())

    # Recorded from the axes themselves, so the provenance says what the
    # figure actually printed rather than what its source appears to say. A
    # label that spans two source lines cannot be read by grepping the script.
    labels = []
    for index, axes in enumerate(figure_object.axes):
        labels.append({"axes": index, "title": axes.get_title(),
                       "xlabel": axes.get_xlabel(),
                       "ylabel": axes.get_ylabel(),
                       "xscale": axes.get_xscale(),
                       "yscale": axes.get_yscale()})

    from PIL import Image
    with Image.open(png) as image:
        width_in = image.width / plt.rcParams["savefig.dpi"]
    plt.close(figure_object)
    if abs(width_in - declared) > 0.02:
        raise RuntimeError(
            f"{stem} was authored at {declared:.3f} in but saved at "
            f"{width_in:.3f} in. Every configured point size would print at "
            f"{declared / width_in:.3f} of its value.")
    return {"png": relative(png), "png_sha256": digest(png),
            "pdf": relative(pdf), "pdf_sha256": digest(pdf),
            "width_inches": round(declared, 3),
            "height_inches": round(height, 3),
            "smallest_configured_pt": min(FONT_SIZES.values()),
            "smallest_printed_pt": min(FONT_SIZES.values()),
            "axes": labels}


def write_provenance(stem: str, out_dir: Path, *, inputs: Sequence[Path],
                     outputs: dict, filters: dict, rows: dict,
                     command: str, question: str, notes: str = "") -> Path:
    """A sidecar naming every input, its hash, and exactly what was plotted.

    ``question`` is the single scientific question the figure answers. A figure
    that cannot state one is a figure that is doing more than one job.
    """
    record = {
        "figure": stem,
        "answers": question,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit(),
        "command": command,
        "inputs": [{"path": relative(p), "sha256": digest(p),
                    "bytes": Path(p).stat().st_size} for p in inputs],
        "outputs": outputs,
        "plotted_filters": filters,
        "row_counts": rows,
        "layout": {"figure_width_in": FIGURE_WIDTH_IN,
                   "minimum_rendered_pt": MIN_RENDERED_PT,
                   "configured_font_sizes": FONT_SIZES},
        "notes": notes,
    }
    path = Path(out_dir) / f"{stem}_provenance.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path
