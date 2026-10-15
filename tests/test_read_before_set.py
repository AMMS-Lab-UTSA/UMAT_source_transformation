"""Locals a UMAT can read before it assigns them (umat_oti.fortran.read_before_set).

The case behind it: a plasticity UMAT sets its plastic-strain increment only inside its
Newton loop and adds it to the state on every call, so an elastic increment adds
whatever the stack held. The analysis must find that read, name it in the
transform report, and the generated code must start the variable at zero on
entry -- explicitly, because the transformed UMAT is compiled by Abaqus with its
default flags, not with -init=zero.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from umat_oti.fortran.read_before_set import (
    analyse_text, executable_text, first_executable_line, insert_at_entry, statement_line)

REPO = Path(__file__).resolve().parents[1]

HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
"""

#: A plastic-increment case: DEP set only inside a loop that an elastic
#: call jumps over, and added to the state on every call.
NEWTON_LOOP_SHAPE = HEADER + """      DIMENSION ETR(6)
      E = PROPS(1)
      DO I = 1, NTENS
        ETR(I) = STRAN(I) + DSTRAN(I)
      END DO
      PHI = ETR(1)*E - PROPS(2)
      IF (PHI .LE. 0.0D0) GOTO 300
      DO ITER = 1, 20
        DEP = PHI/E
        IF (ABS(DEP) .LT. 1.0D-12) EXIT
        PHI = PHI - E*DEP
      END DO
  300 CONTINUE
      DO I = 1, NTENS
        STRESS(I) = E*ETR(I)
      END DO
      STATEV(1) = STATEV(1) + DEP
      RETURN
      END
"""


def _names(analysis):
    return {(f.name, f.line) for f in analysis.findings}


def _line_of(text, needle):
    return next(n for n, line in enumerate(text.splitlines(), 1) if needle in line)


def test_the_newton_loop_shape_is_found_at_the_read_and_nothing_else_is():
    analysis = analyse_text(NEWTON_LOOP_SHAPE, "UMAT", form="fixed")
    assert not analysis.undecided
    assert _names(analysis) == {("DEP", _line_of(NEWTON_LOOP_SHAPE, "STATEV(1) + DEP"))}
    finding = analysis.findings[0]
    assert finding.type == "real" and finding.rank == "scalar" and finding.initialisable
    assert finding.zero_statement() == "DEP = 0.0D0"
    # the report sentence names the variable and the line
    assert "DEP" in analysis.warnings()[0] and str(finding.line) in analysis.warnings()[0]


@pytest.mark.parametrize("body, flagged", [
    # assigned on both branches: defined
    ("""      IF (STRAN(1) .GT. 0.0D0) THEN
        X = 1.0D0
      ELSE
        X = 2.0D0
      END IF
      STRESS(1) = X
""", set()),
    # assigned on one branch only
    ("""      IF (STRAN(1) .GT. 0.0D0) THEN
        X = 1.0D0
      END IF
      STRESS(1) = X
""", {"X"}),
    # ELSE IF chain without ELSE
    ("""      IF (STRAN(1) .GT. 0.0D0) THEN
        X = 1.0D0
      ELSE IF (STRAN(1) .LT. 0.0D0) THEN
        X = 2.0D0
      END IF
      STRESS(1) = X
""", {"X"}),
    # a counted loop with literal bounds runs at least once
    ("""      DO I = 1, 3
        X = DBLE(I)
      END DO
      STRESS(1) = X
""", set()),
    # a loop whose trip count is known only at run time may not run
    ("""      DO I = 1, NTENS
        X = DBLE(I)
      END DO
      STRESS(1) = X
""", {"X"}),
    # labelled DO with a shared terminal statement
    ("""      DO 10 I = 1, 3
      DO 10 J = 1, 3
        X = DBLE(I*J)
   10 CONTINUE
      STRESS(1) = X
""", set()),
    # a jump over the only assignment
    ("""      IF (STRAN(1) .GT. 0.0D0) GO TO 20
      X = 1.0D0
   20 CONTINUE
      STRESS(1) = X
""", {"X"}),
    # read on the right of its own first assignment
    ("""      X = X + 1.0D0
      STRESS(1) = X
""", {"X"}),
    # set by a CALL (the callee may set it): not reported
    ("""      CALL HELPER(X)
      STRESS(1) = X
""", set()),
    # an array element assigned in a loop before the read: not reported
    ("""      DO I = 1, NTENS
        T(I) = 0.0D0
      END DO
      STRESS(1) = T(1)
""", set()),
    # an array no path assigns before the read
    ("""      STRESS(1) = T(1)
      T(1) = 0.0D0
""", {"T"}),
    # SELECT CASE without a default
    ("""      SELECT CASE (NTENS)
      CASE (6)
        X = 1.0D0
      CASE (4)
        X = 2.0D0
      END SELECT
      STRESS(1) = X
""", {"X"}),
    ("""      SELECT CASE (NTENS)
      CASE (6)
        X = 1.0D0
      CASE DEFAULT
        X = 2.0D0
      END SELECT
      STRESS(1) = X
""", set()),
    # EXIT from an infinite loop after the assignment
    ("""      DO
        X = 1.0D0
        IF (X .GT. 0.0D0) EXIT
      END DO
      STRESS(1) = X
""", set()),
])
def test_control_flow(body, flagged):
    source = HEADER + "      DIMENSION T(6)\n" + body + "      RETURN\n      END\n"
    analysis = analyse_text(source, "UMAT", form="fixed")
    assert not analysis.undecided, analysis.undecided
    assert {f.name for f in analysis.findings} == flagged


