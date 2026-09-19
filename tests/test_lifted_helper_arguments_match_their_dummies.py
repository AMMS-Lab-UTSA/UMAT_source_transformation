"""Actual arguments of lifted helpers match their dummies' types (2026-09-18).

The lifted helpers are external subprograms, so every call to them goes
through an implicit interface and a type mismatch compiles without a word
from gfortran 9 or ifort. UMAT_HIN's transformed build had two:

* the integer flags ISTEP, ICYCLE and IFLAG were promoted because they sit on
  the stress path, and their shadows were passed to KCONSTITU, whose lifted
  body keeps those dummies INTEGER (it read the flag as 0);
* the reals RSTE, TMPTIM, DSTNNOR, CTIME and TIMEH, kept real by the
  contract, were passed to dummies the lifted bodies type hypercomplex through
  ``implicit type(ONUMM4N1) (a-h,o-z)`` -- the reader of the lifted text saw
  only explicit ``type(...) ::`` declarations, so neither the rewrite nor the
  check that exists for this noticed.

gfortran 10 and later refuse both, which is how continuous integration found
them. Integers are no longer promoted, the reader honours IMPLICIT, and a
shadow reaching a kept-type dummy is now reported too.
"""
from __future__ import annotations

import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from umat_oti.cli_json import run_config_transform
from umat_oti.transform.source_transform import (
    oti_arguments_into_non_oti_helper_dummies, oti_typed_dummies_of_lifted_helpers,
    real_arguments_into_oti_helper_dummies,
)
from umat_oti.validation.parameter_sensitivity_validation import (
    ABA_PARAM, build_original_driver, driver_source, replay,
)

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.regression]

LIFTED = """\
subroutine kstep_oti(stress, istep, rste, flag)
    implicit type(ONUMM4N1) (a-h,o-z)
    implicit integer (i-n)
    logical :: flag
    type(ONUMM4N1) :: stress(4)
end subroutine kstep_oti
"""


def test_the_reader_types_dummies_by_implicit_rules_and_declarations():
    dummies = oti_typed_dummies_of_lifted_helpers(LIFTED)
    # stress explicit OTI, istep implicit INTEGER, rste implicit OTI,
    # flag explicit LOGICAL
    assert dummies == {"KSTEP_OTI": ["stress", None, "rste", None]}


def test_both_directions_of_a_mismatch_are_reported():
    caller = """\
      TYPE(ONUMM4N1) :: STRESS_OTI(4), ISTEP_OTI
      REAL*8 RSTE
      LOGICAL FLAG
      CALL KSTEP_OTI(STRESS_OTI, ISTEP_OTI, RSTE, FLAG)
"""
    assert real_arguments_into_oti_helper_dummies(caller, "fixed", LIFTED, "ONUMM4N1") == [
        ("KSTEP_OTI", "RSTE", "RSTE")]
    assert oti_arguments_into_non_oti_helper_dummies(caller, "fixed", LIFTED, "ONUMM4N1") == [
        ("KSTEP_OTI", "ISTEP_OTI", 2)]
    matched = caller.replace("ISTEP_OTI)", "ISTEP)").replace("ISTEP_OTI, RSTE", "ISTEP, RSTE_OTI")
    matched = matched.replace("REAL*8 RSTE", "TYPE(ONUMM4N1) :: RSTE_OTI\n      INTEGER ISTEP")
    assert real_arguments_into_oti_helper_dummies(matched, "fixed", LIFTED, "ONUMM4N1") == []
    assert oti_arguments_into_non_oti_helper_dummies(matched, "fixed", LIFTED, "ONUMM4N1") == []


@pytest.mark.fortran
def test_hin_calls_match_and_its_stress_equals_the_original(tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, code = run_config_transform(REPO / "benchmarks" / "UMAT_HIN.json", tmp_path / "t")
    assert code == 0 and summary["transform_success"], summary.get("blockers")
    out = tmp_path / "t"
    text = next(out.glob("*_oti.for")).read_text()
    lifted = (out / "umat_oti_helpers.f90").read_text()
    for flag in ("ISTEP_OTI", "ICYCLE_OTI", "IFLAG_OTI"):
        assert flag not in text, f"the integer {flag[:-4]} was promoted"
    assert real_arguments_into_oti_helper_dummies(text, "fixed", lifted, "ONUMM4N1") == []
    assert oti_arguments_into_non_oti_helper_dummies(text, "fixed", lifted, "ONUMM4N1") == []

    # the same stress as the ORIGINAL, compiled separately and driven along the
    # same strain path with the paired-validation probe constants
    source = REPO / "UMATs" / "UMATs" / "ICP" / "UMAT_HIN.for"
    ntens, nstatv, nprops = 4, 48, 24
    props = [1.0] * nprops
    path = [[7.5e-4, -3.0e-4, 0.0, 0.0]] * 4
    original = replay(build_original_driver(source, tmp_path / "original", ntens=ntens,
                                            nstatv=nstatv, nprops=nprops),
                      props, path, ntens=ntens, nstatv=nstatv)
    work = tmp_path / "transformed"
    work.mkdir()
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / include).write_text(ABA_PARAM)
    (work / "driver.f90").write_text(driver_source(ntens=ntens, nstatv=nstatv, nprops=nprops))
    combined = next(out.glob("*_oti_combined.f90"))
    compiled = subprocess.run(["gfortran", "-O0", "-ffree-line-length-none", "-I", str(work), "-c",
                               str(combined), "-o", "umat.o"], cwd=work, capture_output=True, text=True)
    assert compiled.returncode == 0 and "Type mismatch" not in compiled.stderr, compiled.stderr[-2000:]
    subprocess.run(["gfortran", "driver.f90", "umat.o", "-o", "driver"], cwd=work, check=True,
                   capture_output=True, text=True)
    transformed = replay(work / "driver", props, path, ntens=ntens, nstatv=nstatv)
    # HIN iterates to its own tolerance (DATA TOLCL/1.0e-7/ in KCHKLOAD), and
    # the hypercomplex real part need not round exactly like REAL*8, so the
    # two builds may stop at slightly different iterates: agreement is judged
    # at that tolerance. Measured on 2026-09-18: 1.1e-9 of the stress scale.
    # The build with the mismatched arguments was 0.63 off on this path.
    scale = max(abs(v) for row in original.stress for v in row)
    assert scale > 0
    worst = max(abs(a - b) for ra, rb in zip(original.stress, transformed.stress) for a, b in zip(ra, rb))
    assert worst <= 1e-7 * scale, (worst, scale)
