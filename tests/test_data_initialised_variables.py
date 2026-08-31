"""A DATA statement gives a value that no assignment scan can see.

Everything downstream reads "never assigned" as "never given a value". For a
DATA-initialised name the truth is the opposite: it holds a compile-time
constant. Promoting one declares a shadow, the initialiser zeroes it, and the
DATA values never arrive -- so the constant silently becomes zero in the
stress that is written back and in every derivative taken from it, with the
file compiling and every semantic check green.
"""
from __future__ import annotations

import json

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.core.roles import data_initialised_names
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.source_transform import _data_initialised_shadow_blockers


class TestReadingDataStatements:
    def test_a_simple_array_initialiser(self):
        assert data_initialised_names(
            "      data xi/1.d0,1.d0,1.d0,0.d0,0.d0,0.d0/") == {"XI"}

    def test_several_names_in_one_statement(self):
        assert data_initialised_names("      DATA A,B/1.0,2.0/") == {"A", "B"}

    def test_an_implied_do_names_the_array_not_the_index(self):
        assert data_initialised_names("      DATA (X(I),I=1,3)/1.,2.,3./") == {"X"}

    def test_a_repeat_count_is_not_a_name(self):
        assert data_initialised_names("      data z/6*0.d0/") == {"Z"}

    def test_a_commented_data_statement_initialises_nothing(self):
        assert data_initialised_names("C     data nope/1.0/") == frozenset()

    def test_a_source_without_data_yields_nothing(self):
        assert data_initialised_names("      real*8 a\n      a = 1.0") == frozenset()


#: The shape mholla/growth uses: the Voigt identity as a DATA-initialised
#: local, read in the stress update and never assigned. The arithmetic is only
#: enough to put xi on the derivative path.
VOIGT_IDENTITY_UMAT = """\
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


def _transform(tmp_path, text, name="voigt"):
    src = tmp_path / f"{name}.f"
    src.write_text(text, encoding="utf-8")
    config, _finite = _build_contract(name, "auto", "STRESS", "DDSDDE", 6, 1, src)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _ = run_transformation(config_path, tmp_path / "out",
                                    TransformationOptions(compile_generated=False))
    generated = list((tmp_path / "out").glob("*_oti.f"))
    text_out = generated[0].read_text(encoding="utf-8") if generated else ""
    return config, summary, text_out


def test_a_data_constant_is_not_promoted(tmp_path):
    config, _summary, _text = _transform(tmp_path, VOIGT_IDENTITY_UMAT)
    assert "XI" not in config["variables"]["promote"]


def test_a_data_constant_is_kept_real(tmp_path):
    config, _summary, _text = _transform(tmp_path, VOIGT_IDENTITY_UMAT)
    assert "XI" in config["variables"]["real"]


def test_the_data_statement_survives_into_the_generated_file(tmp_path):
    _config, _summary, text = _transform(tmp_path, VOIGT_IDENTITY_UMAT)
    assert "data xi/" in text.lower()


def test_no_zeroed_shadow_replaces_the_constant(tmp_path):
    """XI_OTI(...) = 0.0D0 beside a live XI_OTI read is the silent failure."""
    _config, _summary, text = _transform(tmp_path, VOIGT_IDENTITY_UMAT)
    assert "XI_OTI" not in text.upper(), (
        "a shadow for a DATA constant is zeroed and never given its values")


def test_the_constant_is_still_read_on_the_stress_path(tmp_path):
    """Keeping it real must not remove it from the expression."""
    _config, _summary, text = _transform(tmp_path, VOIGT_IDENTITY_UMAT)
    stress_lines = [l for l in text.splitlines()
                    if "STRESS_OTI" in l.upper() and "xi(" in l.lower()]
    assert stress_lines, "the identity term left the stress update entirely"


def test_the_transform_still_succeeds(tmp_path):
    _config, summary, _text = _transform(tmp_path, VOIGT_IDENTITY_UMAT)
    assert summary.get("transform_success") is True, (
        summary.get("blockers"), summary.get("warnings"))


class TestTheUnhandledCaseIsRefused:
    """DATA-initialised AND assigned needs the value carried, and nothing does."""

    def test_a_promoted_data_variable_is_a_blocker(self):
        source = ("      real*8 v(3)\n"
                  "      data v/1.0,2.0,3.0/\n"
                  "      v(1) = v(1) + dstran(1)\n")
        blockers = _data_initialised_shadow_blockers(
            source, {"seed": set(), "promote": {"V"}})
        assert len(blockers) == 1
        assert "start at zero" in blockers[0]

    def test_a_data_variable_that_is_not_promoted_is_not_a_blocker(self):
        source = "      real*8 v(3)\n      data v/1.0,2.0,3.0/\n"
        assert _data_initialised_shadow_blockers(
            source, {"seed": set(), "promote": {"W"}}) == []

    def test_a_source_with_no_data_statement_is_not_a_blocker(self):
        assert _data_initialised_shadow_blockers(
            "      real*8 v(3)\n", {"seed": set(), "promote": {"V"}}) == []

    def test_a_seeded_data_variable_is_refused_too(self):
        source = "      real*8 v(3)\n      data v/1.0,2.0,3.0/\n      v(1)=v(1)+1.d0\n"
        assert _data_initialised_shadow_blockers(
            source, {"seed": {"V"}, "promote": set()})
