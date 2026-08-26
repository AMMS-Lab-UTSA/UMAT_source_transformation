#!/usr/bin/env python3
"""Before-and-after sheets, rendered at the size the manuscript places them.

A figure looks fine at 4000 pixels and unreadable at 6.2 inches, so both sides
are scaled to the placed width before being put beside each other. That is the
only comparison that decides anything.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from umat_oti.publication.layout import FIGURE_WIDTH_IN  # noqa: E402

#: Pixels per inch the sheet is drawn at. High enough that text printed at the
#: placed size is legible on screen, and no higher.
SHEET_DPI = 150

PAIRS = [
    ("The request screen",
     ["figure1_gui_request.png"], ["figure_gui_request.png"],
     "Was: one long page cut into pieces, sections 1, 3, 4 because section 2 "
     "did not fit, labels at 8.8 pt.\n"
     "Now: one numbered step, its own screen, every label at 9.3 pt, and an "
     "unsupported product refused before the run."),
    ("The results screen",
     ["figure2_gui_results.png"], ["figure_gui_results.png",
                                   "figure_gui_products.png"],
     "Was: a wall of thirteen bullets, then five stacked product blocks, with "
     "no summary and no durations.\n"
     "Now: a stage table with outcomes and durations, the parity question "
     "answered with its number, and one card per product."),
    ("Illustrative derivative verification",
     ["figure3_illustrative_derivatives.png"],
     ["figure_tangent_verification.png",
      "figure_higher_order_verification.png"],
     "Was: four panels, two of them symmetric-log over ninety decades, ticks "
     "at 7.9 pt and notes at 7.1 pt.\n"
     "Now: two figures, one question each, log axes with no zero on them, "
     "nothing below 9.5 pt."),
    ("Parameter and state sensitivities",
     ["figure4_parameter_sensitivities.png"], ["figure_sensitivities.png"],
     "Was: three stacked panels mixing stress, state and a row-count "
     "histogram, on symmetric-log axes, with E scaled by a hardcoded 200000.\n"
     "Now: two aligned panels, linear axes so the exact zeros sit where they "
     "belong, curves labelled in place, E read from the contract as 210000, "
     "and the row counts moved to Table 8."),
    ("Collection verification",
     ["figure5_collection_verification.png"],
     ["figure_collection_coverage.png", "figure_verification_routes.png"],
     "Was: three panels answering three different questions, one of which "
     "belonged in a table.\n"
     "Now: coverage and route as separate figures, each with its denominator "
     "named on the axis; the internal Jacobians are Table 3."),
]


def _scaled(path: Path, width_px: int) -> Image.Image:
    with Image.open(path) as image:
        ratio = width_px / image.width
        return image.convert("RGB").resize(
            (width_px, max(1, int(image.height * ratio))), Image.LANCZOS)


def _font(size: int):
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _column(paths: list[Path], width_px: int, gap: int) -> Image.Image:
    images = [_scaled(path, width_px) for path in paths if path.is_file()]
    if not images:
        return Image.new("RGB", (width_px, 40), "white")
    height = sum(image.height for image in images) + gap * (len(images) - 1)
    column = Image.new("RGB", (width_px, height), "white")
    offset = 0
    for image in images:
        column.paste(image, (0, offset))
        offset += image.height + gap
    return column


def build(before_dir: Path, after_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    width_px = int(FIGURE_WIDTH_IN * SHEET_DPI)
    margin, gap = 26, 18
    title_font, body_font, label_font = _font(26), _font(15), _font(19)
    written = []

    for index, (title, before, after, note) in enumerate(PAIRS, start=1):
        left = _column([before_dir / name for name in before], width_px, gap)
        right = _column([after_dir / name for name in after], width_px, gap)
        note_lines = [line for block in note.split("\n")
                      for line in _wrap(block, body_font, width_px * 2)]
        header = 44 + 26
        footer = 12 + 20 * len(note_lines)
        height = header + max(left.height, right.height) + footer + margin * 2
        sheet = Image.new("RGB", (width_px * 2 + margin * 3, height), "#f2f3f5")
        draw = ImageDraw.Draw(sheet)
        draw.text((margin, margin), f"{index}. {title}", fill="#111",
                  font=title_font)
        top = margin + 44
        for offset, (label, column) in enumerate(
                (("before", left), ("after", right))):
            x = margin + offset * (width_px + margin)
            draw.text((x, top), label, fill="#555", font=label_font)
            sheet.paste(column, (x, top + 26))
            draw.rectangle([x, top + 26, x + width_px,
                            top + 26 + column.height], outline="#c3c7cd")
        text_y = top + 26 + max(left.height, right.height) + 12
        for line in note_lines:
            draw.text((margin, text_y), line, fill="#333", font=body_font)
            text_y += 20
        path = out_dir / f"comparison_{index}_{title.lower().replace(' ', '_')}.png"
        sheet.save(path)
        written.append(path)
    return written


def _wrap(text: str, font, max_px: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) > max_px and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path,
                        default=REPO_ROOT / "paper_results" / "figures")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    for path in build(args.before, args.after, args.out_dir):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
