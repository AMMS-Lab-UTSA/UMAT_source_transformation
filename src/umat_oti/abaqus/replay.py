"""Re-running one recorded increment, offline, with a perturbed strain.

The tangent Abaqus asks a UMAT for is the derivative of the stress increment
with respect to the strain increment, at the state the increment starts from.
Checking it therefore needs three things at once: the state, the increment, and
a way to move the increment without moving anything else. The probe records the
first two; this supplies the third.

The perturbation is applied to the *untransformed* source. That is the point of
doing it this way rather than perturbing the OTI build: the two sides then share
no code path, so an error in the transform cannot cancel itself out of the
comparison. The transformed build supplies DDSDDE; the original build supplies
the differences it is checked against.

Nothing here writes into STATEV or changes a constitutive statement. The
increment is replayed exactly as Abaqus ran it, except for one component of
DSTRAN, which is what a partial derivative means.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

#: The state file the driver reads. Written rather than generated into the
#: source because a crystal-plasticity model carries hundreds of constants and
#: state variables, and a source with a thousand literal assignments in it is
#: neither compilable in reasonable time nor readable by anyone checking it.
STATE_FILE = "otis_state.txt"

_DRIVER = """PROGRAM otis_replay
! Replays one recorded UMAT call with one component of DSTRAN perturbed.
! Every other input is the one the solver passed, read from a file the probe's
! ENTRY record was written into. The perturbation is a command-line argument so
! that a sweep over components and step sizes compiles once and runs many times.
  IMPLICIT NONE
  INTEGER :: NTENS,NSTATV,NPROPS,NDI,NSHR,I,J,U,IOS,COMPONENT
  REAL(8) :: DTIME,TEMP,DTEMP,PNEWDT,CELENT,SSE,SPD,SCD,RPL,DRPLDT,STEP
  REAL(8), ALLOCATABLE :: STRESS(:),STATEV(:),DDSDDE(:,:),STRAN(:),DSTRAN(:)
  REAL(8), ALLOCATABLE :: PROPS(:),DDSDDT(:),DRPLDE(:)
  REAL(8) :: TIME(2),PREDEF(1),DPRED(1),COORDS(3),DROT(3,3)
  REAL(8) :: DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NOEL,NPT,LAYER,KSPT,KSTEP,KINC
  CHARACTER(80) :: CMNAME
  CHARACTER(64) :: ARG

  CALL GET_COMMAND_ARGUMENT(1,ARG); READ(ARG,*) COMPONENT
  CALL GET_COMMAND_ARGUMENT(2,ARG); READ(ARG,*) STEP

  OPEN(NEWUNIT=U,FILE='%(state)s',STATUS='OLD',ACTION='READ',IOSTAT=IOS)
  IF (IOS .NE. 0) THEN
    WRITE(*,*) 'OTIS-REPLAY: no state file'
    STOP 2
  END IF
  READ(U,*) NTENS,NSTATV,NPROPS,NDI,NSHR
  ALLOCATE(STRESS(NTENS),STATEV(MAX(NSTATV,1)),DDSDDE(NTENS,NTENS))
  ALLOCATE(STRAN(NTENS),DSTRAN(NTENS),PROPS(MAX(NPROPS,1)))
  ALLOCATE(DDSDDT(NTENS),DRPLDE(NTENS))
  READ(U,*) DTIME,TIME(1),TIME(2),TEMP,DTEMP,CELENT
  READ(U,*) NOEL,NPT,KSTEP,KINC
  READ(U,*) (STRESS(I),I=1,NTENS)
  READ(U,*) (STATEV(I),I=1,MAX(NSTATV,1))
  READ(U,*) (STRAN(I),I=1,NTENS)
  READ(U,*) (DSTRAN(I),I=1,NTENS)
  READ(U,*) (PROPS(I),I=1,MAX(NPROPS,1))
  READ(U,*) ((DFGRD0(I,J),J=1,3),I=1,3)
  READ(U,*) ((DFGRD1(I,J),J=1,3),I=1,3)
  READ(U,*) ((DROT(I,J),J=1,3),I=1,3)
  READ(U,*) (COORDS(I),I=1,3)
  CLOSE(U)

