#!/usr/bin/env python3
"""Capture one deliberate screenshot of each step of the working interface.

The previous version screenshotted one very long scrolling page and then cut it
into pieces to make it fit. That is why a figure showed sections 1, 3 and 4:
section 2 was a piece that did not fit. Each step of the guided workflow is now
a screen of its own, so a screenshot is a screen rather than an excerpt.

The viewport is narrower than the widths the interface must remain usable at,
and deliberately so. Those are different questions: this one is "how large does
this text print in the manuscript", which is fixed by how many CSS pixels span
the figure's width; that one is "does anything overflow", which is checked
separately at the laptop sizes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.publication.layout import (  # noqa: E402
    FIGURE_WIDTH_IN, GUI_MIN_TEXT_PX, MIN_RENDERED_PT, SCREENSHOT_VIEWPORT_PX,
    SUPPORTED_VIEWPORTS,
)

APP = REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py"
DEFAULT_OUT = REPO_ROOT / "paper_results" / "figures"

#: Captured at twice the CSS size, so the image is sharp. This changes how many
#: pixels the file has and not how large its text prints.
SCALE = 2

#: The example the figures are taken from. It ships with the repository, so no
#: personal path can appear in a screenshot.
EXAMPLE = "m3_j2"

#: What each screenshot is for. Kept beside the capture so a caption and the
#: figure it describes cannot drift apart.
PURPOSE = {
    "figure_gui_source": "Choosing the UMAT and reading what the analysis "
                         "found in it.",
    "figure_gui_material": "The material description, prefilled from the "
                           "example's committed contract.",
    "figure_gui_request": "Choosing what to compute, with an unsupported "
                          "product reported before the run rather than after "
                          "it.",
    "figure_gui_results": "The completed run: every stage, its duration, and "
                          "whether the two builds agree before any derivative "
                          "is compared.",
    "figure_gui_products": "One card per derivative product, each with its "
                           "outcome word, what that word means, and the "
                           "numbers behind it.",
}

CHROME_CSS = """
  header[data-testid="stHeader"] {display: none !important;}
  div[data-testid="stToolbar"] {display: none !important;}
  div[data-testid="stDecoration"] {display: none !important;}
  footer {display: none !important;}
  .stApp {padding-top: 0 !important;}
  .block-container {padding-top: .8rem !important; padding-bottom: .8rem
                    !important; max-width: 100% !important;}
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> subprocess.Popen:
    environment = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "src"))
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(APP),
         "--server.port", str(port), "--server.headless", "true",
         "--browser.gatherUsageStats", "false",
         "--server.fileWatcherType", "none"],
        cwd=str(REPO_ROOT), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for(url: str, server: subprocess.Popen, seconds: int = 90) -> None:
    import urllib.error
    import urllib.request
    for _ in range(seconds * 2):
        if server.poll() is not None:
            raise RuntimeError("the Streamlit server exited before it served")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    raise RuntimeError(f"the Streamlit server did not come up on {url}")


def _printed_point_size(css_px: float) -> float:
    return css_px / SCREENSHOT_VIEWPORT_PX * FIGURE_WIDTH_IN * 72.0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _click(page, text: str, timeout: int = 20000) -> None:
    button = page.get_by_role("button", name=text)
    button.first.wait_for(state="visible", timeout=timeout)
    button.first.click()
    page.wait_for_timeout(900)


def _tick(page, label: str) -> None:
    """Ensure a checkbox is ticked. Clicking blindly toggles."""
    box = page.locator(f'label:has-text("{label}")').first
    if not box.count():
        return
    checkbox = box.locator('input[type="checkbox"]').first
    if checkbox.count() and checkbox.is_checked():
        return
    box.click()
    page.wait_for_timeout(600)


def _shoot(page, path: Path, selector: str = "div.block-container") -> tuple[int, int]:
    """Capture one real region of the interface, trimmed to what it drew.

    ``selector`` names a region the app itself declares, so a figure is a part
    of the interface rather than a rectangle chosen with a ruler.
    """
    from PIL import Image

    container = page.locator(selector).first
    container.wait_for(state="visible", timeout=20000)
    page.wait_for_timeout(500)
    container.screenshot(path=str(path))
    with Image.open(path) as image:
        ink = image.convert("L").point(lambda v: 0 if v >= 250 else 255)
        box = ink.getbbox()
        if box:
            pad = 8 * SCALE
            trimmed = image.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                                  min(box[2] + pad, image.width),
                                  min(box[3] + pad, image.height)))
            trimmed.save(path)
            return trimmed.size
        return image.size


def _overflow(page) -> dict:
    """Whether anything on the page reaches past the viewport horizontally."""
    return page.evaluate("""() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        overflowing: [...document.querySelectorAll('body *')]
            .filter(e => e.getBoundingClientRect().right >
                         document.documentElement.clientWidth + 2)
            .slice(0, 5)
            .map(e => (e.tagName + '.' + (e.className || '')).slice(0, 70)),
    })""")


def _choose_example(page, name: str) -> None:
    """Pick an example from the source list."""
    combo = page.get_by_role("combobox").first
    combo.click()
    page.wait_for_timeout(500)
    page.get_by_role("option").filter(has_text=name).first.click()
    page.wait_for_timeout(1400)