@pytest.mark.parametrize("declaration", [
    "      SAVE X\n",
    "      DATA X /1.0D0/\n",
    "      COMMON /BLK/ X\n",
    "      PARAMETER (X = 1.0D0)\n",
])
def test_names_that_carry_a_value_into_the_call_are_not_candidates(declaration):
    source = (HEADER + declaration + "      IF (STRAN(1) .GT. 0.0D0) THEN\n        Y = X\n      END IF\n"
              "      STRESS(1) = X\n      RETURN\n      END\n")
    analysis = analyse_text(source, "UMAT", form="fixed")
    assert "X" not in {f.name for f in analysis.findings}


def test_inquiry_intrinsics_functions_and_internal_procedures_are_not_reads_of_a_local():
    source = """subroutine umat(stress, props, nprops)
  implicit none
  integer :: nprops
  real(8) :: stress(6), props(nprops), a(2, 2), det
  real(8) :: helper
  a = reshape((/ 1.0d0, 0.0d0, 0.0d0, props(1) /), shape(a))
  det = helper(a)
  stress(1) = det + size(a)
contains
  subroutine inner(x)
    real(8) :: x, y
    x = y
  end subroutine inner
end subroutine umat
"""
    analysis = analyse_text(source, "UMAT", form="free")
    assert not analysis.undecided and analysis.findings == []


def test_a_name_an_include_puts_in_common_is_not_reset(tmp_path):
    body = ("      INCLUDE 'state.inc'\n      DOUBLE PRECISION X\n      IF (STRAN(1) .GT. 0.0D0) X = 1.0D0\n"
            "      STRESS(1) = X\n      RETURN\n      END\n")
    source = tmp_path / "umat.f"
    source.write_text(HEADER + body)
    (tmp_path / "STATE.INC").write_text("      COMMON /KEEP/ X\n")
    analysis = analyse_text(source.read_text(), "UMAT", form="fixed", source_path=source)
    assert analysis.findings == []
    (tmp_path / "STATE.INC").unlink()
    analysis = analyse_text(source.read_text(), "UMAT", form="fixed", source_path=source)
    assert [(f.name, f.initialisable) for f in analysis.findings] == [("X", False)]
    assert "state.inc" in analysis.findings[0].why_not


def test_a_bare_save_makes_every_local_static_and_the_analysis_says_so():
    source = HEADER + "      SAVE\n      STRESS(1) = X\n      X = 1.0D0\n      RETURN\n      END\n"
    analysis = analyse_text(source, "UMAT", form="fixed")
    assert analysis.undecided and not analysis.findings


def test_an_assigned_goto_stops_the_analysis():
    source = HEADER + "      ASSIGN 10 TO L\n      GO TO L\n   10 CONTINUE\n      RETURN\n      END\n"
    analysis = analyse_text(source, "UMAT", form="fixed")
    assert "assigned GO TO" in analysis.undecided and not analysis.findings