! One component of the strain increment moves. Nothing else does -- that is
! what makes the difference a partial derivative and not a directional one.
  IF (COMPONENT .GE. 1 .AND. COMPONENT .LE. NTENS) THEN
    DSTRAN(COMPONENT) = DSTRAN(COMPONENT) + STEP
  END IF

  DDSDDE=0.0_8; SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8
  DDSDDT=0.0_8; DRPLDE=0.0_8; DRPLDT=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PNEWDT=1.0_8; LAYER=1; KSPT=1; CMNAME='%(name)s'

  CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
    STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
    NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
    NOEL,NPT,LAYER,KSPT,KSTEP,KINC)

  OPEN(NEWUNIT=U,FILE='otis_replay_out.txt',STATUS='REPLACE',ACTION='WRITE')
  WRITE(U,'(A,I0)') 'NTENS ',NTENS
  DO I=1,NTENS
    WRITE(U,'(ES26.17E3)') STRESS(I)
  END DO
  WRITE(U,'(A)') 'DDSDDE'
  DO I=1,NTENS
    DO J=1,NTENS
      WRITE(U,'(ES26.17E3)') DDSDDE(I,J)
    END DO
  END DO
  CLOSE(U)
END PROGRAM otis_replay

%(stubs)s"""


def driver_source(name: str = "REPLAY") -> str:
    """The replay program, for a source that has to be linked beside it."""
    from umat_oti.validation.actual_umat_higher_order_generic import (
        _abaqus_utility_stubs)

    return _DRIVER % {"state": STATE_FILE, "name": name.upper()[:60],
                      "stubs": _abaqus_utility_stubs()}


def _row(values) -> str:
    return " ".join(f"{float(value)!r}" for value in values)


def write_state(entry: dict, path: Path) -> None:
    """One ENTRY record, in the order the driver reads it.

    Written in Python's shortest round-tripping form, which reproduces every
    double exactly. A rounded state would make the replay start somewhere the
    solver never was, and the difference of two such runs is a derivative of
    the wrong function.
    """
    ntens = int(entry.get("NTENS") or len(entry.get("STRESS0") or ()))
    nstatv = int(entry.get("NSTATV") or len(entry.get("STATEV0") or ()))
    nprops = int(entry.get("NPROPS") or len(entry.get("PROPS") or ()))
    ndi = int(entry.get("NDI") or 3)
    nshr = int(entry.get("NSHR") or max(ntens - ndi, 0))
    coords = list(entry.get("COORDS") or (0.0, 0.0, 0.0, 1.0))
    celent = coords[3] if len(coords) > 3 else 1.0
    temp = list(entry.get("TEMP") or (0.0, 0.0))
    time = float(entry.get("time") or 0.0)
    dtime = (entry.get("DTIME") or [0.0])[0]

    lines = [
        f"{ntens} {nstatv} {nprops} {ndi} {nshr}",
        _row((dtime, time, time, temp[0], temp[1] if len(temp) > 1 else 0.0, celent)),
        f"{entry.get('element', 1)} {entry.get('point', 1)} "
        f"{entry.get('step', 1)} {entry.get('increment', 1)}",
        _row(entry.get("STRESS0") or [0.0] * ntens),
        _row(entry.get("STATEV0") or [0.0] * max(nstatv, 1)),
        _row(entry.get("STRAN") or [0.0] * ntens),
        _row(entry.get("DSTRAN") or [0.0] * ntens),
        _row(entry.get("PROPS") or [0.0] * max(nprops, 1)),
        _row(entry.get("DFGRD0") or _identity()),
        _row(entry.get("DFGRD1") or _identity()),
        _row(entry.get("DROT") or _identity()),
        _row(coords[:3]),
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def parse_replay_output(path: Path) -> tuple[list[float], list[list[float]]]:
    """The stress and tangent one replay produced."""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return [], []
    if not lines or not lines[0].startswith("NTENS"):
        return [], []
    ntens = int(lines[0].split()[1])
    stress = [float(line) for line in lines[1:1 + ntens]]
    rest = lines[1 + ntens:]
    if not rest or rest[0].strip() != "DDSDDE":
        return stress, []
    flat = [float(line) for line in rest[1:1 + ntens * ntens]]
    tangent = [flat[row * ntens:(row + 1) * ntens] for row in range(ntens)]
    return stress, tangent


#: Where an Abaqus installation keeps the headers a UMAT includes. Preferred
#: over a stub whenever it is there: the replay is a reference the transform is
#: checked against, and a reference built on an approximation of the header the
#: solver used is an approximation of the reference.
_PUBLIC_INTERFACES = "SMAUsubs/PublicInterfaces"


def abaqus_include_dir(abaqus: Optional[str] = None) -> Optional[Path]:
    """The installation's own header directory, if one can be found."""
    launcher = shutil.which(abaqus or "abaqus")
    if launcher is None:
        return None
    root = Path(launcher).resolve()
    for parent in root.parents:
        candidate = parent / _PUBLIC_INTERFACES
        if (candidate / "aba_param.inc").is_file():
            return candidate
    # The launcher is usually a small script outside the installation, so also
    # look where the products are installed.
    for base in (Path("/usr/SIMULIA"), Path("/opt/SIMULIA")):
        if not base.is_dir():
            continue
        for candidate in sorted(base.glob(f"*/*/{_PUBLIC_INTERFACES}")):
            if (candidate / "aba_param.inc").is_file():
                return candidate
    return None


