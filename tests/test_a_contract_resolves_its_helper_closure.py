"""A compact contract can name where the helpers its UMAT calls are published.

UMAT_PCO.for calls KCLEAR, KMMULT, KSMULT, ... and defines none of them; its
family (the EAFIT ICP UMATs, MIT-licensed upstream at jgomezc1/ABAQUS-US) defines
them in sibling files. The committed benchmark contract used to fail the
transform for that reason. It now declares ``"dependency_roots"`` and the
transformation service resolves the routine closure, writes it entry file first
(so every line anchor still points at the same statement) and transforms that
one file; the paired validation reads the same resolved file for the original.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from umat_oti.services.transformation import (
    TransformationOptions, _payload_with_resolved_closure, run_transformation,
)

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.regression]

ENTRY = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),DSTRAN(NTENS),DDSDDE(NTENS,NTENS),PROPS(NPROPS)
      CALL KSCALE(DDSDDE,NTENS,PROPS(1))
      RETURN
      END
"""
HELPER = """\
      SUBROUTINE KSCALE(A,N,S)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION A(N,N)
      DO I=1,N
        A(I,I)=S
      END DO
      RETURN
      END
"""


def _contract(tmp_path: Path, roots) -> Path:
    (tmp_path / "entry").mkdir()
    (tmp_path / "helpers").mkdir()
    (tmp_path / "entry" / "umat_entry.for").write_text(ENTRY)
    (tmp_path / "helpers" / "library.for").write_text(HELPER)
    path = tmp_path / "contract.json"
    payload = {"name": "entry", "source": "entry/umat_entry.for", "ntens": 6, "order": 1,
               "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"}}
    if roots is not None:
        payload["dependency_roots"] = roots
    path.write_text(json.dumps(payload))
    return path


def test_a_contract_without_roots_is_read_unchanged(tmp_path):
    path = _contract(tmp_path, None)
    payload, closure = _payload_with_resolved_closure(path, tmp_path / "out")
    assert closure is None
    assert payload == path.read_bytes()


def test_declared_roots_resolve_the_helper_entry_file_first(tmp_path):
    path = _contract(tmp_path, ["helpers"])
    payload, closure = _payload_with_resolved_closure(path, tmp_path / "out")
    resolved = Path(closure["resolved_source"])
    assert [d["routine"] for d in closure["external_definitions"]] == ["KSCALE"]
    text = resolved.read_text()
    assert text.startswith(ENTRY.rstrip("\n"))
    assert "SUBROUTINE KSCALE" in text
    assert json.loads(payload)["source"] == str(resolved)


def test_a_root_that_lacks_the_helper_is_an_error_not_a_guess(tmp_path):
    path = _contract(tmp_path, ["entry"])
    with pytest.raises(ValueError, match="KSCALE"):
        _payload_with_resolved_closure(path, tmp_path / "out")


def test_jacobian_can_discover_transitive_helpers_without_a_manual_contract(tmp_path):
    from umat_oti.services.jacobian_request import jacobian_contract

    path = _contract(tmp_path, None)
    helper = tmp_path / "helpers" / "library.for"
    helper.write_text(HELPER.replace("      RETURN", "      CALL FINISH(A,N)\n      RETURN"))
    (tmp_path / "helpers" / "finish.for").write_text(
        "      SUBROUTINE FINISH(A,N)\n      REAL*8 A(N,N)\n      END\n")
    contract = jacobian_contract(
        tmp_path / "entry" / "umat_entry.for", ntens=6,
        discover_dependencies=True, dependency_roots=[tmp_path / "helpers"])
    path.write_text(json.dumps(contract))
    output = tmp_path / "entry" / "out"
    output.mkdir()
    (output / "stale.for").write_text(HELPER.replace("A(I,I)=S", "A(I,I)=99*S"))
    payload, closure = _payload_with_resolved_closure(path, output)

    assert {row["routine"] for row in closure["external_definitions"]} == {"KSCALE", "FINISH"}
    assert Path(json.loads(payload)["source"]).is_file()


def test_jacobian_dependency_discovery_is_opt_in(tmp_path):
    from umat_oti.services.jacobian_request import jacobian_contract

    contract = jacobian_contract(tmp_path / "umat.for", ntens=6)
    assert "dependency_roots" not in contract