def test_types_and_free_form():
    source = """subroutine umat(stress, statev, ntens, nstatv, props, nprops)
  implicit none
  integer :: ntens, nstatv, nprops, n
  real(8) :: stress(ntens), statev(nstatv), props(nprops), x
  logical :: plastic
  if (props(1) > 0.0d0) then
    n = 1
    x = 1.0d0
    plastic = .true.
  end if
  stress(1) = x*n
  if (plastic) statev(1) = 1.0d0
end subroutine umat
"""
    analysis = analyse_text(source, "UMAT", form="free")
    found = {f.name: f.type for f in analysis.findings}
    assert found == {"N": "integer", "X": "real", "PLASTIC": "logical"}
    statements = [f.zero_statement() for f in analysis.findings]
    assert set(statements) == {"N = 0", "X = 0.0D0", "PLASTIC = .FALSE."}


def test_insertion_goes_before_the_first_executable_statement():
    text = insert_at_entry(NEWTON_LOOP_SHAPE, "UMAT", "fixed", ["DEP = 0.0D0"])
    lines = text.splitlines()
    first = first_executable_line(NEWTON_LOOP_SHAPE, "UMAT", "fixed")
    assert NEWTON_LOOP_SHAPE.splitlines()[first - 1].strip() == "E = PROPS(1)"
    assert lines[first - 1].startswith("C ") and lines[first].strip() == "DEP = 0.0D0"
    assert lines[first + 1].strip() == "E = PROPS(1)"
    # the result is again a routine whose finding is defined on every path
    assert not analyse_text(text, "UMAT", form="fixed").findings
    assert "DEP" in executable_text(text, "UMAT", "fixed")


def test_a_long_fixed_form_statement_is_continued():
    line = statement_line("fixed", "A_VERY_LONG_VARIABLE_NAME_OF_THIRTY_ONE_X_OTI = 0.0D0" + " " * 0)
    assert all(len(part) <= 72 for part in line.split("\n"))


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_tangent_transform_reports_and_initialises_the_finding(tmp_path):
    source = tmp_path / "src" / "newton_loop_shape.f"
    source.parent.mkdir()
    source.write_text(NEWTON_LOOP_SHAPE)
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, "-m", "umat_oti.cli", "jacobian", str(source), "--ntens", "6",
                           "--out", str(out), "--compile"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    report = json.loads((out / "transform_report.json").read_text())
    reads = report["reads_before_assignment"]
    assert [(f["name"], f["line"]) for f in reads["findings"]] == [
        ("DEP", _line_of(NEWTON_LOOP_SHAPE, "STATEV(1) + DEP"))]
    assert reads["initialised_in_generated_code"] == ["DEP_OTI = 0.0D0"]
    assert any(w.startswith("DEP can be read before it is assigned") for w in report["warnings"])
    generated = (out / "newton_loop_shape_oti.f").read_text()
    first = first_executable_line(generated, "UMAT", "fixed")
    assert generated.splitlines()[first - 1].strip() == "DEP_OTI = 0.0D0"


@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_provider_starts_the_finding_at_zero_in_both_builds(tmp_path):
    from umat_oti.provider.build import build_provider

    model = tmp_path / "model"
    model.mkdir()
    (model / "umat.f").write_text(NEWTON_LOOP_SHAPE)
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 2, "nstatev": 1},
        "parameters": [{"name": "E", "props_index": 1}, {"name": "Y", "props_index": 2}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": True},
        "output": {"object": "toy.obj", "contract": "toy.json"}}))
    built = build_provider(model / "contract.json", tmp_path / "out", regular_object="REAL_UMAT.obj")
    contract = json.loads(Path(built["contract"]).read_text())
    assert contract["build"]["original_entry_statements"] == ["DEP = 0.0D0"]
    assert [f["name"] for f in contract["build"]["reads_before_assignment"]["findings"]] == ["DEP"]
    assert "DEP = 0.0D0 placed at its entry" in contract["regular_object"]["role"]
    assert contract["regular_object"]["source_sha256_full"] != contract["regular_object"][
        "compiled_source_sha256_full"]
    build_dir = Path(built["build_dir"])
    lifted = (build_dir / "umat_oti_lifted.f90").read_text()
    assert first_executable_line(lifted, "UMAT_OTI", "free")
    assert not analyse_text(lifted, "UMAT_OTI", form="free").findings
    original = (build_dir / "original" / "umat.f").read_text()
    assert not analyse_text(original, "UMAT", form="fixed").findings
    # the file on disk is untouched
    assert (model / "umat.f").read_text() == NEWTON_LOOP_SHAPE
    assert built["warnings"] and built["warnings"][0].startswith("DEP can be read")


