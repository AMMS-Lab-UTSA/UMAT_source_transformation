"""A minimal routine-level path driver for the mechanics checks, and its tests.

Kept here (curie's test/support file) rather than in ``src``: the campaign's
harness is gauss's (``umat_oti.corpus_features``), and this is only the
smallest driver that lets the mechanics checks be validated on ORIGINAL corpus
routines without Abaqus. It reuses the replay driver's build pieces --
the installation's ``aba_param.inc`` under every casing, the author's PROGRAM
units commented out, console writes silenced, the shared Abaqus-utility stubs
-- so the routine compiled here is the routine the replay and the solver ran.

What the driver does per increment, following the Abaqus/Standard UMAT
conventions:

* hands STRESS, STATEV, SSE, SPD, SCD as returned by the previous call;
* for a finite-strain path (DFGRD1 given) rotates STRESS (tensor shear) and
  STRAN (engineering shear) by DROT before the call, as Abaqus does, and
  passes DFGRD0/DFGRD1/DROT from :mod:`umat_oti.corpus_features.loading_paths`;
* TIME(1)=TIME(2) = time at the start of the increment (one step);
* calls the author's SDVINI before the first increment only when asked
  (the author's deck requests user initial conditions) and the source has one;
* zeroes DDSDDE before each call; PNEWDT=1;
* writes STRESS, STATEV, DDSDDE (row-major, DDSDDE(i,j) = dsig_i/deps_j),
  SSE, SPD, SCD, PNEWDT after every call and flushes, so a routine that stops
  (XIT, a NaN trap) leaves the prefix it computed.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from umat_oti.corpus_features.loading_paths import (
    Increment,
    LoadingPath,
    dfgrd0_of,
    drot_of,
    hooke_matrix,
    time_of,
)

REPO = Path(__file__).resolve().parents[1]
J2_FIXTURE = REPO / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"

_DRIVER = """PROGRAM cc_cur_path_driver
  IMPLICIT NONE
  INTEGER :: NTENS,NSTATV,NPROPS,NDI,NSHR,NINC,FINITE,INIT,I,J,K,U,V
  REAL(8) :: DTIME,TEMP,DTEMP,PNEWDT,CELENT,SSE,SPD,SCD,RPL,DRPLDT
  REAL(8), ALLOCATABLE :: STRESS(:),STATEV(:),DDSDDE(:,:),STRAN(:),DSTRAN(:)
  REAL(8), ALLOCATABLE :: PROPS(:),DDSDDT(:),DRPLDE(:),TMP(:)
  REAL(8) :: TIME(2),PREDEF(1),DPRED(1),COORDS(3),DROT(3,3)
  REAL(8) :: DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NOEL,NPT,LAYER,KSPT,KSTEP,KINC
  CHARACTER(80) :: CMNAME

  OPEN(NEWUNIT=U,FILE='path.txt',STATUS='OLD',ACTION='READ')
  READ(U,*) NTENS,NSTATV,NPROPS,NDI,NSHR,NINC,FINITE,INIT
  ALLOCATE(STRESS(NTENS),STATEV(MAX(NSTATV,1)),DDSDDE(NTENS,NTENS))
  ALLOCATE(STRAN(NTENS),DSTRAN(NTENS),PROPS(MAX(NPROPS,1)),TMP(NTENS))
  ALLOCATE(DDSDDT(NTENS),DRPLDE(NTENS))
  READ(U,*) (PROPS(I),I=1,MAX(NPROPS,1))
  READ(U,*) (STATEV(I),I=1,MAX(NSTATV,1))
  STRESS=0.0_8; STRAN=0.0_8; SSE=0.0_8; SPD=0.0_8; SCD=0.0_8
  COORDS=0.0_8; CELENT=1.0_8; NOEL=1; NPT=1; LAYER=1; KSPT=1; KSTEP=1
  CMNAME='CC_CUR_MATERIAL'
