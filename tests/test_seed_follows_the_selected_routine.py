"""The seed is a variable the routine being transformed actually receives.

The contract scaffolder used to write ``variables.seed = ["DSTRAN"]`` for
every source, whatever the kinematics and whatever the selected routine takes.
When the material lives in a routine one call below UMAT -- an ordinary way to
write one, and how fifteen of the seventy-one discovered sources are written
-- that routine is handed the arguments the model needs, which for a
finite-strain material is the deformation gradient and not the strain
increment. The emitter then wrote ``DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)`` into a
routine whose argument list has no DSTRAN, and the ``implicit none`` those
routines declare turned it into "Function 'dstran_oti' has no IMPLICIT type".

What each shape must produce:

  * a small-strain UMAT that takes DSTRAN            -> seed from DSTRAN
  * a finite-strain routine with DFGRD1 and no DSTRAN -> seed from DFGRD1 alone
  * a routine that takes both                        -> seed from DSTRAN, with
    the same directions also mapped into DFGRD1, so neither input is dropped
"""
from __future__ import annotations

import json
import shutil

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.corpus.cli import _write_aba_param_stub
from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.fortran.symbols import find_routine, routine_symbol_names
from umat_oti.services.transformation import TransformationOptions, run_transformation

#: The Abaqus entry point, which receives everything, delegating to a model
#: routine that receives only what it uses. The wrapper is a pure delegation,
#: so the transform selects the model routine.
DELEGATED_FINITE_STRAIN = """\
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

      call model_routine(stress,statev,ddsdde,props,dfgrd1,
     #                   ntens,nstatv,nprops)

      return
      end

      subroutine model_routine(stress,statev,ddsdde,props,dfgrd1,
     #                         ntens,nstatv,nprops)
      implicit none
      integer ntens, nstatv, nprops, i, j
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 props(nprops), dfgrd1(3,3)
      real*8 lam, mu, detf, bb(3,3), trbb
      lam = props(1)
      mu  = props(2)
      detf = dfgrd1(1,1)*dfgrd1(2,2)*dfgrd1(3,3)
      do i = 1, 3
        do j = 1, 3
          bb(i,j) = dfgrd1(i,j)*dfgrd1(j,i)
        end do
      end do
      trbb = bb(1,1) + bb(2,2) + bb(3,3)
      do i = 1, ntens
        stress(i) = (lam*(detf-1.d0) + mu*trbb)/detf
      end do
      do i = 1, ntens
        do j = 1, ntens
          ddsdde(i,j) = lam/detf
        end do
      end do
      statev(1) = detf
      return
      end
"""

#: A conventional small-strain UMAT: the strain increment drives the stress
#: update and there is no deformation gradient on the path.
SMALL_STRAIN = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),DFGRD0(3,3),DFGRD1(3,3)
      EMOD=PROPS(1)
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)
      END DO
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=0.0D0
        END DO
        DDSDDE(K1,K1)=EMOD
      END DO
      STATEV(1)=STRESS(1)
      RETURN
      END
"""

#: One routine holding the whole Abaqus argument list, so DSTRAN and DFGRD1
#: are both in reach, with the deformation gradient driving the stress update.
FINITE_STRAIN_WITH_BOTH = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),DFGRD0(3,3),DFGRD1(3,3)
      EMOD=PROPS(1)
      DET=DFGRD1(1,1)*DFGRD1(2,2)*DFGRD1(3,3)
      DO K1=1,3
        STRESS(K1)=EMOD*(DFGRD1(K1,K1)-1.0D0)/DET
      END DO
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=0.0D0
        END DO
        DDSDDE(K1,K1)=EMOD
      END DO
      STATEV(1)=DET
      RETURN
      END
"""


def _contract(tmp_path, text, stem="src"):
    source = tmp_path / f"{stem}.f"
    source.write_text(text, encoding="utf-8")
    config, finite = _build_contract(stem, "auto", "STRESS", "DDSDDE", 6, 1, source)
    return config, finite, source


def _transform(tmp_path, text, stem="src", compile_generated=False):
    config, finite, source = _contract(tmp_path, text, stem)
    _write_aba_param_stub(tmp_path)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    _write_aba_param_stub(out)
    report, _ = run_transformation(
        config_path, out, TransformationOptions(compile_generated=compile_generated))
    generated = next(out.glob("*_oti.f"))
    return config, report, generated.read_text(encoding="utf-8")


def _roles(config):
    return config["variables"]


