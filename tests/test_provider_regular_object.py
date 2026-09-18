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
    assert entry["compile_command"][-2:] == ["-c", "original/umat.for"]
    assert not any(part.startswith("/") or str(tmp_path) in part for part in entry["compile_command"])
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


def _stage(directory: Path) -> Path:
    directory.mkdir(parents=True)
    for name in ("umat.for", "contract_v2.json"):
        (directory / name).write_bytes((J2 / name).read_bytes())
    return directory / "contract_v2.json"


def test_no_directory_of_the_developer_ships_inside_the_objects(tmp_path):
    """A shared object must not carry the developer's directory names.

    gfortran writes the file name it was given into every bounds-check message,
    and gfortran 9 ignores -ffile-prefix-map there; the build therefore compiles
    relative names from inside its build directory. Source and output sit in
    directories with distinctive names, and neither name, nor the home or
    temporary directory, may appear anywhere in either object or in the mapping.
    """
    contract = _stage(tmp_path / "private_source_dir_Q7X")
    built = build_provider(contract, tmp_path / "private_output_dir_K9W", regular_object="REAL_UMAT.obj")
    forbidden = [b"private_source_dir_Q7X", b"private_output_dir_K9W", str(tmp_path).encode(),
                 str(Path.home()).encode()]
    for path in (built["object"], built["regular_object"], built["contract"]):
        payload = Path(path).read_bytes()
        leaked = [name for name in forbidden if name in payload]
        assert not leaked, (Path(path).name, leaked)
    strings = subprocess.run(["strings", "-a", built["object"]], capture_output=True, text=True,
                             check=True).stdout
    locations = {line.split(" of file ", 1)[1] for line in strings.splitlines() if " of file " in line}
    assert locations and all(not name.startswith("/") for name in locations), sorted(locations)[:5]
    assert "original/umat.for" in locations


def test_a_rebuild_reproduces_both_objects_byte_for_byte(tmp_path):
    """Same source, same contract, different directories: identical bytes.

    With no path in the objects there is nothing left that differs between
    builds (gfortran writes no timestamp into an ELF object, and ld -r keeps the
    input order), so the digest in Mapping.json identifies the build itself.
    """
    first = build_provider(_stage(tmp_path / "a" / "model"), tmp_path / "a" / "out",
                           regular_object="REAL_UMAT.obj")
    second = build_provider(_stage(tmp_path / "b" / "elsewhere"), tmp_path / "b" / "build_two",
                            regular_object="REAL_UMAT.obj")
    for key in ("object", "regular_object"):
        assert Path(first[key]).read_bytes() == Path(second[key]).read_bytes(), key
    one, two = (json.loads(Path(built["contract"]).read_text()) for built in (first, second))
    assert one["object"] == two["object"] and one["regular_object"] == two["regular_object"]


@pytest.mark.abaqus
def test_the_abaqus_toolchain_builds_the_regular_object_with_abaqus_make(tmp_path):
    """--abaqus-toolchain: REAL_UMAT.obj is what `abaqus make` produces.

    That object refers to the Intel runtime Abaqus ships, not to libgfortran,
    and (on relative names) records no directory either. The OTI object is
    unchanged by the option.
    """
    import shutil

    if shutil.which("abaqus") is None:
        pytest.skip("no abaqus on this machine")
    contract = _stage(tmp_path / "private_source_dir_Q7X")
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.provider", "build", str(contract), "--out",
         str(tmp_path / "out"), "--regular-object", "REAL_UMAT.obj", "--abaqus-toolchain"],
        capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    built = json.loads(completed.stdout)
    entry = json.loads(Path(built["contract"]).read_text())["regular_object"]
    regular = Path(built["regular_object"])
    assert entry["toolchain"] == "abaqus make" and "Intel" in (entry["compiler"] or "")
    assert entry["compile_command"] == ["abaqus", "make", "library=umat.for"]
    assert entry["sha256_full"] == hashlib.sha256(regular.read_bytes()).hexdigest()
    assert regular.read_bytes() == (Path(built["build_dir"]) / "abaqus_make" / "umat-std.o").read_bytes()
    undefined = subprocess.run(["nm", "-u", str(regular)], capture_output=True, text=True,
                               check=True).stdout
    assert "_gfortran" not in undefined and "umat_" in _symbols(regular)
    assert b"private_source_dir_Q7X" not in regular.read_bytes()
    plain = build_provider(_stage(tmp_path / "plain"), tmp_path / "plain_out")
    assert Path(plain["object"]).read_bytes() == Path(built["object"]).read_bytes()


def test_the_abaqus_toolchain_needs_a_regular_object_name(tmp_path):
    with pytest.raises(ProviderBuildError, match="--regular-object"):
        build_provider(J2 / "contract_v2.json", tmp_path / "out", abaqus_toolchain=True)
