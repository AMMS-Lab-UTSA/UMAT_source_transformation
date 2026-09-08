"""What Abaqus interface a file presents, decided by parsing rather than naming.

``detect_entry_routines`` matched ``SUBROUTINE UMAT`` anywhere in a file, so a
file whose Abaqus entry point is a 36-argument ``SUBROUTINE UEL`` -- with a
``SUBROUTINE UMAT`` beside it that the element calls as its own constitutive
kernel -- read as a UMAT. Twenty-five corpus files are exactly that. Driven
through a ``*USER MATERIAL`` deck, Abaqus resolved the global symbol ``UMAT``
to the element's kernel, and the finite-difference reference then perturbed a
deformation gradient that kernel never reads: the difference came out
identically zero at every step size, and the rows were recorded as UMAT
tangent failures. Nothing about anyone's UMAT was tested.

Three things decide it, none of which a filename can fake: the routine's name,
its exact dummy-argument count, and whether a sibling unit calls it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.corpus.entry_routines import (HELPER_ONLY,  # noqa: E402
                                            OTHER_ABAQUS_ENTRY, UMAT,
                                            classify, program_units)

UMAT_HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,
     3 COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,
     4 KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      RETURN
      END
"""

UEL_HEADER = """      SUBROUTINE UEL(RHS,AMATRX,SVARS,ENERGY,NDOFEL,NRHS,NSVARS,
     1 PROPS,NPROPS,COORDS,MCRD,NNODE,U,DU,V,A,JTYPE,TIME,DTIME,
     2 KSTEP,KINC,JELEM,PARAMS,NDLOAD,JDLTYP,ADLMAG,PREDEF,NPREDF,
     3 LFLAGS,MLVARX,DDLMAG,MDLOAD,PNEWDT,JPROPS,NJPROP,PERIOD)
      INCLUDE 'ABA_PARAM.INC'
      DO K = 1, 3
        IF (K .GT. 1) THEN
          CALL UMAT(A,B,C)
        END IF
      END DO
      RETURN
      END
"""


def test_a_real_umat_is_a_umat():
    result = classify(UMAT_HEADER)
    assert result.kind == UMAT and result.is_umat
    assert result.entry_interface == "UMAT"


def test_a_uel_whose_umat_is_its_own_callee_is_not_a_umat():
    result = classify(UEL_HEADER + UMAT_HEADER)
    assert result.kind == OTHER_ABAQUS_ENTRY
    assert result.entry_interface == "UEL"
    assert not result.is_umat
    assert "own callee" in result.reason


def test_the_reason_names_both_routines_and_their_lines():
    """A classification that cannot be checked is not evidence."""
    result = classify(UEL_HEADER + UMAT_HEADER)
    assert "SUBROUTINE UEL" in result.reason
    assert "36 arguments" in result.reason
    assert "line" in result.reason


def test_end_if_does_not_end_the_subroutine():
    """A pattern allowing any word after END treated every `END IF` as the
    end of the unit, so a CALL after the first conditional was attributed to
    nothing -- which is exactly why the CALL UMAT inside a UEL was missed."""
    units = {u.name.upper(): u for u in program_units(UEL_HEADER + UMAT_HEADER)}
    assert "UEL" in units["UMAT"].called_by


def test_a_routine_that_shares_the_name_but_not_the_interface_is_not_one():
    """warp3d's own `umat` takes 43 arguments; MML's takes 5. Neither is the
    Abaqus UMAT, and the argument count is what says so."""
    result = classify("      SUBROUTINE UMAT(A,B,C,D,E)\n      RETURN\n      END\n")
    assert result.kind == HELPER_ONLY
    assert "5 arguments" in result.reason and "37" in result.reason


def test_a_free_form_source_is_read_as_free_form():
    """Guessing a fixed-form name truncated every .f90 at column 72 and found
    no program unit at all in files that plainly declare one."""
    free = ("subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, &\n"
            "     ddsddt, drplde, drpldt, stran, dstran, time, dtime, temp, dtemp, &\n"
            "     predef, dpred, cmname, ndi, nshr, ntens, nstatv, props, nprops, &\n"
            "     coords, drot, pnewdt, celent, dfgrd0, dfgrd1, noel, npt, layer, &\n"
            "     kspt, kstep, kinc)\n"
            "end subroutine\n")
    assert classify(free, path=Path("m.f90")).is_umat


def test_a_file_with_no_program_unit_is_not_a_umat():
    assert not classify("      ! nothing here\n").is_umat


def test_the_classification_carries_its_working():
    """Units, argument counts and who-calls-whom, so the claim can be checked
    without re-parsing."""
    record = classify(UEL_HEADER + UMAT_HEADER).as_dict()
    names = {u["name"].upper(): u for u in record["units"]}
    assert names["UEL"]["arguments"] == 36
    assert names["UMAT"]["arguments"] == 37
    assert names["UMAT"]["called_by"] == ["UEL"]


# ---- the batch keeps it off the ladder -----------------------------------
def test_not_a_umat_is_not_a_rung():
    """It is not a statement about how far a UMAT got, because the file is
    not a UMAT. Ranking it would let it be read as progress."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from verify_store_in_abaqus import NOT_A_UMAT, STAGES, stage_rank

    assert NOT_A_UMAT not in STAGES
    assert stage_rank(NOT_A_UMAT) == -1
