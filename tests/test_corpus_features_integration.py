"""Slow integration test: the routine-level harness on a tiny elastic UMAT.

Builds the ORIGINAL routine and the generically lifted OTI build with
gfortran, runs local and total parameter sensitivities along the internal
small-strain paths, and checks (a) the FD reference of the original against
the closed-form derivative of isotropic elasticity (independence check) and
(b) the OTI derivatives against that FD reference under decision D-4.
"""
import shutil

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.fortran]

TINY_UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      EG2=EMOD/(1.D0+ENU)
      EG=EG2/2.D0
      ELAM=(EMOD/(1.D0-2.D0*ENU)-EG2)/3.D0
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=0.D0
        END DO
      END DO
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1)=EG
      END DO
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)
        END DO
      END DO
      STATEV(1)=STATEV(1)+STRESS(1)*DSTRAN(1)
      RETURN
      END
"""


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    root = tmp_path_factory.mktemp("cf")
    source = root / "tiny_elastic.f"
    source.write_text(TINY_UMAT)
    from umat_oti.corpus_features.harness import CorpusEntry
    entry = CorpusEntry(key="tiny", source_id="test/tiny_elastic.f", original_source=source,
                        ntens=6, nstatv=1, props=[2.0e5, 0.3], kinematics="small",
                        family="elasticity")
    return root, entry


def test_fd_reference_reproduces_closed_form_elasticity(tiny):
    from umat_oti.corpus_features.harness import build_all
    from umat_oti.corpus_features.independence import check_iso_elastic
    from umat_oti.corpus_features.paths import internal_paths, kinematics_for
    root, entry = tiny
    builds = build_all(entry, root / "ind", want_store=False, want_lifted=False)
    assert builds.original.ok, builds.original.log
    path = internal_paths(entry.as_mapping())[1]
    kin = kinematics_for(path, 3, 3)
    incs = [(d, f0, f1, r, i.dtime, i.temp, i.dtemp) for (d, f0, f1, r), i in zip(kin, path.increments)]
    result = check_iso_elastic(builds.original, root / "ind" / "run", props=entry.props,
                               ntens=6, ndi=3, nshr=3, increments=incs)
    assert result["status"] == "verified", result
    assert result["min_plateau"] >= 3 and result["worst_rel"] < 1e-8


def test_harness_verifies_local_and_total_parameter_sensitivities(tiny):
    from umat_oti.corpus_features.harness import run_entry
    from umat_oti.corpus_features.paths import internal_paths
    root, entry = tiny
    features = ("stress_param_sens_local", "stress_param_sens_total",
                "state_param_sens_local", "state_param_sens_total",
                "stress_state_sens_local", "state_state_sens_local")
    records = run_entry(entry, root / "work", paths=internal_paths(entry.as_mapping()),
                        features=features)
    by = {(r["feature"], r["path"]): r for r in records}
    for path in ("gauss_small_elastic", "gauss_small_load_unload"):
        for feature in features[:4]:
            record = by[(feature, path)]
            assert record["status"] == "verified", (feature, path, record.get("reason"),
                                                    record.get("worst"))
            assert record["min_plateau_observed"] >= 3
            assert record["gates"]["lifted_primal"]["agrees"]
            assert record["derivative_kind"] in ("local", "total")
            assert record["held_fixed"] and record["wrt"] and record["quantity"]
    # STATEV(1) does not feed back into the stress: d sigma / d STATEV_n == 0
    zero = by[("stress_state_sens_local", "gauss_small_elastic")]
    assert zero["status"] == "not_attempted" and "structural zero" in zero["reason"]
    # build identity (Vera B1/E) and locators
    for record in records:
        assert record["build"] == "lifted"
        assert record["build_identity"]["transformer"].startswith(
            "umat_oti.transform.parameter_sensitivity_transform")
        assert len(record["compiled_source_sha256"]) == 64
        assert record["transformer_fingerprint"]
        assert record["reference_identity"]["build"] == "original"
        assert ":" in record["evidence_dir"] and not record["evidence_dir"].startswith("/")
        assert record["gates"]["hidden_state_trips"] == []
        assert "hidden_state_trips" not in record
    cov = by[("stress_param_sens_total", "gauss_small_load_unload")]["coverage"]
    assert cov["n_states_judged"] == cov["n_states"] > 0
