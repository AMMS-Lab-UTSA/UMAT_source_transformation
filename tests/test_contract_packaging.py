"""The contract's schemas must survive being installed.

``umat_oti.contract.schema`` reads its schema documents and its lock off disk,
relative to the package, to validate every record crossing to
Residual_Assembler. An editable install hides a missing declaration
completely: the source tree is still there, so files that were never declared
as package data resolve anyway. Only a built wheel shows the truth, and the
failure it hides is a consumer-facing one -- ``load_schema`` raising on first
use in a pip-installed copy, at the moment somebody tries to validate a record.

The companion test in ``tests/test_packaging.py`` makes the same point about
the OTI support sources; it was written after a cross-repository CI run
exposed exactly this.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from umat_oti.contract.schema import (GENERATION_FILE, LOCK_NAME, SCHEMA_FILES,
                                      SHARED_FILES)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Read at run time by umat_oti.contract.schema, so each must be in the wheel.
REQUIRED_CONTRACT_DATA = tuple(
    f"umat_oti/contract/schemas/{name}"
    for name in tuple(SCHEMA_FILES.values()) + (GENERATION_FILE,)
) + (f"umat_oti/contract/{LOCK_NAME}",)


def test_the_schemas_resolve_inside_the_package():
    """Resolution must not depend on the repository layout around the package."""
    import umat_oti.contract.schema as module

    package_root = Path(umat_oti_root())
    assert module.SCHEMA_DIR.is_relative_to(package_root), (
        f"the schemas resolved to {module.SCHEMA_DIR}, outside the package at "
        f"{package_root}; a wheel install would not find them")
    for name in SCHEMA_FILES.values():
        assert (module.SCHEMA_DIR / name).is_file(), name
    assert (module.SCHEMA_DIR / GENERATION_FILE).is_file()
    assert (module.SCHEMA_DIR.parent / LOCK_NAME).is_file()


def umat_oti_root() -> Path:
    import umat_oti
    return Path(umat_oti.__file__).resolve().parent


def test_pyproject_declares_the_contract_data():
    """The declaration, checked without building anything, so a missing one is
    a fast failure rather than a slow one."""
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    declared = config["tool"]["setuptools"]["package-data"]
    assert "umat_oti.contract" in declared, (
        "umat_oti.contract reads JSON off disk at run time and declares no "
        "package data, so a wheel would omit every schema it validates with")
    patterns = declared["umat_oti.contract"]
    assert "schemas/*.json" in patterns
    assert LOCK_NAME in patterns


def test_every_shared_file_is_either_packaged_or_python():
    """Nothing in the shared set may be a file the wheel would drop."""
    for name in SHARED_FILES:
        if name.endswith(".py"):
            continue          # packages.find ships Python modules already
        assert f"umat_oti/contract/schemas/{name}" in REQUIRED_CONTRACT_DATA, \
            f"{name} is shared with Residual_Assembler but is not packaged"


@pytest.mark.slow
def test_a_built_wheel_carries_every_schema_the_contract_validates_with(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps",
         "--no-build-isolation", "-w", str(tmp_path), str(REPO_ROOT)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"could not build a wheel here: {proc.stderr[-400:]}")
    wheels = list(tmp_path.glob("umat_oti-*.whl")) + \
        list(tmp_path.glob("umat-oti-*.whl"))
    assert wheels, f"no wheel was produced: {proc.stdout[-400:]}"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    missing = [name for name in REQUIRED_CONTRACT_DATA if name not in names]
    assert not missing, (
        f"the wheel omits contract data files: {missing}. A pip-installed "
        f"copy would raise on the first record it tried to validate.")
