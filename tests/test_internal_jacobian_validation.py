"""Internal-Jacobian extraction: driver regressions and the end-to-end funnel."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    _emit_driver,
)
from umat_oti.validation.internal_jacobian_validation import (
    InternalJacobianCase,
    verify_internal_jacobian,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _contract(tmp_path: Path) -> GenericPSContract:
    return GenericPSContract(
        name="probe", umat_source_path=tmp_path / "umat.for",
        parameters=(("P1", 1),), parameter_values=(1.0,),
        state_variables=(("SDV1", 1),), ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1e-4, 0.0, 0.0, 0.0, 0.0, 0.0), n_increments=4,
        static_props=(1.0,))


def test_driver_advances_the_increment_number(tmp_path):
    """KINC must track the loading loop.

    Regression: the emitted driver pinned KINC=1 for every increment while the
    untransformed reference driver ran DO KINC=1,NINC. Any UMAT that branches on
    the increment number -- first-increment initialisation is a common idiom --
    would then see a different loading history in the two builds, so primal
    parity would compare unlike responses.
    """
    driver = _emit_driver(_contract(tmp_path), "otim", "oti_real")
    assert "KINC = INC" in driver
    body = driver[driver.index("DO INC = 1, N_INC"):]
    assert body.index("KINC = INC") < body.index("CALL umat_oti")


def test_driver_advances_total_time(tmp_path):
    """TIME must advance with the strain, as the reference driver does.

    Regression: TIME stayed at zero for the whole path in the transformed
    build, so rate- and time-dependent models integrated a different history
    from the reference they were compared against.
    """
    driver = _emit_driver(_contract(tmp_path), "otim", "oti_real")
    assert "TIME(1) = TIME(1) + DTIME" in driver
    assert "TIME(2) = TIME(2) + DTIME" in driver


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_m5_cpflow_internal_jacobian_is_extracted_and_verified(tmp_path):
    """The full funnel on a redistributable model with a local Newton solve.

    Asserts the scientific content rather than a stored number: the extracted
    coefficient must agree with centred differences of the independently
    compiled untransformed build, and the recording injection must leave the
    primal response bit-identical.
    """
    case = InternalJacobianCase(
        model="m5_cpflow",
        source_path=REPO_ROOT / "parameter_sensitivity/models/m5_cpflow/umat.for",
        props=(200000.0, 0.3, 1500.0, 25.0, 0.4, 1.6, 0.1, 60000.0),
        dstran_per_increment=(1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=20, ntens=6, nstatv=1, ndi=3, nshr=3,
        state_names=("EQPLAS",))
    record = verify_internal_jacobian(case, tmp_path)

    assert record["stages"]["recording_is_non_perturbing"]["status"] == "succeeded"
    assert record["stages"]["recording_is_non_perturbing"]["max_stress_drift"] == 0.0
    assert record["furthest_stage"] == "jacobian_verified"
    assert record["stages"]["jacobian_verified"]["status"] == "succeeded"

    extracted = record["extracted"]
    reference = extracted["finite_difference"]
    assert abs(extracted["oti"] - reference) / abs(reference) < 1e-8
    # The source's own Jacobian is audited against the same reference, never
    # used as the reference for the extracted value.
    assert record["hand_coded_audit"]["relative_difference"] < 1e-8
