#!/usr/bin/env python
"""Capture publication screenshots of the workbench, automatically.

A screenshot in a paper is a claim about what the software does, so it is taken
from the tested interface driving the real backend, by a script, rather than
cropped by hand from whatever happened to be on screen. Re-running this
regenerates the figures.

Two things are deliberate. The app is served from a clean example project so no
personal path, username or hostname appears, and the browser chrome is excluded
by screenshotting the page rather than the window.
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
APP = REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py"
OUT = REPO_ROOT / "paper_results" / "figures"

# The printed size of the text is set by how much of the figure's width one
# CSS pixel occupies, not by the capture resolution. Streamlit's body text is
# 14 CSS px, and a figure placed at FIGURE_WIDTH_IN inches prints that as
# 14 / width * FIGURE_WIDTH_IN inches. At the 1600 px a desktop browser opens
# with, that is under 4 pt -- sharp and unreadable. This width keeps it above
# the 9 pt the manuscript requires; the page becomes tall instead, which the
# column composition below handles.
VIEWPORT = {"width": 720, "height": 1200}
SCALE = 2
# Single-column figure width used by the manuscript, in inches.
FIGURE_WIDTH_IN = 7.0

#: Streamlit's body text size, which sets what the figure prints at.
BODY_TEXT_CSS_PX = 14

# Regions are listed in page order and carry a separate drop priority, because
# the two are not the same. The derivative request is the point of Figure 1 and
# must survive; the source information above it is the first thing to lose. A
# single "most important first" list would have to choose between showing the
# page in its own order and dropping the right thing.
#: (label, text that starts the region, text that ends it or None, priority)
#: where a higher priority number is dropped sooner.
REQUEST_REGIONS = (
    ("source and dependencies", "1. Source and dependencies", None, 1),
    ("detected source information", "2. Detected source information", None, 3),
    ("dimensions, properties and state", "3. Dimensions, properties and state",
     None, 2),
    ("derivative products and loading history",
     "4. Derivative products and loading history", "5. Run", 0),
)

#: The verification evidence outranks the artefact list: a reader who sees only
#: part of this figure must see the part that says whether anything was checked.
RESULT_REGIONS = (
    ("pipeline stages", "Pipeline stages", None, 2),
    ("primal parity", "Primal parity", None, 0),
    ("derivative products", "Derivative products", None, 1),
    ("comparison summary", "Comparison summary", None, 3),
    ("artifacts", "Artifacts", None, 4),
)  # publication resolution


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait(url: str, timeout: float = 90.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.7)
    return False


def _launch(port: int) -> subprocess.Popen:
    environment = dict(os.environ)
    environment.update({
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        "STREAMLIT_SERVER_HEADLESS": "true",
        # Keep the developer's identity out of the figure.
        "STREAMLIT_GLOBAL_DEVELOPMENT_MODE": "false",
    })
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(APP),
         "--server.port", str(port), "--server.headless", "true",
         "--server.address", "127.0.0.1",
         "--browser.gatherUsageStats", "false"],
        cwd=str(REPO_ROOT), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def capture(out_dir: Path, keep_running: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    server = _launch(port)
    captured: dict[str, str] = {}
    try:
        if not _wait(url):
            raise RuntimeError(f"the Streamlit server did not come up on {url}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE)
            page.goto(url, wait_until="networkidle")
            # Hide Streamlit's own chrome. It is not part of the software being
            # described and it carries a Deploy button that means nothing here.
            # The vertical rhythm is tightened rather than the text shrunk.
            # A figure's printed text size is fixed by how many CSS pixels
            # span its width, so the only way to fit more of the page at a
            # readable size is to make the page shorter -- not smaller.
            page.add_style_tag(content="""
                header[data-testid="stHeader"] {display: none !important;}
                div[data-testid="stToolbar"] {display: none !important;}
                div[data-testid="stDecoration"] {display: none !important;}
                footer {display: none !important;}
                .stApp {padding-top: 0 !important;}
                .block-container {padding-top: 0.4rem !important;
                                  padding-bottom: 0.4rem !important;}
                div[data-testid="stVerticalBlock"] {gap: 0.35rem !important;}
                div[data-testid="stElementContainer"] {margin-bottom: 0 !important;}
                h2, h3 {margin-top: 0.5rem !important;
                        margin-bottom: 0.25rem !important;
                        padding-top: 0 !important; padding-bottom: 0 !important;}
                textarea {min-height: 0 !important;}
                div[data-testid="stTextArea"] textarea {height: 74px !important;}
                div[data-testid="stCaptionContainer"] {margin: 0 !important;}
                div[data-testid="stMarkdownContainer"] p {margin-bottom: 0.2rem
                                                          !important;}
                div[data-testid="stCheckbox"] {margin-bottom: -0.35rem
                                               !important;}
                hr {margin: 0.3rem 0 !important;}
                /* Lists and button stacks are the tallest things on the
                   results page, and they are lists rather than prose: setting
                   them in columns costs nothing and removes several inches. */
                div[data-testid="stMarkdownContainer"] ul {margin: 0.1rem 0
                    !important; padding-left: 1.1rem !important;}
                div[data-testid="stMarkdownContainer"] li {margin: 0 !important;}
                div[data-testid="stDownloadButton"] button {padding: 0.1rem
                    0.4rem !important;}
                /* Tall enough for the four-line property and parameter
                   lists. Shorter than this and the last value is scrolled out
                   of the figure, which hides data rather than saving space. */
                div[data-testid="stTextArea"] textarea {height: 74px
                    !important; line-height: 1.2 !important;
                    padding: 0.2rem 0.5rem !important;}
                div[data-testid="stNumberInput"] input {padding: 0.15rem 0.5rem
                    !important;}
                div[data-testid="stSelectbox"] div {min-height: 0 !important;}
                label {margin-bottom: 0.05rem !important;}
                div[data-testid="stMetric"] {padding: 0 !important;}
            """)
            page.wait_for_timeout(2500)

            # --- Figure 1: request construction ------------------------------
            _select(page, "m3_j2")
            page.wait_for_timeout(3000)
            for product in ("DSIGMA_DP", "DSTATEV_DP", "INTERNAL_JACOBIAN"):
                _check(page, product)
            page.wait_for_timeout(2500)
            first = out_dir / "figure1_gui_request.png"
            shown_first = _compose_regions(page, first, REQUEST_REGIONS,
                                           MAX_CONTENT_CSS_PIXELS)
            _write_pdf(first)
            _report_size(first, "figure1")
            captured["figure1_gui_request"] = first

            # --- Figure 2: execution and evidence ----------------------------
            run = page.get_by_role("button", name="Analyze, transform, build and verify")
            if run.count():
                run.first.click()
                # The pipeline compiles and runs two Fortran builds.
                page.wait_for_timeout(4000)
                for _ in range(120):
                    body = page.inner_text("body")
                    if "Primal parity" in body and "Derivative products" in body:
                        break
                    page.wait_for_timeout(2000)
                page.wait_for_timeout(2500)
            second = out_dir / "figure2_gui_results.png"
            shown_second = _compose_regions(page, second, RESULT_REGIONS,
                                            MAX_CONTENT_CSS_PIXELS)
            _write_pdf(second)
            _report_size(second, "figure2")
            captured["figure2_gui_results"] = second

            body_text = page.inner_text("body")
            browser.close()
    finally:
        if not keep_running:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()

    provenance = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "app": str(APP.relative_to(REPO_ROOT)),
        "commit": _commit(),
        "viewport": VIEWPORT,
        "device_scale_factor": SCALE,
        "example_project": "parameter_sensitivity/models/m3_j2/umat.for",
        "requested_products": ["DSIGMA_DP", "DSTATEV_DP", "INTERNAL_JACOBIAN"],
        "screenshots": {name: _describe(path) for name, path in captured.items()},
        "page_reported_primal_parity": "Primal parity" in body_text,
        "page_reported_derivative_products": "Derivative products" in body_text,
        "page_reported_outcomes": _outcomes(body_text),
        "regions": {"figure1_gui_request": shown_first,
                    "figure2_gui_results": shown_second},
        "note": ("Captured from the tested interface driving the real backend. "
                 "Paths are repository-relative and the example project ships "
                 "with the repository, so no personal path appears in the "
                 "figures or in this record."),
    }
    (out_dir / "gui_screenshots_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return provenance


def _commit() -> str:
    """The commit the app was captured at, or a marker when it is unavailable."""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return out.stdout.strip() if out.returncode == 0 else "unavailable"


def _describe(path: Path) -> dict:
    """Record a screenshot by relative path, digest and pixel size.

    The absolute path is deliberately not stored: this record is committed
    alongside the figures and must not carry a home directory.
    """
    data = path.read_bytes()
    record = {"path": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT)
              else path.name,
              "sha256": hashlib.sha256(data).hexdigest(),
              "bytes": len(data)}
    pdf = path.with_suffix(".pdf")
    if pdf.exists():
        record["pdf"] = (str(pdf.relative_to(REPO_ROOT))
                         if pdf.is_relative_to(REPO_ROOT) else pdf.name)
        record["pdf_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    try:
        from PIL import Image
        with Image.open(path) as image:
            record["pixels"] = list(image.size)
    except Exception:  # pragma: no cover - Pillow is a capture-time dependency
        pass
    return record


#: How tall a captured page may be before it cannot be printed legibly. A
#: figure's text size is set by CSS pixels per printed inch: at VIEWPORT width
#: and FIGURE_WIDTH_IN, body text prints at about 9.8 pt, and the figure is
#: then FIGURE_WIDTH_IN * height / width inches tall. Beyond this the figure no
#: longer fits a page, and the capture says so rather than shipping a figure
#: whose text has been shrunk to fit.
# A SoftwareX page leaves about 9.4 inches of text height. At FIGURE_WIDTH_IN
# wide, a figure of this height fills a page; its caption then sits below it or
# at the top of the next, which is ordinary for a full-page figure.
MAX_CONTENT_CSS_PIXELS = 980

#: Gutter between composed columns, in pixels of the source image.
GUTTER = 40


def _compose_regions(page, path: Path, regions, budget: int):
    """Stack crops of named regions, dropping the lowest-priority ones that
    will not fit a page.

    A screenshot's printed text size is fixed by how many CSS pixels span the
    figure's width, so the only way to keep it readable is to show less of the
    page rather than to shrink it. The regions are listed in priority order and
    the ones that do not fit are reported, so a caption can say what is not
    shown instead of a reader assuming they are seeing the whole interface.
    """
    from PIL import Image, ImageDraw

    page.wait_for_timeout(400)
    content = page.evaluate(
        "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight,"
        " ...[...document.querySelectorAll('section, .stApp, [data-testid]')]"
        ".map(e => e.scrollHeight || 0))")
    page.set_viewport_size({"width": VIEWPORT["width"],
                            "height": min(int(content) + 200, 14000)})
    page.wait_for_timeout(1200)
    full = path.with_suffix(".full.png")
    page.screenshot(path=str(full), full_page=True)

    def _y(text: str):
        found = page.get_by_text(text, exact=True)
        return found.first.bounding_box()["y"] if found.count() else None

    bounds, missing = [], []
    for label, start_text, end_text, priority in regions:
        top = _y(start_text)
        if top is None:
            missing.append(label)
            continue
        bottom = _y(end_text) if end_text else None
        # No headroom: any reach above the heading pulls in the tail of the
        # region above and leaves a sliver of unrelated text at the seam. Each
        # crop is trimmed to its own content below, which is what gives the
        # clean edge.
        bounds.append([label, top, bottom, priority, top])

    image = Image.open(full)
    scale = SCALE
    page_bottom = image.height / scale
    for index, entry in enumerate(bounds):
        if entry[2] is None:
            entry[2] = (bounds[index + 1][4] if index + 1 < len(bounds)
                        else page_bottom)

    # Drop by priority, then lay out what survives in page order.
    surviving = list(bounds)
    dropped: list[str] = []
    while surviving and sum(max(e[2] - e[1], 0) for e in surviving) > budget:
        victim = max(surviving, key=lambda e: (e[3], e[2] - e[1]))
        if len(surviving) == 1:
            break
        surviving.remove(victim)
        dropped.append(victim[0])
    surviving.sort(key=lambda e: e[1])

    kept, crops = [], []
    for label, top, bottom, _priority, _raw in surviving:
        crop = image.crop((0, int(top * scale), image.width,
                           int(min(bottom, page_bottom) * scale)))
        # Trim each region to its own content. Without this a crop carries the
        # descenders of the heading above it as a sliver of unrelated text.
        box = crop.convert("L").point(lambda v: 0 if v >= 246 else 255).getbbox()
        if box is not None:
            pad = int(4 * scale)
            crop = crop.crop((0, max(box[1] - pad, 0), crop.width,
                              min(box[3] + pad, crop.height)))
        kept.append(label)
        crops.append(crop)

    left, right = None, None
    for crop in crops:
        box = crop.convert("L").point(lambda v: 0 if v >= 246 else 255).getbbox()
        if box is None:
            continue
        left = box[0] if left is None else min(left, box[0])
        right = box[2] if right is None else max(right, box[2])
    margin = int(12 * scale)
    left = max((left or 0) - margin, 0)
    right = min((right or image.width) + margin, image.width)

    gap = int(14 * scale)
    width = right - left
    total = sum(crop.height for crop in crops) + gap * max(len(crops) - 1, 0)
    canvas = Image.new("RGB", (width, total), "white")
    draw = ImageDraw.Draw(canvas)
    offset = 0
    for index, crop in enumerate(crops):
        canvas.paste(crop.crop((left, 0, right, crop.height)), (0, offset))
        offset += crop.height
        if index < len(crops) - 1:
            draw.line([(0, offset + gap // 2), (width, offset + gap // 2)],
                      fill="#d0d0d0", width=2)
            offset += gap
    canvas.save(path)
    full.unlink(missing_ok=True)
    return {"shown": kept, "omitted": dropped + missing}


def _report_size(path: Path, name: str) -> None:
    """Say what this figure's text will print at, and complain if it is small.

    The size follows from geometry, not from the capture resolution: a body
    text of BODY_TEXT_CSS_PX in a VIEWPORT-wide page, printed FIGURE_WIDTH_IN
    inches wide, lands at BODY_TEXT_CSS_PX / VIEWPORT * FIGURE_WIDTH_IN * 72
    points. Capturing at a higher device scale makes it sharper, never bigger.
    """
    from PIL import Image
    with Image.open(path) as image:
        width, height = image.size
    points = BODY_TEXT_CSS_PX / VIEWPORT["width"] * FIGURE_WIDTH_IN * 72
    inches = FIGURE_WIDTH_IN * height / width
    print(f"    {name}: body text prints at {points:.1f} pt, "
          f"figure {FIGURE_WIDTH_IN:.1f} x {inches:.1f} in")
    if points < 9.0:
        print(f"    WARNING: {name} prints below 9 pt")
    if height / SCALE > MAX_CONTENT_CSS_PIXELS:
        print(f"    WARNING: {name} is {inches:.1f} in tall; it will not fit a "
              "page beside its caption")


def _write_pdf(png: Path) -> Path:
    """Embed the screenshot in a PDF at its true capture resolution.

    A screenshot has no vector form, so the PDF carries the same pixels; the
    DPI tag is what makes it place at the intended physical width.
    """
    from PIL import Image
    pdf = png.with_suffix(".pdf")
    with Image.open(png) as image:
        dpi = max(150, round(image.width / FIGURE_WIDTH_IN))
        image.convert("RGB").save(pdf, "PDF", resolution=dpi)
    return pdf


def _outcomes(body_text: str) -> dict:
    """Read back the outcome word the page printed for each product.

    This is what the figure actually shows, not what the run intended, so a
    silently dropped request cannot be described in the caption as verified.
    """
    words = ("PASS", "FAILED", "UNRESOLVED", "BLOCKED", "UNSUPPORTED",
             "NOT REQUESTED", "COMPILED")
    found = {}
    for line in body_text.splitlines():
        for product in ("DDSDDE", "DSIGMA_DP", "DSTATEV_DP",
                        "HIGHER_ORDER_STRESS", "INTERNAL_JACOBIAN"):
            if line.strip().startswith(f"{product} \u2014"):
                tail = line.split("\u2014", 1)[1].strip().upper()
                for word in words:
                    if tail.startswith(word):
                        found[product] = word
                        break
    return found


def _clip(page, path: Path, start_heading: str, end_heading: str | None) -> None:
    """Screenshot the page between two headings.

    A full-page capture of a Streamlit app is one very tall image in which the
    part that matters is unreadable at figure size, so each figure is cropped to
    its own section. The crop is done on the captured image rather than through
    the browser's clip: Streamlit renders into a scrolling container, so the
    page height the browser reports is the viewport rather than the document,
    and a clip computed from it silently truncates the figure.
    """
    from PIL import Image

    page.wait_for_timeout(400)
    # Streamlit renders into its own scrolling container, so full_page captures
    # only what fits the viewport. Growing the viewport to the content height is
    # what actually makes the whole page visible.
    content = page.evaluate(
        "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight,"
        " ...[...document.querySelectorAll('section, .stApp, [data-testid]')]"
        ".map(e => e.scrollHeight || 0))")
    page.set_viewport_size({"width": VIEWPORT["width"],
                            "height": min(int(content) + 200, 12000)})
    page.wait_for_timeout(1200)
    full = path.with_suffix(".full.png")
    page.screenshot(path=str(full), full_page=True)

    start = page.get_by_text(start_heading, exact=True)
    top = (start.first.bounding_box()["y"] - 24) if start.count() else 0
    bottom = None
    if end_heading:
        end = page.get_by_text(end_heading, exact=True)
        if end.count():
            bottom = end.first.bounding_box()["y"] + 48

    image = Image.open(full)
    scale = SCALE
    upper = max(int(top * scale), 0)
    lower = image.height if bottom is None else min(int(bottom * scale), image.height)
    if lower - upper < 200 * scale:
        lower = image.height

    # The horizontal bounds are measured, not assumed. Fixed margins were tuned
    # to one viewport width and sliced the section numbers off the headings as
    # soon as the viewport changed.
    band = image.crop((0, upper, image.width, lower))
    ink = band.convert("L").point(lambda value: 0 if value >= 246 else 255)
    box = ink.getbbox()
    if box is None:
        band.save(path)
        full.unlink(missing_ok=True)
        return
    margin = int(12 * scale)
    left = max(box[0] - margin, 0)
    right = min(box[2] + margin, band.width)
    # box[3] trims the uniform trailing whitespace at the same time, so the
    # figure is not a quarter blank.
    bottom_edge = min(box[3] + margin, band.height)
    band.crop((left, 0, right, bottom_edge)).save(path)
    full.unlink(missing_ok=True)


def _check(page, label: str) -> None:
    """Ensure a checkbox is ticked.

    Clicking unconditionally toggles, so a product that starts checked gets
    turned off -- which is how DSIGMA_DP ended up reported as "not requested"
    in a figure meant to show it verified.
    """
    box = page.locator(f'label:has-text("{label}")').first
    if not box.count():
        return
    checkbox = box.locator('input[type="checkbox"]').first
    if checkbox.count() and checkbox.is_checked():
        return
    box.click()
    page.wait_for_timeout(500)


def _select(page, option: str) -> None:
    boxes = page.locator('div[data-testid="stSelectbox"]')
    if not boxes.count():
        return
    boxes.first.click()
    page.wait_for_timeout(600)
    item = page.get_by_text(option, exact=True)
    if item.count():
        item.first.click()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args(argv)

    if shutil.which("gfortran") is None:
        print("gfortran is not on PATH; Figure 2 would show a build failure "
              "rather than a verified run.", file=sys.stderr)
        return 2
    provenance = capture(args.out_dir)
    for name, record in provenance["screenshots"].items():
        pixels = "x".join(str(v) for v in record.get("pixels", []))
        print(f"  {name}: {Path(record['path']).name} "
              f"({record['bytes'] // 1024} KiB, {pixels})")
    print(f"  primal parity shown: {provenance['page_reported_primal_parity']}")
    print(f"  derivative products shown: "
          f"{provenance['page_reported_derivative_products']}")
    for product, word in sorted(provenance["page_reported_outcomes"].items()):
        print(f"    {product}: {word}")
    return 0 if provenance["page_reported_primal_parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
