"""Installed, the developer screens write under the working directory.

In a source checkout the screens' default workspace is the checkout's
git-ignored ``umat_oti_workspace/gui``, found four directories above the
module. An installed package has no checkout there: four directories above
``site-packages/umat_oti/app/presentation_screens.py`` is the Python
environment's ``lib/python3.X``, and the screens wrote into the environment
(2a4dd95). The same commit made the uniaxial check path, which is read from
the checkout's ``parameter_sensitivity/loading_paths.json``, say that the file
is not installed instead of failing on a missing file.

The package is copied into the ``site-packages`` of a temporary environment
layout, with nothing else beside it, and imported from there by a fresh
interpreter started in an unrelated working directory.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "umat_oti"

PROBE = r"""
import json
import umat_oti.app.presentation_screens as screens
from umat_oti.provider import collaborator
try:
    collaborator.check_path_spec("uniaxial")
    uniaxial = None
except (ValueError, OSError) as error:
    uniaxial = type(error).__name__ + ": " + str(error)
print(json.dumps({"module": screens.__file__, "workspace": str(screens.workspace_root()),
                  "uniaxial": uniaxial}))
"""


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """(environment root, working directory, what the probe printed)."""
    root = tmp_path_factory.mktemp("installed")
    environment_root = root / "env"
    site = environment_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    shutil.copytree(PACKAGE, site / "umat_oti", ignore=shutil.ignore_patterns("__pycache__"))
    work = root / "work"
    work.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("PYTHONPATH", "UMAT_OTI_GUI_WORKSPACE", "UMAT_OTI_REPO")}
    environment.update(PYTHONPATH=str(site), PYTHONNOUSERSITE="1")
    completed = subprocess.run([sys.executable, "-c", PROBE], cwd=work, env=environment,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    probe = json.loads(completed.stdout.strip().splitlines()[-1])
    # the copy is what was imported, not a checkout or another installation
    assert site in Path(probe["module"]).resolve().parents, probe["module"]
    return environment_root.resolve(), work.resolve(), probe


def test_the_default_workspace_is_under_the_working_directory(installed):
    environment_root, work, probe = installed
    workspace = Path(probe["workspace"]).resolve()
    assert workspace.parent == work / "umat_oti_workspace"
    assert environment_root not in workspace.parents


def test_the_uniaxial_check_path_says_its_file_is_not_installed(installed):
    _, _, probe = installed
    assert probe["uniaxial"] is not None, "the uniaxial path was given although its file is not installed"
    assert probe["uniaxial"].startswith("ValueError: "), probe["uniaxial"]
    assert "parameter_sensitivity/loading_paths.json" in probe["uniaxial"]
    assert "does not include" in probe["uniaxial"]