%(sdvini)s
  OPEN(NEWUNIT=V,FILE='history.txt',STATUS='REPLACE',ACTION='WRITE')
  DO K=1,NINC
    READ(U,*) (DSTRAN(I),I=1,NTENS)
    READ(U,*) ((DFGRD0(I,J),J=1,3),I=1,3)
    READ(U,*) ((DFGRD1(I,J),J=1,3),I=1,3)
    READ(U,*) ((DROT(I,J),J=1,3),I=1,3)
    READ(U,*) DTIME,TIME(1),TIME(2),TEMP,DTEMP
    IF (FINITE .EQ. 1) THEN
      CALL ROTSIG(STRESS,DROT,TMP,1,NDI,NSHR)
      STRESS=TMP
      CALL ROTSIG(STRAN,DROT,TMP,2,NDI,NSHR)
      STRAN=TMP
    END IF
    DDSDDE=0.0_8; RPL=0.0_8; DDSDDT=0.0_8; DRPLDE=0.0_8; DRPLDT=0.0_8
    PREDEF=0.0_8; DPRED=0.0_8; PNEWDT=1.0_8; KINC=K
    CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
      STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
      NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
      NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
    STRAN=STRAN+DSTRAN
    WRITE(V,'(A,I0)') 'INC ',K
    WRITE(V,'(*(ES26.17E3))') (STRESS(I),I=1,NTENS)
    WRITE(V,'(*(ES26.17E3))') (STATEV(I),I=1,MAX(NSTATV,1))
    WRITE(V,'(*(ES26.17E3))') ((DDSDDE(I,J),J=1,NTENS),I=1,NTENS)
    WRITE(V,'(*(ES26.17E3))') SSE,SPD,SCD,PNEWDT
    FLUSH(V)
  END DO
  CLOSE(V)
  CLOSE(U)
END PROGRAM cc_cur_path_driver

