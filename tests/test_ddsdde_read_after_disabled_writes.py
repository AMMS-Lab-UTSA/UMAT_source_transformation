"""A source may use DDSDDE as its own scratch array. Disabling the writes alone
turns the stress into an exact zero.

The transform comments out every assignment to DDSDDE inside an old-tangent
region -- correct, because DDSDDE is the tangent output and the transform
supplies it from the derivative. Four corpus entries write the *elastic
stiffness* into DDSDDE and then form the predictor stress from it:

    DO K1=1, NDI
      DO K2=1, NDI
        DDSDDE(K2, K1)=ELAM          <- commented out as OTIS-SKIP
      END DO
      DDSDDE(K1, K1)=EG2+ELAM        <- commented out as OTIS-SKIP
    END DO
    ...
    STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)   <- left reading DDSDDE

The caller has already zeroed DDSDDE, so the emitted program computed
STRESS = 0 in all six components and the tangent that GETIM read back off it
was zero too. The offline gate reported worst_relative of exactly 1.0 on
UEL8_PCOR, UEL8_PCLI_R, UEL9_PCOR and UEL9_PCLI_R -- a silent wrong answer, not
a crash, and the existing ``old_ddsdde_assignments_disabled`` check passed on
every one of them because it only ever looked at the writes.

Two behaviours are pinned here, and the second holds whether or not the first
one fires:

* the source's own scratch use survives -- the disabled writes are redirected
  into the DDSDDE shadow and the reads follow them there, so DDSDDE itself
  stays the transform's output;
* ``no_ddsdde_read_after_disabled_assignment`` refuses any file where a live
  statement still reads DDSDDE after a write to it was disabled. If the
  redirect ever stops covering a shape, the transform reports it instead of
  emitting a program that returns zero.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.transform.source_transform import (  # noqa: E402
    _no_ddsdde_read_after_disabled_assignment,
    transform_umat_to_oti_from_config,
)

#: ABA_PARAM.INC is supplied by Abaqus at build time; this is the stub the rest
#: of the project uses so gfortran can resolve the INCLUDE standalone.
ABA_PARAM = "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"

#: The shape of the four failing entries, reduced to what the defect needs: a
#: stress region before the tangent block (so the tangent block is not skipped
#: for being ahead of the stress path), the elastic stiffness written into
#: DDSDDE, the predictor stress read back out of it, and a hand-coded tangent
#: afterwards that the extraction replaces.
SCRATCH_DDSDDE_UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),
     2 PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      PARAMETER (ONE=1.D0, TWO=2.D0, THREE=3.D0)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      ELAM=(EBULK3-EG2)/THREE
      EQPLAS=STATEV(1)
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
      STATEV(1)=EQPLAS
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=ELAM*TWO
        END DO
      END DO
      RETURN
      END
"""

#: Same source, except the value the disabled writes store is itself computed
#: inside the disabled region. Redirecting those writes would execute them
#: against a name nothing assigns any more, so the repair must decline and the
#: transform must refuse rather than emit the zero.
UNRECOVERABLE_SCRATCH_UMAT = SCRATCH_DDSDDE_UMAT.replace(
    """      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=ELAM
        END DO""",
    """      DO K1=1,NDI
        BETA=ELAM
        DO K2=1,NDI
          DDSDDE(K2,K1)=BETA
        END DO""",
)

UMAT_ARGUMENTS = [
    "STRESS", "STATEV", "DDSDDE", "SSE", "SPD", "SCD", "RPL", "DDSDDT",
    "DRPLDE", "DRPLDT", "STRAN", "DSTRAN", "TIME", "DTIME", "TEMP", "DTEMP",
    "PREDEF", "DPRED", "CMNAME", "NDI", "NSHR", "NTENS", "NSTATV", "PROPS",
    "NPROPS", "COORDS", "DROT", "PNEWDT", "CELENT", "DFGRD0", "DFGRD1",
    "NOEL", "NPT", "LAYER", "KSPT", "KSTEP", "KINC",
]


def _line_of(source: str, needle: str, start: int = 1) -> int:
    lines = source.splitlines()
    for index in range(start - 1, len(lines)):
        if needle in lines[index]:
            return index + 1
    raise AssertionError(f"{needle!r} is not in the source")


