"""Hidden-state gate (Vera B1/A) and finite-strain FD direction (Vera B1/A, item 7).

Vera's three toy UMATs (corpus_campaign/batches/B1/vera/a_hidden/) are linear
elasticity with one defect each that makes restored-state finite differences
of the routine invalid:

* a1 -- SAVEd Lame constants initialised from PROPS on the FIRST call: every
  later PROPS perturbation is ignored (FD d sigma/dE exactly 0); B1's gate
  (base STRESS only) did not trip;
* a2 -- a SAVEd call counter written into STATEV(2): B1 absorbed the moving
  slot as "nonsmooth" and folded DDSDDE verified;
* a3 -- file I/O carrying the previous call's stress into STATEV(2).

Each must make the WHOLE source ``not_attempted`` with a reason that names
the DEFINED output that moved; the clean control must not trip; an
out-of-bounds write trips too.

Decision D-12 (undefined behaviour in the ORIGINAL) is tested with two more
toys: the Jeff97 PureGrowth pattern (a local never assigned, written only to
STATEV(2), which never feeds the stress) must verify STRESS/DDSDDE with
STATEV(2) listed ``undefined_in_original``; a toy whose uninitialised value
feeds every STRESS component must not verify anything about the stress. Each toy is built with the toy itself as its "store" build,
as in Vera's run_hidden.py.
"""
import shutil

import numpy as np
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.fortran]

HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
"""
LAME = """      E=PROPS(1)
      ANU=PROPS(2)
      ALAM=E*ANU/((1.D0+ANU)*(1.D0-2.D0*ANU))
      AMU=E/(2.D0*(1.D0+ANU))
"""
BODY = """      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
      END DO
      DO I=1,NDI
        DO J=1,NDI
          DDSDDE(I,J)=ALAM
        END DO
        DDSDDE(I,I)=ALAM+2.D0*AMU
      END DO
      DO I=NDI+1,NTENS
        DDSDDE(I,I)=AMU
      END DO
      DO I=1,NTENS
        DO J=1,NTENS
          STRESS(I)=STRESS(I)+DDSDDE(I,J)*DSTRAN(J)
        END DO
      END DO
      STATEV(1)=STATEV(1)+STRESS(1)*DSTRAN(1)
"""
END = """      RETURN
      END
"""

TOYS = {
    "toy_clean": HEADER + LAME + BODY + END,
    "toy_a1_saveinit": HEADER + """      LOGICAL INIT
      SAVE INIT,ALAM,AMU
      DATA INIT /.FALSE./
      IF (.NOT. INIT) THEN
      E=PROPS(1)
      ANU=PROPS(2)
      ALAM=E*ANU/((1.D0+ANU)*(1.D0-2.D0*ANU))
      AMU=E/(2.D0*(1.D0+ANU))
      INIT=.TRUE.
      END IF
""" + BODY + END,
    "toy_a2_counter_statev": HEADER + """      INTEGER NCALL
      SAVE NCALL
      DATA NCALL /0/
      NCALL=NCALL+1
""" + LAME + BODY + """      STATEV(2)=STATEV(2)+1.D-3*DBLE(MOD(NCALL,7))
""" + END,
    "toy_a3_fileio": HEADER + """      LOGICAL EX
      PREV=0.D0
      INQUIRE(FILE='vera_prev.txt',EXIST=EX)
      IF (EX) THEN
      OPEN(77,FILE='vera_prev.txt',STATUS='OLD')
      READ(77,*) PREV
      CLOSE(77)
      END IF
""" + LAME + BODY + """      STATEV(2)=PREV
      OPEN(77,FILE='vera_prev.txt',STATUS='REPLACE')
      WRITE(77,*) STRESS(1)
      CLOSE(77)
""" + END,
    # Jeff97 PureGrowth.for:106/208 pattern: a local that is never assigned
    # is written to a STATEV slot.
    "toy_uninitialised": HEADER + LAME + BODY + """      STATEV(2)=XLAMZ