%(stubs)s"""

_SDVINI = """  IF (INIT .EQ. 1) THEN
    CALL SDVINI(STATEV,COORDS,NSTATV,3,NOEL,NPT,LAYER,KSPT)
  END IF"""


@dataclass
class Build:
    program: Path | None
    ok: bool
    reason: str = ""
    header: str = ""
    has_sdvini: bool = False


def build_driver(
    source: Path,
    work_dir: Path,
    *,
    compiler: str = "gfortran",
    flags: Sequence[str] = ("-O0", "-ffpe-summary=none"),
) -> Build:
    """Compile the path driver against one ORIGINAL UMAT source."""
    from umat_oti.abaqus.probe import silence_console_writes
    from umat_oti.abaqus.replay import (
        _install_header,
        _replay_utility_stubs,
        defines_sdvini,
        without_the_authors_program,
    )
    from umat_oti.fortran.normalize import detect_source_form
    from umat_oti.validation.actual_umat_higher_order_generic import (
        _abaqus_utility_stubs,
    )

    work_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which(compiler) is None:
        return Build(None, False, f"{compiler} is not on PATH")
    text = source.read_text(errors="replace")
    form = detect_source_form(source, text)
    text, _ = silence_console_writes(text, form)
    text, _ = without_the_authors_program(text, form)
    suffix = ".f90" if str(form).lower().startswith("free") else ".f"
    unit = work_dir / ("cc_cur_source" + suffix)
    unit.write_text(text, encoding="utf-8")
    sdvini = defines_sdvini(text)
    driver = work_dir / "cc_cur_driver.f90"
    driver.write_text(
        _DRIVER
        % {
            "sdvini": _SDVINI if sdvini else "",
            "stubs": _abaqus_utility_stubs() + _replay_utility_stubs(),
        },
        encoding="utf-8",
    )
    header = _install_header(work_dir)
    program = work_dir / "cc_cur_driver"
    extra = (
        ["-ffixed-line-length-none"] if suffix == ".f" else ["-ffree-line-length-none"]
    )
    # The source and the driver are compiled apart: a fixed-form flag must
    # not reach the free-form driver.
    obj = work_dir / "cc_cur_source.o"
    first = subprocess.run(
        [compiler, *flags, *extra, f"-I{work_dir}", "-c", str(unit), "-o", str(obj)],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if first.returncode != 0:
        return Build(
            None,
            False,
            "source did not compile: " + (first.stdout + first.stderr)[-1500:],
            header,
            sdvini,
        )
    second = subprocess.run(
        [
            compiler,
            *flags,
            "-ffree-line-length-none",
            str(driver),
            str(obj),
            "-o",
            str(program),
        ],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if second.returncode != 0 or not program.is_file():
        return Build(
            None,
            False,
            "driver did not link: " + (second.stdout + second.stderr)[-1500:],
            header,
            sdvini,
        )
    return Build(program, True, "", header, sdvini)


def _row(values) -> str:
    return " ".join(repr(float(v)) for v in values)


def write_path(
    path: LoadingPath,
    props: Sequence[float],
    statev0: Sequence[float],
    nstatv: int,
    file: Path,
    *,
    initialise: bool,
) -> None:
    finite = any(inc.dfgrd1 is not None for inc in path.increments)
    lines = [
        (
            f"{path.ntens} {nstatv} {len(props)} {path.ndi} {path.nshr} "
            f"{len(path.increments)} {1 if finite else 0} {1 if initialise else 0}"
        ),
        _row(props or [0.0]),
        _row(list(statev0) + [0.0] * (max(nstatv, 1) - len(statev0))),
    ]
    for k, inc in enumerate(path.increments):
        f1 = (
            np.asarray(inc.dfgrd1, dtype=float) if inc.dfgrd1 is not None else np.eye(3)
        )
        f0 = dfgrd0_of(path, k) if inc.dfgrd1 is not None else np.eye(3)
        lines += [
            _row(inc.dstran or [0.0] * path.ntens),
            _row(f0.ravel()),
            _row(f1.ravel()),
            _row(drot_of(path, k).ravel()),
            _row((inc.dtime, *time_of(path, k), inc.temp, inc.dtemp)),
        ]
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_history(file: Path, ntens: int) -> list[dict]:
    rows: list[dict] = []
    if not file.is_file():
        return rows
    lines = file.read_text().splitlines()
    k = 0
    while k + 4 < len(lines) + 1 and k < len(lines):
        if not lines[k].startswith("INC"):
            k += 1
            continue
        try:
            stress = [float(x) for x in lines[k + 1].split()]
            statev = [float(x) for x in lines[k + 2].split()]
            dd = np.array([float(x) for x in lines[k + 3].split()]).reshape(
                ntens, ntens
            )
            sse, spd, scd, pnewdt = (float(x) for x in lines[k + 4].split())
        except (IndexError, ValueError):
            break
        rows.append(
            {
                "stress": stress,
                "statev": statev,
                "ddsdde": dd.tolist(),
                "sse": sse,
                "spd": spd,
                "scd": scd,
                "pnewdt": pnewdt,
            }
        )
        k += 5
    return rows


def run_path(
    build: Build,
    path: LoadingPath,
    props: Sequence[float],
    statev0: Sequence[float],
    nstatv: int,
    work_dir: Path,
    *,
    initialise: bool = False,
    timeout: int = 120,
) -> tuple[list[dict], str]:
    """Run one path; returns (history, stderr tail)."""
    run_dir = work_dir / f"run_{path.name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_path(
        path, props, statev0, nstatv, run_dir / "path.txt", initialise=initialise
    )
    done = subprocess.run(
        [str(build.program)],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return read_history(run_dir / "history.txt", path.ntens), (
        done.stdout + done.stderr
    )[-800:]


# ---------------------------------------------------------------------------
# tests of the driver itself
# ---------------------------------------------------------------------------
needs_gfortran = pytest.mark.skipif(
    shutil.which("gfortran") is None, reason="gfortran not on PATH"
)


@needs_gfortran
@pytest.mark.slow
def test_the_driver_reproduces_hooke_on_the_elastic_branch_of_j2(tmp_path):
    """Below yield the J2 fixture is Hooke's law: the driver must hand it the
    strain increments in engineering shear and carry the stress."""
    build = build_driver(J2_FIXTURE, tmp_path)
    assert build.ok, build.reason
    e, nu = 200000.0, 0.3
    props = [e, nu, 1.0e9, 1000.0]  # yield far away: elastic
    dstran = (1e-4, -2e-5, 3e-5, 4e-5, -1e-5, 2e-5)
    path = LoadingPath(
        "t",
        "elastic",
        "small",
        [Increment(dstran, None, 0.1, 0.0, 0.0)] * 3,
        ntens=6,
        ndi=3,
        nshr=3,
    )
    hist, err = run_path(build, path, props, [0.0], 1, tmp_path)
    assert len(hist) == 3, err
    expected = 3 * hooke_matrix(e, nu, 6) @ np.asarray(dstran)
    assert np.allclose(hist[-1]["stress"], expected, rtol=1e-12, atol=1e-9)


@needs_gfortran
@pytest.mark.slow
def test_the_driver_keeps_the_prefix_a_routine_computed_before_it_stopped(tmp_path):
    """A routine that calls XIT on its second call leaves one increment."""
    src = tmp_path / "stopper.f"
    src.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,\n"
        "     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,\n"
        "     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,\n"
        "     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
        "      INCLUDE 'ABA_PARAM.INC'\n"
        "      CHARACTER*80 CMNAME\n"
        "      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),\n"
        "     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS)\n"
        "      IF (KINC.GE.2) CALL XIT\n"
        "      DO I=1,NTENS\n"
        "        DDSDDE(I,I)=PROPS(1)\n"
        "        STRESS(I)=STRESS(I)+PROPS(1)*DSTRAN(I)\n"
        "      END DO\n"
        "      RETURN\n"
        "      END\n"
    )
    build = build_driver(src, tmp_path / "b")
    assert build.ok, build.reason
    path = LoadingPath(
        "t",
        "elastic",
        "small",
        [Increment((1e-3, 0.0, 0.0), None, 1.0, 0.0, 0.0)] * 4,
        ntens=3,
        ndi=2,
        nshr=1,
    )
    hist, _ = run_path(build, path, [10.0], [0.0], 1, tmp_path)
    assert len(hist) == 1
    assert hist[0]["stress"][0] == pytest.approx(1e-2)


def source_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
