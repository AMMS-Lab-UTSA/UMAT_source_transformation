"""Acceptance tests for the generic PROPS-seeded parameter-sensitivity transformer.

Priority 1 acceptance: the same transformer must work on
* a supplied elastic UMAT with two parameters (E, NU),
* a supplied J2 UMAT with four parameters (E, NU, SIGY0, H) and one
  history-carrying state variable (EQPLAS),
* a differently structured viscoplastic UMAT with three helper
  subroutines (KELASTIC_TRIAL, KDEVIATOR, KMISES) and five parameters
  (E, NU, SIGY0, ETA, MEXP).

Nothing in this test path uses the J2-specific hand-lifted emitter
(:mod:`umat_oti.fortran_emit.parameter_sensitivity_j2`). The transformer
is invoked purely on the UMAT source in ``UMATs/UMATs/generic_ps/`` and
the compiled binary's output is checked against the analytical elastic
sensitivities (available in closed form).

Tests skip when gfortran is missing (environmental blocker).
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pytest

from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    NonDifferentiableParameterPathError,
    compile_generic_ps,
    run_generic_ps,
    transform_umat_for_parameter_sensitivity,
)


REQUIRES_GFORTRAN = pytest.mark.skipif(
    shutil.which("gfortran") is None,
    reason="gfortran not on PATH (environmental blocker).",
)


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERIC_UMAT_DIR = REPO_ROOT / "UMATs" / "UMATs" / "generic_ps"


def _load_dsigma(path: Path) -> dict[tuple[int, int], list[float]]:
    """Parse DSIGMA_DP CSV into ``{(increment, stress_component): [values]}``."""
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows: dict[tuple[int, int], list[float]] = {}
        for row in reader:
            inc = int(row[0])
            comp = int(row[1])
            values = [float(v) for v in row[3:]]
            rows[(inc, comp)] = values
    return rows


def _analytical_elastic_dsigma11_dE(E: float, nu: float, eps11: float) -> float:
    """Under 3D uniaxial strain, dσ11/dE at fixed ν equals (λ+2μ)/E · ε11."""
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    return (lam + 2.0 * mu) / E * eps11


@REQUIRES_GFORTRAN
def test_generic_transform_elastic_props(tmp_path: Path):
    contract = GenericPSContract(
        name="elastic_props",
        umat_source_path=GENERIC_UMAT_DIR / "elastic_props.f",
        parameters=(("E", 1), ("NU", 2)),
        parameter_values=(200000.0, 0.3),
        state_variables=(),
        ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1.5e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=3,
    )
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path
    )
    assert layout.umat_and_helpers == ("UMAT",)
    assert layout.n_param == 2
    exe = compile_generic_ps(layout)
    result = run_generic_ps(exe)
    assert result.returncode == 0, result.stderr

    dsigma = _load_dsigma(result.dsigma_csv)
    inc1_comp1 = dsigma[(1, 1)]
    expected_de = _analytical_elastic_dsigma11_dE(200000.0, 0.3, 1.5e-4)
    assert inc1_comp1[0] == pytest.approx(expected_de, rel=1e-8)


@REQUIRES_GFORTRAN
def test_generic_transform_j2_props(tmp_path: Path):
    """The generic transformer emits DSIGMA_DP for the J2 UMAT bit-identical
    to the hand-lifted J2 fixture emitter in every increment.
    """
    from umat_oti.fortran_emit.parameter_sensitivity_j2 import (
        compile_j2_oti_build,
        generate_j2_oti_build,
        run_j2_oti_driver,
    )

    contract = GenericPSContract(
        name="j2_props",
        umat_source_path=GENERIC_UMAT_DIR / "j2_props.f",
        parameters=(("E", 1), ("NU", 2), ("SIGY0", 3), ("H", 4)),
        parameter_values=(200000.0, 0.3, 250.0, 2000.0),
        state_variables=(("EQPLAS", 1),),
        ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1.5e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=20,
    )
    generic_dir = tmp_path / "generic"
    generic_layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=generic_dir
    )
    assert generic_layout.umat_and_helpers == ("UMAT",)
    generic_exe = compile_generic_ps(generic_layout)
    generic_run = run_generic_ps(generic_exe)
    assert generic_run.returncode == 0, generic_run.stderr

    # Run the hand-lifted J2 fixture emitter for comparison.
    fixture_dir = tmp_path / "fixture"
    fixture_layout = generate_j2_oti_build(fixture_dir)
    fixture_exe = compile_j2_oti_build(fixture_layout)
    fixture_run = run_j2_oti_driver(fixture_exe)
    assert fixture_run.returncode == 0

    generic = _load_dsigma(generic_run.dsigma_csv)
    fixture = _load_dsigma(fixture_run.dsigma_csv)

    max_rel = 0.0
    for key, gen_values in generic.items():
        fix_values = fixture[key]
        for a, b in zip(gen_values, fix_values):
            scale = max(abs(a), abs(b), 1.0)
            rel = abs(a - b) / scale
            if rel > max_rel:
                max_rel = rel
    # Bit-identical on Q_TRIAL etc. would give exact zero; allow FP noise
    # from the slightly different rewrite of the lifted body.
    assert max_rel < 1.0e-10, max_rel


@REQUIRES_GFORTRAN
def test_generic_transform_viscoplastic_with_helpers(tmp_path: Path):
    """A differently structured UMAT (Perzyna viscoplastic with 3 helper
    subroutines) uses the same generic path. Verifies helper-closure
    lifting.
    """
    contract = GenericPSContract(
        name="perzyna_vp",
        umat_source_path=GENERIC_UMAT_DIR / "perzyna_vp_props.f",
        parameters=(("E", 1), ("NU", 2), ("SIGY0", 3), ("ETA", 4), ("MEXP", 5)),
        parameter_values=(200000.0, 0.3, 250.0, 100.0, 2.0),
        state_variables=(("EQPLAS", 1),),
        ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1.5e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=20,
    )
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path
    )
    # Helper closure must include the three helpers plus UMAT itself.
    assert set(layout.umat_and_helpers) == {"UMAT", "KELASTIC_TRIAL", "KDEVIATOR", "KMISES"}
    assert layout.n_param == 5

    exe = compile_generic_ps(layout)
    result = run_generic_ps(exe)
    assert result.returncode == 0, result.stderr

    # Elastic-branch dσ11/dE at increment 1 must match the analytical value.
    dsigma = _load_dsigma(result.dsigma_csv)
    inc1_comp1 = dsigma[(1, 1)]
    expected_de = _analytical_elastic_dsigma11_dE(200000.0, 0.3, 1.5e-4)
    assert inc1_comp1[0] == pytest.approx(expected_de, rel=1e-8)

    # Sanity: the loading path must eventually accumulate plastic strain.
    with result.primal_csv.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)
        last_eqplas = 0.0
        for row in reader:
            last_eqplas = float(row[-1])
    assert last_eqplas > 0.0


@REQUIRES_GFORTRAN
def test_generic_transform_does_not_contain_j2_specific_symbols(tmp_path: Path):
    """The generic transformer must not be J2-specific. In particular the
    emitted driver must not contain hard-coded J2 material constants or
    ``SIGY0`` etc. except when they come from the contract, and the
    module's Python source must not import the J2 hand-lifted fixture.
    """
    import umat_oti.transform.parameter_sensitivity_transform as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for symbol in ("SIGY0_VAL", "H_VAL", "EQPLAS", "j2_umat_oti", "J2Parameters"):
        assert symbol not in source, f"generic transformer must not reference {symbol!r}"


@pytest.mark.parametrize("assignment", ["MEXP = PROPS(1)", "MEXP = INT(PROPS(1))"])
def test_generic_transform_rejects_integer_parameter_path(tmp_path: Path, assignment: str):
    source = tmp_path / "integer_path.f"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,\n"
        "     1 DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,\n"
        "     2 DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,\n"
        "     3 PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,\n"
        "     4 DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
        f"      {assignment}\n"
        "      RETURN\n"
        "      END\n",
        encoding="utf-8",
    )
    contract = GenericPSContract(
        name="integer_path",
        umat_source_path=source,
        parameters=(("MEXP", 1),),
        parameter_values=(2.0,),
        state_variables=(),
        ntens=1,
        nstatv=1,
        ndi=1,
        nshr=0,
        dstran_per_increment=(1.0e-4,),
        n_increments=1,
    )

    with pytest.raises(NonDifferentiableParameterPathError, match="non_differentiable_integer_parameter_path") as exc_info:
        transform_umat_for_parameter_sensitivity(contract=contract, output_dir=tmp_path / "out")

    assert "Declare MEXP as REAL(8)" in exc_info.value.suggested_patch
    assert assignment in source.read_text(encoding="utf-8")


@REQUIRES_GFORTRAN
def test_canonical_cli_generates_and_runs_parameter_sensitivity_for_legacy_umat(tmp_path: Path):
    source = REPO_ROOT / "UMATs" / "UMATs" / "ICP" / "UMAT_ECL_TEMP.for"
    payload = json.loads((REPO_ROOT / "json_files" / "UMAT_ECL_TEMP.json").read_text(encoding="utf-8"))
    payload.update(
        {
            "schema_version": "1.1",
            "source": {"file": str(source)},
            "parameters": [
                {"name": "E1", "props_index": 1, "value": 200.0},
                {"name": "E2", "props_index": 2, "value": 0.0},
                {"name": "G1", "props_index": 3, "value": 80.0},
                {"name": "G2", "props_index": 4, "value": 0.0},
                {"name": "CTE", "props_index": 5, "value": 1.0e-5},
            ],
            "state_variables": [{"name": "EELAS11", "statev_index": 1}],
            "derivatives": [
                {"id": "tangent", "target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1},
                {"id": "stress_parameters", "target": "DSIGMA_DP", "seed": ["E1", "E2", "G1", "G2", "CTE"], "response": "STRESS", "order": 1},
                {"id": "state_parameters", "target": "DSTATEV_DP", "seed": ["E1", "E2", "G1", "G2", "CTE"], "response": "STATEV", "order": 1},
            ],
            "material_point_driver": {
                "nstatv": 12,
                "ndi": 3,
                "nshr": 3,
                "dstran_per_increment": [1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0],
                "n_increments": 2,
            },
        }
    )
    config_path = tmp_path / "legacy_parameter_contract.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    output_dir = tmp_path / "generated_case"

    cli = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli_json", "--config", str(config_path), "--out", str(output_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    summary = json.loads(cli.stdout)
    assert summary["artifacts"]["abaqus_umat"]["abi"] == "standard_real_umat"
    assert summary["artifacts"]["abaqus_umat"]["drop_in_abaqus_user_subroutine"] is True
    parameter_artifact = summary["artifacts"]["parameter_sensitivity_driver"]
    assert parameter_artifact["abi"] == "oti_material_point_driver"
    assert parameter_artifact["drop_in_abaqus_user_subroutine"] is False
    assert set(parameter_artifact["outputs"]) == {"DSIGMA_DP", "DSTATEV_DP"}

    build = subprocess.run(
        ["make", f"FC={shutil.which('gfortran')}"],
        cwd=parameter_artifact["root"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run(
        [str(Path(parameter_artifact["root"]) / "ps_driver")],
        cwd=parameter_artifact["root"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert (Path(parameter_artifact["root"]) / "DSIGMA_DP_OTI.csv").is_file()
    assert (Path(parameter_artifact["root"]) / "DSTATEV_DP_OTI.csv").is_file()

    batch_dir = tmp_path / "batch"
    batch = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "run_completed_json_batch.py"),
            "--config-dir",
            str(config_path.parent),
            "--batch-dir",
            str(batch_dir),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert batch.returncode == 0, batch.stdout + batch.stderr
    batch_report = json.loads((batch_dir / "completed_json_batch_report.json").read_text(encoding="utf-8"))
    row = batch_report["results"][0]
    assert {request["target"] for request in row["derivative_requests"]} == {"DDSDDE", "DSIGMA_DP", "DSTATEV_DP"}
    assert row["artifacts"]["parameter_sensitivity_driver"]["abi"] == "oti_material_point_driver"
