"""Slides 16/40 and 17/41 in a real browser: ``pytest -m gui tests/gui``.

Each test drives the primary GUI (``streamlit run scripts/app.py``) the way the
slide describes it -- upload the source, set the fields, one click -- with
headless Chromium, downloads what the screen offers, and compares it with what
the command line produces for the same inputs. Screenshots go to
docs/screenshots/ for docs/GUI.md and the usage report.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from gui_helpers import REPO_ROOT, fill_grid, grid_cells, save_screenshot, settle, streamlit_server

pytest.importorskip("playwright.sync_api", reason="playwright is not installed")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.browser, pytest.mark.slow, pytest.mark.fortran]

APP = REPO_ROOT / "scripts" / "app.py"
J2_SOURCE = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"
FCC_SOURCE = REPO_ROOT / "parameter_sensitivity" / "models" / "m6_fcc" / "umat.for"
ELASTIC_SOURCE = REPO_ROOT / "UMATs" / "UMATs" / "ICP" / "elasticity" / "elastic.f"
J2_TABLE = [("E", "1", "200000"), ("nu", "2", "0.3"), ("SIGY0", "3", "250"), ("H", "4", "2000")]
#: Slide 17's table. The shipped contract fills it; the slide's g0, gsat and h0
#: (13, 55, 800) differ from the contract's (16, 40, 300) and are typed in.
FCC_TABLE = [("C11", "1", "168000"), ("C12", "2", "121000"), ("C44", "3", "75000"),
             ("g0", "4", "13"), ("gsat", "5", "55"), ("h0", "6", "800"), ("a", "7", "2"),
             ("q", "8", "1.4"), ("gd0", "9", "0.001"), ("m", "10", "0.05")]


def _report_table(report: str) -> list[tuple[str, str, float]]:
    """The (name, PROPS index, value) lines transform_report.txt records."""
    rows = re.findall(r"^  (\S+)\s+PROPS\((\d+)\)\s+(\S+)$", report, flags=re.MULTILINE)
    return [(name, index, float(value)) for name, index, value in rows]


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    work = tmp_path_factory.mktemp("umat_gui")
    env = dict(os.environ, UMAT_OTI_GUI_WORKSPACE=str(work / "workspace"),
               PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT / "src"),
                                                       os.environ.get("PYTHONPATH")])))
    with streamlit_server(APP, env=env, log=work / "server.log") as (url, pid):
        yield {"url": url, "pid": pid, "work": work}


@pytest.fixture
def page(server):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1900}, accept_downloads=True)
        page = context.new_page()
        page.goto(server["url"], wait_until="networkidle", timeout=120000)
        yield page
        browser.close()


def _download(page, locator, directory: Path) -> Path:
    with page.expect_download(timeout=60000) as event:
        locator.click()
    download = event.value
    target = directory / download.suggested_filename
    download.save_as(target)
    return target


def _jacobian(page, source: Path, ntens: int, lines: str):
    page.get_by_role("tab", name="Constitutive Jacobian", exact=True).click()
    panel = page.get_by_role("tabpanel", name="Constitutive Jacobian")
    expect(panel.get_by_role("heading", name="umat-oti — Constitutive Jacobian")).to_be_visible()
    panel.locator('input[type="file"]').first.set_input_files(str(source))
    settle(page)
    ntens_box = panel.get_by_label("Number of stress components (NTENS)")
    ntens_box.fill(str(ntens))
    ntens_box.press("Enter")
    settle(page)
    # Seed, response and target are the presentation's defaults.
    for label, value in (("differentiate with respect to", "DSTRAN"), ("of the output", "STRESS"),
                         ("write into", "DDSDDE")):
        expect(panel.get_by_role("combobox", name=label)).to_match_aria_snapshot(
            f'- combobox "{label}": {value}')
    # "The Jacobian block is found for you."
    expect(panel.get_by_label("line(s) that assign the tangent")).to_have_value(lines, timeout=60000)
    panel.get_by_role("button", name="Transform →").click()
    expect(panel.get_by_text("Transform succeeded", exact=True)).to_be_visible(timeout=120000)
    settle(page)
    return panel


@pytest.mark.parametrize("source,ntens,lines,shot", [
    (J2_SOURCE, 6, "86-108", "umat_constitutive_jacobian.png"),
    (ELASTIC_SOURCE, 4, "83-87", None),
], ids=["m3_j2", "elastic"])
def test_slide16_constitutive_jacobian(page, server, tmp_path, source, ntens, lines, shot):
    panel = _jacobian(page, source, ntens, lines)
    transformed = _download(page, panel.get_by_role("button", name=re.compile("^Transformed UMAT")), tmp_path)
    report = _download(page, panel.get_by_role("button", name=re.compile("^Transform report")), tmp_path)
    assert "Transformation    : SUCCESS" in report.read_text()
    assert f"Old tangent blocks replaced: 1  (lines {lines})" in report.read_text()
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli", "jacobian", str(source), "--ntens", str(ntens),
         "--out", str(tmp_path / "cli")], capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT / "src"),
                                                                     os.environ.get("PYTHONPATH")]))))
    assert completed.returncode == 0, completed.stderr
    assert transformed.read_bytes() == (tmp_path / "cli" / transformed.name).read_bytes()
    if shot:
        save_screenshot(panel, shot)


def _build(page, panel, *, j2: bool, expected: str):
    if j2:
        panel.get_by_text("Options", exact=True).click()
        panel.get_by_text("require the check path to cross elastic", exact=False).click()
        settle(page)
    panel.get_by_role("button", name="Build OTI object →").click()
    expect(panel.get_by_text(expected, exact=True)).to_be_visible(timeout=600000)
    settle(page)


def test_slide17_parameter_sensitivities_j2(page, server, tmp_path):
    """Take the UMAT from the transform, list E, nu, SIGY0, H, tick, Build."""
    _jacobian(page, J2_SOURCE, 6, "86-108")
    page.get_by_role("tab", name="Parameter Sensitivities", exact=True).click()
    panel = page.get_by_role("tabpanel", name="Parameter Sensitivities")
    expect(panel.get_by_role("heading", name="umat-oti — Parameter Sensitivities")).to_be_visible()
    assert panel.get_by_label("use the UMAT from the Constitutive Jacobian screen", exact=False).is_checked()
    nstatv = panel.get_by_label("Number of state variables (NSTATV)")
    nstatv.fill("1")
    nstatv.press("Enter")
    settle(page)
    grid = panel.locator('[data-testid="stDataFrame"]').first
    fill_grid(page, grid, J2_TABLE)
    assert grid_cells(grid) == [cell for row in J2_TABLE for cell in row]
    assert panel.get_by_label("stress (DSIGMA_DP)").is_checked()
    assert panel.get_by_label("state (DSTATEV_DP, auto)").is_checked()
    _build(page, panel, j2=True, expected="Build succeeded and verified")
    files = {}
    for name in ("OTI_UMAT.obj", "REAL_UMAT.obj", "Mapping.json", "transform_report.txt"):
        files[name] = _download(page, panel.get_by_role("button", name=re.compile("^" + re.escape(name))), tmp_path)
    mapping = json.loads(files["Mapping.json"].read_text())
    assert mapping["object"]["sha256_full"] == _sha(files["OTI_UMAT.obj"])
    assert mapping["regular_object"]["sha256_full"] == _sha(files["REAL_UMAT.obj"])
    assert [(p["name"], p["props_index"]) for p in mapping["parameters"]] == \
        [(n, int(i)) for n, i, _ in J2_TABLE]
    report = files["transform_report.txt"].read_text()
    assert "bit-identical" in report
    assert _report_table(report) == [(n, i, float(v)) for n, i, v in J2_TABLE]
    save_screenshot(panel, "umat_parameter_sensitivities_j2.png")

    # The command line, same table: same verdict and the same measured numbers.
    from umat_oti.provider import collaborator

    parameters = collaborator.parse_parameters(
        [{"parameter": n, "PROPS index": int(i), "value": float(v)} for n, i, v in J2_TABLE])
    contract = collaborator.stage_model(J2_SOURCE, tmp_path / "cli" / "m3_j2", collaborator.provider_contract(
        "umat.for", name="m3_j2", nstatev=1, parameters=parameters))
    completed = subprocess.run([sys.executable, "-m", "umat_oti.provider.collaborator", str(contract),
                                "--out", str(tmp_path / "cli" / "out"), "--j2-branches"],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    cli_report = (tmp_path / "cli" / "out" / "collaborator" / "transform_report.txt").read_text()

    def measured(text):
        return [line for line in text.splitlines()
                if line.startswith(("  parameter step", "  strain step", "FD plateau", "Primal parity"))]

    assert measured(report) == measured(cli_report) and measured(report)
    cli_mapping = json.loads((tmp_path / "cli" / "out" / "collaborator" / "Mapping.json").read_text())
    for key in ("parameters", "dimensions", "symbols", "layouts", "history", "regular_source_hash"):
        assert mapping[key] == cli_mapping[key], key
    shown = panel.inner_text()
    headline = collaborator.headline_errors(
        json.loads((tmp_path / "cli" / "out" / "verification" / "verification.json").read_text()))
    for value in headline.values():
        assert f"{value:.2e}" in shown


def test_slide17_parameter_sensitivities_fcc(page, server, tmp_path):
    """Slide 17's ten crystal-plasticity parameters at the slide's values."""
    page.get_by_role("tab", name="Parameter Sensitivities", exact=True).click()
    panel = page.get_by_role("tabpanel", name="Parameter Sensitivities")
    panel.locator('input[type="file"]').first.set_input_files(str(FCC_SOURCE))
    settle(page)
    panel.get_by_role("button", name=re.compile("^Fill the table from")).click()
    settle(page)
    grid = panel.locator('[data-testid="stDataFrame"]').first
    fill_grid(page, grid, FCC_TABLE)
    assert grid_cells(grid) == [cell for row in FCC_TABLE for cell in row]
    assert panel.get_by_label("Number of state variables (NSTATV)").input_value() == "12"
    panel.get_by_role("button", name="Build OTI object →").click()
    outcome = panel.get_by_text(re.compile(r"^Build succeeded"))
    expect(outcome).to_be_visible(timeout=600000)
    settle(page)
    mapping = json.loads(_download(page, panel.get_by_role("button", name=re.compile("^Mapping.json")),
                                   tmp_path).read_text())
    assert [(p["name"], str(p["props_index"])) for p in mapping["parameters"]] == \
        [(n, i) for n, i, _ in FCC_TABLE]
    assert mapping["dimensions"] == {"ntens": 6, "nprops": 10, "nstatev": 12, "nparam": 10}
    report = _download(page, panel.get_by_role("button", name=re.compile("^transform_report.txt")),
                       tmp_path).read_text()
    assert _report_table(report) == [(n, i, float(v)) for n, i, v in FCC_TABLE]
    save_screenshot(panel, "umat_parameter_sensitivities_fcc.png")
