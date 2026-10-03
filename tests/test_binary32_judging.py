"""Binary32 judging, Vera B10 B32-0..3 (fd.B32_RULE).

Wrinkle (Jeff97 l1-is-1--l2-is-12) stores G11..G22 in REAL; for STATEV_n(3)
the OTI value (8.18) agreed with neither the original's FD (-2.083) nor the
double variant's (0.435): it must stay FAIL. An entry whose OTI matches the
double variant, while the two references both resolve and differ, is
unresolved_binary32 -- never a pass.
"""
import shutil

import numpy as np
import pytest

from umat_oti.corpus_features import binary32_scope, fd

pytestmark = pytest.mark.unit

L = fd.DEFAULT_LADDER
USABLE = list(range(len(L)))


def _column(values):
    est = [np.asarray(values, float) for _ in L]
    return fd.ColumnFD(est, est, est, USABLE, USABLE, True, "smooth", [0.0] * len(L),
                       steps=list(L), base=np.zeros(len(values)),
                       magnitude=np.full(len(values), 1e-6))


KW = dict(magnitude=np.array([1e-6]), derivative_scale=2.0, euler=False)


def test_b32_1_a_pass_under_the_binary32_noise_is_labelled_pass_b32():
    v = fd.judge_binary32(np.array([2.0 * (1 + 1e-9)]), _column([2.0]).estimates, USABLE, L,
                          **KW)
    assert v.codes == [fd.PASS_B32] and v.passed == 1 and v.status == "verified"


def test_b32_1_the_resolution_gate_stays():
    # a large output magnitude: the binary32 atol is above 1e-3 |D| -> unresolved
    v = fd.judge_binary32(np.array([2.0]), _column([2.0]).estimates, USABLE, L,
                          magnitude=np.array([1.0]), derivative_scale=2.0, euler=False)
    assert v.codes == [fd.UNRESOLVED_ROUNDOFF]
    assert fd.judge_column(np.array([2.0]), _column([2.0]).estimates, USABLE, L,
                           magnitude=np.array([1.0]), derivative_scale=2.0, euler=False).codes == [fd.PASS]


def test_b32_2_a_double_floor_failure_that_is_no_b32_pass_stays_fail():
    # the binary32 noise makes the entry unresolved; the double floor failed it
    v = fd.judge_binary32(np.array([2.5]), _column([2.0]).estimates, USABLE, L,
                          magnitude=np.array([1.0]), derivative_scale=2.0, euler=False)
    assert v.codes == [fd.FAIL] and v.failed == 1
    (_, value, ref, tol, _), = v.failed_entries
    assert abs(value - ref) / tol > 1.0


def test_b32_3_wrinkle_statev3_agrees_with_neither_reference_and_stays_fail():
    original, variant = _column([-2.083]), _column([0.435])
    v = fd.judge_binary32(np.array([8.18]), original.estimates, USABLE, L, variant=variant,
                          **KW)
    assert v.codes == [fd.FAIL] and not v.binary32_entries


def test_b32_3_matching_the_double_variant_is_unresolved_binary32_never_a_pass():
    original, variant = _column([-2.083]), _column([0.435])
    v = fd.judge_binary32(np.array([0.435]), original.estimates, USABLE, L, variant=variant,
                          **KW)
    assert v.codes == [fd.UNRESOLVED_BINARY32]
    assert v.passed == 0 and v.failed == 0 and v.unresolved == 1
    assert v.binary32_entries == [(0, -2.083, 0.435, 0.435)]


def test_b32_3_needs_the_references_to_differ_and_a_variant_at_all():
    # the value matches the variant, but the references are within 1e-3
    near = fd.judge_binary32(np.array([2.0 * (1 + 1e-4)]), _column([2.0]).estimates, USABLE, L,
                             variant=_column([2.0 * (1 + 1e-4)]), **KW)
    assert near.codes == [fd.FAIL]
    none = fd.judge_binary32(np.array([0.435]), _column([-2.083]).estimates, USABLE, L,
                             variant=None, **KW)
    assert none.codes == [fd.FAIL]                       # no variant: the failure stays


def test_b32_0_scope_is_the_transform_map():
    assert binary32_scope.scope(None, "x")["in_scope"] is None
    assert binary32_scope.scope({"stores": []}, "x")["in_scope"] is False
    s = binary32_scope.scope({"stores": [{"name": "G11"}], "rounded_operations": 3}, "x")
    assert s["in_scope"] is True and s["stores"] == ["G11"]


def test_b32_0_a_store_entry_map_is_read_from_its_transform_report(tmp_path):
    (tmp_path / "transform_report.json").write_text(
        '{"binary32_stores": {"present": true, "stores": [{"name": "MMOD"}]}}')
    s = binary32_scope.store_scope(tmp_path, [], "")
    assert s["in_scope"] is True and s["origin"].startswith("transform_report.json")


def test_the_double_variant_widens_every_explicit_single_declaration_only():
    text = ("      SUBROUTINE U(X)\n"
            "      INCLUDE 'ABA_PARAM.INC'\n"
            "      REAL  TOTALT,G11,G22\n"
            "      REAL*4 H\n"
            "      DOUBLE PRECISION D\n"
            "      G11 = 1.0\n"
            "      END\n")
    variant, info = binary32_scope.double_variant(text)
    assert "REAL*8  TOTALT,G11,G22" in variant and "REAL*8 H" in variant
    assert "DOUBLE PRECISION D" in variant and "G11 = 1.0" in variant
    assert info["widened"] == ["G11", "G22", "H", "TOTALT"]
    assert len(info["changes"]) == 2


BINARY32_UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      REAL GMOD
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      GMOD=PROPS(1)/3.D0
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=0.D0
        END DO
        DDSDDE(K1,K1)=GMOD
        STRESS(K1)=STRESS(K1)+GMOD*DSTRAN(K1)
      END DO
      STATEV(1)=STATEV(1)+DSTRAN(1)
      RETURN
      END
"""


@pytest.mark.slow
@pytest.mark.fortran
def test_the_harness_applies_b32_to_a_build_in_scope(tmp_path, monkeypatch):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features import harness
    from umat_oti.corpus_features.harness import CorpusEntry, run_entry
    from umat_oti.corpus_features.paths import internal_paths
    monkeypatch.setattr(harness.binary32_scope, "lifted_scope", lambda *a, **k:
                        binary32_scope.scope({"stores": [{"name": "GMOD"}]}, "test"))
    source = tmp_path / "b32.f"
    source.write_text(BINARY32_UMAT)
    entry = CorpusEntry(key="b32", source_id="test/b32.f", original_source=source,
                        ntens=6, nstatv=1, props=[2.0e5], kinematics="small",
                        family="elasticity")
    paths = internal_paths(entry.as_mapping())[:1]
    records = run_entry(entry, tmp_path / "work", paths=paths,
                        features=("stress_param_sens_local",))
    (record,) = [r for r in records if r["feature"] == "stress_param_sens_local"]
    b32 = record["binary32"]
    assert b32["applied"] is True and b32["scope"]["stores"] == ["GMOD"]
    assert "same perturbations" in b32["double_variant"], b32
    # every pass in scope is a B32 pass
    assert not record["entries"].get(fd.PASS) and not record["entries"].get(fd.ZERO_PASS)
    assert b32["pass_b32"] == record["entries"].get(fd.PASS_B32, 0)
