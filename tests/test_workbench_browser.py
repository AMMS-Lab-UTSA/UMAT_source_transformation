"""The interface in a real browser, at the sizes people actually use it at.

AppTest exercises the logic but renders nothing, so it cannot see a control
that has slid off the right edge or a table that scrolls inside itself. These
tests open the real page at the two laptop viewports the interface has to
remain usable at, and check what a user would see.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "src" / "umat_oti" / "app" / "workbench_app.py"

sys.path.insert(0, str(REPO_ROOT / "src"))
from umat_oti.publication.layout import SUPPORTED_VIEWPORTS  # noqa: E402

pytest.importorskip("playwright.sync_api",
                    reason="playwright is not installed")

pytestmark = [pytest.mark.slow, pytest.mark.browser]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    environment = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "src"))
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(APP),
         "--server.port", str(port), "--server.headless", "true",
         "--browser.gatherUsageStats", "false",
         "--server.fileWatcherType", "none"],
        cwd=str(REPO_ROOT), env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    import urllib.error
    import urllib.request
    for _ in range(180):
        if process.poll() is not None:
            pytest.skip("the Streamlit server exited before it served")
        try:
            with urllib.request.urlopen(url, timeout=2):
                break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    else:
        process.terminate()
        pytest.skip("the Streamlit server did not come up")
    yield url
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _overflowing(page) -> list[str]:
    return page.evaluate("""() => [...document.querySelectorAll('body *')]
        .filter(e => e.getBoundingClientRect().right >
                     document.documentElement.clientWidth + 2)
        .slice(0, 6)
        .map(e => (e.tagName + '.' + (e.className || '')).slice(0, 70))""")


@pytest.fixture
def page(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(server, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2500)
        yield page
        browser.close()


def _choose_example(page, name: str = "m3_j2") -> None:
    combo = page.get_by_role("combobox").first
    combo.click()
    page.wait_for_timeout(500)
    page.get_by_role("option").filter(has_text=name).first.click()
    page.wait_for_timeout(1400)


def _click(page, prefix: str, timeout: int = 20000) -> None:
    button = page.get_by_role("button", name=prefix)
    button.first.wait_for(state="visible", timeout=timeout)
    button.first.click()
    page.wait_for_timeout(900)


@pytest.mark.parametrize("width,height", SUPPORTED_VIEWPORTS)
def test_the_first_step_fits_without_horizontal_scrolling(server, width, height):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_context(
            viewport={"width": width, "height": height}).new_page()
        page.goto(server, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2500)
        assert not _overflowing(page), \
            f"content past the right edge at {width}x{height}"
        assert page.evaluate("document.documentElement.scrollWidth") <= width + 2
        browser.close()


def test_the_workflow_shows_one_step_at_a_time_and_numbers_them(page):
    headings = page.locator("h3").all_inner_texts()
    assert headings and headings[0].startswith("1. "), headings
    assert len(headings) == 1, f"more than one step on screen: {headings}"
    chips = page.locator(".oti-step").all_inner_texts()
    assert [chip.split(".")[0] for chip in chips] == ["1", "2", "3", "4"]


def test_next_is_disabled_until_the_source_is_analysed(page):
    button = page.get_by_role("button", name="Next").first
    assert button.is_disabled()
    _choose_example(page)
    _click(page, "Analyse this source")
    assert not page.get_by_role("button", name="Next").first.is_disabled()


def test_an_unsupported_product_is_explained_before_the_run(page):
    _choose_example(page)
    _click(page, "Analyse this source")
    _click(page, "Next")
    _click(page, "Next")
    page.locator('label:has-text("Internal Jacobian of the local solve")') \
        .first.click()
    page.wait_for_timeout(900)
    body = page.inner_text("body")
    assert "UNSUPPORTED" in body
    assert "without a local Newton iteration" in body
    assert "Run the pipeline" not in body, \
        "the run control is reachable before the request has been reviewed"


def test_a_real_run_reports_every_stage_and_its_products(page):
    _choose_example(page)
    _click(page, "Analyse this source")
    _click(page, "Next")
    _click(page, "Next")
    _click(page, "Review and run")
    _click(page, "Run the pipeline", timeout=30000)
    for _ in range(180):
        if "Derivative products" in page.inner_text("body"):
            break
        page.wait_for_timeout(2000)
    body = page.inner_text("body")
    assert "PASS" in body
    assert "Derivatives compared" in body, "the stage table is truncated"
    assert not _overflowing(page), "the results overflow the viewport"
