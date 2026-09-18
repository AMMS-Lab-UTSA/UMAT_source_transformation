"""``umat-oti-provider build --regular-object``: the matched regular driver.

The presentation's developer hands over two objects: REAL_UMAT.obj, the
original UMAT compiled unchanged for production analyses, and OTI_UMAT.obj,
the provider. The option publishes the very object the provider bundles, and
records its SHA-256 in the completed contract so the pair can be checked.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from umat_oti.provider.build import ProviderBuildError, build_provider
from umat_oti.validation.parameter_sensitivity_provider import J2_PATH
from umat_oti.validation.parameter_sensitivity_validation import (
    build_original_driver, driver_source, replay,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
J2 = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2"

pytestmark = [pytest.mark.fortran, pytest.mark.slow]


def _symbols(path: Path) -> set[str]:
    listed = subprocess.run(["nm", "--defined-only", str(path)], capture_output=True, text=True,
                            check=True).stdout
    return {line.split()[-1] for line in listed.splitlines() if len(line.split()) == 3}


def test_the_regular_object_is_the_original_and_its_hash_is_in_the_contract(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.provider", "build", str(J2 / "contract_v2.json"),
         "--out", str(tmp_path / "out"), "--regular-object", "REAL_UMAT.obj"],
        capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    built = json.loads(completed.stdout)
    regular = Path(built["regular_object"])
    contract = json.loads(Path(built["contract"]).read_text())
    entry = contract["regular_object"]
    assert entry["file"] == "REAL_UMAT.obj"
    assert entry["sha256_full"] == hashlib.sha256(regular.read_bytes()).hexdigest()
    assert entry["source_sha256_full"] == hashlib.sha256((J2 / "umat.for").read_bytes()).hexdigest()
    assert contract["regular_source_hash"] == entry["source_sha256_full"][:16]
    assert "<source>" in entry["compile_command"] and not any("/" in part for part in entry["compile_command"])
    # It is exactly the object bundled in the provider build ...
    assert regular.read_bytes() == (Path(built["build_dir"]) / "original_umat.o").read_bytes()
    # ... it defines the Abaqus entry point and nothing differentiated ...
    symbols = _symbols(regular)
    assert "umat_" in symbols
    assert not {"umat_oti_eval_", "umat_oti_march_", "umat_oti_internal_"} & symbols
    assert {"umat_", "umat_oti_eval_", "umat_oti_march_"} <= _symbols(Path(built["object"]))
    # ... and linked into the reference driver it replays the ORIGINAL exactly.
    reference = build_original_driver(J2 / "umat.for", tmp_path / "reference", ntens=6, nstatv=1, nprops=4)
    driver = tmp_path / "regular" / "driver.f90"
    driver.parent.mkdir()
    driver.write_text(driver_source(ntens=6, nstatv=1, nprops=4))
    executable = tmp_path / "regular" / "driver"
    subprocess.run(["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none", str(driver),
                    str(regular), "-o", str(executable)], check=True, capture_output=True)
    props = [210000.0, 0.3, 250.0, 2000.0]
    ours = replay(executable, props, J2_PATH.tolist(), ntens=6, nstatv=1)
    theirs = replay(reference, props, J2_PATH.tolist(), ntens=6, nstatv=1)
    np.testing.assert_array_equal(ours.stress, theirs.stress)
    np.testing.assert_array_equal(ours.statev, theirs.statev)


def test_without_the_option_the_contract_is_unchanged(tmp_path):
    built = build_provider(J2 / "contract_v2.json", tmp_path / "out")
    contract = json.loads(Path(built["contract"]).read_text())
    assert "regular_object" not in contract and "regular_object" not in built


@pytest.mark.parametrize("name,message", [
    ("REAL_UMAT.o", "plain .obj filename"), ("../REAL.obj", "plain .obj filename"),
    ("umat_m3_j2_oti.obj", "different from the OTI object"),
])
def test_a_bad_regular_object_name_is_refused_before_building(tmp_path, name, message):
    with pytest.raises(ProviderBuildError, match=message):
        build_provider(J2 / "contract_v2.json", tmp_path / "out", regular_object=name)
    assert not (tmp_path / "out").exists()
