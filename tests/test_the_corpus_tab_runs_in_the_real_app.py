"""The corpus page, driven through Streamlit itself rather than a stand-in.

A recorder proves the page asked for the right things. This proves the page
runs: that the module imports under Streamlit, that the tab is reachable in the
app a user launches, and that what it puts on screen is what the batch's own
record says. A screenshot of it is then evidence, because the panel decided
nothing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "src" / "umat_oti" / "app" / "streamlit_app.py"

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

ROW = {
    "key": "aaaa1111", "source": "owner__repo/umat.for", "repository": "owner/repo",
    "stage": "verified", "reason": "agreed at all 3 states",
    "element_type": "CPE4", "ntens": 4, "kinematics": "finite",
    "props_count": 3, "deck": "owner__repo/decks/job.inp",
    "material_provenance": "job.inp *MATERIAL STEEL: 3 constants",
    "primal": {"agrees": True, "worst_stress_relative": 0.0, "increments": 30},
    "tangent": {"verified": True, "states": []},
}
BLOCKED = {
    "key": "bbbb2222", "source": "owner__repo/other.for", "repository": "owner/repo",
    "stage": "needs_material_data",
    "reason": "no deck is paired with this source",
}


@pytest.fixture()
def a_run(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    (results / "store_verification.jsonl").write_text(
        "\n".join(json.dumps(row) for row in (ROW, BLOCKED)) + "\n",
        encoding="utf-8")
    work = tmp_path / "work"
    (work / "aaaa1111" / "original").mkdir(parents=True)
    (work / "aaaa1111" / "original" / "original.inp").write_text(
        "*HEADING\nsingle-element verification deck\n", encoding="utf-8")
    monkeypatch.setenv("UMAT_OTI_CORPUS_RESULTS", str(results))
    monkeypatch.setenv("UMAT_OTI_CORPUS_WORK", str(work))
    return results, work


def _text(app) -> str:
    """Everything the page put on screen, tables included.

    A table is not markdown, and the terminal-state counts are a table -- so a
    reader of only the markdown would conclude the page never showed them.
    """
    parts = []
    for name in ("markdown", "caption", "info", "text", "code", "json",
                 "metric", "subheader", "header", "title", "warning", "error",
                 "table", "dataframe"):
        try:
            elements = getattr(app, name)
        except Exception:                          # noqa: BLE001 - not present
            continue
        for element in elements:
            value = getattr(element, "value", element)
            try:
                parts.append(value.to_json())      # a table or dataframe
            except AttributeError:
                parts.append(str(value))
    return "\n".join(parts)


def test_the_app_runs_with_the_corpus_tab_present(a_run):
    app = AppTest.from_file(str(APP), default_timeout=240.0).run()
    assert not app.exception, app.exception
    tabs = [tab.label for tab in app.tabs] if hasattr(app, "tabs") else []
    assert any("Corpus" in label for label in tabs), tabs


def test_the_page_shows_what_the_record_says(a_run):
    app = AppTest.from_file(str(APP), default_timeout=240.0).run()
    assert not app.exception, app.exception
    shown = _text(app)
    assert "Corpus verification" in shown
    assert "fully_verified" in shown
    assert "missing_material_data" in shown


def test_a_directory_with_no_run_says_so_instead_of_a_blank_panel(tmp_path,
                                                                  monkeypatch):
    monkeypatch.setenv("UMAT_OTI_CORPUS_RESULTS", str(tmp_path / "nothing"))
    monkeypatch.setenv("UMAT_OTI_CORPUS_WORK", str(tmp_path / "nowhere"))
    app = AppTest.from_file(str(APP), default_timeout=240.0).run()
    assert not app.exception, app.exception
    assert "No corpus round has written" in _text(app)


def test_the_page_starts_no_run_by_merely_being_opened(a_run):
    results, _work = a_run
    AppTest.from_file(str(APP), default_timeout=240.0).run()
    assert not (results / "discovery.log").exists()
    assert not (results / "regression.log").exists()