def test_discovery_uses_the_selected_nonstandard_entry(tmp_path):
    path = _contract(tmp_path, ["helpers"])
    entry = tmp_path / "entry" / "umat_entry.for"
    entry.write_text(ENTRY.replace("SUBROUTINE UMAT(", "SUBROUTINE UMAT_MATERIAL("))
    _, closure = _payload_with_resolved_closure(path, tmp_path / "out")
    assert closure["entry_routine"] == "UMAT_MATERIAL"
    assert [row["routine"] for row in closure["external_definitions"]] == ["KSCALE"]


@pytest.mark.fortran
def test_cli_discovers_lifts_and_compiles_helpers(tmp_path, capsys):
    from umat_oti.cli import main

    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required")
    source = tmp_path / "umat.f90"
    source.write_text("""subroutine umat(stress, dstran, ddsdde, ntens)
implicit none
integer :: ntens, component
real(8) :: stress(ntens), dstran(ntens), ddsdde(ntens,ntens), delta
do component = 1, ntens
  call increment(dstran(component), delta)
  stress(component) = stress(component) + delta
end do
ddsdde = 0.0d0
end subroutine umat
""")
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "increment.f90").write_text("""subroutine increment(strain, delta)
implicit none
real(8) :: strain, delta
call scale_value(strain, delta)
end subroutine increment
""")
    (helpers / "scale.f90").write_text("""subroutine scale_value(strain, delta)
implicit none
real(8) :: strain, delta
delta = 2.0d0 * strain
end subroutine scale_value
""")
    output = tmp_path / "out"
    arguments = ["jacobian", str(source), "--ntens", "6", "--out", str(output),
                 "--discover-dependencies", "--dependency-root", str(helpers), "--compile"]
    assert main(arguments) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["compilation"]["status"] == "compiled"
    assert {row["routine"] for row in summary["dependency_closure"]["external_definitions"]} == {
        "INCREMENT", "SCALE_VALUE"}
    lifted = (output / "umat_oti_helpers.f90").read_text().upper()
    assert "SUBROUTINE INCREMENT_OTI" in lifted
    assert "SUBROUTINE SCALE_VALUE_OTI" in lifted
    assert "CALL SCALE_VALUE_OTI" in lifted
    driver = tmp_path / "check.f90"
    driver.write_text("""program check
implicit none
integer :: component
real(8) :: stress(6), dstran(6), ddsdde(6,6), expected(6,6)
stress = 0.0d0
dstran = 0.125d0
expected = 0.0d0
do component = 1, 6
    expected(component, component) = 2.0d0
end do
call umat(stress, dstran, ddsdde, 6)
if (maxval(abs(stress - 0.25d0)) > 1.0d-12) stop 1
if (maxval(abs(ddsdde - expected)) > 1.0d-12) stop 2
end program check
""")
    executable = tmp_path / "check"
    subprocess.run(["gfortran", "-ffree-line-length-none", summary["combined_source"],
                    str(driver), "-o", str(executable)], cwd=output,
                   capture_output=True, text=True, check=True)
    subprocess.run([str(executable)], capture_output=True, text=True, check=True)
    assert main(arguments) == 0
    capsys.readouterr()
    (helpers / "conflict.f90").write_text(
        (helpers / "scale.f90").read_text().replace("2.0d0", "3.0d0"))
    assert main(arguments) != 0
    summary = json.loads(capsys.readouterr().out)
    assert "ambiguous SCALE_VALUE" in summary["error"]
    (helpers / "conflict.f90").unlink()
    (helpers / "scale.f90").unlink()
    assert main(arguments) != 0
    summary = json.loads(capsys.readouterr().out)
    assert "missing SCALE_VALUE" in summary["error"]
    dependency_report = json.loads((output / "dependency_report.json").read_text())
    assert dependency_report["missing"]
    assert "SCALE_VALUE" in dependency_report["edges"]["INCREMENT"]


@pytest.mark.fortran
def test_the_pco_benchmark_transforms_and_compiles_from_its_committed_contract(tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, code = run_transformation(REPO / "benchmarks" / "UMAT_PCO.json", tmp_path / "t",
                                           TransformationOptions(compile_generated=True))
    assert code == 0 and summary["transform_success"], summary.get("blockers")
    assert summary["compilation"]["status"] == "compiled"
    closure = summary["dependency_closure"]
    assert closure["multi_file"] is True
    helpers = {d["routine"] for d in closure["external_definitions"]}
    assert {"KCLEAR", "KMMULT", "KSMULT"} <= helpers
    assert summary["source"] == closure["resolved_source"]
