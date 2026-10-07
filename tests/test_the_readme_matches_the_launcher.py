"""The README's first command is the one that works: the launcher exists and is
executable, ``check`` is no longer marked as coming, and every flag and file the
README names is one ``check`` has."""
import os
import re
from pathlib import Path

import pytest

from umat_oti.app import check_command as check

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def test_the_launcher_the_readme_names_exists_and_is_executable():
    assert "python umat-oti check my_umat.for my_deck.inp" in README
    launcher = ROOT / "umat-oti"
    assert launcher.is_file() and os.access(launcher, os.X_OK)
    assert launcher.read_text().startswith("#!/usr/bin/env python3")


def test_check_is_not_described_as_coming():
    assert "NOT AVAILABLE YET" not in README and "once it lands" not in README
    assert "Until `check` lands" not in README


def test_every_check_flag_the_readme_names_is_accepted_by_check():
    section = README.split("What `check` does:")[1].split("The lower-level steps")[0]
    flags = set(re.findall(r"--[a-z][a-z-]+", section))
    assert {"--deck", "--props", "--peak", "--material-config"} <= flags
    parser = check.build_parser()
    known = {opt for action in parser._actions for opt in action.option_strings}
    assert flags <= known, flags - known


def test_the_files_the_readme_names_are_the_ones_check_writes():
    assert "my_umat_material.json" in README and "<name>_check/results_table.txt" in README
    assert "<name>_check/workflow_summary.json" in README
    source = Path(check.__file__).read_text()
    assert '_material.json' in source and '_check"' in source
    from umat_oti.app import check_summary
    assert "results_table.txt" in Path(check_summary.__file__).read_text()