def _walk(page, capture, out_dir: Path) -> dict:
    """Drive the wizard, photographing each step as it is reached."""
    captured: dict[str, dict] = {}

    _choose_example(page, EXAMPLE)
    _click(page, "Analyse this source")
    captured["figure_gui_source"] = capture(page, out_dir, "figure_gui_source")

    _click(page, "Next")
    captured["figure_gui_material"] = capture(page, out_dir,
                                              "figure_gui_material")

    # Ask for something this source cannot do, so the figure shows a refusal
    # being explained before any build happens rather than after one.
    _click(page, "Next")
    _tick(page, "State sensitivity to material parameters")
    _tick(page, "Internal Jacobian of the local solve")
    page.wait_for_timeout(900)
    captured["figure_gui_request"] = capture(page, out_dir,
                                             "figure_gui_request")

    _click(page, "Review and run")
    _click(page, "Run the pipeline", timeout=30000)
    for _ in range(180):
        body = page.inner_text("body")
        if "Derivative products" in body and "Pipeline stages" in body:
            break
        page.wait_for_timeout(2000)
    page.wait_for_timeout(1500)
    # Two regions the app names for itself, rather than one figure the height
    # of a page and a half.
    captured["figure_gui_results"] = capture(
        page, out_dir, "figure_gui_results", ".st-key-results_summary")
    captured["figure_gui_products"] = capture(
        page, out_dir, "figure_gui_products", ".st-key-results_products")
    return captured


def _capture_step(page, out_dir: Path, stem: str,
                  selector: str = "div.block-container") -> dict:
    from PIL import Image

    path = out_dir / f"{stem}.png"
    width, height = _shoot(page, path, selector)
    pdf = path.with_suffix(".pdf")
    with Image.open(path) as image:
        dpi = max(150, round(image.width / FIGURE_WIDTH_IN))
        image.convert("RGB").save(pdf, "PDF", resolution=dpi)
    inches = FIGURE_WIDTH_IN * height / width
    record = {
        "png": str(path.relative_to(REPO_ROOT)),
        "png_sha256": _digest(path),
        "pdf": str(pdf.relative_to(REPO_ROOT)),
        "pixels": [width, height],
        "placed_height_in": round(inches, 2),
        "smallest_text_printed_pt": round(_printed_point_size(GUI_MIN_TEXT_PX), 2),
        "step_heading": page.locator("h3").first.inner_text(),
        "purpose": PURPOSE.get(stem, ""),
        "region": selector,
        "visible_text_head": page.inner_text(selector)[:400],
        "overflow": _overflow(page),
    }
    return record


def capture(out_dir: Path) -> dict:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    server = _start_server(port)
    try:
        _wait_for(url, server)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page_context = browser.new_context(
                viewport={"width": SCREENSHOT_VIEWPORT_PX, "height": 1400},
                device_scale_factor=SCALE)
            page = page_context.new_page()
            page.goto(url, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(2500)
            page.add_style_tag(content=CHROME_CSS)
            page.wait_for_timeout(800)
            captured = _walk(page, _capture_step, out_dir)

            # The interface has to survive the laptop widths as well. That is a
            # different question from how large its text prints, so it is asked
            # separately rather than inferred from the screenshots.
            viewports = {}
            for width, height in SUPPORTED_VIEWPORTS:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(900)
                viewports[f"{width}x{height}"] = _overflow(page)
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()

    provenance = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip() or "unavailable",
        "command": "python tools/figures/capture_gui_screenshots.py",
        "app": str(APP.relative_to(REPO_ROOT)),
        "example": f"parameter_sensitivity/models/{EXAMPLE}/umat.for",
        "viewport": {"width": SCREENSHOT_VIEWPORT_PX, "height": 1400,
                     "device_scale_factor": SCALE},
        "placed_width_in": FIGURE_WIDTH_IN,
        "smallest_text_css_px": GUI_MIN_TEXT_PX,
        "smallest_text_printed_pt": round(
            _printed_point_size(GUI_MIN_TEXT_PX), 2),
        "minimum_required_pt": MIN_RENDERED_PT,
        "screenshots": captured,
        "supported_viewports": viewports,
        "note": ("Each screenshot is one step of the guided workflow, captured "
                 "whole. Nothing is composited and nothing is cropped away "
                 "except the browser chrome. The example ships with the "
                 "repository, so no personal path appears."),
    }
    (out_dir / "gui_screenshots_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if shutil.which("gfortran") is None:
        print("gfortran is not on PATH; the results screenshot needs a real run")
        return 2

    provenance = capture(args.out_dir)
    failures = []
    for stem, record in sorted(provenance["screenshots"].items()):
        print(f"  {stem}: {record['pixels'][0]}x{record['pixels'][1]} px, "
              f"{FIGURE_WIDTH_IN} x {record['placed_height_in']} in, "
              f"text {record['smallest_text_printed_pt']} pt")
        print(f"      heading: {record['step_heading']}")
        if record["overflow"]["overflowing"]:
            failures.append(f"{stem} overflows: {record['overflow']['overflowing']}")
    for viewport, overflow in sorted(provenance["supported_viewports"].items()):
        state = "no horizontal overflow" if not overflow["overflowing"] \
            else f"OVERFLOWS: {overflow['overflowing']}"
        print(f"  {viewport}: {state}")
        if overflow["overflowing"]:
            failures.append(f"{viewport} overflows")
    if provenance["smallest_text_printed_pt"] < MIN_RENDERED_PT:
        failures.append(f"smallest text prints at "
                        f"{provenance['smallest_text_printed_pt']} pt")
    for failure in failures:
        print(f"  FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
