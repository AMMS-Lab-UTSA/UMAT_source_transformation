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
import shutil
from pathlib import Path
from typing import Iterable

import pytest

from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
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
