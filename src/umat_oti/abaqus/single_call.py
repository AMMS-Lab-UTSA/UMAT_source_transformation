"""Replay ONE recorded UMAT call, offline, in either build, and compare.

``call_isolation`` finds the call at which two builds parted while holding the
same arguments. It reads that out of the probe records, which is enough to
refute a hypothesis and not enough to confirm a mechanism: a recorded pair of
numbers cannot be bisected. What can be bisected is the call itself, re-run.

Everything needed is already on disk after a verification run. The probe's
ENTRY record holds every argument Abaqus passed. The transformed build's work
directory holds the generated source and the compiled OTI modules it links
against. So one call can be replayed outside Abaqus, from exactly the arguments
the solver used, in either build, as many times as a bisection needs -- with no
solver, no licence and no queue.

Measured on ``Worlthen/simplified_curing.for``: the transformed build replayed
this way returns ``STRESS`` = NaN in all six components and ``STATEV`` =
(NaN, NaN, 1.2470275728981441E-02, NaN, 0, 0), which is what the pass9 probe
recorded to the last digit. That agreement is what makes the replay evidence
rather than a simulation of evidence, and this module checks it: a replay whose
outputs do not reproduce the recorded ones is reported as not reproducing them,
never quietly used as though it had.

Two things this deliberately does NOT do.

**It does not call SDVINI.** ``replay.py`` does, when the recorded state is all
zeros, because a finite difference of an uninitialised model is a derivative of
the wrong function. Here the question is different: did the routine return what
it returned FROM THE ARGUMENTS IT WAS GIVEN? Initialising state the solver did
not initialise would answer a different question -- and on simplified_curing it
would have hidden the finding, because the author's SDVINI seeds
``STATEV(1) = 1.d-15`` precisely to keep the model off the singular point the
generated deck put it on.

**It does not perturb anything.** One call, the arguments as recorded. A sweep
belongs in ``replay.py``, which already has one.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

#: The state file the driver reads. Same layout as ``replay.STATE_FILE`` and
#: written by ``replay.write_state``, so one writer serves both drivers and
#: there is no second definition of what a recorded call looks like.
STATE_FILE = "otis_state.txt"

#: What the driver writes back.
RESULT_FILE = "otis_call_out.txt"

_DRIVER = """PROGRAM otis_single_call
! Replays one recorded UMAT call with the arguments exactly as recorded.
! No perturbation, and no SDVINI: the question is what the routine returned
! from what it was handed, and initialising state the solver did not
! initialise would answer a different one.
  IMPLICIT NONE
  INTEGER :: NTENS,NSTATV,NPROPS,NDI,NSHR,I,J,U,IOS
  REAL(8) :: DTIME,TEMP,DTEMP,PNEWDT,CELENT,SSE,SPD,SCD,RPL,DRPLDT
  REAL(8), ALLOCATABLE :: STRESS(:),STATEV(:),DDSDDE(:,:),STRAN(:),DSTRAN(:)
  REAL(8), ALLOCATABLE :: PROPS(:),DDSDDT(:),DRPLDE(:)
  REAL(8) :: TIME(2),PREDEF(1),DPRED(1),COORDS(3),DROT(3,3)
  REAL(8) :: DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NOEL,NPT,LAYER,KSPT,KSTEP,KINC
  CHARACTER(80) :: CMNAME

  OPEN(NEWUNIT=U,FILE='%(state)s',STATUS='OLD',ACTION='READ',IOSTAT=IOS)
  IF (IOS .NE. 0) THEN
    WRITE(*,*) 'OTIS-CALL: no state file'
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

  DDSDDE=0.0_8; SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8
  DDSDDT=0.0_8; DRPLDE=0.0_8; DRPLDT=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PNEWDT=1.0_8; LAYER=1; KSPT=1; CMNAME='%(name)s'

  CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
    STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
    NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
    NOEL,NPT,LAYER,KSPT,KSTEP,KINC)

  OPEN(NEWUNIT=U,FILE='%(out)s',STATUS='REPLACE',ACTION='WRITE')
  WRITE(U,'(A,I0)') 'NTENS ',NTENS
  DO I=1,NTENS
    WRITE(U,'(ES26.17E3)') STRESS(I)
  END DO
  WRITE(U,'(A,I0)') 'NSTATV ',NSTATV
  DO I=1,MAX(NSTATV,1)
    WRITE(U,'(ES26.17E3)') STATEV(I)
  END DO
  WRITE(U,'(A)') 'DDSDDE'
  DO I=1,NTENS
    DO J=1,NTENS
      WRITE(U,'(ES26.17E3)') DDSDDE(I,J)
    END DO
  END DO
  CLOSE(U)