#: The casings sources in this corpus use for the Abaqus parameter header. A
#: case-sensitive filesystem makes each one a distinct filename, and a source
#: that spells it differently from the installation cannot compile.
_HEADER_NAMES = ("ABA_PARAM.INC", "aba_param.inc", "ABA_PARAM.inc", "aba_param.INC")


def _install_header(work_dir: Path, abaqus: Optional[str] = None) -> str:
    """Put the Abaqus parameter header in the build directory, every casing.

    Returns a description of what was installed, which goes into the build
    record: whether a reference was built against the installation's own header
    or against a stub changes what the reference means.
    """
    directory = abaqus_include_dir(abaqus)
    real = (directory / "aba_param.inc") if directory is not None else None
    if real is not None and real.is_file():
        body = real.read_text(errors="replace")
        described = f"{real} (installation), installed under {len(_HEADER_NAMES)} casings"
    else:
        from umat_oti.corpus.cli import _write_aba_param_stub
        _write_aba_param_stub(work_dir)
        return "stub: the installation's own header was not found"
    for name in _HEADER_NAMES:
        (work_dir / name).write_text(body, encoding="utf-8")
    return described


@dataclass
class ReplayBuild:
    """A compiled replay program, or the reason there is none."""

    program: Optional[Path] = None
    compiler: str = ""
    ok: bool = False
    reason: str = ""
    log: str = ""
    #: Which aba_param.inc the build used: the installation's, or a stub. It is
    #: recorded because it changes what the reference means.
    header: str = ""


