"""A DATA constant that a contract lists under "promote" stays real (2026-09-18).

The stress-path promotion already declined to ADD a DATA-initialised,
never-assigned name to the promote list, but a name the contract itself listed
there stayed promoted, and the DATA blocker then refused the whole file. That is
how UMAT_HIN's committed benchmark contract failed: it promotes ONE, TWO and ZERO,
which the source's helpers set by DATA and nothing ever assigns. Such a name is a
compile-time constant and nothing seeded can reach it, so it is now kept real.
A DATA-initialised name that IS assigned still needs its value carried into a
shadow, which nothing does, and is still refused.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.cli_json import run_config_transform
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.validation.parameter_sensitivity_validation import (
    ABA_PARAM, build_original_driver, driver_source, replay,
)

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.regression]

#: The minimal shape: a Voigt identity set by DATA, read in the stress update,
#: never assigned.
DATA_CONSTANT_UMAT = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     #rpl,ddsddt,drplde,drpldt,
     #stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     #ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,
     #celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv),
     #ddsdde(ntens,ntens),ddsddt(ntens),drplde(ntens),
     #stran(ntens),dstran(ntens),time(2),predef(1),dpred(1),
     #props(nprops),coords(3),drot(3,3),dfgrd0(3,3),dfgrd1(3,3)
      real*8  xi(6), lam, mu, trde
      data xi/1.d0,1.d0,1.d0,0.d0,0.d0,0.d0/
      lam = props(1)
      mu  = props(2)
      trde = dstran(1) + dstran(2) + dstran(3)
      do k1 = 1, ntens
        stress(k1) = stress(k1) + lam*trde*xi(k1) + 2.d0*mu*dstran(k1)
      end do
      ddsdde(1,1) = lam + 2.d0*mu
      return
      end
"""


def _contract_promoting(tmp_path: Path, source_text: str, name: str) -> Path:
    """The engine's contract for this source, with NAME moved into "promote"
    the way UMAT_HIN's committed contract lists its DATA constants."""
    source = tmp_path / "data_constant.f"
    source.write_text(source_text, encoding="utf-8")
    config, _finite = _build_contract("data_constant", "auto", "STRESS", "DDSDDE", 6, 1, source)
    variables = config["variables"]
    for role in ("constant", "real"):
        variables[role] = [v for v in variables[role] if v != name]
    variables["promote"] = sorted(set(variables["promote"]) | {name})
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _transform(tmp_path: Path, source_text: str, name: str, compile_generated: bool = False):
    contract = _contract_promoting(tmp_path, source_text, name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, _ = run_transformation(contract, tmp_path / "out",
                                        TransformationOptions(compile_generated=compile_generated))
    return summary


def test_a_promoted_data_constant_is_kept_real_and_the_transform_succeeds(tmp_path):
    summary = _transform(tmp_path, DATA_CONSTANT_UMAT, "XI")
    assert summary.get("transform_success") is True, summary.get("blockers")
    text = next((tmp_path / "out").glob("*_oti.f")).read_text()
    assert "XI_OTI" not in text.upper(), "the DATA constant was given a zeroed shadow"
    assert "data xi/" in text.lower()


@pytest.mark.fortran
def test_the_kept_constant_still_reaches_the_stress(tmp_path):
    """Transformed and original builds return the same stress on a volumetric path."""
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    summary = _transform(tmp_path, DATA_CONSTANT_UMAT, "XI", compile_generated=True)
    assert summary.get("transform_success") is True, summary.get("blockers")
    props, path = [100.0, 50.0], [[1e-3, 2e-4, -3e-4, 1e-4, 0.0, 0.0]] * 3
    original = replay(build_original_driver(tmp_path / "data_constant.f", tmp_path / "original",
                                            ntens=6, nstatv=1, nprops=2),
                      props, path, ntens=6, nstatv=1)
    work = tmp_path / "transformed"
    work.mkdir()
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / include).write_text(ABA_PARAM)
    (work / "driver.f90").write_text(driver_source(ntens=6, nstatv=1, nprops=2))
    combined = next((tmp_path / "out").glob("*_oti_combined.f90"))
    subprocess.run(["gfortran", "-ffree-line-length-none", "-I", str(work), "-c", str(combined),
                    "-o", "umat.o"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(["gfortran", "driver.f90", "umat.o", "-o", "driver"], cwd=work, check=True,
                   capture_output=True, text=True)
    transformed = replay(work / "driver", props, path, ntens=6, nstatv=1)
    # the lam*trde*xi term is what a zeroed shadow would drop; it is present
    assert abs(original.stress[-1][0] - 2.0 * 50.0 * 3e-3) > 1e-3
    for a_row, b_row in zip(original.stress, transformed.stress):
        for a, b in zip(a_row, b_row):
            assert abs(a - b) <= 1e-12 * max(abs(a), 1.0)


def test_an_assigned_data_variable_in_the_promote_list_is_still_refused(tmp_path):
    assigned = DATA_CONSTANT_UMAT.replace(
        "      lam = props(1)\n", "      xi(1) = xi(1) + 0.d0*dstran(1)\n      lam = props(1)\n")
    summary = _transform(tmp_path, assigned, "XI")
    assert summary.get("transform_success") is False
    assert any("DATA statement" in str(b) for b in summary.get("blockers", []))


@pytest.mark.fortran
def test_the_hin_benchmark_transforms_from_its_committed_contract(tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, code = run_config_transform(REPO / "benchmarks" / "UMAT_HIN.json", tmp_path / "t")
    assert code == 0 and summary["transform_success"], summary.get("blockers")
    text = Path(summary["transformed_source"]).read_text().upper()
    for name in ("ONE_OTI", "TWO_OTI", "ZERO_OTI"):
        assert name not in text
    combined = next((tmp_path / "t").glob("*_oti_combined.f90"))
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (tmp_path / "t" / include).write_text(ABA_PARAM)
    compiled = subprocess.run(["gfortran", "-fsyntax-only", "-ffree-line-length-none", "-I", ".",
                               combined.name], cwd=tmp_path / "t", capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr[-2000:]
    # gfortran 10 and later refuse an argument whose type differs from the
    # dummy's; gfortran 9 only warns, so the warning is asserted absent too.
    # HIN's transformed build once passed the integer flag ISTEP as a
    # hypercomplex shadow and the reals RSTE and TMPTIM to hypercomplex
    # dummies (see tests/test_lifted_helper_arguments_match_their_dummies.py).
    assert "Type mismatch" not in compiled.stderr, compiled.stderr[-2000:]
