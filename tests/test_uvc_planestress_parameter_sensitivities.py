"""UVCplanestress in parameter-sensitivity mode compiles, and DSIGMA_DP matches FD.

Regression for a symbol-table leak across program units. UVCplanestress's
UMAT declares scalars ``a`` and ``b`` and CONTAINS ``matinv3(A) result(B)``
with A(3,3) and B(3,3). The shape table read the internal function's
declarations as the host's, so the parameter-sensitivity transform declared
the host's shadows A_OTI(3,3) and B_OTI(3,3), and the emitted file failed
to compile at HARD_ISO_Q_OTI = Q_INF_OTI*(ONE-EXP(-B_OTI*EP_EQ_OTI)) while
the transform report listed every check as passed. With that fixed, the
lifted MATINV3_OTI returns an array and needed an explicit interface at its
call, the combined entry's driver needed the classic or JSTEP(4) 36th
argument and an XIT stub.

The contract is the paper session's c4 (ten PROPS, every one but ``a``; the
combined entry UMAT_WITH_SENSITIVITIES), pointed at this repository's
unchanged copy of the source. The derivative is checked against centred
differences of the separately compiled original along a path that yields.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "UMATs" / "UMATs" / "UVC_MatMod" / "UVCplanestress.for"
CONTRACT = REPO / "tests" / "fixtures" / "uvc_planestress" / "c4_props.json"
PROPS = [179800.0, 0.3, 318.5, 100.7, 8.0, 0.0, 200.0, 11608.2, 145.2, 1026.3, 4.7]
DSTRAN = [4.0e-4, 0.0, 0.0]
INCREMENTS = 12

pytestmark = [pytest.mark.fortran, pytest.mark.regression]


def test_the_source_is_the_unchanged_upstream_file():
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert digest == "d25ee404fed5493ea479a3a38c8b0b59a25526dd5703fff9a6d0c99bf447b46e"


def test_internal_procedure_declarations_do_not_shape_the_host():
    from umat_oti.transform import source_transform as st

    parsed = st._parse_source(SOURCE.read_text(), SOURCE)
    shapes = st._shapes_declared_in_selected_routine(parsed, "UMAT", {"A": "3, 3", "B": "3, 3"})
    assert "A" not in shapes and "B" not in shapes
    own = st._with_the_routines_own_shapes({}, parsed, "UMAT")
    assert "A" not in own and "B" not in own


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not shutil.which("gfortran"):
        pytest.skip("gfortran is required")
    from umat_oti.services.transformation import TransformationOptions, run_transformation

    work = tmp_path_factory.mktemp("uvc")
    contract = json.loads(CONTRACT.read_text())
    contract["source"] = str(SOURCE)
    contract["material_point_driver"] = {
        "nstatv": 10, "dstran_per_increment": DSTRAN, "n_increments": INCREMENTS,
        "static_props": PROPS}
    path = work / "c4.json"
    path.write_text(json.dumps(contract))
    summary, code = run_transformation(path, work / "out", TransformationOptions(compile_generated=True))
    # Build and run the OTI driver here, so every test below reads the same
    # run whichever worker it lands on.
    ps = work / "out" / "parameter_sensitivity"
    if (ps / "Makefile").is_file():
        make = subprocess.run(["make", "FC=" + shutil.which("gfortran")], cwd=ps,
                              capture_output=True, text=True)
        run = subprocess.run([str(ps / "ps_driver")], cwd=ps, capture_output=True, text=True) \
            if make.returncode == 0 else None
        summary["_test_driver"] = {
            "make": (make.returncode, make.stderr[-2000:]),
            "run": (run.returncode, run.stderr[-2000:]) if run is not None else None}
    return summary, code, contract, work


def _tangent_driver(ntens: int, nstatv: int, nprops: int) -> str:
    """The reference driver's loop, writing DDSDDE after every increment."""
    return f"""PROGRAM tangent_driver
  IMPLICIT NONE
  INTEGER, PARAMETER :: NTENS={ntens}, NSTATV={nstatv}, NPROPS={nprops}
  REAL(8) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
  REAL(8) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
  REAL(8) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3)
  REAL(8) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,I,NINC
  CHARACTER(80) :: CMNAME
  STRESS=0;STATEV=0;DDSDDE=0;STRAN=0;DSTRAN=0;SSE=0;SPD=0;SCD=0;RPL=0
  DDSDDT=0;DRPLDE=0;DRPLDT=0;TIME=0;DTIME=1;TEMP=293.15_8;DTEMP=0;PREDEF=0;DPRED=0
  COORDS=0;DROT=0;DFGRD0=0;DFGRD1=0
  DO I=1,3
    DROT(I,I)=1;DFGRD0(I,I)=1;DFGRD1(I,I)=1
  END DO
  PNEWDT=1;CELENT=1;CMNAME='ORIGINAL_REFERENCE'
  NDI=3;NSHR={max(ntens - 3, 0)};NOEL=1;NPT=1;LAYER=1;KSPT=1;KSTEP=1
  READ(*,*) PROPS
  READ(*,*) NINC
  DO KINC=1,NINC
    READ(*,*) DSTRAN
    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV, &
      PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
    WRITE(*,'({ntens * ntens}(ES26.17E3,1X))') DDSDDE
    STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
  END DO
END PROGRAM tangent_driver
SUBROUTINE XIT
  STOP 3
END SUBROUTINE XIT
SUBROUTINE GETOUTDIR(PATH,NCHAR)
  CHARACTER(*) :: PATH
  INTEGER :: NCHAR
  PATH='.';NCHAR=1
END SUBROUTINE GETOUTDIR
"""