def build_replay(source: Path, work_dir: Path, *, compiler: str = "gfortran",
                 name: str = "REPLAY", extra: Sequence[Path] = (),
                 flags: Sequence[str] = (), timeout: int = 900) -> ReplayBuild:
    """Compile the driver against one UMAT source, once for the whole sweep."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which(compiler) is None:
        return ReplayBuild(reason=f"{compiler} is not on PATH")

    driver = work_dir / "otis_replay.f90"
    driver.write_text(driver_source(name), encoding="utf-8")
    program = work_dir / "otis_replay"

    # The header is installed into the build directory under every casing a
    # source in this corpus uses, not merely pointed at with -I. Abaqus ships
    # it as `aba_param.inc`, sources include it as `ABA_PARAM.INC`, and the
    # filesystem is case-sensitive: three of the first eight sources piloted
    # failed to build with "Can't open included file 'ABA_PARAM.INC'" while the
    # real header sat in an included directory under its own name. The
    # repository's stub writer already emits four casings for this reason; the
    # installation's own header deserves the same treatment, because it is the
    # header the solver actually compiled against.
    used = _install_header(work_dir)
    includes = [f"-I{work_dir}"]

    # Order is load-bearing, not cosmetic. A compiler processes these in the
    # order given, and a module has to be compiled before the code that uses
    # it -- the transformed UMAT opens with `use otim6n1`. Putting the driver
    # first gave "Reading module otim6n1: Unexpected EOF", which is what a
    # half-written module file reads like.
    command = [compiler, *flags, *includes,
               *[str(path) for path in extra], str(source), str(driver),
               "-o", str(program)]
    try:
        done = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return ReplayBuild(reason=f"{type(error).__name__}: {error}")
    if done.returncode != 0 or not program.is_file():
        return ReplayBuild(compiler=compiler, header=used,
                           reason=f"the replay driver did not link against "
                                  f"{Path(source).name} (exit {done.returncode})",
                           log=(done.stdout + done.stderr)[-6000:])
    return ReplayBuild(program=program, compiler=compiler, ok=True,
                       header=used, log=(done.stdout + done.stderr)[-2000:])


def run_replay(build: ReplayBuild, work_dir: Path, component: int,
               step: float, timeout: int = 900) -> tuple[list[float], str]:
    """One perturbed call. Returns the stress it produced, and any complaint."""
    work_dir = Path(work_dir)
    out = work_dir / "otis_replay_out.txt"
    if out.exists():
        out.unlink()
    try:
        done = subprocess.run([str(build.program), str(component), repr(float(step))],
                              cwd=str(work_dir), capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        return [], f"{type(error).__name__}: {error}"
    stress, _ = parse_replay_output(out)
    if not stress:
        return [], (done.stdout + done.stderr)[-2000:] or "the replay wrote no stress"
    return stress, ""


@dataclass
class DifferenceSweep:
    """Centred differences of one recorded increment, at several step sizes."""

    matrices: dict = field(default_factory=dict)
    unperturbed: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    ok: bool = False
    reason: str = ""


def difference_tangent(build: ReplayBuild, work_dir: Path, ntens: int,
                       steps: Sequence[float], *, scale: float = 1.0,
                       components: Sequence[int] = ()) -> DifferenceSweep:
    """The tangent by centred differences, one column per strain component.

    ``steps`` are relative to ``scale``, the size of the strain increment being
    perturbed, so the same sweep means the same thing for a model loaded to a
    strain of a percent and one loaded to a strain of a millionth.
    """
    sweep = DifferenceSweep()
    if not build.ok:
        sweep.reason = build.reason
        return sweep

    unperturbed, complaint = run_replay(build, work_dir, 0, 0.0)
    if not unperturbed:
        sweep.reason = f"the unperturbed replay produced no stress: {complaint}"
        return sweep
    sweep.unperturbed = unperturbed

    wanted = tuple(components) or tuple(range(1, ntens + 1))
    for relative in steps:
        step = relative * scale
        columns: list[list[float]] = []
        for component in wanted:
            plus, first = run_replay(build, work_dir, component, step)
            minus, second = run_replay(build, work_dir, component, -step)
            if not plus or not minus:
                sweep.failures.append(
                    f"step {relative:g}, component {component}: "
                    f"{first or second}")
                columns = []
                break
            columns.append([(a - b) / (2.0 * step) for a, b in zip(plus, minus)])
        if not columns:
            continue
        # columns[j][i] is d STRESS(i) / d DSTRAN(j); the tangent is its
        # transpose, because DDSDDE(i,j) is indexed the other way round.
        sweep.matrices[relative] = [
            [columns[j][i] for j in range(len(columns))] for i in range(ntens)]

    sweep.ok = bool(sweep.matrices)
    if not sweep.ok and not sweep.reason:
        sweep.reason = "no step size produced a complete set of columns"
    return sweep