def _region(source: str, region_id: str, start: int, end: int, role: str) -> dict:
    return {
        "region_id": region_id,
        "start_line": start,
        "end_line": end,
        "role": role,
        "classification": ("Main stress update, transform with OTIS"
                           if role == "transform_with_oti" else "Old tangent, replace"),
        "variables": ["DDSDDE"],
        "reason": "fixture",
        "preview": "\n".join(source.splitlines()[start - 1:end]),
    }


def _config(source: str) -> dict:
    """The contract shape that produced the four failing store entries: the
    elastic-stiffness block classified as an old-tangent output region rather
    than as keep-real setup the stress update needs."""
    state = _line_of(source, "EQPLAS=STATEV(1)")
    elastic_start = _line_of(source, "DO K1=1,NDI")
    elastic_end = _line_of(source, "DO K1=NDI+1,NTENS", elastic_start) + 2
    stress_start = _line_of(source, "DO K1=1,NTENS", elastic_end + 1)
    stress_end = stress_start + 4
    tangent_start = _line_of(source, "DO K1=1,NTENS", stress_end + 2)
    tangent_end = tangent_start + 4
    ddsdde_writes = [
        (index + 1, line.strip())
        for index, line in enumerate(source.splitlines())
        if re.match(r"^\s*DDSDDE\s*\(", line)
    ]
    return {
        "source": {"selected_umat_file": "scratch_ddsdde.for", "selected_umat_name": "UMAT"},
        "mapping": {
            "stress": "STRESS", "ddsdde": "DDSDDE", "dstran": "DSTRAN",
            "statev": "STATEV", "props": "PROPS", "stran": "STRAN",
            "ntens": "NTENS", "nstatv": "NSTATV", "nprops": "NPROPS",
        },
        "transformation_settings": {"ntens": 6, "order": 1},
        "transformation_review": {
            "ready_for_transformation": True,
            "seed_variables": ["DSTRAN"],
            "promoted_variables": ["STRESS", "STATEV", "EQPLAS"],
            "constant_variables": ["PROPS", "EMOD", "ENU", "EBULK3", "EG2", "EG",
                                   "ELAM", "BETA", "ONE", "TWO", "THREE", "STRAN"],
            "keep_real_variables": ["DDSDDE", "NTENS", "NDI", "K1", "K2",
                                    "NSTATV", "NPROPS"],
            "stress_update_regions_to_transform": [
                _region(source, "STRESS-000", state, state, "transform_with_oti"),
                _region(source, "STRESS-001", stress_start, stress_end, "transform_with_oti"),
            ],
            "old_tangent_regions_to_replace": [
                _region(source, "TANGENT-001", elastic_start, elastic_end, "ddsdde_output_replace"),
                _region(source, "TANGENT-002", tangent_start, tangent_end, "ddsdde_output_replace"),
            ],
            "shared_setup_regions_to_keep": [],
        },
        "analysis": {
            "form": "fixed",
            "assignments_to_ddsdde": [
                {"line_numbers": [number], "text": text} for number, text in ddsdde_writes
            ],
            "detected_umat_routines": [{"name": "UMAT", "arguments": UMAT_ARGUMENTS}],
        },
    }


def _transform(source: str, out_dir: Path):
    return transform_umat_to_oti_from_config(source, _config(source), out_dir, 6)


def _active_statements(text: str) -> list[str]:
    return [line for line in text.splitlines()
            if line.strip() and line[:1] not in {"C", "c", "*", "!"}]


# --------------------------------------------------------------------------
# The check, on its own. Every case here was a real emitted shape.
# --------------------------------------------------------------------------

