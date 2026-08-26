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

VIEWPORT = {"width": 1600, "height": 1200}
SCALE = 2
# Single-column figure width used by the manuscript, in inches.
FIGURE_WIDTH_IN = 7.0  # publication resolution


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
            page.add_style_tag(content="""
                header[data-testid="stHeader"] {display: none !important;}
                div[data-testid="stToolbar"] {display: none !important;}
                div[data-testid="stDecoration"] {display: none !important;}
                footer {display: none !important;}
                .stApp {padding-top: 0 !important;}
            """)
            page.wait_for_timeout(2500)

            # --- Figure 1: request construction ------------------------------
            _select(page, "m3_j2")
            page.wait_for_timeout(3000)
            for product in ("DSIGMA_DP", "DSTATEV_DP", "INTERNAL_JACOBIAN"):
                _check(page, product)
            page.wait_for_timeout(2500)
            first = out_dir / "figure1_gui_request.png"
            _clip(page, first, "1. Source and dependencies", "5. Run")
            _write_pdf(first)
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
            _clip(page, second, "6. Results", None)
            _write_pdf(second)
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
    left = int(50 * scale)
    right = image.width - int(40 * scale)
    upper = max(int(top * scale), 0)
    lower = image.height if bottom is None else min(int(bottom * scale), image.height)
    if lower - upper < 200 * scale:
        lower = image.height
    cropped = image.crop((left, upper, right, lower))
    # Trim uniform trailing whitespace so the figure is not a quarter blank.
    grey = cropped.convert("L")
    width, height = grey.size
    last = height
    for row in range(height - 1, 0, -1):
        line = grey.crop((0, row, width, row + 1)).getextrema()
        if line[0] < 245:
            last = min(row + 40, height)
            break
    cropped.crop((0, 0, width, last)).save(path)
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