@pytest.fixture(scope="module")
def c1_tangents(built):
    """DDSDDE along the path from the tangent-only transform of the same source (c1)."""
    from umat_oti.services.transformation import TransformationOptions, run_transformation

    _summary, _code, contract, work = built
    c1 = {key: value for key, value in contract.items() if key != "material_point_driver"}
    c1["name"] = "uvc_tangent"
    c1["derivatives"] = [d for d in contract["derivatives"] if d["target"] == "DDSDDE"]
    path = work / "c1.json"
    path.write_text(json.dumps(c1))
    summary, code = run_transformation(path, work / "c1", TransformationOptions(compile_generated=True))
    assert code == 0 and summary["compilation"]["status"] == "compiled", summary.get("blockers")
    out = work / "c1"
    driver = out / "tangent_driver.f90"
    driver.write_text(_tangent_driver(3, 10, len(PROPS)))
    objects = sorted(str(p) for p in out.glob("*.o"))
    link = subprocess.run([shutil.which("gfortran"), "-ffree-line-length-none", "-I", str(out),
                           str(driver), *objects, "-o", str(out / "tangent_driver")],
                          cwd=out, capture_output=True, text=True)
    assert link.returncode == 0, link.stderr[-2000:]
    stdin = " ".join(repr(v) for v in PROPS) + f"\n{INCREMENTS}\n" + \
        "".join(" ".join(repr(v) for v in DSTRAN) + "\n" for _ in range(INCREMENTS))
    run = subprocess.run([str(out / "tangent_driver")], input=stdin, cwd=out,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-2000:]
    rows = [[float(v) for v in line.split()] for line in run.stdout.splitlines() if line.strip()]
    assert len(rows) == INCREMENTS
    # Fortran writes DDSDDE column by column: entry (i, j) is at j*NTENS + i.
    return [[[row[j * 3 + i] for j in range(3)] for i in range(3)] for row in rows]


def test_the_transform_compiles_and_says_so(built):
    summary, code, _contract, _work = built
    assert summary["transform_success"], summary.get("blockers")
    assert summary["compilation"]["status"] == "compiled", summary["compilation"].get("stderr", "")[:2000]
    assert code == 0