#: A routine whose first executable statements are logical IFs with an
#: assignment: they look like ``NAME(...) = ...`` and are not statement
#: functions. Starting SCALE at zero after them overwrote the value they set.
LOGICAL_IF_FIRST = HEADER.replace("      INCLUDE 'ABA_PARAM.INC'\n",
                                  "      INCLUDE 'ABA_PARAM.INC'\n      DOUBLE PRECISION SCALE\n") + """\
      IF (PROPS(1) .GT. 0.0D0) SCALE = 2.0D0
      IF (PROPS(1) .LE. 0.0D0) SCALE = 3.0D0
      E = PROPS(2)*SCALE
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + E*DSTRAN(I)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = E
      END DO
      RETURN
      END
"""


def _index(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


def test_a_logical_if_is_not_a_statement_function_and_the_zero_goes_before_it():
    first_if = _line_of(LOGICAL_IF_FIRST, "SCALE = 2.0D0")
    analysis = analyse_text(LOGICAL_IF_FIRST, "UMAT", form="fixed")
    assert analysis.first_executable_line == first_if
    assert [(f.name, f.line) for f in analysis.findings] == [("SCALE", _line_of(LOGICAL_IF_FIRST, "E = PROPS(2)*SCALE"))]
    lines = insert_at_entry(LOGICAL_IF_FIRST, "UMAT", "fixed", ["SCALE = 0.0D0"]).splitlines()
    # checked on the text, not through first_executable_line
    assert _index(lines, "SCALE = 0.0D0") < _index(lines, "IF (PROPS(1) .GT. 0.0D0) SCALE = 2.0D0")


def test_a_first_logical_if_reading_a_name_nothing_sets_is_a_finding():
    source = HEADER + "      IF (A .GT. 0.0D0) STRESS(1) = 1.0D0\n      RETURN\n      END\n"
    analysis = analyse_text(source, "UMAT", form="fixed")
    assert [(f.name, f.line, f.initialisable) for f in analysis.findings] == [
        ("A", _line_of(source, "IF (A .GT."), False)]
    assert "nothing in the routine assigns it" in analysis.findings[0].why_not


def test_a_statement_function_is_still_one():
    source = HEADER + "      SQ(X) = X*X\n      STRESS(1) = SQ(PROPS(1))\n      RETURN\n      END\n"
    analysis = analyse_text(source, "UMAT", form="fixed")
    assert analysis.first_executable_line == _line_of(source, "STRESS(1) = SQ")
    assert analysis.findings == []


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_generated_tangent_and_the_provider_original_set_scale_before_the_ifs(tmp_path):
    from umat_oti.provider.build import build_provider

    model = tmp_path / "model"
    model.mkdir()
    (model / "umat.f").write_text(LOGICAL_IF_FIRST)
    out = tmp_path / "tangent"
    done = subprocess.run([sys.executable, "-m", "umat_oti.cli", "jacobian", str(model / "umat.f"),
                           "--ntens", "6", "--out", str(out), "--compile"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    generated = (out / "umat_oti.f").read_text().splitlines()
    zeros = [i for i, line in enumerate(generated) if line.strip().startswith("SCALE") and "= 0.0D0" in line]
    assert zeros and max(zeros) < _index(generated, "IF (PROPS(1) .GT. 0.0D0)")
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 2, "nstatev": 0},
        "parameters": [{"name": "P1", "props_index": 1}, {"name": "P2", "props_index": 2}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": False},
        "output": {"object": "toy.obj", "contract": "toy.json"}}))
    built = build_provider(model / "contract.json", tmp_path / "out")
    build_dir = Path(built["build_dir"])
    original = (build_dir / "original" / "umat.f").read_text().splitlines()
    assert _index(original, "SCALE = 0.0D0") < _index(original, "IF (PROPS(1) .GT. 0.0D0)")
    lifted = (build_dir / "umat_oti_lifted.f90").read_text().splitlines()
    assert _index(lifted, "SCALE = 0.0D0") < _index(lifted, "SCALE = 2.0D0")
