"""The two secondary interfaces are documented, and the documented command works.

``docs/GUI_GUIDE.md`` names ``workbench_app`` and ``unified_app`` with the
``streamlit run`` command that starts each and a line on what it is for. Being
named is not enough: until this test existed the unified view's documented
command opened an empty page, because the module never called its own
``main``. So each command is taken from the guide and run the way
``streamlit run`` runs it -- the file as ``__main__``, with ``sys.argv`` holding
the script path and whatever followed ``--`` -- and the page must render.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from umat_oti.app.unified_app import AREAS

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "docs" / "GUI_GUIDE.md"
CORPUS = REPO_ROOT / "tests" / "fixtures" / "corpus"
SECONDARY = ("workbench_app", "unified_app")
_COMMAND = re.compile(
    r"^streamlit run (?P<path>src/umat_oti/app/(?P<name>\w+)\.py)\s+#\s*(?P<purpose>\S.*)$")


def _documented_commands() -> dict[str, dict[str, str]]:
    """``streamlit run`` lines inside the guide's bash blocks, by module name."""
    found: dict[str, dict[str, str]] = {}
    inside = False
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            inside = line.strip() == "```bash"
            continue
        match = _COMMAND.match(line.strip()) if inside else None
        if match:
            found[match["name"]] = match.groupdict()
    return found


def test_the_gui_guide_names_each_secondary_interface_with_its_command_and_purpose():
    commands = _documented_commands()
    assert set(SECONDARY) <= set(commands), commands
    for name in SECONDARY:
        assert (REPO_ROOT / commands[name]["path"]).is_file(), commands[name]
        assert len(commands[name]["purpose"].split()) >= 4, commands[name]
    # A reader reaches the guide from the README.
    assert "(docs/GUI_GUIDE.md)" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SECONDARY)
def test_each_documented_command_starts_its_interface(name, monkeypatch):
    path = REPO_ROOT / _documented_commands()[name]["path"]
    # `streamlit run <file>` hands the script its own path as argv[0].
    monkeypatch.setattr(sys, "argv", [str(path)])
    monkeypatch.setenv("UMAT_OTI_CORPUS_RESULTS", str(CORPUS / "results"))
    monkeypatch.setenv("UMAT_OTI_CORPUS_WORK", str(CORPUS / "work"))

    app = AppTest.from_file(str(path), default_timeout=240).run()

    assert not app.exception, [e.value for e in app.exception]
    if name == "workbench_app":
        assert [t.value for t in app.title] == ["UMAT-OTI workbench"]
    else:
        assert [t.value for t in app.title] == ["Home"]
        assert list(app.sidebar.radio[0].options) == [a["label"] for a in AREAS]
        # It read the round it was pointed at: the fixture holds one material.
        assert {m.label: m.value for m in app.metric}["materials here"] == "1"


def test_the_plain_language_view_takes_the_folders_the_guide_documents(
        monkeypatch, tmp_path):
    """``-- --results-dir <results> --work-dir <work>``, as the guide says."""
    guide = GUIDE.read_text(encoding="utf-8")
    assert ("streamlit run src/umat_oti/app/unified_app.py -- "
            "--results-dir <results> --work-dir <work>") in guide
    path = REPO_ROOT / "src" / "umat_oti" / "app" / "unified_app.py"
    # Environment pointing nowhere, so only the arguments can find the round.
    monkeypatch.setenv("UMAT_OTI_CORPUS_RESULTS", str(tmp_path / "absent" / "results"))
    monkeypatch.setenv("UMAT_OTI_CORPUS_WORK", str(tmp_path / "absent" / "work"))
    monkeypatch.setattr(sys, "argv", [str(path), "--results-dir", str(CORPUS / "results"),
                                      "--work-dir", str(CORPUS / "work")])

    app = AppTest.from_file(str(path), default_timeout=240).run()

    assert not app.exception, [e.value for e in app.exception]
    assert {m.label: m.value for m in app.metric}["materials here"] == "1"