class TestTheCheckSeesTheRead:
    def test_a_live_read_after_a_disabled_write_fails(self):
        """The exact defect: nine writes disabled, the read left behind."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE(K2,K1)*DSTRAN_OTI(K1)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert not _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_the_redirected_read_passes(self):
        """What the repair emits: the read follows the writes into the shadow."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      DDSDDE_OTI(K2,K1)=ELAM\n"
                "      STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE_OTI(K2,K1)*DSTRAN_OTI(K1)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_a_read_after_the_extraction_passes(self):
        """Past the extraction DDSDDE holds the derivative, so reading it is
        the intended thing -- a source that scales its own tangent afterwards
        must not be refused."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n"
                "      DDSDDE(I,J)=DDSDDE(I,J)*FAC\n")
        assert _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_no_disabled_write_means_nothing_to_report(self):
        text = ("      DDSDDE(K2,K1)=ELAM\n"
                "      STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE(K2,K1)*DSTRAN_OTI(K1)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_a_declaration_naming_ddsdde_is_not_a_read(self):
        """DIMENSION ... DDSDDE(NTENS,NTENS) mentions the name and reads
        nothing. Refusing on it would refuse every source in the corpus."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      DIMENSION STRESS(NTENS),DDSDDE(NTENS,NTENS)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_a_read_carried_on_a_continuation_line_is_seen(self):
        """Fixed-form continuations are joined first. The read that motivated
        this arrives split across two physical lines in two of the four
        sources, and a per-physical-line reader misses it."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      STRESS_OTI(K2)=STRESS_OTI(K2)+\n"
                "     1DDSDDE(K2,K1)*DSTRAN_OTI(K1)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert not _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_a_bare_write_inside_the_scratch_window_fails(self):
        """A statement that only WRITES DDSDDE while the shadow is the working
        store desynchronises the two, and the read rule cannot see it. Three
        sources scale the stiffness by damage in the middle of the window
        (CALL KSMULT(DDSDDE,...)); leaving that one statement on the array
        would put a different stiffness in each."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      DDSDDE_OTI(K2,K1)=ELAM\n"
                "      DDSDDE(OTI_HI,OTI_HJ)=DDSDDE_OTI(OTI_HI,OTI_HJ)*FAC\n"
                "      STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE_OTI(K2,K1)*DSTRAN_OTI(K1)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert not _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_the_array_is_free_again_past_the_last_shadow_use(self):
        """The window closes at the last use of the shadow. An inlined
        CALL KCLEAR(DDSDDE,...) after it -- UEL8_PCOR has one, ahead of its
        hand-coded tangent -- touches the output array, which the extraction
        overwrites, and must not be refused."""
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "      DDSDDE_OTI(K2,K1)=ELAM\n"
                "      STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE_OTI(K2,K1)*DSTRAN_OTI(K1)\n"
                "      DDSDDE(OTI_HI,OTI_HJ) = 0.0D0\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")

    def test_a_commented_read_is_not_a_read(self):
        text = ("C     OTIS-SKIP: DDSDDE(K2,K1)=ELAM\n"
                "C     OTIS-SKIP: STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)\n"
                "      DDSDDE(OTI_I,OTI_J) = GETIM(STRESS_OTI(OTI_I),OTI_J)\n")
        assert _no_ddsdde_read_after_disabled_assignment(text, "fixed", "DDSDDE")


# --------------------------------------------------------------------------
# The repair, through the transform.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def emitted(tmp_path_factory) -> str:
    result = _transform(SCRATCH_DDSDDE_UMAT, tmp_path_factory.mktemp("scratch"))
    assert result.success, result.warnings + result.blockers
    return result.transformed_source


class TestTheScratchUseSurvives:
    def test_the_predictor_no_longer_reads_the_output_array(self, emitted: str):
        """This is the failure itself: with DDSDDE zeroed by the caller, the
        predictor computed STRESS = 0 in all six components."""
        predictor = [line for line in _active_statements(emitted)
                     if "STRESS_OTI(K2)=STRESS_OTI(K2)" in line.replace(" ", "")]
        assert predictor, "the predictor stress statement was not emitted"
        assert all("DDSDDE_OTI" in line for line in predictor), predictor
        assert not any(re.search(r"\bDDSDDE\b", line) for line in predictor), predictor

    def test_the_disabled_writes_are_redirected_into_the_shadow(self, emitted: str):
        active = _active_statements(emitted)
        assert any("DDSDDE_OTI(K2,K1)=ELAM" in line.replace(" ", "") for line in active)
        assert any("DDSDDE_OTI(K1,K1)=EG2+ELAM" in line.replace(" ", "") for line in active)
        assert any("DDSDDE_OTI(K1,K1)=EG" in line.replace(" ", "") for line in active)

    def test_the_original_write_is_still_disabled(self, emitted: str):
        """The redirect adds a statement; it does not revive the old tangent.
        DDSDDE stays the transform's output, and the audit trail stays legible."""
        assert "OTIS-SKIP: DDSDDE(K2,K1)=ELAM" in emitted
        assert not any(re.match(r"\s*DDSDDE\s*\(\s*K2\s*,\s*K1\s*\)\s*=\s*ELAM",
                                line) for line in _active_statements(emitted))

    def test_the_shadow_is_declared_with_the_arrays_own_shape(self, emitted: str):
        assert re.search(r"TYPE\(ONUMM6N1\)\s*::\s*DDSDDE_OTI\(NTENS,\s*NTENS\)",
                         emitted), emitted

    def test_the_shadow_starts_from_what_the_caller_passed(self, emitted: str):
        """The source's scratch use relies on the entries it never writes being
        whatever the caller left there -- zero, for every Abaqus caller in the
        corpus. Copying reproduces that exactly rather than assuming it."""
        assert re.search(r"DDSDDE_OTI\(OTI_HI,\s*OTI_HJ\)\s*=\s*DDSDDE\(OTI_HI,\s*OTI_HJ\)",
                         emitted), emitted

    def test_the_extraction_still_writes_the_real_ddsdde(self, emitted: str):
        assert re.search(r"\bDDSDDE\(OTI_I,\s*OTI_J\)\s*=", emitted), emitted

    def test_both_ddsdde_checks_pass(self, tmp_path):
        result = _transform(SCRATCH_DDSDDE_UMAT, tmp_path)
        checks = result.report["semantic_checks"]
        assert checks["old_ddsdde_assignments_disabled"]
        assert checks["no_ddsdde_read_after_disabled_assignment"]


