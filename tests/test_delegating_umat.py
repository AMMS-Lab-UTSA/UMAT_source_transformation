"""A UMAT that hands its whole job to another routine in the same file.

Keeping the Abaqus interface separate from the constitutive model is an
ordinary way to write one: ``subroutine umat(...)`` declares the argument list
Abaqus insists on, calls the model routine with what that model actually
needs, and returns. Transforming the routine named UMAT then transforms a
routine holding no stress update and no tangent, and the report says both are
missing -- accurately, one call above where they live.
"""
from __future__ import annotations

import json

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.fortran.callgraph import delegated_material_routine
from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.services.transformation import TransformationOptions, run_transformation

#: These sources ship SDVINI above the UMAT to initialise the state variables.
#: It matters here because it assigns STATEV thirty lines before the material
#: routine begins, and the search for where the finite-strain path starts read
#: the whole file.
_SDVINI = """\
      subroutine sdvini(statev,coords,nstatv,ncrds,noel,npt,layer,kspt)
      include 'aba_param.inc'
      dimension statev(nstatv), coords(ncrds)
      statev(1)=1.0d0
      statev(2)=1.0d0
      return
      end

"""

_WRAPPER = _SDVINI + """\
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
%(body)s
      return
      end
"""

_MODEL = """\
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
          bb(i,j) = 0.d0
        end do
      end do
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

DELEGATING = _WRAPPER % {"body": (
    "      call model_routine(stress,statev,ddsdde,props,dfgrd1,\n"
    "     #                   ntens,nstatv,nprops)")} + "\n" + _MODEL

#: The same file, except the entry routine also does arithmetic of its own.
#: It is then the routine to transform, call or no call.
NOT_PURE_DELEGATION = _WRAPPER % {"body": (
    "      call model_routine(stress,statev,ddsdde,props,dfgrd1,\n"
    "     #                   ntens,nstatv,nprops)\n"
    "      stress(1) = stress(1) + dstran(1)")} + "\n" + _MODEL

#: A call that does not carry the outputs is a subordinate calculation.
CALL_WITHOUT_THE_OUTPUTS = _WRAPPER % {"body": (
    "      call model_routine(props,nprops)\n"
    "      stress(1) = dstran(1)")} + """
      subroutine model_routine(props,nprops)
      implicit none
      integer nprops
      real*8 props(nprops)
      return
      end
"""


def _resolve(tmp_path, text, name="src.f"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return delegated_material_routine(parse_fortran_file(path), "UMAT")


def test_a_pure_delegation_resolves_to_the_model_routine(tmp_path):
    assert _resolve(tmp_path, DELEGATING) == "MODEL_ROUTINE"


def test_an_entry_that_computes_anything_itself_is_the_routine_to_transform(tmp_path):
    assert _resolve(tmp_path, NOT_PURE_DELEGATION) is None


def test_a_call_that_does_not_carry_stress_and_ddsdde_is_not_a_delegation(tmp_path):
    assert _resolve(tmp_path, CALL_WITHOUT_THE_OUTPUTS) is None


def test_a_call_to_a_routine_defined_elsewhere_is_not_followed(tmp_path):
    """Nothing can be transformed in a body this source does not contain."""
    external = _WRAPPER % {"body": (
        "      call vendor_model(stress,statev,ddsdde,props,dfgrd1,\n"
        "     #                  ntens,nstatv,nprops)")}
    assert _resolve(tmp_path, external) is None


def test_a_wrapper_around_a_wrapper_resolves_to_the_model(tmp_path):
    chained = _WRAPPER % {"body": (
        "      call middle(stress,statev,ddsdde,props,dfgrd1,\n"
        "     #            ntens,nstatv,nprops)")} + """
      subroutine middle(stress,statev,ddsdde,props,dfgrd1,
     #                  ntens,nstatv,nprops)
      implicit none
      integer ntens, nstatv, nprops
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 props(nprops), dfgrd1(3,3)
      call model_routine(stress,statev,ddsdde,props,dfgrd1,
     #                   ntens,nstatv,nprops)
      return
      end
""" + _MODEL
    assert _resolve(tmp_path, chained) == "MODEL_ROUTINE"


def _transform(tmp_path, text):
    src = tmp_path / "delegating.f"
    src.write_text(text, encoding="utf-8")
    config, _finite = _build_contract("delegating", "auto", "STRESS", "DDSDDE",
                                      6, 1, src)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _ = run_transformation(config_path, tmp_path / "out",
                                    TransformationOptions(compile_generated=False))
    generated = next((tmp_path / "out").glob("*_oti.f"))
    return config, summary, generated.read_text(encoding="utf-8")


def test_the_contract_names_the_model_routine_and_says_why(tmp_path):
    config, _summary, _text = _transform(tmp_path, DELEGATING)
    assert config["source"]["selected_umat_name"] == "MODEL_ROUTINE"
    assert "single call" in config["source"]["selected_umat_reason"]


def test_the_delegating_source_transforms_without_a_blocker(tmp_path):
    _config, summary, _text = _transform(tmp_path, DELEGATING)
    assert summary.get("transform_success") is True, (
        summary.get("blockers"), summary.get("warnings"))


def test_the_model_routines_dummy_arguments_are_left_alone(tmp_path):
    """Renaming them to the shadow names leaves a call no caller can satisfy.

    A finite-strain routine names DFGRD1 in its own argument list and again in
    its declarations, and those count as lines reading the deformation
    gradient. Starting the propagation region there put the header inside a
    stress region and rewrote it along with the body.
    """
    _config, _summary, text = _transform(tmp_path, DELEGATING)
    header = next(line for line in text.splitlines()
                  if "subroutine model_routine" in line.lower())
    assert "_OTI" not in header.upper(), header
    assert "stress,statev,ddsdde" in header.lower()


def test_the_module_use_line_reaches_the_model_routine(tmp_path):
    _config, _summary, text = _transform(tmp_path, DELEGATING)
    lines = text.splitlines()
    header = next(i for i, line in enumerate(lines)
                  if "subroutine model_routine" in line.lower())
    assert any("USE otim" in line for line in lines[header:header + 12])


def test_the_derivative_is_extracted_inside_the_model_routine(tmp_path):
    _config, _summary, text = _transform(tmp_path, DELEGATING)
    lines = text.splitlines()
    getim = next(i for i, line in enumerate(lines) if "GETIM" in line)
    opened = [line.strip().split()[1].split("(")[0].upper()
              for line in lines[:getim + 1]
              if line.strip().lower().startswith("subroutine ")]
    assert opened[-1] == "MODEL_ROUTINE"