""" + END,
    # The uninitialised value reaches every STRESS component (D-12: STRESS is
    # then undefined_in_original; nothing about the stress may verify).
    "toy_uninitialised_feeds_stress": HEADER + LAME + """      DO I=1,NTENS
        STRESS(I)=STRESS(I)+XGARB*DSTRAN(I)
      END DO
""" + BODY + END,
    "toy_bounds": HEADER + """      DIMENSION SCRATCH(2)
""" + LAME + BODY + """      DO I=1,3
        SCRATCH(I)=STRESS(I)
      END DO
      STATEV(2)=SCRATCH(1)
""" + END,
}

FEATURES = ("primal_stress_state", "ddsdde", "stress_param_sens_local",
            "stress_param_sens_total", "state_param_sens_local", "state_state_sens_local")


def _entry(root, name):
    from umat_oti.corpus_features.harness import CorpusEntry
    store = root / "store" / name
    store.mkdir(parents=True, exist_ok=True)
    source = root / f"{name}.f"
    source.write_text(TOYS[name])
    shutil.copy(source, store / "umat.f")
    (store / "compile_order.txt").write_text("umat.f\n")
    return CorpusEntry(key=name, source_id=f"vera_toy/{name}", original_source=source,
                       ntens=6, nstatv=2, props=[2.0e5, 0.3], store_dir=store)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features.harness import run_entry
    from umat_oti.corpus_features.paths import internal_paths
    root = tmp_path_factory.mktemp("hidden")
    out = {}
    for name in TOYS:
        entry = _entry(root, name)
        out[name] = run_entry(entry, root / "work", paths=internal_paths({"ndi": 3, "nshr": 3}),
                              features=FEATURES)
    return out


def test_the_clean_toy_does_not_trip_and_verifies(results):
    records = results["toy_clean"]
    assert all(not r.get("hidden_state_trips") for r in records)
    by = {(r["feature"], r["path"]): r for r in records}
    for path in ("gauss_small_elastic", "gauss_small_load_unload"):
        assert by[("ddsdde", path)]["status"] == "verified", by[("ddsdde", path)]["reason"]
        assert by[("primal_stress_state", path)]["status"] == "verified"
        assert by[("stress_param_sens_total", path)]["status"] == "verified"
    assert by[("ddsdde", "gauss_small_elastic")]["build"] == "store"
    assert by[("stress_param_sens_local", "gauss_small_elastic")]["build"] == "lifted"
    eq = by[("stress_param_sens_local", "gauss_small_elastic")]["primal_equivalence_lifted_vs_store"]
    assert eq["status"] in ("bit-equal", "within")


@pytest.mark.parametrize("name, needle", [
    ("toy_a1_saveinit", "fresh process with PROPS(1)+h differs"),
    ("toy_a2_counter_statev", "STATEV(2)"),
    ("toy_a3_fileio", "STATEV(2)"),
    ("toy_bounds", "-fcheck=bounds run stopped"),
])
def test_every_hidden_state_defect_makes_the_whole_source_not_attempted(results, name, needle):
    records = results[name]
    assert records
    assert all(r["status"] == "not_attempted" for r in records), \
        sorted({(r["feature"], r["status"]) for r in records})
    assert all(r["reason"].startswith("hidden state: ") for r in records)
    assert any(needle in t for t in records[0]["hidden_state_trips"]), records[0]["hidden_state_trips"]


def test_an_undefined_slot_that_never_feeds_stress_is_listed_and_stress_verifies(results):
    records = results["toy_uninitialised"]
    assert all(not r.get("hidden_state_trips") for r in records), records[0].get("hidden_state_trips")
    assert all(r["undefined_outputs"] == ["STATEV(2)"] for r in records)
    assert all(r["stress_and_ddsdde_fully_defined"] for r in records)
    by = {(r["feature"], r["path"]): r for r in records}
    for path in ("gauss_small_elastic", "gauss_small_load_unload"):
        assert by[("ddsdde", path)]["status"] == "verified", by[("ddsdde", path)]["reason"]
        assert by[("primal_stress_state", path)]["status"] == "verified"
        assert by[("stress_param_sens_local", path)]["status"] == "verified"
        assert by[("stress_param_sens_total", path)]["status"] == "verified"
        # the undefined slot is never compared: its entries are counted as such
        assert by[("state_param_sens_local", path)]["entries"].get("undefined_in_original", 0) > 0
    # the -Wmaybe-uninitialized hint is best effort; when present it is right
    flagged = records[0]["undefined_variables_flagged"]
    assert not flagged or "xlamz" in flagged
    from umat_oti.corpus_features.cells import fold
    cells = fold(records, evidence="e")
    ddsdde = next(c for c in cells if c["feature"] == "ddsdde")
    assert ddsdde["status"] == "verified" and ddsdde["undefined_outputs"] == ["STATEV(2)"]
    assert ddsdde["stress_and_ddsdde_fully_defined"] is True


def test_an_undefined_value_that_feeds_stress_verifies_nothing_about_stress(results):
    records = results["toy_uninitialised_feeds_stress"]
    assert all(not r.get("hidden_state_trips") for r in records), records[0].get("hidden_state_trips")
    assert {f"STRESS({i})" for i in range(1, 7)} <= set(records[0]["undefined_outputs"])
    assert all(r["stress_and_ddsdde_fully_defined"] is False for r in records)
    for r in records:
        if r["feature"] in ("primal_stress_state", "ddsdde", "stress_param_sens_local",
                            "stress_param_sens_total"):
            assert r["status"] != "verified", (r["feature"], r["path"], r["reason"])


def test_the_fd_strain_direction_is_built_from_the_kinematics():
    from umat_oti.corpus_features.harness import canonical_strain_direction
    from umat_oti.validation.finite_strain_tangent import strain_direction
    seed = {1: ((1, 1, 1.0),), 2: ((2, 2, 1.0),), 3: ((3, 3, 1.0),),
            4: ((1, 2, 0.5), (2, 1, 0.5)), 5: ((1, 3, 0.5), (3, 1, 0.5)),
            6: ((2, 3, 0.5), (3, 2, 0.5))}
    for j in range(1, 7):
        assert np.array_equal(canonical_strain_direction(j, 3, 3),
                              np.asarray(strain_direction(seed[j], 1.0)))
    # NTENS=4 (3 direct + 12 shear) and plane stress (11, 22, 12)
    assert np.array_equal(canonical_strain_direction(4, 3, 1),
                          np.asarray(strain_direction(seed[4], 1.0)))
    assert np.array_equal(canonical_strain_direction(3, 2, 1),
                          np.asarray(strain_direction(seed[4], 1.0)))


def test_a_seed_map_that_disagrees_with_the_kinematics_fails_ddsdde(tmp_path):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    from umat_oti.corpus_features import harness as H
    from umat_oti.corpus_features.paths import internal_paths
    entry = _entry(tmp_path, "toy_clean")
    builds = H.build_all(entry, tmp_path / "w", want_lifted=False)
    builds.gradient_driven = True
    path = internal_paths({"kinematics": "finite"})[0]
    good = {1: ((1, 1, 1.0),), 2: ((2, 2, 1.0),), 3: ((3, 3, 1.0),),
            4: ((1, 2, 0.5), (2, 1, 0.5)), 5: ((1, 3, 0.5), (3, 1, 0.5)),
            6: ((2, 3, 0.5), (3, 2, 0.5))}
    builds.gradient_terms = {**good, 4: ((1, 2, 1.0), (2, 1, 1.0))}   # tensor, not engineering
    records, _h, _t = H.evaluate_path(entry, builds, path, tmp_path / "bad",
                                      features=("primal_stress_state", "ddsdde"))
    ddsdde = next(r for r in records if r["feature"] == "ddsdde")
    assert ddsdde["status"] == "failed" and "column(s) [4]" in ddsdde["reason"]
    builds.gradient_terms = good
    records, _h, _t = H.evaluate_path(entry, builds, path, tmp_path / "good",
                                      features=("primal_stress_state", "ddsdde"))
    ddsdde = next(r for r in records if r["feature"] == "ddsdde")
    assert "seed map" not in (ddsdde.get("reason") or "")