END PROGRAM otis_single_call

%(stubs)s"""


@dataclass
class CallBuild:
    """A compiled replay of one source, or the reason there is not one."""

    program: Optional[Path] = None
    compiler: str = ""
    ok: bool = False
    reason: str = ""
    log: str = ""

    def as_dict(self) -> dict:
        return {"program": str(self.program) if self.program else None,
                "compiler": self.compiler, "ok": self.ok,
                "reason": self.reason, "log": self.log[-2000:]}


@dataclass
class CallResult:
    """What one replayed call returned."""

    stress: list = field(default_factory=list)
    state: list = field(default_factory=list)
    tangent: list = field(default_factory=list)
    ok: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {"stress": list(self.stress), "state": list(self.state),
                "ok": self.ok, "reason": self.reason}


#: A program unit's opening line, in either source form.
_UNIT_OPENS = re.compile(
    r"^\s*(?:\w+\s+)*(SUBROUTINE|FUNCTION)\s+(\w+)", re.IGNORECASE)
#: Its closing line. ``END IF`` and ``END DO`` must NOT match: written as
#: ``END\s*\w*`` they did, so the first ``END IF`` inside a stub ended the
#: block, the rest of that stub was scanned as though it were a new program
#: unit, and one routine was reported -- and removed -- twice.
_UNIT_ENDS = re.compile(
    r"^\s*END\s*(?:(?:SUBROUTINE|FUNCTION)(?:\s+\w+)?)?\s*$",
    re.IGNORECASE)


def routines_defined(source_text: str) -> set:
    """Every SUBROUTINE and FUNCTION the text defines, upper-cased."""
    found = set()
    for line in source_text.splitlines():
        if line[:1] in "cC*!":
            continue
        match = _UNIT_OPENS.match(line)
        if match and not re.match(r"^\s*END\b", line, re.IGNORECASE):
            found.add(match.group(2).upper())
    return found


def drop_stubs_defined_by(stubs: str, source_text: str) -> tuple:
    """Remove stubs the source under test defines for itself.

    ``awhelanUCD/HETVAL_lemaitreDamageNonLocal.f`` ships its own ``ROTSIG``.
    Linking the stub block beside it gave
    ``multiple definition of 'rotsig_'`` and no replay at all -- a source
    excluded from the evidence for supplying more of Abaqus's interface than
    the others, which is not a reason to learn less about it.
    """
    defined = routines_defined(source_text)
    kept: list = []
    dropped: list = []
    lines = stubs.splitlines(True)
    index = 0
    while index < len(lines):
        match = _UNIT_OPENS.match(lines[index])
        if not match:
            kept.append(lines[index])
            index += 1
            continue
        start, name = index, match.group(2).upper()
        depth = 0
        while index < len(lines):
            if _UNIT_OPENS.match(lines[index]) and not re.match(
                    r"^\s*END\b", lines[index], re.IGNORECASE):
                depth += 1
            elif _UNIT_ENDS.match(lines[index]):
                depth -= 1
                if depth <= 0:
                    index += 1
                    break
            index += 1
        block = lines[start:index]
        if name in defined:
            dropped.append(name)
        else:
            kept.extend(block)
    return "".join(kept), dropped


def driver_source(name: str = "REPLAY", source_text: str = "") -> str:
    """The single-call program, for a source linked beside it.

    ``source_text`` is the UMAT being replayed. Any Abaqus utility it defines
    itself is dropped from the stub block rather than defined twice.
    """
    from umat_oti.abaqus.replay import _replay_utility_stubs
    from umat_oti.validation.actual_umat_higher_order_generic import (
        _abaqus_utility_stubs)

    stubs = _abaqus_utility_stubs() + _replay_utility_stubs()
    if source_text:
        stubs, _ = drop_stubs_defined_by(stubs, source_text)
    return _DRIVER % {"state": STATE_FILE, "out": RESULT_FILE,
                      "name": name.upper()[:60], "stubs": stubs}


def install_headers(work_dir: Path, include: Optional[Path] = None) -> list:
    """Abaqus's own headers, under every casing a corpus source includes them by.

    ``-I`` alone is not enough on a case-sensitive filesystem: Abaqus ships
    ``aba_param.inc`` and ``SMAAspUserSubroutines.hdr``, and sources in this
    corpus include them as ``ABA_PARAM.INC`` and
    ``#INCLUDE <SMAASPUSERSUBROUTINES.HDR>``. One pass9 entry --
    ``victorlefevre/.../UMAT_KLP_RK5_hybrid.f`` -- failed to build in Abaqus
    for exactly that and was recorded as ``original_job_failed``.
    """
    from umat_oti.abaqus.replay import abaqus_include_dir

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    source = Path(include) if include else abaqus_include_dir()
    installed: list = []
    if not source or not source.is_dir():
        return installed
    for header in sorted(source.iterdir()):
        if not header.is_file():
            continue
        for name in {header.name, header.name.upper(), header.name.lower()}:
            target = work_dir / name
            if target.exists():
                continue
            try:
                shutil.copyfile(header, target)
                installed.append(name)
            except OSError:
                pass
    return installed


def build_call(source: Path, work_dir: Path, *, compiler: str = "ifort",
               name: str = "REPLAY", objects: Sequence[Path] = (),
               module_dirs: Sequence[Path] = (), flags: Sequence[str] = (),
               include: Optional[Path] = None,
               timeout: int = 900) -> CallBuild:
    """Compile the single-call driver against one UMAT source.

    ``objects`` are already-compiled units -- the OTI modules a transformed
    build links against -- and are passed through untouched. Only Fortran
    SOURCE is cleaned of an author's own PROGRAM and of console writes, and
    only source can be.
    """
    from umat_oti.abaqus.probe import silence_console_writes
    from umat_oti.abaqus.replay import _text_of, without_the_authors_program
    from umat_oti.fortran.normalize import detect_source_form

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which(compiler) is None:
        return CallBuild(compiler=compiler,
                         reason=f"{compiler} is not on PATH")

    unit = Path(source)
    text = _text_of(unit)
    form = detect_source_form(unit, text)
    text, silenced = silence_console_writes(text, form)
    without, removed = without_the_authors_program(text, form)
    if removed or silenced:
        prepared = work_dir / f"single_{unit.name}"
        prepared.write_text(without if removed else text, encoding="utf-8")
        unit = prepared

    driver = work_dir / "otis_single_call.f90"
    driver.write_text(driver_source(name, text), encoding="utf-8")
    program = work_dir / "otis_single_call"
    install_headers(work_dir, include)
    includes = [f"-I{work_dir}"] + [f"-I{Path(d)}" for d in module_dirs]
    command = [compiler, *flags, *includes, str(unit),
               *[str(Path(o)) for o in objects], str(driver),
               "-o", str(program)]
    try:
        done = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return CallBuild(compiler=compiler,
                         reason=f"{type(error).__name__}: {error}")
    if done.returncode != 0 or not program.is_file():
        return CallBuild(compiler=compiler,
                         reason=f"the single-call driver did not link against "
                                f"{Path(source).name} (exit {done.returncode})",
                         log=(done.stdout + done.stderr)[-6000:])
    return CallBuild(program=program, compiler=compiler, ok=True,
                     log=(done.stdout + done.stderr)[-2000:])


def parse_result(path: Path) -> CallResult:
    """The stress, state and tangent one replayed call wrote."""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return CallResult(reason="the replay wrote no result file")
    if not lines or not lines[0].startswith("NTENS"):
        return CallResult(reason="the result file has no NTENS header")
    ntens = int(lines[0].split()[1])
    stress = [float(value) for value in lines[1:1 + ntens]]
    rest = lines[1 + ntens:]
    state: list = []
    if rest and rest[0].startswith("NSTATV"):
        nstatv = int(rest[0].split()[1])
        state = [float(value) for value in rest[1:1 + max(nstatv, 1)]]
        rest = rest[1 + max(nstatv, 1):]
    tangent: list = []
    if rest and rest[0].strip() == "DDSDDE":
        flat = [float(value) for value in rest[1:1 + ntens * ntens]]
        tangent = [flat[row * ntens:(row + 1) * ntens] for row in range(ntens)]
    return CallResult(stress=stress, state=state, tangent=tangent, ok=True)


def run_call(build: CallBuild, work_dir: Path, timeout: int = 900) -> CallResult:
    """Run one replayed call and read back what it returned."""
    work_dir = Path(work_dir)
    out = work_dir / RESULT_FILE
    if out.exists():
        out.unlink()
    if not build.ok or build.program is None:
        return CallResult(reason=build.reason or "no program to run")
    try:
        done = subprocess.run([str(build.program)], cwd=str(work_dir),
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        return CallResult(reason=f"{type(error).__name__}: {error}")
    result = parse_result(out)
    if not result.ok:
        result.reason = (result.reason + " -- "
                         + (done.stdout + done.stderr)[-1500:]).strip(" -")
    return result


#: How close a replay has to come to the recorded call to be treated as a
#: replay of it. Not a tolerance on the model: a tolerance on whether this
#: program ran the same code on the same numbers. Anything above rounding here
#: means the replay is of something else, and its bisection proves nothing.
REPLAY_SAME = 1e-12


def reproduces(result: CallResult, recorded: dict,
               *, tolerance: float = REPLAY_SAME) -> dict:
    """Did the replay return what the solver recorded for this call?

    Reported, never assumed. A NaN in the recorded output must be matched by a
    NaN in the replay: two NaNs compare unequal, so a comparison that only
    asked "is the difference small" would call the one case this was built for
    a failure to reproduce.
    """
    verdict = {"reproduced": False, "reason": "", "worst": 0.0,
               "worst_field": "", "worst_index": -1}
    if not result.ok:
        verdict["reason"] = result.reason or "the replay produced no result"
        return verdict
    worst = 0.0
    for field_name, replayed in (("STRESS", result.stress),
                                 ("STATEV", result.state)):
        reference = list(recorded.get(field_name) or ())
        if not reference:
            continue
        if len(reference) != len(replayed):
            verdict["reason"] = (
                f"{field_name} has {len(reference)} components in the record "
                f"and {len(replayed)} in the replay")
            return verdict
        scale = max((abs(v) for v in reference if math.isfinite(v)),
                    default=0.0) or 1.0
        for index, (left, right) in enumerate(zip(reference, replayed)):
            finite = math.isfinite(left), math.isfinite(right)
            if finite != (True, True):
                if finite[0] == finite[1]:
                    continue        # both non-finite: the replay matched
                verdict["reason"] = (
                    f"{field_name}({index + 1}) is "
                    f"{'finite' if finite[0] else 'not finite'} in the record "
                    f"and {'finite' if finite[1] else 'not finite'} in the "
                    f"replay, so the replay is not of the recorded call")
                return verdict
            difference = abs(left - right) / scale
            if difference > worst:
                worst, verdict["worst_field"], verdict["worst_index"] = (
                    difference, field_name, index + 1)
    verdict["worst"] = worst
    verdict["reproduced"] = worst <= tolerance
    if not verdict["reproduced"]:
        verdict["reason"] = (
            f"the replay differs from the recorded call by {worst:.3e} of "
            f"{verdict['worst_field']}'s scale at component "
            f"{verdict['worst_index']}, which is above {tolerance:.0e}: it is "
            f"not a replay of that call and nothing bisected in it applies")
    return verdict


def transformed_build_inputs(work_dir: Path) -> dict:
    """The source, objects and module directory a transformed replay needs.

    Read off the work directory a verification run left behind. The compiled
    OTI modules are kept there beside the generated source, which is what makes
    this possible without re-running the transform.
    """
    directory = Path(work_dir) / "transformed"
    source = directory / "transformed_user.f"
    objects = sorted(path for path in directory.glob("*.o"))
    return {"source": source if source.is_file() else None,
            "objects": objects, "module_dirs": [directory],
            "present": source.is_file() and bool(objects)}


#: The flags Abaqus 2021 compiles a user subroutine with on this installation,
#: copied verbatim from a job's own ``.com`` file
#: (``compile_fortran`` in
#: ``corpus_run/pass9/work/0d97f9db648d23a064062989/transformed/transformed.com``),
#: minus ``-c``, ``-V`` and the ``%P``/``%I`` placeholders.
#:
#: Every one of them is here on purpose, and the vectorisation and alignment
#: ones especially. A replay built without ``-axcore-avx2,avx`` and
#: ``-align array64byte`` is a different binary from the one the solver ran,
#: and a difference between it and the recorded call then says only that two
#: different binaries differ. Measured: the crystal-plasticity replay built
#: without them returns the CORRECT STATEV(25) where the solver's build
#: returned 1.7e-30, which is a finding about the build, not about the
#: arithmetic -- and it could only be read that way once the flags matched.
ABAQUS_IFORT_FLAGS = (
    "-fpp", "-fPIC", "-extend_source", "-DABQ_LNX86_64", "-DABQ_FORTRAN",
    "-auto", "-pc64", "-align", "array64byte", "-prec-div", "-prec-sqrt",
    "-fp-model", "precise", "-fimf-arch-consistency=true",
    "-mP2OPT_hpo_vec_divbyzero=F", "-no-fma", "-fp-speculation=safe",
    "-fprotect-parens", "-fstack-protector-strong",
    "-reentrancy", "threaded", "-msse3", "-axcore-avx2,avx", "-WB",
)
