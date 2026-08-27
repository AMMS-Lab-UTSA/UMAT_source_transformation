#!/usr/bin/env python3
"""Contact sheets for visual review: figures, table previews, and screenshots.

Three sheets, one per kind of artefact, because they are reviewed for different
things. A figure is checked for readability at the printed size; a table
preview for whether its columns and denominators make sense; a screenshot for
whether the interface looks like something a person would use.

Figures are scaled to the width they are placed at in the manuscript, so what
is legible on the sheet is legible on the page.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from umat_oti.publication.layout import FIGURE_WIDTH_IN  # noqa: E402

FIGURES = REPO_ROOT / "paper_results" / "figures"
PREVIEWS = REPO_ROOT / "paper_results" / "tables" / "previews"

#: Pixels per inch the sheets are drawn at.
SHEET_DPI = 130


def _font(size: int):
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                break
    return ImageFont.load_default()


def _tile(path: Path, width_px: int) -> Image.Image:
    with Image.open(path) as image:
        ratio = width_px / image.width
        return image.convert("RGB").resize(
            (width_px, max(1, int(image.height * ratio))), Image.LANCZOS)


def sheet(paths: list[Path], title: str, out: Path, columns: int,
          tile_width: int) -> dict:
    if not paths:
        raise SystemExit(f"nothing to put on the {title!r} sheet")
    tiles = [(path, _tile(path, tile_width)) for path in paths]
    margin, gap, label = 22, 16, 20
    rows = -(-len(tiles) // columns)
    heights = []
    for row in range(rows):
        chunk = tiles[row * columns:(row + 1) * columns]
        heights.append(max(tile.height for _, tile in chunk) + label + gap)
    width = margin * 2 + columns * tile_width + (columns - 1) * gap
    canvas = Image.new("RGB", (width, margin * 2 + 34 + sum(heights)), "#eef0f2")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, margin - 6), title, fill="#111", font=_font(21))

    y = margin + 34
    for row in range(rows):
        chunk = tiles[row * columns:(row + 1) * columns]
        for column, (path, tile) in enumerate(chunk):
            x = margin + column * (tile_width + gap)
            canvas.paste(tile, (x, y + label))
            draw.rectangle([x, y + label, x + tile_width, y + label + tile.height],
                           outline="#bcc2ca")
            draw.text((x, y + 2), path.name, fill="#333", font=_font(13))
        y += heights[row]
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return {"sheet": str(out.relative_to(REPO_ROOT)) if out.is_relative_to(REPO_ROOT)
            else str(out), "tiles": [p.name for p, _ in tiles],
            "size": list(canvas.size)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    gui = sorted(FIGURES.glob("figure_gui_*.png"))
    plots = sorted(p for p in FIGURES.glob("figure_*.png") if p not in gui)
    previews = sorted(PREVIEWS.glob("table*_preview.png"))

    # Plots at the width they are placed at, so legibility on the sheet is
    # legibility on the page.
    placed = int(FIGURE_WIDTH_IN * SHEET_DPI)
    records = {
        "figures": sheet(plots, "Publication figures, at the 6.2 in width they "
                                "are placed at",
                         args.out_dir / "contact_sheet_figures.png", 2, placed),
        "tables": sheet(previews, "Publication table previews",
                        args.out_dir / "contact_sheet_tables.png", 2, 700),
        "screenshots": sheet(gui, "Interface screenshots, at the 6.2 in width "
                                  "they are placed at",
                             args.out_dir / "contact_sheet_screenshots.png", 3,
                             placed),
    }
    (args.out_dir / "contact_sheets.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python tools/figures/build_contact_sheets.py",
        "sheets": records,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, record in records.items():
        print(f"  {name:12s} {record['sheet']}  "
              f"({len(record['tiles'])} tiles, {record['size'][0]}x{record['size'][1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
