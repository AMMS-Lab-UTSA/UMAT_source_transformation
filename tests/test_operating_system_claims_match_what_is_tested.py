"""The software metadata claims exactly the operating systems that are tested.

What is tested is read from where the testing happens: every CI job's
``runs-on`` runner. What the documentation says is read from README.md and
docs/INSTALL.md, which name Linux as the tested platform and say Windows and
macOS are not tested. The metadata a package index or an archive shows --
``codemeta.json`` and the ``Operating System ::`` classifiers in
``pyproject.toml`` -- has to claim that set and nothing more, and
``CITATION.cff`` and ``.zenodo.json`` must claim no platform at all.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    # tomllib joined the standard library in 3.11; the `test` extra declares
    # tomli, the same parser under its original name, for 3.10.
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A CI runner label, by prefix, and the operating system it provides.
RUNNER_SYSTEMS = {"ubuntu": "Linux", "windows": "Windows", "macos": "macOS"}
#: The operating-system classifier that names each system.
CLASSIFIERS = {"Linux": "Operating System :: POSIX :: Linux",
               "Windows": "Operating System :: Microsoft :: Windows",
               "macOS": "Operating System :: MacOS"}


def _tested_systems() -> set[str]:
    systems = set()
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no CI workflow found"
    for workflow in workflows:
        for runner in re.findall(r"^\s*runs-on:\s*(\S+)", workflow.read_text(), re.MULTILINE):
            prefix = runner.split("-", 1)[0].lower()
            assert prefix in RUNNER_SYSTEMS, f"{workflow.name}: unrecognised runner {runner}"
            systems.add(RUNNER_SYSTEMS[prefix])
    return systems


def test_ci_tests_on_linux_only():
    assert _tested_systems() == {"Linux"}


def test_the_documentation_names_linux_as_tested_and_the_others_as_not():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    install = (REPO_ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    assert re.search(r"^## Install\s+Linux with Python", readme, re.MULTILINE)
    assert "Only Linux is tested. Windows and macOS are not" in readme
    assert re.search(r"^\| Linux \(x86-64\) \| everything \| Ubuntu", install, re.MULTILINE)
    assert "Windows and macOS are not tested." in install


def test_codemeta_claims_the_tested_systems_and_no_others():
    codemeta = json.loads((REPO_ROOT / "codemeta.json").read_text(encoding="utf-8"))
    claimed = codemeta["operatingSystem"]
    claimed = [claimed] if isinstance(claimed, str) else claimed
    assert claimed == sorted(_tested_systems())


def test_the_package_classifiers_claim_the_tested_systems_and_no_others():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    claimed = [c for c in project["project"]["classifiers"]
               if c.startswith("Operating System ::")]
    assert claimed == [CLASSIFIERS[system] for system in sorted(_tested_systems())]
    assert "Operating System :: OS Independent" not in claimed


def test_the_citation_and_archive_metadata_claim_no_platform():
    for name in ("CITATION.cff", ".zenodo.json"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        found = re.findall(r"(?i)operating.?system|os independent|\bwindows\b|\bmacos\b", text)
        assert not found, f"{name} claims a platform: {found}"
