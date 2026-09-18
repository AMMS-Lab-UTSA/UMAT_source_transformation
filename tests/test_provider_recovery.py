"""Real compiler/ABI regressions; no mocked constitutive core."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from umat_oti.provider import build_provider
from umat_oti.provider.build import ProviderBuildError
from umat_oti.validation.parameter_sensitivity_provider import (
    J2_PATH, ProviderLibrary, _relative_error, verify_provider,
)


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "parameter_sensitivity" / "models"


@pytest.fixture(scope="module")
def j2_provider(tmp_path_factory):
    directory = tmp_path_factory.mktemp("provider-j2")
    contract = MODELS / "m3_j2" / "contract_v2.json"
    report = verify_provider(contract, directory)
    return directory, report


def test_provider_j2_original_fd_and_carryover(j2_provider):
    directory, report = j2_provider
    assert report["passed"]
    assert report["branches"] == ["elastic", "elastic", "plastic", "plastic", "elastic", "plastic", "elastic"]
    # Every entry of DSIGMA_DP, DSTATEV_DP and DDSDDE (EVAL and MARCH) is judged
    # against the step ladder: 628 are determined to the tolerance and agree,
    # 240 are zero to within the reference (elastic increments, zero shear),
    # none is unresolved and none disagrees; every column agrees.
    assert report["verdict"] == "verified" and not report["unresolved_columns"]
    assert report["comparisons"] == {
        "eval_primal": 49, "march_final_primal": 6, "verified_entries": 628,
        "consistent_with_zero": 240, "reference_unresolved": 0, "disagreeing": 0,
    }
    assert all(column["verdict"] == "agrees" for column in report["columns"])
    assert report["path_source"].startswith("provider default")
    assert report["carry_reset_stress_derivative_difference"] > 1
    assert json.loads((directory / "verification.json").read_text())["passed"]


def test_provider_object_signatures_and_hash(j2_provider):
    _, report = j2_provider
    obj = Path(report["provider"]["object"])
    metadata = json.loads(Path(report["provider"]["contract"]).read_text())
    symbols = subprocess.run(["nm", "--defined-only", str(obj)], check=True, text=True, capture_output=True).stdout
    for symbol in ("umat_", "umat_oti_internal_", "umat_oti_eval_", "umat_oti_march_"):
        assert symbol in {line.split()[-1] for line in symbols.splitlines()}
    assert len(metadata["symbols"]["oti_eval_signature"]) == 18
    assert len(metadata["march"]["signature"]) == 11
    assert metadata["march"]["directions"] == 10
    assert metadata["object"]["sha256"] == hashlib.sha256(obj.read_bytes()).hexdigest()[:16]
    assert metadata["object"]["sha256_full"] == hashlib.sha256(obj.read_bytes()).hexdigest()
    assert metadata["validation"] == {"status": "not_run", "passed": False}


def test_provider_j2_repeatable_without_hidden_state(j2_provider):
    directory, report = j2_provider
    metadata = json.loads(Path(report["provider"]["contract"]).read_text())
    library = ProviderLibrary(Path(report["provider"]["object"]), metadata, directory / "restart")
    first = library.evaluate(report["props"], J2_PATH)
    second = library.evaluate(report["props"], J2_PATH)
    for left, right in zip(first, second):
        np.testing.assert_array_equal(left, right)
    assert first[1].shape == (7, 1)
    assert first[4].shape == (7, 1, 4)


def test_provider_cli_build_elastic_and_independent_fd(tmp_path):
    contract = MODELS / "m1_elastic" / "contract_v2.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "umat_oti.provider", "build", str(contract), "--out", str(tmp_path)],
        cwd=tmp_path, env=env, check=True, capture_output=True, text=True,
    )
    built = json.loads(result.stdout)
    assert Path(built["object"]).is_file()
    assert len(json.loads(Path(built["contract"]).read_text())["symbols"]["oti_eval_signature"]) == 16
    report = verify_provider(contract, tmp_path / "verified", require_j2_branches=False)
    assert report["passed"]


@pytest.mark.parametrize(("field", "value", "message"), [
    ("schema", "other", "resasm_umat_transform_v2"),
    ("kinematics", "finite_strain", "small_strain"),
    ("dimensions", {"ntens": 3, "nprops": 4, "nstatev": 1}, "NTENS=6"),
    ("dimensions", {"ntens": 6, "nprops": 4, "nstatev": -1}, "nonnegative integer"),
    ("parameters", [{"name": "E", "props_index": 5}], "PROPS index"),
    ("parameters", [{"name": "E", "props_index": 1}] * 2, "unique"),
    ("derivative", {"of": "STRESS", "wrt": "PROPS", "order": 2}, "first-order"),
    ("history", {"path_dependent": False}, "physical STATEV"),
    ("source", {"main_file": "umat.for", "entry_point": "OTHER"}, "entry_point=UMAT"),
    ("source", {"main_file": "umat.for", "extra_sources": ["helper.for"]}, "extra sources"),
])
def test_provider_rejects_unsupported_contract(tmp_path, field, value, message):
    contract = json.loads((MODELS / "m3_j2" / "contract_v2.json").read_text())
    contract[field] = value
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract))
    with pytest.raises(ProviderBuildError, match=message):
        build_provider(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_provider_cli_errors_are_nonzero_and_do_not_publish(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"schema":"not_supported"}')
    result = subprocess.run(
        [sys.executable, "-m", "umat_oti.provider", "build", str(path), "--out", str(tmp_path / "out")],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "expected schema" in result.stderr
    assert not (tmp_path / "out").exists()


def test_provider_reordered_sparse_parameter_columns(tmp_path):
    raw = json.loads((MODELS / "m3_j2" / "contract_v2.json").read_text())
    raw["source"]["main_file"] = str(MODELS / "m3_j2" / "umat.for")
    raw["parameters"] = [raw["parameters"][3], raw["parameters"][0]]
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(raw))
    report = verify_provider(contract_path, tmp_path.parent / (tmp_path.name + "-built"))
    metadata = json.loads(Path(report["provider"]["contract"]).read_text())
    assert metadata["parameters"] == [
        {"name": "H", "props_index": 4, "oti_direction": 1},
        {"name": "E", "props_index": 1, "oti_direction": 2},
    ]
    assert metadata["dimensions"]["nprops"] == 4
    assert metadata["dimensions"]["nparam"] == 2


def test_provider_nonfinite_data_cannot_pass_verification():
    with pytest.raises(AssertionError, match="nonfinite"):
        _relative_error(np.array([[np.nan]]), np.ones((1, 1)), (0, 1))


def test_provider_verification_failure_is_machine_readable(tmp_path):
    contract_path = tmp_path / "invalid.json"
    contract_path.write_text(json.dumps({"schema": "unsupported", "validation": {"props_values": [1.0]}}))
    output = tmp_path / "failed"
    result = subprocess.run(
        [sys.executable, "-m", "umat_oti.validation.parameter_sensitivity_provider",
         str(contract_path), "--out", str(output)],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True,
    )
    assert result.returncode == 2
    report = json.loads((output / "verification.json").read_text())
    assert report["passed"] is False
    assert "expected schema" in report["error"]
    assert not list(output.glob("*.obj"))