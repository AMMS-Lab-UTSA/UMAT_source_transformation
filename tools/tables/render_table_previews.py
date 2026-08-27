#!/usr/bin/env python3
"""Render each publication table as a readable PNG, for visual review only.

The CSV is the canonical artefact and the one that becomes the editable
manuscript table. This produces a picture of it so a human can check the table
the way they check a figure -- at a glance, at the size it will be read -- which
is not something a CSV or a Word file makes easy in a review loop.

Nothing here recomputes a value. It reads the CSV a generator already wrote, so
a preview cannot disagree with the table it previews.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLES = REPO_ROOT / "paper_results" / "tables"

#: Preview width. Wider than a figure because a table is read, not scanned, and
#: a preview is for review rather than for the page.
PREVIEW_WIDTH_IN = 13.0
HEADER_PT = 9.5
CELL_PT = 8.5
ROW_HEIGHT_IN = 0.26

#: Longer than this and a cell is elided in the preview, with an ellipsis, so
#: one long reason cannot squeeze every other column to nothing. The CSV keeps
#: the full text.
MAX_CELL = 58


def _read(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def _elide(value: str) -> str:
    value = value.strip()
    return value if len(value) <= MAX_CELL else value[:MAX_CELL - 1] + "…"


def render(csv_path: Path, out_dir: Path) -> dict:
    header, rows = _read(csv_path)
    stem = csv_path.stem
    caption = ""
    twin = csv_path.with_suffix(".json")
    if twin.is_file():
        caption = json.loads(twin.read_text(encoding="utf-8")).get("caption", "")

    body = [[_elide(cell) for cell in row] for row in rows]
    height = max(2.0, (len(body) + 4) * ROW_HEIGHT_IN)
    figure, axis = plt.subplots(figsize=(PREVIEW_WIDTH_IN, height))
    axis.axis("off")

    table = axis.table(cellText=body or [[""] * len(header)],
                       colLabels=header, cellLoc="left", loc="upper center")
    table.auto_set_font_size(False)
    table.set_fontsize(CELL_PT)
    table.scale(1.0, 1.32)
    for (row, _column), cell in table.get_celld().items():
        cell.set_edgecolor("#c9ced6")
        cell.set_linewidth(0.5)
        if row == 0:
            cell.set_text_props(weight="bold", fontsize=HEADER_PT)
            cell.set_facecolor("#eef1f5")
        elif row % 2 == 0:
            cell.set_facecolor("#fafbfc")
    table.auto_set_column_width(col=list(range(len(header))))

    title = f"{stem}  —  {len(rows)} rows × {len(header)} columns"
    axis.set_title(title, fontsize=HEADER_PT + 1.5, loc="left", pad=14)
    if caption:
        figure.text(0.01, 0.005, _wrap(caption, 170), fontsize=CELL_PT - 0.5,
                    va="bottom", color="0.3")

    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}_preview.png"
    figure.savefig(png, dpi=160, facecolor="white",
                   bbox_inches="tight", pad_inches=0.12)
    plt.close(figure)
    return {"csv": str(csv_path.relative_to(REPO_ROOT)),
            "preview": str(png.relative_to(REPO_ROOT)),
            "rows": len(rows), "columns": len(header),
            "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            "preview_sha256": hashlib.sha256(png.read_bytes()).hexdigest()}


def _wrap(text: str, width: int) -> str:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def _commit() -> str:
    done = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else "unavailable"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables-dir", type=Path, default=TABLES)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    out_dir = args.out_dir or (args.tables_dir / "previews")

    sources = sorted(args.tables_dir.glob("table*.csv"))
    if not sources:
        print(f"no table CSV found in {args.tables_dir}")
        return 1
    rendered = [render(path, out_dir) for path in sources]
    (out_dir / "table_previews_provenance.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _commit(),
        "command": "python tools/tables/render_table_previews.py",
        "note": ("Previews are pictures of the canonical CSVs, for visual "
                 "review only. The CSV is what becomes the manuscript table; "
                 "a preview recomputes nothing and so cannot disagree with it. "
                 f"A cell longer than {MAX_CELL} characters is elided here and "
                 "kept in full in the CSV."),
        "previews": rendered,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for record in rendered:
        print(f"  {record['preview']}  ({record['rows']} x {record['columns']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