class TestWhatCannotBeRepairedIsRefused:
    """A silent zero is the worst failure mode after a nondeterministic one, so
    where the scratch cannot be recovered the transform reports it."""

    def test_the_transform_refuses_rather_than_emitting_the_zero(self, tmp_path):
        result = _transform(UNRECOVERABLE_SCRATCH_UMAT, tmp_path)
        assert not result.success
        assert not result.report["semantic_checks"]["no_ddsdde_read_after_disabled_assignment"]
        assert any("no_ddsdde_read_after_disabled_assignment" in warning
                   for warning in result.warnings), result.warnings


# --------------------------------------------------------------------------
# Numerical proof. Compiling is not verification; this runs the emitted UMAT.
# --------------------------------------------------------------------------

DRIVER = """PROGRAM scratch_driver
  IMPLICIT NONE
  INTEGER, PARAMETER :: NTENS=6, NSTATV=1, NPROPS=2
  REAL(8) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
  REAL(8) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
  REAL(8) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3)
  REAL(8) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3)
  INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,I,J
  CHARACTER(80) :: CMNAME
  STRESS=0.0_8; STATEV=0.0_8; DDSDDE=0.0_8; STRAN=0.0_8
  DSTRAN=(/1.0D-4,-2.0D-5,3.0D-5,4.0D-5,-5.0D-5,6.0D-5/)
  SSE=0.0_8; SPD=0.0_8; SCD=0.0_8; RPL=0.0_8; DDSDDT=0.0_8
  DRPLDE=0.0_8; DRPLDT=0.0_8; TIME=0.0_8; DTIME=1.0_8
  TEMP=293.15_8; DTEMP=0.0_8; PREDEF=0.0_8; DPRED=0.0_8
  PROPS(1)=210000.0_8; PROPS(2)=0.3_8
  COORDS=0.0_8; DROT=0.0_8; DFGRD0=0.0_8; DFGRD1=0.0_8
  DO I=1,3
    DROT(I,I)=1.0_8; DFGRD0(I,I)=1.0_8; DFGRD1(I,I)=1.0_8
  END DO
  PNEWDT=1.0_8; CELENT=1.0_8; CMNAME='SCRATCH'
  NDI=3; NSHR=3; NOEL=1; NPT=1; LAYER=1; KSPT=1; KSTEP=1; KINC=1
  CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
    STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR, &
    NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1, &
    NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
  DO I=1,NTENS
    WRITE(*,'(A,I0,ES24.16)') 'S',I,STRESS(I)
  END DO
  DO I=1,NTENS
    DO J=1,NTENS
      WRITE(*,'(A,I0,A,I0,ES24.16)') 'D',I,'_',J,DDSDDE(I,J)
    END DO
  END DO
END PROGRAM scratch_driver
"""


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(cwd), check=False,
                          capture_output=True, text=True, timeout=600)


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
def test_the_recovered_source_returns_the_elastic_answer(tmp_path):
    """The whole point of the repair, measured rather than inspected.

    Before it, this emitted file returned STRESS = 0 in all six components and
    DDSDDE = 0 in all thirty-six -- the store's worst_relative of exactly 1.0.
    After it, both match closed-form isotropic elasticity to round-off.
    """
    out = tmp_path / "out"
    result = _transform(SCRATCH_DDSDDE_UMAT, out)
    assert result.success, result.warnings + result.blockers
    for name in ("ABA_PARAM.INC", "aba_param.inc"):
        (out / name).write_text(ABA_PARAM, encoding="utf-8")
    (out / "driver.f90").write_text(DRIVER, encoding="utf-8")

    units = (out / "compile_order.txt").read_text(encoding="utf-8").split()
    for unit in units:
        flags = (["-ffixed-form", "-ffixed-line-length-none"] if unit.endswith(".for")
                 else ["-ffree-form", "-ffree-line-length-none"])
        built = _run(["gfortran", "-c", *flags, "-I.", unit], out)
        assert built.returncode == 0, built.stderr
    built = _run(["gfortran", "-c", "-ffree-form", "-I.", "driver.f90"], out)
    assert built.returncode == 0, built.stderr
    objects = sorted(p.name for p in out.glob("*.o"))
    linked = _run(["gfortran", "-o", "driver", *objects], out)
    assert linked.returncode == 0, linked.stderr
    ran = _run([str(out / "driver")], out)
    assert ran.returncode == 0, ran.stderr

    stress = [float(line[len("S1"):]) for line in ran.stdout.splitlines()
              if line.startswith("S")]
    tangent = [float(line.split("_")[1][1:]) for line in ran.stdout.splitlines()
               if line.startswith("D")]

    emod, enu = 210000.0, 0.3
    ebulk3 = emod / (1.0 - 2.0 * enu)
    eg2 = emod / (1.0 + enu)
    eg = eg2 / 2.0
    elam = (ebulk3 - eg2) / 3.0
    stiffness = [[0.0] * 6 for _ in range(6)]
    for i in range(3):
        for j in range(3):
            stiffness[j][i] = elam
        stiffness[i][i] = eg2 + elam
    for i in range(3, 6):
        stiffness[i][i] = eg
    dstran = [1.0e-4, -2.0e-5, 3.0e-5, 4.0e-5, -5.0e-5, 6.0e-5]
    expected_stress = [sum(stiffness[k2][k1] * dstran[k1] for k1 in range(6))
                       for k2 in range(6)]

    assert max(abs(value) for value in stress) > 0.0, (
        "every stress component came back exactly zero: the predictor is still "
        "reading the tangent array the caller zeroed")
    for got, want in zip(stress, expected_stress):
        assert abs(got - want) <= 1.0e-9 * max(abs(want), 1.0), (stress, expected_stress)
    flat = [stiffness[i][j] for i in range(6) for j in range(6)]
    for got, want in zip(tangent, flat):
        assert abs(got - want) <= 1.0e-6 * max(abs(want), 1.0), (tangent, flat)


