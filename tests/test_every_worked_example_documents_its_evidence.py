"""Every worked example documents what a reader needs to run and to trust it.

For each ``examples/0N_*/README.md``: its inputs, the command, the expected
output as it was measured, how that output is checked, the tolerance or the
measured agreement, the files it writes (at least one machine-readable),
the common problems and their fixes, and the GUI equivalent -- or, where
there is none, a sentence that says so.

The headings are the ones the six READMEs share. A heading with nothing under
it does not count: each section is checked for the content that makes it
that section.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
READMES = sorted(EXAMPLES.glob("0*/README.md"))

#: Requirement -> the heading every example uses for it.
SECTIONS = {
    "inputs": "Inputs",
    "command": "Run it from the command line",
    "GUI equivalent": "Run it from the GUI",
    "report or files produced": "What you get",
    "expected output": "Expected output",
    "verification": "How the result is checked",
    "failure diagnostics": "Common problems",
}

#: A tolerance or an agreement stated with its number, e.g. "tolerance 1e-08",
#: "agrees with finite differences to 2.7e-13", "equals ... to 1e-12".
_TOLERANCE = re.compile(
    r"\b(?:tolerance|agree\w*|equals?)\b[^.\n]*?\b\d(?:\.\d+)?e[-+]?\d+", re.IGNORECASE)
_MACHINE_READABLE = re.compile(r"`[^`\s]+\.(?:json|csv)`")
_MEASURED = re.compile(r"Measured on \d{4}-\d{2}-\d{2}")


def _sections(text: str) -> dict[str, str]:
    """Level-two sections by heading; a ``## `` inside a code fence is code."""
    sections: dict[str, list[str]] = {}
    current = None
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _table_rows(text: str) -> list[str]:
    rows = [line for line in text.splitlines() if line.startswith("|")]
    return [row for row in rows[2:] if row.strip("| -")]      # past header and rule


def test_there_are_six_worked_examples_and_the_index_links_each():
    assert [p.parent.name[:2] for p in READMES] == ["01", "02", "03", "04", "05", "06"]
    index = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for readme in READMES:
        assert f"({readme.parent.name}/README.md)" in index, readme.parent.name


@pytest.mark.parametrize("readme", READMES, ids=[p.parent.name for p in READMES])
def test_each_example_documents_all_eight_elements(readme):
    sections = _sections(readme.read_text(encoding="utf-8"))
    missing = [need for need, heading in SECTIONS.items() if not sections.get(heading)]
    assert not missing, f"{readme.parent.name} lacks {missing}"

    inputs = sections["Inputs"]
    assert re.search(r"\]\([^)]+\)|`[^`]+/[^`]+`", inputs), "inputs name no file"

    command = sections["Run it from the command line"]
    assert "```bash" in command, "the command is not given as a runnable block"

    expected = sections["Expected output"]
    assert _MEASURED.search(expected), "the expected output does not say when it was measured"
    assert "```text" in expected, "the expected output is not shown"

    checked = sections["How the result is checked"]
    assert re.search(r"finite difference|analytic|reference", checked, re.IGNORECASE), \
        "the verification names no independent reference"

    agreement = _TOLERANCE.search(expected + "\n" + checked)
    assert agreement, "neither a tolerance nor a measured agreement is stated with its number"

    produced = sections["What you get"]
    assert _MACHINE_READABLE.search(produced), "no machine-readable report is named"

    problems = _table_rows(sections["Common problems"])
    assert len(problems) >= 3, "the failure diagnostics table is nearly empty"

    gui = sections["Run it from the GUI"]
    names_a_screen = re.search(r"\*\*[^*]+\*\*", gui)
    says_there_is_none = re.search(r"There is no GUI screen", gui)
    assert names_a_screen or says_there_is_none, gui


@pytest.mark.parametrize("number", ["05", "06"])
def test_an_example_without_a_gui_says_so_and_points_to_the_nearest_screen(number):
    """Internal Jacobians and the twenty-model sweep have no GUI screen."""
    readme = next(p for p in READMES if p.parent.name.startswith(number))
    gui = _sections(readme.read_text(encoding="utf-8"))["Run it from the GUI"]
    assert gui.startswith("There is no GUI screen for"), gui
    assert re.search(r"\*\*[^*]+\*\*", gui), "it does not name the nearest screen"
