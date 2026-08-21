"""End-to-end test: compiled OTI Fortran J2 driver vs. centered-FD reference.

This is the acceptance test for Priority 1+2 of the SoftwareX continuation:

* Priority 1: PROPS-seeded OTI Fortran generation for ``DSIGMA_DP`` and
  ``DSTATEV_DP``.
* Priority 2: history-dependent OTI state propagation across a full
  multi-increment loading path (elastic -> yield -> continued hardening).

Test flow:

1. Emit the Fortran build tree (module_generator + hand-lifted J2 UMAT +
   PROPS-seeding driver) via
   :mod:`umat_oti.fortran_emit.parameter_sensitivity_j2`.
2. Compile with a real ``gfortran``.
3. Execute the driver, which writes ``DSIGMA_DP_OTI.csv`` /
   ``DSTATEV_DP_OTI.csv`` / ``primal_stress_state_OTI.csv``.
4. Emit the Python centered-FD reference alongside via
   :mod:`umat_oti.validation.parameter_sensitivity` (full-history replay
   for every ± parameter perturbation).
5. Assert primal ``STRESS`` / ``STATEV`` are bit-close between the OTI
   Fortran and the Python reference at every increment (proves the OTI
   real-part matches the reference algorithm).
6. Assert ``DSIGMA_DP`` and ``DSTATEV_DP`` agree between the compiled OTI
   Fortran driver and the FD reference at every increment across the
   entire loading path -- including the yield transition and continued
   hardening.

The test is skipped only when ``gfortran`` is not on ``PATH``. In that
case the failure is an environmental blocker, not a hidden pass.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from umat_oti.fortran_emit.parameter_sensitivity_j2 import (
    PARAMETER_NAMES,
    compare_oti_vs_fd,
    compile_j2_oti_build,
    generate_j2_oti_build,
    run_j2_oti_driver,
)
from umat_oti.validation.j2_reference import J2Parameters, build_softwarex_j2_path
from umat_oti.validation.parameter_sensitivity import (
    ParameterMap,
    StateMap,
    compute_j2_parameter_sensitivities,
    export_sensitivity_csv,
)


REQUIRES_GFORTRAN = pytest.mark.skipif(
    shutil.which("gfortran") is None,
    reason="gfortran not on PATH (environmental blocker, not a code failure).",
)


def _read_matrix_csv(path: Path) -> dict:
    """Parse a DSIGMA_DP-style CSV into ``{(increment, row_label): [floats]}``.

    Row labels are the second column ('stress_component' or 'state_variable').
    Values are the numeric columns after the ``method`` column.
    """
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        # columns: increment, row_label, method, param1..paramN
        rows: dict[tuple[int, str], list[float]] = {}
        for entry in reader:
            inc = int(entry[0])
            row_label = entry[1].strip()
            values = [float(v) for v in entry[3:]]
            rows[(inc, row_label)] = values
    return {"header": header, "rows": rows}


def _read_primal_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        out: dict[int, dict] = {}
        for entry in reader:
            inc = int(entry[0])
            out[inc] = {
                "yielded": entry[1].strip(),
                "method": entry[2].strip(),
                "stress": [float(v) for v in entry[3:9]],
                "eqplas": float(entry[9]),
            }
    return out


@REQUIRES_GFORTRAN
def test_j2_oti_fortran_driver_matches_fd_reference(tmp_path: Path):
    # 1) generate + compile + run the OTI Fortran driver.
    build_root = tmp_path / "oti_build"
    layout = generate_j2_oti_build(build_root)

    # Every emitted file must exist and be non-empty.
    for path in (
        layout.master_parameters,
        layout.real_utils,
        layout.otim_module,
        layout.j2_umat_oti,
        layout.j2_driver,
        layout.makefile,
    ):
        assert path.is_file(), path
        assert path.stat().st_size > 0

    exe = compile_j2_oti_build(layout)
    assert exe.is_file()
    result = run_j2_oti_driver(exe)
    assert result.returncode == 0, result.stderr
    assert result.primal_csv.is_file()
    assert result.dsigma_csv.is_file()
    assert result.dstatev_csv.is_file()

    # 2) Independent Python centered-FD reference.
    fd_dir = tmp_path / "fd"
    fd_run = compute_j2_parameter_sensitivities(
        params=J2Parameters(),
        path=build_softwarex_j2_path(),
        parameter_map=ParameterMap.softwarex_default(),
        state_map=StateMap.softwarex_default(),
        fd_step_relative=1.0e-6,
    )
    fd_files = export_sensitivity_csv(fd_run, fd_dir)

    # 3) Primal stress/state parity.
    oti_primal = _read_primal_csv(result.primal_csv)
    fd_primal = _read_primal_csv(fd_files["primal_FD"])
    assert set(oti_primal.keys()) == set(fd_primal.keys())
    for inc, oti_rec in oti_primal.items():
        fd_rec = fd_primal[inc]
        assert oti_rec["yielded"] == fd_rec["yielded"], (inc, oti_rec, fd_rec)
        for i, (a, b) in enumerate(zip(oti_rec["stress"], fd_rec["stress"])):
            assert a == pytest.approx(b, rel=1e-10, abs=1e-8), (inc, i, a, b)
        assert oti_rec["eqplas"] == pytest.approx(fd_rec["eqplas"], rel=1e-10, abs=1e-10)

    # 4) DSIGMA_DP: OTI Fortran vs. Python FD across every increment + parameter.
    oti_sigma = _read_matrix_csv(result.dsigma_csv)
    fd_sigma = _read_matrix_csv(fd_files["DSIGMA_DP_FD"])
    for key in oti_sigma["rows"]:
        assert key in fd_sigma["rows"], key
    for (inc, row_label), oti_values in oti_sigma["rows"].items():
        fd_values = fd_sigma["rows"][(inc, row_label)]
        assert len(oti_values) == len(fd_values) == len(PARAMETER_NAMES)
        for k, (a, b) in enumerate(zip(oti_values, fd_values)):
            scale = max(abs(a), abs(b), 1.0)
            # The centered-FD step is O(1e-6) so its absolute error can be
            # up to a few times the step size squared. 1e-4 relative is a
            # comfortable envelope on both elastic and plastic branches.
            assert abs(a - b) / scale < 1e-4, (inc, row_label, PARAMETER_NAMES[k], a, b)

    # 5) DSTATEV_DP: same comparison for the state-variable sensitivity.
    oti_state = _read_matrix_csv(result.dstatev_csv)
    fd_state = _read_matrix_csv(fd_files["DSTATEV_DP_FD"])
    for (inc, row_label), oti_values in oti_state["rows"].items():
        fd_values = fd_state["rows"][(inc, row_label)]
        for k, (a, b) in enumerate(zip(oti_values, fd_values)):
            scale = max(abs(a), abs(b), 1.0)
            assert abs(a - b) / scale < 1e-4, (inc, row_label, PARAMETER_NAMES[k], a, b)

    # 6) Comparison CSV summary artefact.
    comparison_csv = tmp_path / "parameter_sensitivity_comparison.csv"
    summary = compare_oti_vs_fd(
        oti_dsigma_csv=result.dsigma_csv,
        oti_dstatev_csv=result.dstatev_csv,
        fd_dsigma_csv=fd_files["DSIGMA_DP_FD"],
        fd_dstatev_csv=fd_files["DSTATEV_DP_FD"],
        output_csv=comparison_csv,
    )
    assert comparison_csv.is_file()
    assert summary["max_rel_diff"] < 1e-4, summary


@REQUIRES_GFORTRAN
def test_generated_fortran_contains_props_seeding_and_getim_extraction(tmp_path: Path):
    """Priority-1 evidence: the generated code must contain a visible
    PROPS-seeding block and GETIM extraction of DSIGMA_DP / DSTATEV_DP.
    """
    layout = generate_j2_oti_build(tmp_path)
    driver_text = layout.j2_driver.read_text(encoding="utf-8")
    # Parameter-seeding block: PROPS gets E1..E4 seeded on top of the operating point.
    for line in (
        "PROPS(1) = E_VAL     + E1",
        "PROPS(2) = NU_VAL    + E2",
        "PROPS(3) = SIGY0_VAL + E3",
        "PROPS(4) = H_VAL     + E4",
    ):
        assert line in driver_text, f"missing PROPS-seeding line: {line}"
    # DSIGMA_DP extraction via GETIM.
    assert "dsigma(I, K) = GETIM(STRESS(I), K)" in driver_text
    # DSTATEV_DP extraction via GETIM.
    assert "dstatev(I, K) = GETIM(STATEV(I), K)" in driver_text
