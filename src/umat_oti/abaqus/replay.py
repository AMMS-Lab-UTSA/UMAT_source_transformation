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

Nothing here changes a constitutive statement. The increment is replayed
exactly as Abaqus ran it, except for one component of DSTRAN, which is what a
partial derivative means.

The one thing the driver writes into STATEV is what Abaqus itself writes there:
when the source ships an SDVINI and the state read from the file is all zeros,
it calls the author's own SDVINI, as the solver does before the first
increment. Never over a state that was recorded -- see the call site below.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from umat_oti.fortran.normalize import detect_source_form
from umat_oti.abaqus.probe import silence_console_writes
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
  CHARACTER(256) :: GFILE
  REAL(8) :: DFPERT(3,3)

  CALL GET_COMMAND_ARGUMENT(1,ARG); READ(ARG,*) COMPONENT
  CALL GET_COMMAND_ARGUMENT(2,ARG); READ(ARG,*) STEP
! An optional third argument names a file holding nine numbers to ADD to
! DFGRD1. A source whose kinematic input is the deformation gradient does not
! see a perturbation of DSTRAN at all: its stress does not move, the centred
! difference is identically zero, and the comparison then reports a relative
! error of exactly 1 at every step size -- which is what it did, for every
! finite-strain source in the corpus.
  CALL GET_COMMAND_ARGUMENT(3,GFILE)

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

  IF (LEN_TRIM(GFILE) .GT. 0) THEN
    OPEN(NEWUNIT=U,FILE=TRIM(GFILE),STATUS='OLD',ACTION='READ',IOSTAT=IOS)
    IF (IOS .NE. 0) THEN
      WRITE(*,*) 'OTIS-REPLAY: no gradient perturbation file'
      STOP 3
    END IF
    READ(U,*) ((DFPERT(I,J),J=1,3),I=1,3)
    CLOSE(U)
    DO I=1,3
      DO J=1,3
        DFGRD1(I,J) = DFGRD1(I,J) + DFPERT(I,J)
      END DO
    END DO
  END IF

  DDSDDE=0.0_8; SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8
  DDSDDT=0.0_8; DRPLDE=0.0_8; DRPLDT=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PNEWDT=1.0_8; LAYER=1; KSPT=1; CMNAME='%(name)s'
%(sdvini)s
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


#: The Abaqus call the solver makes before the first increment, in the shape
#: the interface declares it. NCRDS is 3 because the driver hands COORDS three
#: numbers; LAYER and KSPT are set just above, and STATEV holds what the state
#: file said.
_SDVINI_CALL = """
! Abaqus fills STATEV by calling the author's own SDVINI before the first
! increment, whenever the deck asks for it. Running the author's subroutine is
! not the same as reading the constants out of it: a state variable set from
! COORDS or NOEL is only right if the code that sets it runs.
!
! Only when nothing was recorded. A state read from a probe ENTRY record is the
! state the solver had already reached, and running SDVINI over it would replay
! a different increment from the one that was recorded -- silently, and with a
! plausible-looking answer. An all-zero state is the one case where there is
! nothing to overwrite, and it is exactly the case that was broken: eight
! mholla growth sources returned NaN in all six stress components from the
! UNTRANSFORMED build under an all-zero start, five of them because they read
! a growth stretch their own SDVINI sets to 1.0 and then divide by it.
  IF (NSTATV .GE. 1) THEN
    IF (ALL(STATEV(1:NSTATV) .EQ. 0.0_8)) THEN
      CALL SDVINI(STATEV,COORDS,NSTATV,3,NOEL,NPT,LAYER,KSPT)
    END IF
  END IF
"""

#: A definition of SDVINI, in fixed or free form, with or without a type
#: prefix. Anchored at the start of a statement so that ``CALL SDVINI`` and a
#: fixed-form comment in column 1 are not read as definitions.
_SDVINI_DEFINITION = re.compile(
    r"^(?:\w+\s+)*subroutine\s+sdvini\b", re.IGNORECASE)


def defines_sdvini(source_text: str) -> bool:
    """Whether this text defines SDVINI, so a call to it would link.

    The call has to be emitted conditionally, not always: gfortran resolves
    SDVINI at link time and a driver that calls one no source defines does not
    link at all. That failure would land on every source in the corpus without
    an SDVINI, which is most of them, and would read as a defect in the model.
    """
    for raw in source_text.splitlines():
        stripped = raw.strip()
        # Fixed form marks a comment by column 1; the text is scanned line by
        # line rather than parsed, so the marker is checked on the raw line.
        if raw[:1] in ("c", "C", "*", "!") or stripped.startswith("!"):
            continue
        if _SDVINI_DEFINITION.match(stripped):
            return True
    return False


def quad_driver_text(text: str) -> str:
    """The replay driver with the routine's state in REAL(16) (Vera B7 A2).

    The state file is READ into REAL(8) and widened exactly: a decimal string
    read straight into REAL(16) is a different number from the double the
    solver held (Vera B7 gap (b)). The perturbation step is formed in
    REAL(16) (x + h exact); the outputs are written to 35 significant digits
    so that the difference of two runs is taken exactly
    (:func:`run_replay` with ``exact=True``)."""
    src = text.replace("REAL(8) :: DTIME,TEMP,DTEMP,PNEWDT,CELENT,SSE,SPD,SCD,RPL,DRPLDT,STEP",
                       "REAL(16) :: DTIME,TEMP,DTEMP,PNEWDT,CELENT,SSE,SPD,SCD,RPL,DRPLDT\n"
                       "  REAL(8) :: STEP,R8,R8A(9)")
    for old in ("  REAL(8), ALLOCATABLE :: STRESS(:),STATEV(:),DDSDDE(:,:),STRAN(:),DSTRAN(:)",
                "  REAL(8), ALLOCATABLE :: PROPS(:),DDSDDT(:),DRPLDE(:)",
                "  REAL(8) :: TIME(2),PREDEF(1),DPRED(1),COORDS(3),DROT(3,3)",
                "  REAL(8) :: DFGRD0(3,3),DFGRD1(3,3)",
                "  REAL(8) :: DFPERT(3,3)"):
        assert old in src, old
        src = src.replace(old, old.replace("REAL(8)", "REAL(16)"))
    reads = {
        "  READ(U,*) DTIME,TIME(1),TIME(2),TEMP,DTEMP,CELENT":
            "  READ(U,*) R8A(1:6)\n  DTIME=R8A(1); TIME(1)=R8A(2); TIME(2)=R8A(3)\n"
            "  TEMP=R8A(4); DTEMP=R8A(5); CELENT=R8A(6)",
    }
    # Every list read goes through READ8 (REAL(8) -> REAL(16), exact).
    for name, count in (("STRESS", "NTENS"), ("STATEV", "MAX(NSTATV,1)"), ("STRAN", "NTENS"),
                        ("DSTRAN", "NTENS"), ("PROPS", "MAX(NPROPS,1)"),
                        ("COORDS", "3")):
        old = f"  READ(U,*) ({name}(I),I=1,{count})"
        assert old in src, old
        src = src.replace(old, f"  CALL READ8(U,{name},{count})")
    for name in ("DFGRD0", "DFGRD1", "DROT"):
        old = f"  READ(U,*) (({name}(I,J),J=1,3),I=1,3)"
        assert old in src, old
        src = src.replace(old, f"  CALL READ8M(U,{name})")
    old = "  READ(U,*) DTIME,TIME(1),TIME(2),TEMP,DTEMP,CELENT"
    assert old in src
    src = src.replace(old, reads[old])
    old = "    DSTRAN(COMPONENT) = DSTRAN(COMPONENT) + STEP"
    assert old in src
    src = src.replace(old, "    DSTRAN(COMPONENT) = DSTRAN(COMPONENT) + REAL(STEP,16)")
    old = "    READ(U,*) ((DFPERT(I,J),J=1,3),I=1,3)"
    assert old in src
    src = src.replace(old, "    CALL READ8M(U,DFPERT)")
    src = src.replace("DDSDDE=0.0_8; SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8",
                      "DDSDDE=0.0_16; SSE=0.0_16; SPD=0.0_16; SCD=0.0_16; RPL=0.0_16")
    src = src.replace("DDSDDT=0.0_8; DRPLDE=0.0_8; DRPLDT=0.0_8; PREDEF=0.0_8; DPRED=0.0_8",
                      "DDSDDT=0.0_16; DRPLDE=0.0_16; DRPLDT=0.0_16; PREDEF=0.0_16; DPRED=0.0_16")
    src = src.replace("PNEWDT=1.0_8;", "PNEWDT=1.0_16;")
    src = src.replace("IF (ALL(STATEV(1:NSTATV) .EQ. 0.0_8)) THEN",
                      "IF (ALL(STATEV(1:NSTATV) .EQ. 0.0_16)) THEN")
    src = src.replace("WRITE(U,'(ES26.17E3)')", "WRITE(U,'(ES45.35E4)')")
    helpers = """
SUBROUTINE READ8(U, X, N)
! A row of REAL(8) values, widened exactly into REAL(16).
  INTEGER, INTENT(IN) :: U, N
  REAL(16), INTENT(OUT) :: X(N)
  REAL(8) :: Y(N)
  READ(U,*) Y
  X = REAL(Y, 16)
END SUBROUTINE READ8

SUBROUTINE READ8M(U, X)
  INTEGER, INTENT(IN) :: U
  REAL(16), INTENT(OUT) :: X(3,3)
  REAL(8) :: Y(9)
  INTEGER :: I, J
  READ(U,*) Y
  DO I=1,3
    DO J=1,3
      X(I,J) = REAL(Y((I-1)*3+J), 16)
    END DO
  END DO
END SUBROUTINE READ8M
"""
    marker = "END PROGRAM otis_replay\n"
    assert marker in src
    head, stubs = src.split(marker, 1)
    from umat_oti.corpus_features.drivers import quadify
    return head + marker + helpers + quadify(stubs)


