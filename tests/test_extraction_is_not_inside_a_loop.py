"""The extraction must not run inside a loop the stress update runs in.

Inserted there it executes once per iteration, and both things it does are
destroyed by that. The real copy STRESS(I) = REAL(STRESS_OTI(I)) is merely
repeated; the tangent extraction DDSDDE(i,j) = GETIM(STRESS_OTI(i), j)
overwrites the array the loop is still reading.

Found by numerical verification, not by a compiler: the emitted file built,
ran, and returned a tangent whose first column was right and whose other five
were zero, together with a wrong stress.
"""
from __future__ import annotations

import json

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.core.transformation_anchors import _enclosing_do_end
from umat_oti.services.transformation import TransformationOptions, run_transformation

#: The shape that exposed it: the whole stress update is a two-deep loop nest,
#: so the last stress statement is inside two loops, and the array being
#: assembled is the same one the transform replaces. Tab-indented, as the
#: source that prompted this is -- written for ifort, where a tab in the label
#: field advances to column 7.
LOOPED_STRESS_UMAT = (
    "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,\n"
    "     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,\n"
    "     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,\n"
    "     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
    "      INCLUDE 'ABA_PARAM.INC'\n"
    "      CHARACTER*80 CMNAME\n"
    "      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),\n"
    "     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),\n"
    "     2 PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),\n"
    "     3 DFGRD0(3,3),DFGRD1(3,3)\n"
    "      PARAMETER (ONE=1.D0, TWO=2.D0, THREE=3.D0)\n"
    "\t EMOD=PROPS(1)\n"
    "\t ENU=PROPS(2)\n"
    "\t EBULK3=EMOD/(ONE-TWO*ENU)\n"
    "\t EG2=EMOD/(ONE+ENU)\n"
    "\t EG=EG2/TWO\n"
    "\t ELAM=(EBULK3-EG2)/THREE\n"
    "\t DO K1=1,NDI\n"
    "\t DO K2=1,NDI\n"
    "\t DDSDDE(K2,K1)=ELAM\n"
    "\t END DO\n"
    "\t DDSDDE(K1,K1)=EG2+ELAM\n"
    "\t END DO\n"
    "\t DO K1=NDI+1, NTENS\n"
    "\t DDSDDE(K1,K1)=EG\n"
    "\t END DO\n"
    "\t DO K1=1, NTENS\n"
    "\t DO K2=1, NTENS\n"
    "\t STRESS(K2)=STRESS(K2)+DDSDDE(K2,K1)*DSTRAN(K1)\n"
    "\t END DO\n"
    "\t END DO\n"
    "      RETURN\n"
    "      END\n")


class TestFindingTheEnclosingLoop:
    LINES = ["      A = 1", "\t DO K1=1,6", "\t DO K2=1,6", "\t S=S+1",
             "\t END DO", "\t END DO", "      RETURN"]

    def test_a_line_in_the_inner_loop_reports_the_outer_end(self):
        assert _enclosing_do_end(self.LINES, 4, (1, 7)) == 6

    def test_the_do_line_itself_counts_as_enclosed(self):
        assert _enclosing_do_end(self.LINES, 2, (1, 7)) == 6

    def test_a_line_above_the_loop_is_not_enclosed(self):
        """Not merely "before the END DO" -- it must be inside."""
        assert _enclosing_do_end(self.LINES, 1, (1, 7)) == 0

    def test_a_line_after_the_loop_is_not_enclosed(self):
        assert _enclosing_do_end(self.LINES, 7, (1, 7)) == 0

    def test_a_line_between_two_sibling_loops_is_not_enclosed(self):
        lines = ["      A=1", "      DO I=1,3", "      B=2", "      END DO",
                 "      C=3", "      DO J=1,3", "      D=4", "      END DO"]
        assert _enclosing_do_end(lines, 5, (1, 8)) == 0
        assert _enclosing_do_end(lines, 3, (1, 8)) == 4

    def test_a_line_outside_the_selected_routine_is_not_enclosed(self):
        assert _enclosing_do_end(self.LINES, 4, (5, 7)) == 0


def _transform(tmp_path):
    src = tmp_path / "looped.for"
    src.write_text(LOOPED_STRESS_UMAT, encoding="utf-8")
    config, _ = _build_contract("looped", "auto", "STRESS", "DDSDDE", 6, 1, src)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    run_transformation(cfg, tmp_path / "out", TransformationOptions(compile_generated=False))
    return next((tmp_path / "out").glob("*_oti.for")).read_text(encoding="utf-8")


def _line_of(text: str, needle: str) -> int:
    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} was never emitted")


def test_the_tangent_extraction_lands_after_the_stress_loop(tmp_path):
    text = _transform(tmp_path)
    getim = _line_of(text, "GETIM")
    lines = text.splitlines()
    # Every END DO closing the stress nest must precede the extraction.
    stress_line = _line_of(text, "STRESS_OTI(K2)=STRESS_OTI(K2)")
    closers = [i for i, l in enumerate(lines, start=1)
               if l.replace("\t", " ").strip().upper().startswith("END DO")
               and stress_line < i]
    assert closers, "the emitted file has no END DO after the stress statement"
    assert getim > closers[1] if len(closers) > 1 else getim > closers[0], (
        "the tangent extraction is inside the loop that computes the stress; "
        "GETIM would overwrite DDSDDE while the loop still reads it")


def test_the_real_copy_also_lands_after_the_loop(tmp_path):
    text = _transform(tmp_path)
    stress_line = _line_of(text, "STRESS_OTI(K2)=STRESS_OTI(K2)")
    copy = _line_of(text, "STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))")
    lines = text.splitlines()
    closers = [i for i, l in enumerate(lines, start=1)
               if l.replace("\t", " ").strip().upper().startswith("END DO")
               and stress_line < i]
    assert copy > (closers[1] if len(closers) > 1 else closers[0])


def test_the_stress_loop_is_left_intact(tmp_path):
    """Moving the extraction must not remove the loop it moved past."""
    text = _transform(tmp_path).replace("\t", " ")
    assert text.count("END DO") >= 2
    assert "STRESS_OTI(K2)=STRESS_OTI(K2)+DDSDDE(K2,K1)*DSTRAN_OTI(K1)" in text