def test_dsigma_dp_matches_central_differences_of_the_original(built):
    from umat_oti.validation.parameter_sensitivity_validation import (
        build_original_driver, centered_fd, compare, primal_parity, read_oti_csv,
        replay_reproducibly)

    summary, _code, contract, work = built
    ps = work / "out" / "parameter_sensitivity"
    assert summary["artifacts"]["parameter_sensitivity_driver"].get("status") != "not_generated", \
        summary["artifacts"]["parameter_sensitivity_driver"]
    ran = summary.get("_test_driver") or {}
    assert ran.get("make", (1, "no Makefile"))[0] == 0, ran.get("make")
    assert ran.get("run") and ran["run"][0] == 0, ran.get("run")

    from umat_oti.transform.abaqus_utility_definitions import ROTSIG_DEFINITION

    path = [DSTRAN] * INCREMENTS
    # The original calls ROTSIG, which Abaqus links in; the documented real
    # body (the one the transform supplies in OTI form) stands in for it.
    rotsig = work / "rotsig.for"
    rotsig.write_text(ROTSIG_DEFINITION)
    executable = build_original_driver(SOURCE, work / "original", ntens=3, nstatv=10,
                                       nprops=len(PROPS), extra_sources=[rotsig])
    original = replay_reproducibly(executable, PROPS, path, ntens=3, nstatv=10)
    parity = primal_parity(original, ps / "primal_stress_state_OTI.csv", ntens=3, nstatv=10)
    assert parity["agrees"], parity
    branches = ["inelastic" if abs(sv[0]) > 1e-12 else "elastic" for sv in original.statev]
    assert "inelastic" in branches and "elastic" in branches
    parameters = contract["parameters"]
    reference = centered_fd(executable, PROPS, path, ntens=3, nstatv=10,
                            props_indices=[p["props_index"] for p in parameters])
    scale = max(abs(v) for row in original.stress for v in row)
    rows = compare(read_oti_csv(ps / "DSIGMA_DP_OTI.csv"), reference, array="DSIGMA_DP",
                   parameters=parameters, branches=branches, response_scale=scale)
    assert rows
    # As the Table 6 sweep does: a disagreeing row is judged again against a
    # centred difference at a converged step before it counts as a failure.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sweep_under_test", REPO / "tools" / "run_parameter_sensitivity_sweep.py")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    rows, _evidence = sweep._readjudicate_at_converged_step(
        rows, executable=executable, props=PROPS, path=path, ntens=3, nstatv=10,
        parameters=parameters, ps_dir=ps, stress_scale=scale, branches=branches)
    disagreeing = [r for r in rows if r.agrees is False]
    assert not disagreeing, [r.as_dict() for r in disagreeing[:5]]
    assert sum(1 for r in rows if r.agrees is True) >= 0.9 * len(rows)


def test_dstatev_dp_matches_central_differences_of_the_original(built):
    from umat_oti.validation.parameter_sensitivity_validation import (
        build_original_driver, centered_fd, compare, read_oti_csv, replay_reproducibly)
    from umat_oti.transform.abaqus_utility_definitions import ROTSIG_DEFINITION

    summary, _code, contract, work = built
    ps = work / "out" / "parameter_sensitivity"
    assert (ps / "DSTATEV_DP_OTI.csv").is_file(), summary.get("_test_driver")
    path = [DSTRAN] * INCREMENTS
    rotsig = work / "rotsig_state.for"
    rotsig.write_text(ROTSIG_DEFINITION)
    executable = build_original_driver(SOURCE, work / "original_state", ntens=3, nstatv=10,
                                       nprops=len(PROPS), extra_sources=[rotsig])
    original = replay_reproducibly(executable, PROPS, path, ntens=3, nstatv=10)
    branches = ["inelastic" if abs(sv[0]) > 1e-12 else "elastic" for sv in original.statev]
    parameters = contract["parameters"]
    reference = centered_fd(executable, PROPS, path, ntens=3, nstatv=10,
                            props_indices=[p["props_index"] for p in parameters])
    scale = max(max(abs(v) for row in original.statev for v in row), 1e-30)
    rows = compare(read_oti_csv(ps / "DSTATEV_DP_OTI.csv"), reference, array="DSTATEV_DP",
                   parameters=parameters, branches=branches, response_scale=scale)
    assert rows
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sweep_under_test_state", REPO / "tools" / "run_parameter_sensitivity_sweep.py")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    rows, _evidence = sweep._readjudicate_at_converged_step(
        rows, executable=executable, props=PROPS, path=path, ntens=3, nstatv=10,
        parameters=parameters, ps_dir=ps, stress_scale=scale, branches=branches)
    disagreeing = [r for r in rows if r.agrees is False]
    assert not disagreeing, [r.as_dict() for r in disagreeing[:5]]


def test_the_sensitivity_build_tangent_equals_the_tangent_only_build(built, c1_tangents):
    _summary, _code, _contract, work = built
    csv_path = work / "out" / "parameter_sensitivity" / "DDSDDE_OTI.csv"
    assert csv_path.is_file(), _summary.get("_test_driver")
    c4 = {}
    for line in csv_path.read_text().splitlines()[1:]:
        fields = line.split(",")
        c4.setdefault(int(fields[0]), {})[int(fields[1])] = [float(v) for v in fields[3:]]
    assert sorted(c4) == list(range(1, INCREMENTS + 1))
    worst = 0.0
    for increment, matrix in enumerate(c1_tangents, start=1):
        scale = max(abs(v) for row in matrix for v in row)
        for i in range(3):
            for j in range(3):
                worst = max(worst, abs(c4[increment][i + 1][j] - matrix[i][j]) / scale)
    assert worst < 1e-12, worst