def driver_source(name: str = "REPLAY", *, initialise_state: bool = False) -> str:
    """The replay program, for a source that has to be linked beside it.

    ``initialise_state`` emits the call to SDVINI. It is the caller's job to
    say so, because whether that call can link is a property of the source
    being compiled beside the driver, not of the driver.
    """
    return _DRIVER % {"state": STATE_FILE, "name": name.upper()[:60],
                      "sdvini": _SDVINI_CALL if initialise_state else "",
                      "stubs": utility_stub_block()}


def utility_stub_block() -> str:
    """Every Abaqus-utility stub the replay drivers link, each defined once.

    The shared block (``_abaqus_utility_stubs``) carries SPRIND, SPRINC and SINV
    (B17 G2c); the replay block carries the rest. The two are concatenated
    wherever a replay driver is built.
    """
    from umat_oti.validation.actual_umat_higher_order_generic import (
        _abaqus_utility_stubs)

    return _abaqus_utility_stubs() + _replay_utility_stubs()


def _replay_utility_stubs() -> str:
    """Abaqus utilities the shared stub block does not carry.

    Appended to it rather than added there, because that block is shared with
    the higher-order drivers and these bodies are what *this* driver's corpus
    needs. Each one was an undefined symbol at link time, not a suspicion:
    UMAT_KLP_RK5_hybrid.f failed with `undefined reference to get_thread_id_`,
    `stdb_abqerr_` and `getvrm_`, for the original build and the transformed
    build alike, which accuses the harness rather than the transform.

    Two of them deliberately stop the run instead of returning something. That
    follows the rule the XIT stub already sets: a stub may reproduce the
    solver's behaviour, but it may not invent an answer the solver would have
    had to compute, and it may not swallow a refusal the author raised.
    """
    return """
SUBROUTINE ROTSIG(S, R, OUTPUT, LSTR, NDI, NSHR)
  ! OUTPUT = R S R^T for a symmetric tensor in Abaqus's Voigt storage.
  !
  ! Unlike GETSENSORVALUE this is ON the material-point path: a UMAT calls it
  ! to carry a state tensor through a rigid rotation, and a stop-stub would
  ! turn a verifiable material into an unverifiable one. Abaqus links it in,
  ! so the published source does not define it, and the replay driver's link
  ! failed on the symbol.
  !
  ! The same algebra as the definition the transform supplies for the OTI side
  ! (umat_oti.transform.abaqus_utility_definitions), in free form and over
  ! plain reals, so the reference and the value under test rotate a tensor the
  ! same way. LSTR=2 stores ENGINEERING shear, twice the tensor entry, and
  ! rotating it as though the stored value were the entry is a silent factor
  ! of two on every rotated strain.
  INTEGER :: LSTR, NDI, NSHR, I, J, K, L
  REAL(8) :: S(NDI+NSHR), R(3,3), OUTPUT(NDI+NSHR)
  REAL(8) :: T(3,3), TR(3,3), HALFSH
  HALFSH = 1.0D0
  IF (LSTR == 2) HALFSH = 0.5D0
  T = 0.0D0
  DO I = 1, NDI
    T(I,I) = S(I)
  END DO
  IF (NSHR >= 1) THEN
    T(1,2) = S(NDI+1)*HALFSH
    T(2,1) = T(1,2)
  END IF
  IF (NSHR >= 2) THEN
    T(1,3) = S(NDI+2)*HALFSH
    T(3,1) = T(1,3)
  END IF
  IF (NSHR >= 3) THEN
    T(2,3) = S(NDI+3)*HALFSH
    T(3,2) = T(2,3)
  END IF
  DO I = 1, 3
    DO J = 1, 3
      TR(I,J) = 0.0D0
      DO K = 1, 3
        DO L = 1, 3
          TR(I,J) = TR(I,J) + R(I,K)*T(K,L)*R(J,L)
        END DO
      END DO
    END DO
  END DO
  DO I = 1, NDI
    OUTPUT(I) = TR(I,I)
  END DO
  IF (NSHR >= 1) OUTPUT(NDI+1) = TR(1,2)/HALFSH
  IF (NSHR >= 2) OUTPUT(NDI+2) = TR(1,3)/HALFSH
  IF (NSHR >= 3) OUTPUT(NDI+3) = TR(2,3)/HALFSH
END SUBROUTINE ROTSIG
SUBROUTINE GETRANK(IRANK)
  ! The MPI rank of this process. The replay is one process: rank 0, which is
  ! also what the solver reports for a single-process Standard analysis.
  INTEGER :: IRANK
  IRANK = 0
END SUBROUTINE GETRANK
SUBROUTINE GETSENSORVALUE(SENSORNAME, VALUE)
  ! Abaqus reads a sensor's current value out of the analysis. Five corpus
  ! files carry the author's UAMP amplitude subroutine in the same compilation
  ! unit as the UMAT; the replay driver links the whole file, so this symbol
  ! is undefined at link time even though nothing on the material-point path
  ! ever calls it. The link failed, no sweep was attempted, and the row was
  ! recorded as a tangent that could not be verified -- a statement about the
  ! harness dressed as one about the transform.
  !
  ! It STOPS rather than returning a number. A sensor value is a fact about a
  ! running analysis; there is no analysis here, and inventing one would put a
  ! fabricated amplitude into a stress history. If a replay ever reaches this,
  ! the run has left the material point and the result is not evidence.
  !
  ! REAL(8) for the same implicit-typing reason as GET_THREAD_ID: these files
  ! are IMPLICIT REAL*8(A-H,O-Z) and G falls in A-H.
  CHARACTER(*) :: SENSORNAME
  REAL(8) :: VALUE
  WRITE(0,'(A)') 'GETSENSORVALUE was called during a replay. There is no ' &
    // 'running analysis to read a sensor from, and this driver will not ' &
    // 'invent one. Sensor: ' // SENSORNAME
  VALUE = 0.0D0
  STOP 3
END SUBROUTINE GETSENSORVALUE
FUNCTION GET_THREAD_ID()
  ! The thread this material point is being evaluated on. The replay runs one
  ! point on one thread, so it is the master thread, 0.
  !
  ! REAL(8), not INTEGER, and that is not a mistake. Abaqus declares this
  ! INTEGER in SMAASPUSERSUBROUTINES.HDR, which is a *preprocessor* include
  ! that gfortran does not process in a fixed-form .f file. The caller
  ! therefore types the result by the implicit rule these sources carry --
  ! IMPLICIT REAL*8(A-H,O-Z), and G falls in A-H -- and reads it out of the
  ! floating-point register. Measured on UMAT_KLP_RK5_hybrid.f, gfortran emits
  ! `call get_thread_id_` followed by `cvttsd2sil %xmm0,%eax`. An INTEGER stub
  ! returns in %eax and leaves the caller reading whatever happened to be in
  ! %xmm0; the author guards his input checks with IF (MYTHREADID.EQ.0), so a
  ! garbage id skips them without a word.
  REAL(8) :: GET_THREAD_ID
  GET_THREAD_ID = 0.0D0
END FUNCTION GET_THREAD_ID
SUBROUTINE STDB_ABQERR(LOP,STRING,INTV,REALV,CHARV)
  ! Abaqus's message service. LOP is the severity: 1 information, -1 warning,
  ! -2 an error that ends the analysis at the end of the increment, -3 an error
  ! that ends it at once.
  !
  ! An error is therefore NOT a no-op. A model that refuses its input is
  ! refusing to compute this increment, and letting the run continue would put
  ! whatever STRESS happened to be in the array into the evidence as though the
  ! model had produced it.
  !
  ! The message is written with its %I and %R placeholders unexpanded, and INTV
  ! and REALV are never read. They are declared here only to be passed: without
  ! an interface the caller's actual arguments carry no type information, and
  ! reading a REAL(4) array through a REAL(8) dummy would print numbers that
  ! were never in it.
  IMPLICIT NONE
  INTEGER :: LOP
  CHARACTER(*) :: STRING
  INTEGER :: INTV(*)
  REAL(8) :: REALV(*)
  CHARACTER(*) :: CHARV(*)
  IF (LOP .LE. -2) THEN
    WRITE(0,'(A,I0,A)') 'UMAT called STDB_ABQERR with severity ',LOP, &
      ': the model rejected this increment.'
    WRITE(0,'(A)') TRIM(STRING)
    STOP 5
  END IF
  WRITE(0,'(A,I0,A)') 'STDB_ABQERR (severity ',LOP,'): '//TRIM(STRING)
END SUBROUTINE STDB_ABQERR
SUBROUTINE GETJOBNAME(JOBNAME,LENJOBNAME)
  ! Sources name their scratch files after the job. A blank name would make
  ! them open a file called '', which fails with a runtime error that reads
  ! like a defect in the model.
  IMPLICIT NONE
  CHARACTER(*) :: JOBNAME
  INTEGER :: LENJOBNAME
  JOBNAME = 'otis_replay'
  LENJOBNAME = LEN_TRIM(JOBNAME)
END SUBROUTINE GETJOBNAME
SUBROUTINE GETVRM(VAR,ARRAY,JARRAY,FLGRAY,JRCD,JMAC,JMATYP,MATLAYO,LACCFLA)
  ! Abaqus reads output values back out of its own results database. There is
  ! no database here and no previously computed output to read.
  !
  ! Stubbed so that a file whose UVARM calls it links -- UMAT_KLP_RK5_hybrid.f
  ! is such a file, and this driver never enters UVARM -- but stopping rather
  ! than returning zeros. Zeros would be state this harness invented, and a
  ! model that computes from them would report a stress that nothing in the
  ! author's material produced.
  IMPLICIT NONE
  CHARACTER(*) :: VAR
  REAL(8) :: ARRAY(*)
  INTEGER :: JARRAY(*),JRCD,JMAC(*),JMATYP(*),MATLAYO,LACCFLA
  CHARACTER(*) :: FLGRAY(*)
  WRITE(0,'(A)') 'UMAT called GETVRM: the replay has no results database, '// &
    'so the values it asks for do not exist and were not invented.'
  STOP 6
END SUBROUTINE GETVRM
"""


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
    dtime = (entry.get("DTIME") or [0.0])[0]
    # TIME(1) is the step time and TIME(2) the total time. They are different
    # numbers in every step after the first, and writing one into both slots
    # replays the model at a point on its load history that Abaqus never
    # visited: the Jeff97 growth models ramp on (TIME(1)+DTIME)/TotalT, so a
    # replay handed TIME(2) as TIME(1) grows them twice as far. The centred
    # difference still converges -- both evaluations move together -- to the
    # tangent of the wrong material state, which is worse than not converging.
    # The pair comes from the probe now; the scalar is the fallback for a
    # probe file written before it recorded both.
    recorded = [float(value) for value in (entry.get("TIME") or ())]
    if len(recorded) >= 2:
        step_time, total_time = recorded[0], recorded[1]
    else:
        total_time = float(entry.get("time") or 0.0)
        step_time = total_time

    lines = [
        f"{ntens} {nstatv} {nprops} {ndi} {nshr}",
        _row((dtime, step_time, total_time, temp[0],
              temp[1] if len(temp) > 1 else 0.0, celent)),
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


def declared_start(
    props: Sequence[float], *, ntens: int = 6, nstatv: int = 1,
    strain: float = 1.0e-4, ndi: int = 3,
    transformed_source: Optional[Path] = None,
    initial_statev: Sequence[float] = (),
    temperature: float = 293.15, dtime: float = 1.0,
) -> dict:
    """An unloaded material point, driven along whichever input the source reads.

    Shaped like a probe ENTRY record, so :func:`write_state` accepts it and one
    increment can be replayed without a solver having produced it. Every value
    is stated: the stress and history are zero because that is what an unloaded
    point is, and the constants are the author's.

    Which kinematic input carries the increment is *read from the transformed
    file*, through ``seeded_kinematics`` -- the same map the transform seeded,
    so the reference is driven through the quantity the OTI side differentiated.
    Guessing it wrong is silent: a hyperelastic source that computes its stress
    from the deformation gradient, handed an identity gradient and a nonzero
    DSTRAN, returns zero stress for every increment. Both builds then return
    zero, and a comparison that accepted that would report perfect agreement
    about a model neither build had exercised.
    """
    stran = [0.0] * ntens
    dstran = [0.0] * ntens
    gradient = _identity()

    increment = [strain] + [0.0] * (ntens - 1)
    drive = None
    if transformed_source is not None:
        try:
            from umat_oti.transform.source_transform import seeded_kinematics
            drive = seeded_kinematics(
                Path(transformed_source).read_text(errors="replace"))
        except Exception:                      # noqa: BLE001 - fall back below
            drive = None

    if drive is None or drive.drives_strain_increment:
        dstran = list(increment)
    if drive is not None and drive.drives_deformation_gradient:
        from umat_oti.validation.tangent_validation import _gradient_increment
        advance = _gradient_increment(drive, increment)
        gradient = [1.0 if r == c else 0.0 for r in range(3) for c in range(3)]
        gradient = [value + advance[i // 3][i % 3] for i, value in enumerate(gradient)]

    state = list(initial_statev) or [0.0] * max(nstatv, 1)
    return {
        "NTENS": ntens, "NSTATV": max(nstatv, 1), "NPROPS": len(props),
        "NDI": ndi, "NSHR": max(ntens - ndi, 0),
        "STRESS0": [0.0] * ntens,
        "STATEV0": state,
        "STRAN": stran,
        "DSTRAN": dstran,
        "PROPS": [float(value) for value in props],
        "DTIME": [dtime],
        "TEMP": [temperature, 0.0],
        "time": 0.0,
        "DFGRD0": _identity(),
        "DFGRD1": gradient,
        "DROT": _identity(),
        # Not the origin and not (1,1,1): models in this corpus divide by
        # COORDS(1)**2 - COORDS(2)**2, which both of those make zero.
        "COORDS": [0.3, 0.7, 0.5, 1.0],
        "element": 1, "point": 1, "step": 1, "increment": 1,
        "driven_through": ("deformation gradient"
                           if drive is not None and drive.drives_deformation_gradient
                           else "strain increment"),
    }


def read_state(path: Path) -> dict:
    """Back out of the file :func:`write_state` wrote, as far as it is needed.

    Only the fields a reference has to know about the state it is taken at:
    the shape, and the deformation gradient at the end of the increment. The
    driver reads the whole file; this reads enough to know WHAT to perturb,
    which is a different question from what to pass in.

    Returns an empty dict rather than raising when the file is absent or
    short: a caller with no state file is a caller that cannot correct its
    perturbation, and it should say so rather than correct it wrongly.
    """
    try:
        rows = [line.split() for line in
                Path(path).read_text(errors="replace").splitlines()
                if line.strip()]
    except OSError:
        return {}
    if len(rows) < 10 or len(rows[0]) < 5:
        return {}
    try:
        ntens, nstatv, nprops, ndi, nshr = (int(value) for value in rows[0][:5])
        gradient = [float(value) for value in rows[9][:9]]
    except (TypeError, ValueError):
        return {}
    if len(gradient) < 9:
        return {}
    return {"NTENS": ntens, "NSTATV": nstatv, "NPROPS": nprops,
            "NDI": ndi, "NSHR": nshr, "DFGRD1": gradient}


def parse_replay_output(path: Path, exact: bool = False
                        ) -> tuple[list, list[list[float]]]:
    """The stress and tangent one replay produced. ``exact``: the stress as
    ``decimal.Decimal`` (a quad replay's 35 digits, so that two runs are
    differenced exactly before rounding to double)."""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return [], []
    if not lines or not lines[0].startswith("NTENS"):
        return [], []
    ntens = int(lines[0].split()[1])
    if exact:
        from decimal import Decimal
        stress = [Decimal(line.strip()) for line in lines[1:1 + ntens]]
    else:
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


def _text_of(path: Path) -> str:
    """One source's text, or nothing if it cannot be read.

    A unit that cannot be read is not a unit that defines SDVINI: the compiler
    is about to fail on it anyway, and failing there says why.
    """
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


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
    #: What the units INCLUDE, staged into the build directory
    #: (include_shim.stage_includes records: sha256, link or converted copy).
    includes: list = field(default_factory=list)


#: A PROGRAM unit an author shipped beside the UMAT -- a standalone driver
#: they used to exercise it. The replay driver has its own PROGRAM, and two
#: mains in one link is "multiple definition of `main`", which fails the build
#: and reports as a tangent that could not be measured. Measured on
#: UMAT_Tissue_2d_plane_strain.f and its plane-stress twin.
_PROGRAM_START = re.compile(r"^\s*(?:\d+\s+)?PROGRAM\s+([A-Za-z_]\w*)\s*$",
                            re.IGNORECASE)
_PROGRAM_END = re.compile(r"^\s*(?:\d+\s+)?END\s*(?:PROGRAM(?:\s+\w+)?)?\s*$",
                          re.IGNORECASE)

#: Any subprogram header. Tracked so that a bare END can be told apart: one
#: with a subprogram open closes that subprogram, and one with nothing open
#: closes an IMPLICIT main program -- a unit with no PROGRAM statement, which
#: the compiler still turns into `main`.
_SUBPROGRAM_START = re.compile(
    r"^\s*(?:\d+\s+)?"
    r"(?:(?:RECURSIVE|PURE|ELEMENTAL|MODULE)\s+)*"
    r"(?:(?:DOUBLE\s+PRECISION|REAL|INTEGER|LOGICAL|CHARACTER|COMPLEX)"
    r"(?:\s*\*\s*\d+|\s*\([^)]*\))?\s+)?"
    r"(?:SUBROUTINE|FUNCTION|BLOCK\s*DATA|MODULE)\b", re.IGNORECASE)


def _is_comment(line: str, free: bool) -> bool:
    if free:
        return line.lstrip().startswith("!") or not line.strip()
    return line[:1] in "Cc*!" or not line.strip()


def without_the_authors_program(text: str,
                                form: str = "") -> tuple[str, tuple[str, ...]]:
    """The source with every PROGRAM unit commented out, and their names.

    The replay drives the UMAT subroutine directly and never calls the
    author's own driver, so removing it changes nothing the replay computes.
    Commented rather than deleted, so the emitted file still lines up with the
    original when a reader compares them -- and the ORIGINAL file on disk is
    never touched.

    The comment marker follows the SOURCE FORM. ``C`` in column one is a
    fixed-form comment and a syntax error in free form, so a .f90 cleaned with
    it fails to compile -- which would turn one link error into another. Free
    form gets ``!``, which is a comment in both.

    A file may hold more than one PROGRAM, and the modules and subroutines
    after them have to survive: the removal stops at each program's own END.
    """
    # From the CONTENT when the caller does not know: guessing a filename
    # gets it wrong in one direction or the other, and here that means
    # emitting a `!` comment into a fixed-form file or a `C` into a free-form
    # one -- either of which turns one link error into a syntax error.
    if not form:
        from umat_oti.corpus import detect_source_form as detect_form_from_text
        form = detect_form_from_text(text)
    free = str(form).strip().lower().startswith("free")
    marker = "!" if free else "C"

    def comment(line: str, note: str = "") -> str:
        body = line.rstrip("\n").strip()
        head = f"{marker}     OTIS-REMOVED"
        return f"{head}{note}: {body}\n" if body else f"{head}{note}\n"

    out: list[str] = []
    removed: list[str] = []
    inside = False
    open_subprogram = 0     # depth: an internal procedure after CONTAINS nests
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        # A preprocessor line is not Fortran and must survive untouched: it is
        # read before the compiler ever sees the form.
        if stripped.lstrip().startswith("#"):
            out.append(line)
            continue
        if _is_comment(stripped, free):
            out.append(line)
            continue
        if not inside:
            found = _PROGRAM_START.match(stripped)
            if found:
                inside = True
                removed.append(found.group(1))
                out.append(comment(line, " (the replay supplies its own PROGRAM)"))
                continue
            if _SUBPROGRAM_START.match(stripped):
                open_subprogram += 1
                out.append(line)
                continue
            if _PROGRAM_END.match(stripped):
                if open_subprogram:
                    open_subprogram -= 1
                    out.append(line)
                    continue
                # An END with no subprogram open closes an IMPLICIT main
                # program -- a unit with no PROGRAM statement at all, which
                # gfortran still compiles into `main`. Measured on
                # UMAT_Tissue_2d_plane_strain.f: five subprogram headers and
                # six ENDs, and the trailing one is why the replay link said
                # "multiple definition of `main` ... first defined here" with
                # the UMAT's own object named.
                removed.append("(implicit main program)")
                out.append(comment(line, " (a bare END closing an implicit "
                                         "main program)"))
                continue
            out.append(line)
            continue
        out.append(comment(line))
        if _PROGRAM_END.match(stripped):
            inside = False
    return "".join(out), tuple(removed)


def build_replay(source: Path, work_dir: Path, *, compiler: str = "gfortran",
                 name: str = "REPLAY", extra: Sequence[Path] = (),
                 flags: Sequence[str] = (), timeout: int = 900,
                 quad: bool = False) -> ReplayBuild:
    """Compile the driver against one UMAT source, once for the whole sweep.

    ``quad`` (Vera B7 A2): the source promoted to REAL(16)
    (:func:`umat_oti.corpus_features.drivers.quadify`: REAL*8 / DOUBLE
    PRECISION -> REAL*16, binary32 and every literal unchanged), the header
    an IMPLICIT REAL*16 stub, and the quad driver (:func:`quad_driver_text`).
    Whether that reference is adopted is decided by the caller against the
    double build's primal and termination behaviour."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which(compiler) is None:
        return ReplayBuild(reason=f"{compiler} is not on PATH")

    # Whether the driver may call SDVINI is read from the units being compiled,
    # every one of them, because the definition does not have to live in the
    # entry file: a transformed build compiles its support modules beside the
    # UMAT. Reading it here rather than asking the caller keeps the two builds
    # of one source in step -- the transform carries SDVINI through unchanged,
    # so both sides call it or neither does.
    units = [Path(path) for path in (*extra, source)]
    # A PROGRAM the author shipped beside the UMAT collides with the driver's
    # own main. The unit is replaced by a copy with it commented out, for this
    # build only; the original file on disk is untouched.
    cleaned: list[Path] = []
    removed_programs: list[str] = []
    for index, unit in enumerate(units):
        text = _text_of(unit)
        form = detect_source_form(unit, text)
        # The same statements the Abaqus builds have removed, removed here
        # too, so the reference the finite difference is taken from is the
        # same routine that ran in the solver. Neither changes what is
        # computed -- an output statement with no IOSTAT= assigns nothing --
        # but "the same routine" is the claim this comparison rests on.
        text, silenced = silence_console_writes(text, form)
        without, removed = without_the_authors_program(text, form)
        if quad:
            from umat_oti.corpus_features.drivers import quadify
            without = quadify(without if removed else text)
            replacement = work_dir / f"quad_{index}_{unit.name}"
            replacement.write_text(without, encoding="utf-8")
            cleaned.append(replacement)
            removed_programs.extend(f"{unit.name}:PROGRAM {name}" for name in removed)
            continue
        if not removed and not silenced:
            cleaned.append(unit)
            continue
        if not removed:
            without = text
            removed = [f"{len(silenced)} console write(s)"]
        # Indexed, because two helper files in one bundle can share a name
        # and the second would otherwise overwrite the first's cleaned copy.
        replacement = work_dir / f"noprogram_{index}_{unit.name}"
        replacement.write_text(without, encoding="utf-8")
        cleaned.append(replacement)
        removed_programs.extend(f"{unit.name}:PROGRAM {name}" for name in removed)
    units = cleaned
    driver = work_dir / "otis_replay.f90"
    driver_text = driver_source(name, initialise_state=any(
        defines_sdvini(_text_of(unit)) for unit in units))
    driver.write_text(quad_driver_text(driver_text) if quad else driver_text,
                      encoding="utf-8")
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
    # files the units INCLUDE from beside the author's source, staged into
    # the build directory (on -I) so a cleaned copy compiled here finds them
    # A quad build stages each include PROMOTED as the source is (Vera B10
    # condition A): a linked double include would make the reference
    # mixed-precision.
    from umat_oti.abaqus.include_shim import stage_includes
    staged_includes: list[dict] = []
    for original_unit, unit in zip([Path(path) for path in (*extra, source)], units):
        if quad:
            from umat_oti.corpus_features.drivers import quadify
            staged_includes += stage_includes(
                _text_of(unit), [original_unit.parent], work_dir, convert=quadify,
                conversion="drivers.quadify (REAL*8 -> REAL*16, as the source)")
        else:
            staged_includes += stage_includes(_text_of(unit), [original_unit.parent], work_dir)
    if quad:
        for header in _HEADER_NAMES:
            (work_dir / header).write_text("      implicit real*16(a-h,o-z)\n"
                                           "      parameter (nprecd=2)\n", encoding="utf-8")
        used = "stub: IMPLICIT REAL*16 (quad reference)"
    else:
        used = _install_header(work_dir)
    includes = [f"-I{work_dir}"]

    # Order is load-bearing, not cosmetic. A compiler processes these in the
    # order given, and a module has to be compiled before the code that uses
    # it -- the transformed UMAT opens with `use otim6n1`. Putting the driver
    # first gave "Reading module otim6n1: Unexpected EOF", which is what a
    # half-written module file reads like.
    # The CLEANED units, not the originals. Building the list and then
    # compiling `extra` and `source` anyway left the author's implicit main
    # program on the command line, so the link still failed with "multiple
    # definition of `main`" while a perfectly good cleaned copy sat unused in
    # the build directory.
    command = [compiler, *flags, *includes,
               *[str(path) for path in units], str(driver),
               "-o", str(program)]
    try:
        done = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return ReplayBuild(reason=f"{type(error).__name__}: {error}")
    if done.returncode != 0 or not program.is_file():
        return ReplayBuild(compiler=compiler, header=used, includes=staged_includes,
                           reason=f"the replay driver did not link against "
                                  f"{Path(source).name} (exit {done.returncode})",
                           log=(done.stdout + done.stderr)[-6000:])
    return ReplayBuild(program=program, compiler=compiler, ok=True, includes=staged_includes,
                       header=used, log=(done.stdout + done.stderr)[-2000:])


#: Where a gradient perturbation is written for the driver to read.
GRADIENT_FILE = "otis_gradient.txt"


def run_replay(build: ReplayBuild, work_dir: Path, component: int,
               step: float, timeout: int = 900,
               gradient: Optional[Sequence[float]] = None,
               exact: bool = False) -> tuple[list, str]:
    """One perturbed call. Returns the stress it produced, and any complaint.

    ``gradient`` is nine numbers added to DFGRD1, for a source whose kinematic
    input is the deformation gradient. Such a source does not see a
    perturbation of DSTRAN at all -- its stress does not move, the centred
    difference is identically zero, and the comparison reports a relative error
    of exactly 1 at every step size. That is what it reported, for all ten
    finite-strain sources that had already agreed on their primal histories in
    Abaqus.
    """
    work_dir = Path(work_dir)
    out = work_dir / "otis_replay_out.txt"
    if out.exists():
        out.unlink()
    arguments = [str(build.program), str(component), repr(float(step))]
    if gradient is not None:
        values = [float(value) for value in gradient]
        path = work_dir / GRADIENT_FILE
        path.write_text(
            "\n".join(" ".join(f"{v!r}" for v in values[row * 3:row * 3 + 3])
                       for row in range(3)) + "\n", encoding="utf-8")
        arguments.append(str(path))
    try:
        done = subprocess.run(arguments,
                              cwd=str(work_dir), capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        return [], f"{type(error).__name__}: {error}"
    stress, _ = parse_replay_output(out, exact=exact)
    if not stress:
        return [], (done.stdout + done.stderr)[-2000:] or "the replay wrote no stress"
    return stress, ""


@dataclass
class DifferenceSweep:
    """Centred differences of one recorded increment, at several step sizes."""

    matrices: dict = field(default_factory=dict)
    unperturbed: list = field(default_factory=list)
    #: The tangent the ORIGINAL routine returned at the unperturbed state --
    #: the author's own DDSDDE, read out of the same replay that produced the
    #: difference. It costs nothing: the routine computes it whether or not
    #: anybody reads it. It is a second reference and a different one: the
    #: difference says what the stress DOES, and this says what the author
    #: SAID it does, and the two disagreeing is a finding about the source.
    original_tangent: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    #: Which kinematic input the perturbation moved. Recorded because it
    #: changes what the derivative is a derivative OF.
    driven_through: str = "strain increment"
    #: Per step, the largest disagreement between the forward and backward
    #: one-sided differences, relative to the size of the centred one. Near
    #: zero where the response is smooth; of order one where a constitutive
    #: branch changes between the two perturbations, whatever the step size.
    smoothness: dict = field(default_factory=dict)
    #: Per step, the tangent reconstructed from the FORWARD perturbation
    #: alone, and from the BACKWARD one alone. Kept because at a loading point
    #: of a rate-independent inelastic model the consistent tangent IS the
    #: one-sided derivative along the branch the increment took: the forward
    #: step grows the plastic strain or the damage and the backward step
    #: unloads elastically, so their average is the slope of a chord across a
    #: corner and belongs to neither branch. Only their disagreement used to
    #: be kept, which said a state was transitional without being able to say
    #: what its tangent was.
    forward: dict = field(default_factory=dict)
    backward: dict = field(default_factory=dict)
    #: Per step, the SEED-MAP difference: the derivative with respect to the
    #: perturbation the transform's own seed makes, uncorrected. For a source
    #: driven through the strain increment it is the same thing as
    #: ``matrices``; for one driven through the deformation gradient it is
    #: what ``matrices`` used to hold, and it is kept so the two definitions
    #: can be reported side by side rather than one silently replacing the
    #: other. See :mod:`umat_oti.validation.finite_strain_tangent`.
    seed_map_matrices: dict = field(default_factory=dict)
    #: How the reference was built. Named in the record because a number
    #: compared against DDSDDE is only evidence if it is a difference of the
    #: same thing DDSDDE is a derivative of.
    reference_definition: str = "d STRESS / d DSTRAN"
    ok: bool = False
    reason: str = ""


def one_sided_gap(one_sided: Sequence[tuple], near_zero_fraction: float
                  ) -> Optional[float]:
    """How far the forward and backward one-sided slopes sit from each other.

    ``one_sided`` is ``(component, forward_slope, backward_slope)`` per
    perturbed column. The answer is the worst componentwise disagreement,
    relative to the centred slope the two average to -- which is what says
    whether the two perturbations sat on the same constitutive branch. A kink
    between them shows here and nowhere else: the centred difference itself
    looks perfectly well behaved, because a chord across a corner is a number
    like any other.

    Measured only where a measurement exists. It used to be measured against
    each component's OWN centred slope, so a tangent carrying entries eight
    orders of magnitude below its largest had that many denominators made of
    round-off, and the worst of them decided the state. Measured on
    Growth-MinSur2.for, whose tangent has sixteen such entries: gaps of
    1.7e-04, 31.6, 3.0e-05, 2.0, 0.29, 2.0 across six step sizes. A quantity
    moving six orders of magnitude non-monotonically is not converging to two
    different limits; it is not being measured. Nine corpus entries were
    classified as sitting on a constitutive transition on that basis and
    never had a tangent verified.

    The rule is the one :func:`umat_oti.abaqus.compare.compare_histories`
    already applies to the error it reports, for the same reason and with the
    same constant: a component that is a vanishing fraction of the response
    holds each build's rounding and nothing else, so it is left out rather
    than scored. A real kink is untouched -- its gap is the jump between two
    branch stiffnesses, which lives in the components that carry the
    stiffness, not in the ones that are zero.

    Returns ``None`` when no component was resolvable, so a step with nothing
    to say is absent from the sweep rather than present as a zero.
    """
    middles = []
    for _component, forward_slope, backward_slope in one_sided:
        middles.extend(abs(f + b) / 2.0
                       for f, b in zip(forward_slope, backward_slope))
    if not middles:
        return None
    largest = max(middles)
    floor = largest * max(0.0, float(near_zero_fraction))
    worst = 0.0
    scored = 0
    for _component, forward_slope, backward_slope in one_sided:
        for f, b in zip(forward_slope, backward_slope):
            middle = abs(f + b) / 2.0
            if middle <= 0.0 or middle <= floor:
                continue
            scored += 1
            if abs(f - b) <= floor:
                # The disagreement is below the resolution of the matrix it
                # belongs to. That is agreement, not an absent measurement.
                continue
            worst = max(worst, abs(f - b) / middle)
    return worst if scored else None


def _as_the_solver_defines_it(matrix, stress, ndi: int, *, correct: bool):
    """A difference of stresses, raised to the Jacobian the solver asked for.

    Under ``nlgeom`` the quantity Abaqus calls DDSDDE is not ``d sigma / d
    eps``; it is that plus ``sigma_ij delta_kl``, because the rate it is
    defined on is the Jaumann rate of the Kirchhoff stress divided by J. A
    reference that stops at the stress derivative is a different matrix, and
    the difference is not small -- see
    :mod:`umat_oti.validation.finite_strain_tangent`, which carries the
    measurement.

    ``correct`` is False when the perturbation could not be pushed forward
    through the deformation gradient, because half a correction is worse than
    none: it would move the reference away from BOTH definitions.
    """
    if not correct:
        return [list(row) for row in matrix]
    from umat_oti.validation.finite_strain_tangent import kirchhoff_correction
    return kirchhoff_correction(matrix, stress, ndi)


def difference_tangent(build: ReplayBuild, work_dir: Path, ntens: int,
                       steps: Sequence[float], *, scale: float = 1.0,
                       components: Sequence[int] = (),
                       transformed_source: Optional[Path] = None,
                       near_zero_fraction: float = 1e-8,
                       exact: bool = False,
                       ) -> DifferenceSweep:
    """The tangent by centred differences, one column per strain component.

    ``steps`` are relative to ``scale``, the size of the strain increment being
    perturbed, so the same sweep means the same thing for a model loaded to a
    strain of a percent and one loaded to a strain of a millionth.

    WHICH input is perturbed is read from the transformed file, through the
    same ``seeded_kinematics`` map the transform seeded. Perturbing DSTRAN on a
    source whose kinematic input is the deformation gradient moves nothing at
    all: the stress is unchanged, the centred difference is identically zero,
    and the comparison then reports a relative error of exactly 1 at every step
    size. Measured on all ten finite-strain sources that had already agreed on
    their primal histories in Abaqus -- 2.96e+08 absolute error, unchanged from
    a step of 1e-3 to one of 1e-6, which is what a difference that is not a
    difference looks like.

    The seed map says which DIRECTION to move. It does not say what DDSDDE is a
    derivative of, and it used to be read as though it did: the seed adds its
    direction straight onto DFGRD1, the reference added the same thing onto
    DFGRD1, and the two then agreed about a matrix that was not the one the
    solver had asked for. A reference that shares the value-under-test's
    definition of its own input cannot falsify that definition, and for the ten
    gradient-driven corpus rows it did not.

    So the direction comes from the seed and the DEFINITION comes from Abaqus:
    the perturbation is pushed forward as ``dF = eps . F`` and the assembled
    difference carries the Kirchhoff term ``sigma_ij delta_kl``. Both are
    measured in :mod:`umat_oti.validation.finite_strain_tangent`; together they
    reproduce Trachea.for's own analytic DDSDDE to 2.40e-06 on its worst
    component, where the uncorrected reference sat at 3.000 and did not move
    across four decades of step size.

    The uncorrected difference is not thrown away -- it is kept in
    ``seed_map_matrices``, because the gap between the two is the measurement
    of what the seed map differentiates.
    """
    sweep = DifferenceSweep()
    # Resolved first: which input the perturbation moves is a property of the
    # source, and a caller reading a failed sweep still needs to know it.
    drive = None
    if transformed_source is not None:
        try:
            from umat_oti.transform.source_transform import seeded_kinematics
            drive = seeded_kinematics(
                Path(transformed_source).read_text(errors="replace"))
        except Exception:                      # noqa: BLE001 - fall back below
            drive = None
    gradient_driven = bool(drive is not None and drive.drives_deformation_gradient)
    sweep.driven_through = ("deformation gradient" if gradient_driven
                            else "strain increment")

    if not build.ok:
        sweep.reason = build.reason
        return sweep

    # The state the increment is replayed from, read back out of the file the
    # driver reads. A gradient-driven reference needs F to know what a strain
    # increment IS at this state, and NDI to know which Voigt columns carry a
    # trace. Absent, the correction is not applied and the reference says so
    # rather than applying it to an identity it invented.
    state = read_state(Path(work_dir) / STATE_FILE)
    base_gradient = state.get("DFGRD1") if gradient_driven else None
    ndi = int(state.get("NDI") or max(ntens - 3, 0) or 3)
    if gradient_driven and base_gradient is None:
        sweep.failures.append(
            "the state file carried no deformation gradient, so the "
            "perturbation could not be pushed forward and the Kirchhoff term "
            "could not be added; the reference is the seed-map difference")
    sweep.reference_definition = (
        "d STRESS / d DSTRAN" if not gradient_driven
        else ("d STRESS / d eps with dF = eps.F, plus sigma_ij delta_kl "
              "(the Jacobian Abaqus defines under nlgeom)"
              if base_gradient is not None
              else "d STRESS / d (additive DFGRD1 seed) -- uncorrected"))

    unperturbed, complaint = run_replay(build, work_dir, 0, 0.0, exact=exact)
    if not unperturbed:
        sweep.reason = f"the unperturbed replay produced no stress: {complaint}"
        return sweep
    sweep.unperturbed = [float(v) for v in unperturbed]
    # The author's own tangent at the same state, from the same run.
    _stress, sweep.original_tangent = parse_replay_output(
        Path(work_dir) / "otis_replay_out.txt")

    wanted = tuple(components) or tuple(range(1, ntens + 1))
    for relative in steps:
        step = relative * scale
        columns: list[list[float]] = []
        one_sided: list[tuple[int, list[float], list[float]]] = []
        for component in wanted:
            if gradient_driven:
                from umat_oti.validation.finite_strain_tangent import (
                    corotational_perturbation)
                terms = drive.dfgrd1.get(component, ())
                forward = corotational_perturbation(terms, step, base_gradient)
                backward = corotational_perturbation(terms, -step, base_gradient)
                if not any(forward):
                    # The seed map has no term for this direction, so there is
                    # no perturbation to make and no column to report. Skipped
                    # rather than reported as a column of zeros, which would
                    # read as "the stress does not depend on this component".
                    sweep.failures.append(
                        f"step {relative:g}, component {component}: the seeded "
                        f"map carries no deformation-gradient term for this "
                        f"direction, so no perturbation could be made")
                    columns = []
                    break
                plus, first = run_replay(build, work_dir, 0, 0.0,
                                         gradient=forward, exact=exact)
                minus, second = run_replay(build, work_dir, 0, 0.0,
                                           gradient=backward, exact=exact)
            else:
                plus, first = run_replay(build, work_dir, component, step, exact=exact)
                minus, second = run_replay(build, work_dir, component, -step, exact=exact)
            if not plus or not minus:
                sweep.failures.append(
                    f"step {relative:g}, component {component}: "
                    f"{first or second}")
                columns = []
                break
            # The centred difference, and the two one-sided differences it is
            # made of. A centred difference cannot tell whether its two
            # evaluations sat on the same constitutive branch: at a yield
            # point, damage onset or any other kink, the forward step is on
            # one branch and the backward step on the other, and their average
            # is the slope of a chord across the kink -- a number that is not
            # a derivative of anything and that no step size makes converge.
            #
            # The unperturbed value is the third point that makes the question
            # answerable. Where the response is smooth the forward and
            # backward slopes agree with each other to first order in the
            # step; where a branch changes between them they do not, whatever
            # the step. Recording both lets the caller say "this state sits on
            # a transition" instead of "the transform's tangent is wrong".
            # Differences taken before rounding: exact for a quad replay's
            # Decimal outputs, the same float arithmetic as before otherwise.
            centred = [float(a - b) / (2.0 * step) for a, b in zip(plus, minus)]
            columns.append(centred)
            if unperturbed:
                one_sided.append((
                    component,
                    [float(a - u) / step for a, u in zip(plus, unperturbed)],
                    [float(u - b) / step for u, b in zip(unperturbed, minus)]))
        if not columns:
            continue
        # columns[j][i] is d STRESS(i) / d DSTRAN(j); the tangent is its
        # transpose, because DDSDDE(i,j) is indexed the other way round.
        raw = [[columns[j][i] for j in range(len(columns))]
               for i in range(ntens)]
        sweep.seed_map_matrices[relative] = raw
        sweep.matrices[relative] = _as_the_solver_defines_it(
            raw, sweep.unperturbed, ndi, correct=base_gradient is not None)
        if len(one_sided) == len(columns):
            sweep.forward[relative] = _as_the_solver_defines_it(
                [[one_sided[j][1][i] for j in range(len(one_sided))]
                 for i in range(ntens)],
                sweep.unperturbed, ndi, correct=base_gradient is not None)
            sweep.backward[relative] = _as_the_solver_defines_it(
                [[one_sided[j][2][i] for j in range(len(one_sided))]
                 for i in range(ntens)],
                sweep.unperturbed, ndi, correct=base_gradient is not None)

        # How far the two one-sided slopes are from each other, measured
        # against the centred slope they average to. A kink between the two
        # perturbations shows here and nowhere else: the centred difference
        # itself looks perfectly well-behaved, because a chord across a corner
        # is a number like any other.
        gap = one_sided_gap(one_sided, near_zero_fraction)
        if gap is not None:
            sweep.smoothness[relative] = gap

    sweep.ok = bool(sweep.matrices)
    if not sweep.ok and not sweep.reason:
        sweep.reason = "no step size produced a complete set of columns"
    return sweep


# ---------------------------------------------------------------------------
# Routine-level replay of a WHOLE recorded history (primal gate, part a)
# ---------------------------------------------------------------------------
#
# Why this exists. Comparing the Abaqus histories of the original and the
# transformed build is not a comparison of the two routines: the transformed
# build returns a different DDSDDE (the OTI tangent instead of the author's),
# and the converged FE solution depends on it -- through the Newton path at
# default tolerances, and, on hybrid elements, even at a tight tolerance.
# Measured on From-2D-to-2D-Axe.for (C3D8H, corpus_campaign/batches/B2/curie_g,
# jobs cc_cug_02/03/06/08): with residuals driven to 2e-13 the two builds still
# differed by 3.2e-6; scaling the author's DDSDDE by 1+1e-6 moved the answer by
# 1.2e-12; giving the author's DDSDDE the transformed one's structure (the
# -2/3 sigma' coupling term) reproduced the transformed Abaqus run to 1.6e-12.
# Meanwhile every converged call, replayed offline with the SAME arguments in
# both builds, agreed to 2 stiffness ulps.
#
# So the routine is compared where only the routine can differ: each converged
# call the original's solver made is replayed, in record order and in one
# process, in both builds, from the arguments the probe recorded.

#: Where the history driver reads its calls and writes what each returned.
HISTORY_STATES = "otis_history_states.txt"
HISTORY_OUT = "otis_history_out.txt"

#: The D-12 uninitialised-variable init builds. THE single definition:
#: umat_oti.corpus_features.harness imports these (tested), so the
#: routine-level gate of corpus_features and this Abaqus path mean the same
#: thing by "undefined_in_original". An output that differs between ANY two of
#: the builds is undefined_in_original.
#:
#: Why three (Vera B2 item 2): zero vs snan alone misses an uninitialised value
#: used through a NaN guard (``IF (X.NE.X) X=0`` maps snan back to 0), a comparison
#: (``IF (X.GT.0.5)`` is false for 0 and for NaN alike) and every INTEGER
#: (0 and -77777 are both <= 0). The third build sets reals to +inf, integers
#: to +77777 and logicals to the opposite of the zero build, which separates
#: all three (measured on Vera's toys b2/b4b/b4c; the clean toy is unchanged).
FINIT_SNAN = ("-finit-real=snan", "-finit-integer=-77777", "-finit-logical=true")
FINIT_ZERO = ("-finit-real=zero", "-finit-integer=0", "-finit-logical=false")
FINIT_HUGE = ("-finit-real=inf", "-finit-integer=77777", "-finit-logical=true")
#: (label, flags) of every init build; the first is the reference build.
FINIT_BUILDS = (("zero", FINIT_ZERO), ("snan", FINIT_SNAN), ("inf", FINIT_HUGE))

#: gfortran flags for the init-variant builds. -O0 so the compiler cannot
#: fold an uninitialised read away; -cpp/-D because Abaqus compiles with -fpp.
GFORTRAN_HISTORY_FLAGS = ("-O0", "-std=legacy", "-w", "-fno-range-check",
                          "-ffixed-line-length-132", "-ffree-line-length-none",
                          "-cpp", "-DABQ_LNX86_64", "-DABQ_FORTRAN")

#: Slots allocated past NSTATV and filled with a sentinel, so a routine that
#: writes beyond its own *DEPVAR is seen doing it instead of corrupting the
#: heap silently.
STATEV_GUARD = 64
_SENTINEL = "-7.77D77"

_HISTORY_DRIVER = """PROGRAM otis_history
! Replays every recorded UMAT call of one history, in order, in one process.
! Each call gets exactly the arguments the probe recorded for it; nothing is
! perturbed and nothing is initialised that the solver did not initialise.
  IMPLICIT NONE
  INTEGER :: NTENS,NSTATV,NPROPS,NDI,NSHR,I,J,U,V,NCALL,IC,NOOB
  REAL(8) :: DTIME,TEMP,DTEMP,PNEWDT,CELENT,SSE,SPD,SCD,RPL,DRPLDT
  REAL(8), ALLOCATABLE :: STRESS(:),STATEV(:),DDSDDE(:,:),STRAN(:),DSTRAN(:)
  REAL(8), ALLOCATABLE :: PROPS(:),DDSDDT(:),DRPLDE(:)
  REAL(8) :: TIME(2),PREDEF(1),DPRED(1),COORDS(3),DROT(3,3)
  REAL(8) :: DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NOEL,NPT,LAYER,KSPT,KSTEP,KINC
  CHARACTER(80) :: CMNAME
  OPEN(NEWUNIT=U,FILE='%(states)s',STATUS='OLD',ACTION='READ')
  OPEN(NEWUNIT=V,FILE='%(out)s',STATUS='REPLACE',ACTION='WRITE')
  READ(U,*) NCALL
  DO IC=1,NCALL
  READ(U,*) NTENS,NSTATV,NPROPS,NDI,NSHR
  ALLOCATE(STRESS(NTENS),STATEV(MAX(NSTATV,1)+%(guard)d),DDSDDE(NTENS,NTENS))
  ALLOCATE(STRAN(NTENS),DSTRAN(NTENS),PROPS(MAX(NPROPS,1)))
  ALLOCATE(DDSDDT(NTENS),DRPLDE(NTENS))
  STATEV = %(sentinel)s
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
  DDSDDE=0.0_8; SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8
  DDSDDT=0.0_8; DRPLDE=0.0_8; DRPLDT=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PNEWDT=1.0_8; LAYER=1; KSPT=1; CMNAME='%(name)s'
  CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
    STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
    NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
    NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
  NOOB = COUNT(STATEV(MAX(NSTATV,1)+1:) .NE. %(sentinel)s)
  WRITE(V,'(A,I0,1X,I0,1X,I0,1X,I0)') 'CALL ',IC,NTENS,MAX(NSTATV,1),NOOB
  WRITE(V,'(ES26.17E3)') (STRESS(I),I=1,NTENS)
  WRITE(V,'(ES26.17E3)') (STATEV(I),I=1,MAX(NSTATV,1))
  WRITE(V,'(ES26.17E3)') ((DDSDDE(I,J),J=1,NTENS),I=1,NTENS)
  FLUSH(V)
  DEALLOCATE(STRESS,STATEV,DDSDDE,STRAN,DSTRAN,PROPS,DDSDDT,DRPLDE)
  END DO
  CLOSE(U); CLOSE(V)
END PROGRAM otis_history
"""


@dataclass
class HistoryBuild:
    """One compiled history replay, or the reason there is none."""

    label: str = ""
    program: Optional[Path] = None
    compiler: str = ""
    flags: tuple = ()
    ok: bool = False
    reason: str = ""
    log: str = ""

    def as_dict(self) -> dict:
        return {"label": self.label, "compiler": self.compiler,
                "flags": list(self.flags), "ok": self.ok,
                "reason": self.reason, "log": self.log[-1500:]}


@dataclass
class HistoryReplay:
    """What each replayed call returned, in record order."""

    label: str = ""
    ok: bool = False
    reason: str = ""
    #: One dict per call: STRESS, STATEV, DDSDDE (flat, row-major as the probe
    #: writes it) and how many guard slots past NSTATV the call wrote.
    calls: list = field(default_factory=list)
    returncode: Optional[int] = None
    tail: str = ""

    @property
    def writes_beyond_nstatv(self) -> int:
        return max((c.get("guard_writes", 0) for c in self.calls), default=0)

    def as_dict(self) -> dict:
        return {"label": self.label, "ok": self.ok, "reason": self.reason,
                "calls": len(self.calls), "returncode": self.returncode,
                "writes_beyond_nstatv": self.writes_beyond_nstatv,
                "tail": self.tail[-800:]}


def write_history_states(entries: Sequence[dict], path: Path) -> None:
    """Every ENTRY record, in the format :func:`write_state` writes one."""
    import tempfile
    parts = [str(len(entries))]
    with tempfile.TemporaryDirectory() as scratch:
        one = Path(scratch) / "one.txt"
        for entry in entries:
            write_state(entry, one)
            parts.append(one.read_text(encoding="utf-8").rstrip("\n"))
    Path(path).write_text("\n".join(parts) + "\n", encoding="utf-8")


def build_history_replay(source: Path, work_dir: Path, *, label: str,
                         compiler: str = "ifort", flags: Sequence[str] = (),
                         objects: Sequence[Path] = (),
                         module_dirs: Sequence[Path] = (),
                         include_dirs: Sequence[Path] = (),
                         name: str = "REPLAY",
                         timeout: int = 900) -> HistoryBuild:
    """Compile the history driver against one UMAT source.

    ``source`` should be the file the Abaqus job itself compiled (its
    ``<job>_probed`` copy): console writes already silenced, data-file paths
    already staged. Its probe calls write to ``$OTIS_PROBE_FILE``, which the
    runner points at /dev/null.
    """
    from umat_oti.abaqus import single_call

    built = HistoryBuild(label=label, compiler=compiler, flags=tuple(flags))
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which(compiler) is None:
        built.reason = f"{compiler} is not on PATH"
        return built
    text = _text_of(Path(source))
    if not text:
        built.reason = f"{source} could not be read"
        return built
    form = detect_source_form(Path(source), text)
    cleaned, removed = without_the_authors_program(text, form)
    unit = Path(source)
    if removed:
        unit = work_dir / f"noprogram_{Path(source).name}"
        unit.write_text(cleaned, encoding="utf-8")
    stubs = single_call.driver_source(name, text).split(
        "END PROGRAM otis_single_call", 1)[1]
    driver = work_dir / "otis_history.f90"
    driver.write_text(_HISTORY_DRIVER % {
        "states": HISTORY_STATES, "out": HISTORY_OUT,
        "name": name.upper()[:60], "guard": STATEV_GUARD,
        "sentinel": _SENTINEL} + stubs, encoding="utf-8")
    single_call.install_headers(work_dir)
    includes = ([f"-I{work_dir}"] + [f"-I{Path(d)}" for d in include_dirs]
                + [f"-I{Path(d)}" for d in module_dirs])
    program = work_dir / "otis_history"
    if compiler == "gfortran":
        # The unit and the driver are compiled apart: the init flags belong to
        # the author's code, and the free-form driver must not inherit the
        # fixed-form line length.
        steps = [[compiler, *flags, *includes, "-c", str(unit), "-o",
                  str(work_dir / "unit.o")],
                 [compiler, "-O0", *includes, "-c", str(driver), "-o",
                  str(work_dir / "driver.o")],
                 [compiler, str(work_dir / "unit.o"), *map(str, objects),
                  str(work_dir / "driver.o"), "-o", str(program)]]
    else:
        steps = [[compiler, *flags, *includes, str(unit), *map(str, objects),
                  str(driver), "-o", str(program)]]
    log = ""
    for command in steps:
        try:
            done = subprocess.run(command, cwd=str(work_dir), capture_output=True,
                                  text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            built.reason = f"{type(error).__name__}: {error}"
            return built
        log += done.stdout + done.stderr
        if done.returncode != 0:
            built.reason = (f"the history driver did not build against "
                            f"{Path(source).name} ({label}, exit {done.returncode})")
            built.log = log
            return built
    built.program, built.ok, built.log = program, program.is_file(), log
    if not built.ok:
        built.reason = "the link produced no program"
    return built


def parse_history_output(path: Path) -> list[dict]:
    """The calls a history replay wrote, NaN and Inf read as such."""
    calls: list[dict] = []
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return calls
    index = 0
    while index < len(lines):
        head = lines[index].split()
        if not head or head[0] != "CALL":
            index += 1
            continue
        ntens, nstatv, guard = int(head[2]), int(head[3]), int(head[4])
        need = ntens + nstatv + ntens * ntens
        values = lines[index + 1:index + 1 + need]
        if len(values) < need:
            break                          # a call that died mid-write
        numbers = [float(v.replace("D", "E")) for v in values]
        calls.append({"STRESS": numbers[:ntens],
                      "STATEV": numbers[ntens:ntens + nstatv],
                      "DDSDDE": numbers[ntens + nstatv:need],
                      "guard_writes": guard})
        index += 1 + need
    return calls


def run_history_replay(build: HistoryBuild, entries: Sequence[dict],
                       work_dir: Path, timeout: int = 900) -> HistoryReplay:
    """Run every recorded call through one build."""
    import os
    outcome = HistoryReplay(label=build.label)
    if not build.ok or build.program is None:
        outcome.reason = build.reason or "no program"
        return outcome
    work_dir = Path(work_dir)
    write_history_states(entries, work_dir / HISTORY_STATES)
    out = work_dir / HISTORY_OUT
    if out.exists():
        out.unlink()
    env = dict(os.environ, OTIS_PROBE_FILE=os.devnull,
               FOR_DISABLE_STACK_TRACE="1")
    try:
        done = subprocess.run([str(build.program)], cwd=str(work_dir),
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        outcome.reason = f"{type(error).__name__}: {error}"
        return outcome
    outcome.returncode = done.returncode
    outcome.tail = (done.stdout + done.stderr)[-2000:]
    outcome.calls = parse_history_output(out)
    outcome.ok = done.returncode == 0 and len(outcome.calls) == len(entries)
    if not outcome.ok:
        outcome.reason = (f"{build.label}: {len(outcome.calls)} of "
                          f"{len(entries)} calls replayed (exit "
                          f"{done.returncode}): {outcome.tail[-300:].strip()}")
    return outcome


def _bits_differ(a: float, b: float) -> bool:
    return not (a == b or (a != a and b != b))


def undefined_outputs(zero: Sequence[dict], snan: Sequence[dict],
                      ntens: int, *, into: Optional[dict] = None,
                      variant: str = "snan") -> dict:
    """D-12: outputs of the ORIGINAL that differ between zero- and snan-init.

    Returns ``{"STRESS": [...], "STATEV": [...], "DDSDDE": [...],
    "details": [...]}`` with one-based component numbers. Those outputs are
    ``undefined_in_original`` -- a SOURCE defect, never compared, never
    verified. Every other output was bit-identical across the two builds over
    the whole history, which is the evidence it does not depend on the
    undefined value. ``into`` accumulates over several init builds (every
    build of :data:`FINIT_BUILDS` against the zero build); ``snan_init`` in a
    detail is then the value of the build named by ``init_variant``.
    """
    found: dict = into if into is not None else {"STRESS": [], "STATEV": [], "DDSDDE": [],
                                                 "details": []}
    for index, (a, b) in enumerate(zip(zero, snan)):
        for name in ("STRESS", "STATEV", "DDSDDE"):
            for k, (x, y) in enumerate(zip(a.get(name) or (), b.get(name) or ()),
                                       start=1):
                if _bits_differ(x, y) and k not in found[name]:
                    found[name].append(k)
                    label = (f"DDSDDE({(k - 1) // ntens + 1},{(k - 1) % ntens + 1})"
                             if name == "DDSDDE" else f"{name}({k})")
                    found["details"].append({
                        "output": label, "first_call": index,
                        "zero_init": x if x == x else "nan",
                        "snan_init": y if y == y else "nan",
                        "init_variant": variant})
    for name in ("STRESS", "STATEV", "DDSDDE"):
        found[name].sort()
    return found


# ---------------------------------------------------------------------------
# The Jacobian-matched control build (primal gate, part b)
# ---------------------------------------------------------------------------

_JM_FIXED = """
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
C     OTIS JACOBIAN-MATCHED CONTROL. STRESS, STATEV, energies and PNEWDT
C     come from the ORIGINAL routine (UMATO). DDSDDE comes from the
C     TRANSFORMED routine (UMATT), called first on private copies of every
C     argument it may write, so it cannot touch what UMATO is handed. The
C     solver is steered exactly as in the transformed run; nothing the
C     original computes is replaced except the Jacobian.
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION OTSJ_S(NTENS),OTSJ_V(NSTATV),OTSJ_D(NTENS,NTENS),
     1 OTSJ_DT(NTENS),OTSJ_DR(NTENS),OTSJ_ST(NTENS),OTSJ_DS(NTENS),
     2 OTSJ_F0(3,3),OTSJ_F1(3,3),OTSJ_P(NPROPS),OTSJ_C(3),OTSJ_R(3,3),
     3 OTSJ_TM(2)
      OTSJ_S = STRESS
      OTSJ_V = STATEV
      OTSJ_D = 0.D0
      OTSJ_DT = DDSDDT
      OTSJ_DR = DRPLDE
      OTSJ_ST = STRAN
      OTSJ_DS = DSTRAN
      OTSJ_F0 = DFGRD0
      OTSJ_F1 = DFGRD1
      OTSJ_P = PROPS
      OTSJ_C = COORDS
      OTSJ_R = DROT
      OTSJ_TM = TIME
      OTSJSE = SSE
      OTSJSP = SPD
      OTSJSC = SCD
      OTSJRP = RPL
      OTSJRT = DRPLDT
      OTSJPN = PNEWDT
      OTSJCE = CELENT
      OTSJDT = DTIME
      OTSJTP = TEMP
      OTSJDP = DTEMP
      CALL UMATT(OTSJ_S,OTSJ_V,OTSJ_D,OTSJSE,OTSJSP,OTSJSC,OTSJRP,
     1 OTSJ_DT,OTSJ_DR,OTSJRT,OTSJ_ST,OTSJ_DS,OTSJ_TM,OTSJDT,OTSJTP,
     2 OTSJDP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,OTSJ_P,NPROPS,
     3 OTSJ_C,OTSJ_R,OTSJPN,OTSJCE,OTSJ_F0,OTSJ_F1,NOEL,NPT,LAYER,KSPT,
     4 KSTEP,KINC)
      CALL UMATO(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1 DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     2 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,
     3 DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      DDSDDE = OTSJ_D
      RETURN
      END
"""


def _free_form(fixed: str) -> str:
    """The wrapper above in free form: comments with '!' and '&' continuation."""
    out: list[str] = []
    for line in fixed.splitlines():
        if line and line[0] in "Cc":
            out.append("!" + line[1:])
        elif len(line) > 5 and line[5] not in " " and line[:5].strip() == "":
            out[-1] = out[-1] + " &"
            out.append("      " + line[6:])
        else:
            out.append(line)
    return "\n".join(out) + "\n"


_UNIT_HEADER = re.compile(
    r"(?im)^([ \t]*(?:\d+[ \t]+)?(?:(?:RECURSIVE|PURE|ELEMENTAL)[ \t]+)*"
    r"(?:(?:DOUBLE[ \t]+PRECISION|REAL|INTEGER|LOGICAL|COMPLEX|CHARACTER)"
    r"(?:[ \t]*\*[ \t]*\d+|[ \t]*\([^)\n]*\))?[ \t]+)?"
    r"(?:SUBROUTINE|FUNCTION)[ \t]+)(\w+)")


def _defined_units(text: str) -> set:
    names = set()
    for line in text.splitlines():
        if line[:1] in "cC*!" or line.lstrip().startswith("!"):
            continue
        match = _UNIT_HEADER.match(line)
        if match:
            names.add(match.group(2).upper())
    return names


_MODULE_HEADER = re.compile(r"^[ \t]*(?:\d+[ \t]+)?MODULE[ \t]+(?!PROCEDURE\b)(\w+)[ \t]*$",
                           re.IGNORECASE)
_MODULE_END = re.compile(r"^[ \t]*(?:\d+[ \t]+)?END[ \t]*MODULE\b.*$", re.IGNORECASE)


def _module_blocks(text: str, free: bool) -> dict:
    """Each ``MODULE name`` ... ``END MODULE`` block: {NAME: (first, last)}
    line indices (0-based, inclusive). Comments are skipped; a module is not
    nested, so the first END MODULE closes it."""
    blocks: dict = {}
    start = None
    name = ""
    for index, line in enumerate(text.splitlines()):
        stripped = line.rstrip()
        if _is_comment(stripped, free):
            continue
        if start is None:
            found = _MODULE_HEADER.match(stripped)
            if found:
                start, name = index, found.group(1).upper()
        elif _MODULE_END.match(stripped):
            blocks[name] = (start, index)
            start = None
    return blocks


def _normal(lines: Sequence[str], free: bool) -> list:
    """The statements of a block with comments, blanks and case removed."""
    out = []
    for line in lines:
        if _is_comment(line, free):
            continue
        body = " ".join(line.split()).lower()
        if body:
            out.append(body)
    return out


_TYPE_DECLARATION = re.compile(
    r"^(?:integer|real|double\s+precision|logical|complex|character|type\s*\()", re.IGNORECASE)


def _statements(lines: Sequence[str], free: bool) -> list:
    """The statements of a block, continuation lines joined, comments gone."""
    out: list = []
    pending = ""
    for line in lines:
        if _is_comment(line, free):
            continue
        body = line.split("!")[0] if free else line
        if free:
            joined = pending + body.strip()
            if joined.endswith("&"):
                pending = joined[:-1].rstrip() + " "
                continue
            pending = ""
            out.append(joined.strip())
        else:
            if len(body) > 5 and body[5] not in " 0" and out and not pending:
                out[-1] += " " + body[6:].strip()
            else:
                out.append(body[6:].strip() if len(body) > 6 else body.strip())
    return [" ".join(x.split()) for x in out if x.strip()]


def module_holds_only_constants(lines: Sequence[str], free: bool) -> bool:
    """A module whose every declaration is a PARAMETER (or a type, implicit,
    use, public or private statement) and which assigns nothing and holds no
    procedures: a second copy of it cannot carry a different state, so the
    first copy can serve both. A module with a variable, an assignment or a
    CONTAINS is shared STATE or behaviour, and is never dropped."""
    for statement in _statements(lines, free):
        low = statement.lower()
        if re.match(r"^(module\s+\w+|end\s*module\b.*|implicit\s+none|use\s+.*|"
                    r"public\b.*|private\b.*)$", low):
            continue
        if re.match(r"^parameter\s*\(", low):
            continue
        if _TYPE_DECLARATION.match(low):
            head = low.split("::")[0] if "::" in low else low.split("=")[0]
            if re.search(r"\bparameter\b", head):
                continue
            return False
        return False                                # an assignment, CONTAINS, SAVE, ...
    return True


def drop_shared_modules(original_text: str, transformed_text: str,
                        free: bool) -> tuple[str, dict]:
    """The transformed copy without the modules the original copy defines.

    The Jacobian-matched bundle holds both copies of the author's file in one
    compilation, and a module defined in both is "Declaration of module
    'NUMKIND' conflicts with a previous declaration" -- the bundle does not
    compile, and the row was recorded as a primal disagreement
    (AlexanderJFDR NeoHookean_umat, pass22). The original's module comes first
    in the file, so the transformed routines still find it. A module is dropped
    only when its statements are the same text, comments aside; one that
    differs is kept and named, because dropping it would change what the
    transformed copy computes -- the bundle then fails to build, and says why.
    """
    own = _module_blocks(original_text, free)
    other = _module_blocks(transformed_text, free)
    lines = transformed_text.splitlines()
    original_lines = original_text.splitlines()
    marker = "!" if free else "C"
    dropped, differing, stateful = [], [], []
    for name, (first, last) in sorted(other.items(), key=lambda kv: -kv[1][0]):
        if name not in own:
            continue
        mine = own[name]
        if _normal(original_lines[mine[0]:mine[1] + 1], free) != \
                _normal(lines[first:last + 1], free):
            differing.append(name)
            continue
        if not module_holds_only_constants(lines[first:last + 1], free):
            # identical text, but it holds state or procedures: two copies in one
            # compilation is a conflict that cannot be resolved by dropping one
            stateful.append(name)
            continue
        for index in range(first, last + 1):
            lines[index] = f"{marker}     OTIS-REMOVED (module {name} is the original copy's): " \
                           + lines[index].strip()
        dropped.append(name)
    text = "\n".join(lines) + ("\n" if transformed_text.endswith("\n") else "")
    return text, {"modules_dropped_from_the_transformed_copy": sorted(dropped),
                  "modules_that_differ": sorted(differing),
                  "modules_kept_because_not_constants_only": sorted(stateful),
                  "modules_dropped_hold_only_constants": True}


def jacobian_matched_source(original_text: str, transformed_text: str,
                            form: str = "fixed") -> tuple[str, dict]:
    """One source Abaqus can compile: the original as UMATO, the transformed
    as UMATT, and a UMAT that takes STRESS/STATEV from the first and DDSDDE
    from the second.

    Every other unit the transformed file defines that the original also
    defines (helpers, DLOAD, SDVINI, ...) is renamed with a ``_T`` suffix in
    the transformed copy, so each routine keeps calling its own helpers. The
    ORIGINAL's units keep their names: SDVINI and every other Abaqus entry
    point the deck calls is the author's. COMMON blocks are left shared, which
    is what they are in a single Abaqus link of either build.

    Both inputs must be un-instrumented; ``run_one`` instruments the result
    at its (single) UMAT, so the probe records what the solver actually got.
    """
    free = str(form).lower().startswith("free")
    renamed = {}
    original = original_text
    transformed = transformed_text
    for side, new in (("o", "UMATO"), ("t", "UMATT")):
        text = original if side == "o" else transformed
        text, count = re.subn(
            r"(?im)^([ \t]*(?:\d+[ \t]+)?SUBROUTINE[ \t]+)UMAT\b", r"\1" + new,
            text, count=1)
        text = re.sub(r"(?i)(END[ \t]*SUBROUTINE[ \t]+)UMAT\b", r"\1" + new, text)
        renamed[new] = count
        if side == "o":
            original = text
        else:
            transformed = text
    shared = (_defined_units(original) & _defined_units(transformed)) - {"UMATO", "UMATT"}
    for name in sorted(shared):
        transformed = re.sub(rf"(?i)\b{re.escape(name)}\b", name + "_T", transformed)
    # Two copies of one file in one compilation: a module defined in both, and
    # a main program (PROGRAM, or the bare END that closes an implicit one) in
    # both, are conflicting declarations. The transformed copy gives way.
    transformed, modules = drop_shared_modules(original, transformed, free)
    transformed, mains = without_the_authors_program(transformed, "free" if free else "fixed")
    wrapper = _free_form(_JM_FIXED) if free else _JM_FIXED
    note = {"renamed_in_transformed": sorted(f"{n}->{n}_T" for n in shared),
            "entry_renamed": renamed, "form": "free" if free else "fixed",
            **modules, "main_programs_dropped_from_the_transformed_copy": list(mains)}
    return original.rstrip("\n") + "\n\n" + transformed.rstrip("\n") + "\n" + wrapper, note