class TestWhatTheRoutineReceivesDecidesTheSeed:
    def test_a_routine_without_dstran_seeds_from_the_deformation_gradient(self, tmp_path):
        config, finite, _source = _contract(tmp_path, DELEGATED_FINITE_STRAIN)
        assert config["source"]["selected_umat_name"] == "MODEL_ROUTINE"
        assert finite is True
        assert _roles(config)["seed"] == ["DFGRD1"]

    def test_dstran_is_not_left_a_seed_when_the_routine_has_no_dstran(self, tmp_path):
        """Two seeds stop the transform on "Exactly one seed variable".

        The role classifier calls DSTRAN the seed on sight. Choosing DFGRD1
        without saying anything about DSTRAN leaves that suggestion standing
        beside it, and the contract arrives at the transform carrying both.
        """
        config, _finite, _source = _contract(tmp_path, DELEGATED_FINITE_STRAIN)
        roles = _roles(config)
        assert roles["seed"] == ["DFGRD1"]
        assert "DSTRAN" not in roles["promote"]
        assert "DSTRAN" not in roles["constant"]
        assert "DSTRAN" in roles["real"]

    def test_a_small_strain_umat_still_seeds_from_dstran(self, tmp_path):
        config, finite, _source = _contract(tmp_path, SMALL_STRAIN)
        assert finite is False
        assert _roles(config)["seed"] == ["DSTRAN"]
        assert "seed_dfgrd1" not in (config.get("transformation_settings") or {})

    def test_a_routine_that_receives_both_keeps_dstran_as_the_seed(self, tmp_path):
        """Neither input is dropped: DSTRAN seeds, and DFGRD1 is corrected."""
        config, finite, _source = _contract(tmp_path, FINITE_STRAIN_WITH_BOTH)
        assert finite is True
        assert _roles(config)["seed"] == ["DSTRAN"]
        assert config["transformation_settings"]["seed_dfgrd1"] is True


class TestRoutineSymbolNames:
    def test_it_reads_the_routines_own_interface_not_the_files(self, tmp_path):
        source = tmp_path / "src.f"
        source.write_text(DELEGATED_FINITE_STRAIN, encoding="utf-8")
        parsed = parse_fortran_file(source)
        entry = routine_symbol_names(find_routine(parsed, "UMAT"))
        model = routine_symbol_names(find_routine(parsed, "MODEL_ROUTINE"))
        assert {"DSTRAN", "DFGRD1"} <= entry
        assert "DFGRD1" in model
        assert "DSTRAN" not in model

    def test_a_routine_the_source_does_not_hold_is_not_invented(self, tmp_path):
        source = tmp_path / "src.f"
        source.write_text(DELEGATED_FINITE_STRAIN, encoding="utf-8")
        assert find_routine(parse_fortran_file(source), "NO_SUCH_ROUTINE") is None


class TestWhatTheTransformEmits:
    def test_the_selected_routine_is_never_given_an_undeclared_dstran(self, tmp_path):
        _config, report, text = _transform(tmp_path, DELEGATED_FINITE_STRAIN)
        assert report.get("transform_success") is True, (
            report.get("blockers"), report.get("warnings"))
        assert "DSTRAN_OTI" not in text.upper(), (
            "the routine has no DSTRAN; naming its shadow makes an undeclared name")

    def test_the_directions_are_injected_into_the_deformation_gradient(self, tmp_path):
        _config, _report, text = _transform(tmp_path, DELEGATED_FINITE_STRAIN)
        upper = text.upper()
        assert "DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1" in upper
        assert "DFGRD1_OTI(1,2) = DFGRD1_OTI(1,2) + 0.5D0*OTI_E4" in upper

    def test_a_routine_that_takes_both_still_perturbs_both(self, tmp_path):
        """The correction is a correction, not a replacement."""
        _config, report, text = _transform(tmp_path, FINITE_STRAIN_WITH_BOTH)
        assert report.get("transform_success") is True, (
            report.get("blockers"), report.get("warnings"))
        upper = text.upper()
        assert "DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1" in upper
        assert "DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1" in upper

    def test_a_small_strain_umat_is_still_seeded_through_dstran(self, tmp_path):
        _config, report, text = _transform(tmp_path, SMALL_STRAIN)
        assert report.get("transform_success") is True, (
            report.get("blockers"), report.get("warnings"))
        upper = text.upper()
        assert "DSTRAN_OTI(OTI_I) = DSTRAN(OTI_I)" in upper
        assert "DSTRAN_OTI(6) = DSTRAN_OTI(6) + OTI_E6" in upper
        assert "DFGRD1_OTI" not in upper


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
class TestTheEmittedFortranCompiles:
    """Reading the text is not the check; a compiler is.

    "Transformed" here means the generated Fortran compiles. It says nothing
    about whether any derivative is right -- that needs a material vector and
    a loading history these fixtures do not carry.
    """

    def test_the_delegated_finite_strain_routine_compiles(self, tmp_path):
        _config, report, _text = _transform(
            tmp_path, DELEGATED_FINITE_STRAIN, compile_generated=True)
        compilation = report.get("compilation") or {}
        assert compilation.get("status") == "compiled", compilation.get("stderr")

    def test_the_small_strain_umat_still_compiles(self, tmp_path):
        _config, report, _text = _transform(
            tmp_path, SMALL_STRAIN, compile_generated=True)
        compilation = report.get("compilation") or {}
        assert compilation.get("status") == "compiled", compilation.get("stderr")

    def test_a_routine_that_takes_both_still_compiles(self, tmp_path):
        _config, report, _text = _transform(
            tmp_path, FINITE_STRAIN_WITH_BOTH, compile_generated=True)
        compilation = report.get("compilation") or {}
        assert compilation.get("status") == "compiled", compilation.get("stderr")