def test_a_name_inside_quotes_is_a_label_not_a_read():
    """`WRITE(7,*) 'DDSDDE='` mentions the array and reads nothing.

    Counting it refused a source whose repair had in fact worked:
    sd104400__OPA_Modeling's UMAT_DPIsodwAniDM.for, where the disabled write
    and the live reads were resolved correctly and the emitted file was then
    rejected over the label string in a diagnostic WRITE. Costs nothing today
    -- that source is outside the 199 -- and would drop correct sources as the
    corpus grows.
    """
    from umat_oti.transform.source_transform import _statement_reads

    assert not _statement_reads("      WRITE(7,*) 'DDSDDE='", "DDSDDE")
    assert not _statement_reads('      WRITE(6,*) "DDSDDE is:"', "DDSDDE")


def test_a_genuine_read_is_still_counted():
    """The guard must not blind the check it was added to."""
    from umat_oti.transform.source_transform import _statement_reads

    assert _statement_reads(
        "      STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)", "DDSDDE")
    assert _statement_reads("      IF (DDSDDE(1,1).GT.0.0) THEN", "DDSDDE")


def test_a_read_beside_a_label_is_still_counted():
    """Blanking the literal must not blank the statement around it."""
    from umat_oti.transform.source_transform import _statement_reads

    assert _statement_reads("      WRITE(7,*) 'DDSDDE=', DDSDDE(1,1)", "DDSDDE")


def test_blanking_preserves_the_columns():
    """Fixed form counts columns; a shorter line would move what follows."""
    from umat_oti.transform.source_transform import _without_character_literals

    before = "      A='DDSDDE'+B"
    after = _without_character_literals(before)
    assert len(after) == len(before)
    assert after.endswith("+B")
