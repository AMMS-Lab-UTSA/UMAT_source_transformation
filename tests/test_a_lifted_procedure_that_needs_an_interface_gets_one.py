"""A lifted procedure that needs an explicit interface gets one at its call.

An internal procedure is lifted to an external one, which its host then calls
through an implicit interface unless the transform declares one. That is
wrong for a procedure with an assumed-shape dummy (``A(:,:)``), an optional,
allocatable, pointer or VALUE dummy, an array or allocatable result, or the
ELEMENTAL attribute: the call compiles and then reads the wrong memory.
Before 1.2.1 a function with a scalar result and an ``A(:,:)`` dummy was
transformed, reported SUCCESS and crashed when run.

Each fixture is transformed, compiled and run, and checked against its
original: the stress bit for bit, and DDSDDE against central differences.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.source_transform import (
    _lifted_interface_blockers, _lifted_procedures_needing_an_interface)
from umat_oti.validation.parameter_sensitivity_validation import (
    build_original_driver, driver_source, replay)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "explicit_interface"
PROPS = [0.3]
DSTRAN = [0.1, 0.05, 0.02]


@pytest.mark.unit
def test_the_reasons_an_interface_is_needed_are_found():
    text = """function f_oti(a) result(s)
    type(T) :: A(:, :)
    type(T) :: S
end function f_oti
subroutine g_oti(x, y)
    type(T), optional :: Y
    type(T) :: X(3)
end subroutine g_oti
function h_oti(x) result(r)
    type(T) :: X
    type(T) :: R(2)
end function h_oti
subroutine k_oti(x)
    type(T) :: X(3)
end subroutine k_oti
"""
    found = _lifted_procedures_needing_an_interface(text)
    assert set(found) == {"F_OTI", "G_OTI", "H_OTI"}
    assert "assumed-shape" in found["F_OTI"]["why"]
    assert "OPTIONAL" in found["G_OTI"]["why"]
    assert found["G_OTI"]["kind"] == "SUBROUTINE"
    assert "result" in found["H_OTI"]["why"]


@pytest.mark.unit
def test_a_lifted_routine_calling_one_that_needs_an_interface_is_refused():
    text = """function f_oti(a) result(s)
    type(T) :: A(:, :)
    type(T) :: S
end function f_oti
subroutine caller_oti(b, s)
    type(T) :: B(2,2), S
    s = f_oti(b)
end subroutine caller_oti
"""
    blockers = _lifted_interface_blockers(text)
    assert len(blockers) == 1 and "F_OTI" in blockers[0] and "implicit" in blockers[0]


@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
@pytest.mark.parametrize("fixture", ["assumed_shape_function.for"])
def test_the_transformed_build_runs_and_matches_the_original(tmp_path, fixture):
    source = FIXTURES / fixture
    contract = {"name": source.stem, "source": str(source), "ntens": 3, "order": 1,
                "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
                "promote": ["STRESS"], "replace": []}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract))
    out = tmp_path / "oti"
    summary, code = run_transformation(path, out, TransformationOptions(compile_generated=True))
    assert code == 0 and summary["compilation"]["status"] == "compiled", summary.get("blockers")
    assert "INTERFACE" in Path(summary["transformed_source"]).read_text().upper()
    objects = []
    for unit in (out / "compile_order.txt").read_text().split():
        candidate = out / f"{Path(unit).stem}.o"
        objects.append(str(candidate if candidate.exists() else out / "transformed_umat.o"))
    tangents = out / "ddsdde.txt"
    text = driver_source(ntens=3, nstatv=1, nprops=1)
    text = text.replace("  READ(*,*) NINC", f"  READ(*,*) NINC\n  OPEN(77,FILE='{tangents}',STATUS='REPLACE')")
    text = text.replace("STRESS,STATEV\n", "STRESS,STATEV\n    WRITE(77,'(9(ES26.17E3,1X))') DDSDDE\n", 1)
    (out / "driver.f90").write_text(text)
    linked = subprocess.run(["gfortran", "-ffree-line-length-none", str(out / "driver.f90"), *objects,
                             "-o", str(out / "driver")], cwd=out, capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr[-2000:]
    transformed = replay(out / "driver", PROPS, [DSTRAN], ntens=3, nstatv=1)
    original_exe = build_original_driver(source, tmp_path / "original", ntens=3, nstatv=1, nprops=1)
    original = replay(original_exe, PROPS, [DSTRAN], ntens=3, nstatv=1)
    assert transformed.stress == original.stress
    ddsdde = [float(v) for v in tangents.read_text().split()]
    step = 1e-6
    for j in range(3):
        plus, minus = list(DSTRAN), list(DSTRAN)
        plus[j] += step
        minus[j] -= step
        up = replay(original_exe, PROPS, [plus], ntens=3, nstatv=1).stress[0]
        down = replay(original_exe, PROPS, [minus], ntens=3, nstatv=1).stress[0]
        for i in range(3):
            fd = (up[i] - down[i]) / (2 * step)
            assert abs(ddsdde[i + 3 * j] - fd) <= 1e-7 * max(1.0, abs(fd)), (i, j, ddsdde[i + 3 * j], fd)


@pytest.mark.regression
def test_an_internal_subroutine_with_an_assumed_shape_dummy_is_refused_not_miscompiled(tmp_path):
    """Lifting does not yet reach an internal SUBROUTINE called by CALL; the
    transform must refuse it by name rather than report SUCCESS."""
    source = FIXTURES / "assumed_shape_subroutine.for"
    contract = {"name": source.stem, "source": str(source), "ntens": 3, "order": 1,
                "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
                "promote": ["STRESS"], "replace": []}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract))
    summary, code = run_transformation(path, tmp_path / "oti", TransformationOptions(compile_generated=True))
    if code == 0:
        pytest.fail("an internal subroutine with an assumed-shape dummy now transforms; "
                    "extend test_the_transformed_build_runs_and_matches_the_original to it")
    assert not summary.get("transform_success")
    assert any("TRSQS" in str(blocker) for blocker in summary.get("blockers") or []), summary.get("blockers")
