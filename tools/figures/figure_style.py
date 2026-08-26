"""Shared plotting style for the publication figures.

Everything here exists to satisfy a constraint a reviewer can check: text large
enough to read at the printed size, series that survive greyscale and
colourblind vision because they differ in marker and line style as well as
colour, and no reliance on a personal path or a machine name anywhere on the
canvas.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Full text width of the SoftwareX single-column layout, in inches.
FIGURE_WIDTH_IN = 7.0

#: Okabe-Ito, which stays distinguishable under the common colour deficiencies.
PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#E69F00", "#56B4E9", "#000000")

#: Series must differ in shape too: colour alone fails in greyscale print.
MARKERS = ("o", "s", "^", "D", "v", "P", "X")
LINESTYLES = ("-", "--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 2)))


def use_publication_style() -> None:
    """Point sizes are chosen so nothing falls below 9 pt at the printed width."""
    plt.rcParams.update({
        "figure.dpi": 100,
        "savefig.dpi": 600,
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "legend.frameon": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "lines.linewidth": 1.4,
        "lines.markersize": 5,
        "figure.constrained_layout.use": True,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })


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


def save(figure, stem: str, out_dir: Path) -> dict[str, Any]:
    """Write PNG and PDF, and report both so provenance can record them."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    figure.savefig(png)
    figure.savefig(pdf)
    plt.close(figure)
    return {"png": relative(png), "png_sha256": digest(png),
            "pdf": relative(pdf), "pdf_sha256": digest(pdf),
            "width_inches": round(float(figure.get_figwidth()), 3),
            "height_inches": round(float(figure.get_figheight()), 3)}


def write_provenance(stem: str, out_dir: Path, *, inputs: Sequence[Path],
                     outputs: dict, filters: dict, rows: dict,
                     command: str, notes: str = "") -> Path:
    """A sidecar naming every input, its hash, and exactly what was plotted.

    Without the filters and row counts a reader cannot tell whether a figure
    shows all the evidence or a flattering subset of it.
    """
    record = {
        "figure": stem,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit(),
        "command": command,
        "inputs": [{"path": relative(p), "sha256": digest(p),
                    "bytes": Path(p).stat().st_size} for p in inputs],
        "outputs": outputs,
        "plotted_filters": filters,
        "row_counts": rows,
        "notes": notes,
    }
    path = Path(out_dir) / f"{stem}_provenance.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path
