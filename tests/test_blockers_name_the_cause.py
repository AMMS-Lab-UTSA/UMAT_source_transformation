"""A refusal has to name the cause, not the first symptom of it.

Four sources in the discovered set stopped with a message that described
something true about a consequence and left the reason unsaid:

* a UMAT whose material routine lives in another file was reported as
  twenty-two uncovered DDSDDE assignments -- in a routine it never calls;
* a four-argument demonstration routine that happens to be named UMAT was
  reported as four missing anchors, each of them a place that exists only
  inside the Abaqus UMAT interface;
* two sources whose stress path calls into a Fortran module were reported as
  arrays with no confirmed shape, which is what an unreadable module looks
  like to a reader that never learned to read one.

The fifth was not a refusal at all but a false one: a guard against integer
literals on the OTI path read the exponent digits of ``3.8019047483079793e-6``
as a bare integer and refused a file that compiles cleanly.
"""
from __future__ import annotations

import json

from umat_oti.app.engine import _build_contract
from umat_oti.core.transformation_anchors import (
    anchor_completion_status, merge_completed_anchors_into_config,
)
from umat_oti.core.config_loader import load_project_config_json
from umat_oti.fortran.callgraph import (
    delegated_material_routine, undefined_delegate_call,
)
from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.source_transform import (
    _integer_literals_normalized_in_oti_expressions, _uncovered_ddsdde_blockers,
)


# --------------------------------------------------------------------------
# The integer-literal guard, and what is not an integer literal
# --------------------------------------------------------------------------

def _fixed(*statements: str) -> str:
    return "".join(f"      {text}\n" for text in statements)


def test_a_bare_integer_multiplying_an_oti_value_is_still_refused():
    """The guard exists for this. It has to keep firing."""
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = 2*X_OTI")) is False
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = X_OTI/3")) is False
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = X_OTI * 16")) is False


def test_the_exponent_of_a_real_literal_is_not_an_integer_literal():
    """3.8019047483079793e-6 ends in digits that belong to the number."""
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = 3.8019047483079793e-6*SIN(X_OTI)")) is True
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = 1.0D-30*X_OTI")) is True
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = X_OTI/2.5E+3")) is True


def test_a_real_literal_split_across_a_continuation_reads_as_one_number():
    """Fixed form resumes in column 7 with no space inserted, and so must this.

    Reading the physical lines one at a time, the second begins "6*Sin(" --
    a bare integer multiplying something, and the file was refused for it.
    """
    split = ("      Y_OTI = 2.7026494317808357e-\n"
             "     16*SIN(X_OTI)\n")
    assert _integer_literals_normalized_in_oti_expressions(split, "fixed") is True


def test_a_trailing_comment_is_not_part_of_the_statement():
    assert _integer_literals_normalized_in_oti_expressions(
        _fixed("Y_OTI = X_OTI  ! scaled by 2*NTENS elsewhere")) is True


# --------------------------------------------------------------------------
# A UMAT whose material routine is not in this file
# --------------------------------------------------------------------------

_WRAPPER_HEAD = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     #rpl,ddsddt,drplde,drpldt,
     #stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     #ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,
     #celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv),
     #ddsdde(ntens,ntens),ddsddt(ntens),drplde(ntens),
     #stran(ntens),dstran(ntens),time(2),predef(1),dpred(1),
     #props(nprops),coords(3),drot(3,3),dfgrd0(3,3),dfgrd1(3,3)
      call the_model(stress,statev,ddsdde,props,dfgrd1,
     #               ntens,nstatv,nprops)
      return
      end
"""

#: A second model in the same file, spelled differently from the one the
#: wrapper calls, so nothing calls it. Its DDSDDE assignments were the whole
#: of the blocker text for the source this is drawn from.
_UNCALLED_MODEL = """
      subroutine the_model_variant(stress,statev,ddsdde,props,dfgrd1,
     #                             ntens,nstatv,nprops)
      implicit none
      integer ntens, nstatv, nprops, i, j
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 props(nprops), dfgrd1(3,3), detf
      detf = dfgrd1(1,1)*dfgrd1(2,2)*dfgrd1(3,3)
      do i = 1, ntens
        stress(i) = props(1)*(detf-1.d0)
      end do
      ddsdde(1,1) = props(1)/detf
      ddsdde(2,2) = props(1)/detf
      return
      end
"""

DELEGATES_OUTSIDE = _WRAPPER_HEAD + _UNCALLED_MODEL


def _transform(tmp_path, text, stem="src"):
    src = tmp_path / f"{stem}.f"
    src.write_text(text, encoding="utf-8")
    config, _finite = _build_contract(stem, "auto", "STRESS", "DDSDDE", 6, 1, src)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _code = run_transformation(config_path, tmp_path / "out",
                                        TransformationOptions(compile_generated=False))
    return summary


def test_a_delegate_this_source_does_not_define_is_reported_by_name(tmp_path):
    path = tmp_path / "wrapper.f"
    path.write_text(DELEGATES_OUTSIDE, encoding="utf-8")
    parsed = parse_fortran_file(path)
    assert undefined_delegate_call(parsed, "UMAT") == "THE_MODEL"
    # Unchanged: there is still no local routine to follow.
    assert delegated_material_routine(parsed, "UMAT") is None


def test_a_local_delegate_is_not_reported_as_undefined(tmp_path):
    local = _WRAPPER_HEAD.replace("the_model(", "the_model_variant(") + _UNCALLED_MODEL
    path = tmp_path / "local.f"
    path.write_text(local, encoding="utf-8")
    parsed = parse_fortran_file(path)
    assert undefined_delegate_call(parsed, "UMAT") is None


def test_the_blocker_names_the_missing_delegate_and_not_the_symptoms(tmp_path):
    summary = _transform(tmp_path, DELEGATES_OUTSIDE, "wrapper")
    blockers = summary.get("blockers") or []
    assert blockers, summary
    assert "THE_MODEL" in blockers[0] and "does not define" in blockers[0]
    # The uncalled routine's DDSDDE assignments say nothing about this source.
    assert not any("not covered by an old tangent replacement region" in text
                   for text in blockers), blockers


def test_an_assignment_outside_every_reachable_routine_is_not_a_blocker():
    """Line 40 is in a routine nothing calls; line 12 is in the one being run."""
    analysis = {"assignments_to_ddsdde": [
        {"line_numbers": [40], "text": "ddsdde(1,1) = unreachable"},
        {"line_numbers": [12], "text": "ddsdde(2,2) = reachable"},
    ]}
    reachable = [{"region_id": "UMAT", "start_line": 1, "end_line": 20}]
    stress = [{"start_line": 5, "end_line": 6}]
    scoped = _uncovered_ddsdde_blockers(analysis, [], stress, [], reachable)
    assert [text.rsplit(": ", 1)[-1] for text in scoped] == ["ddsdde(2,2) = reachable"]
    # No scope means no scoping, which is what every other caller still gets.
    unscoped = _uncovered_ddsdde_blockers(analysis, [], stress, [], [])
    assert sorted(text.rsplit(": ", 1)[-1] for text in unscoped) == [
        "ddsdde(1,1) = unreachable", "ddsdde(2,2) = reachable"]


# --------------------------------------------------------------------------
# A routine named UMAT that is not an Abaqus UMAT
# --------------------------------------------------------------------------

NOT_A_UMAT = """\
      program demo
      implicit none
      real*8 s(3,3), c(3,3,3,3), f(3,3), e(3,3)
      f = 0.0
      e = 0.0
      call umat(s,c,f,e)
      end program demo

      subroutine umat(siso_arr,c4iso_arr,f_arr,e_arr)
      implicit none
      real*8, dimension(3,3), intent(in) :: f_arr, e_arr
      real*8, dimension(3,3), intent(inout) :: siso_arr
      real*8, dimension(3,3,3,3), intent(inout) :: c4iso_arr
      siso_arr = f_arr + e_arr
      c4iso_arr = 0.d0
      end
"""


def _anchor_issues(tmp_path, text, stem="src"):
    src = tmp_path / f"{stem}.f"
    src.write_text(text, encoding="utf-8")
    raw, _finite = _build_contract(stem, "auto", "STRESS", "DDSDDE", 6, 1, src)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_project_config_json(config_path.read_bytes(), origin_path=config_path)
    config = merge_completed_anchors_into_config(config, text)
    return anchor_completion_status(config)


def test_a_routine_named_umat_without_the_umat_interface_says_so(tmp_path):
    status = _anchor_issues(tmp_path, NOT_A_UMAT, "script")
    assert status["status"] == "needs_json_completion"
    issues = status["completion_issues"]
    # One issue, because one fact answers all the missing anchors.
    assert [row["kind"] for row in issues] == ["selected_routine_is_not_an_abaqus_umat"]
    message = issues[0]["message"]
    assert "SISO_ARR" in message and "STRESS" in message and "DDSDDE" in message


def test_a_real_umat_is_not_mistaken_for_one(tmp_path):
    """The check must not fire on the interface it is written against."""
    real_umat = _WRAPPER_HEAD.replace("the_model(", "the_model_variant(") + _UNCALLED_MODEL
    status = _anchor_issues(tmp_path, real_umat, "real")
    kinds = {row["kind"] for row in status.get("completion_issues", [])}
    assert "selected_routine_is_not_an_abaqus_umat" not in kinds


# --------------------------------------------------------------------------
# A stress path written against a Fortran module this source does not contain
# --------------------------------------------------------------------------

USES_A_MODULE = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     #rpl,ddsddt,drplde,drpldt,
     #stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     #ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,
     #celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      use TensorToolbox
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv),
     #ddsdde(ntens,ntens),ddsddt(ntens),drplde(ntens),
     #stran(ntens),dstran(ntens),time(2),predef(1),dpred(1),
     #props(nprops),coords(3),drot(3,3),dfgrd0(3,3),dfgrd1(3,3)
      stress(1:ntens) = asvoigt(dfgrd1,ntens)
      ddsdde(1,1) = props(1)
      return
      end
"""


def test_a_name_from_a_used_module_names_the_module_not_a_missing_shape(tmp_path):
    summary = _transform(tmp_path, USES_A_MODULE, "moduser")
    blockers = summary.get("blockers") or []
    assert blockers, summary
    named = [text for text in blockers if "ASVOIGT" in text]
    assert named, blockers
    assert "TENSORTOOLBOX" in named[0]
    assert "no confirmed shape" not in named[0]


def test_the_module_import_is_declared_unsupported_where_the_others_are(tmp_path):
    from umat_oti.fortran.scanner import analyze_fortran_source
    src = tmp_path / "moduser.f"
    src.write_text(USES_A_MODULE, encoding="utf-8")
    codes = {row.get("code") for row in
             (analyze_fortran_source(src).get("unsupported_features") or [])}
    assert "module_use" in codes


# --------------------------------------------------------------------------
# Four things the emitted Fortran was getting wrong underneath those messages
# --------------------------------------------------------------------------

def test_the_exponent_letter_of_a_real_literal_is_not_a_variable():
    """1.d-12 declared D_OTI, then rewrote the literal into 1.D_OTI-12."""
    from umat_oti.fortran.variables import _tokens
    assert "D" not in _tokens("xtol = 1.d-12")
    assert "E" not in _tokens("tol = 2.5e-7*scale")
    assert _tokens("xtol = 1.d-12") == {"XTOL"}
    # A variable really called D is still a variable.
    assert "D" in _tokens("y = d*2.0d0")
    assert _tokens("y = 1.0d0*alpha") == {"Y", "ALPHA"}


def test_a_trailing_comment_is_left_alone_by_the_rewriter():
    from umat_oti.transform.source_transform import _transform_executable_line
    line = "      cr_pos  = props(4)   ! critical stress for positive growth"
    out = _transform_executable_line(line, {"STRESS": "STRESS_OTI"}, "ONUMM6N1")
    assert out == line, out
    seeded = "      x = stress(1)   ! stress here"
    out = _transform_executable_line(seeded, {"STRESS": "STRESS_OTI"}, "ONUMM6N1")
    statement, comment = out.split("!", 1)
    assert "REAL(STRESS_OTI(1))" in statement, out
    assert comment == " stress here", out


def test_an_over_long_line_is_not_wrapped_through_its_comment():
    """A line beginning "     1growth" is a continuation, not a comment."""
    from umat_oti.transform.source_transform import _wrap_fixed_form_line
    line = "      cr_pos  = props(4)              ! critical stress for positive growth"
    assert len(line) > 72
    wrapped = _wrap_fixed_form_line(line).splitlines()
    assert wrapped[0] == "      cr_pos  = props(4)"
    assert all(part.startswith("C") for part in wrapped[1:]), wrapped
    assert "critical stress for positive growth" in " ".join(wrapped[1:])
    assert all(len(part) <= 72 for part in wrapped)


def test_a_synthesised_span_does_not_claim_lines_already_classified():
    from umat_oti.transform.source_transform import _spans_excluding
    assert _spans_excluding(1, 10, set()) == [(1, 10)]
    assert _spans_excluding(1, 10, {4, 5, 6}) == [(1, 3), (7, 10)]
    assert _spans_excluding(1, 10, {1, 10}) == [(2, 9)]
    assert _spans_excluding(1, 3, {1, 2, 3}) == []


NO_STRAIN_INCREMENT = _WRAPPER_HEAD.replace("the_model(", "the_model_variant(") + """
      subroutine the_model_variant(stress,statev,ddsdde,props,dfgrd1,
     #                             ntens,nstatv,nprops)
      implicit none
      integer ntens, nstatv, nprops, i, j
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 props(nprops), dfgrd1(3,3), detf
      detf = dfgrd1(1,1)*dfgrd1(2,2)*dfgrd1(3,3)
      do i = 1, ntens
        stress(i) = props(1)*(detf-1.d0)
      end do
      do i = 1, ntens
        do j = 1, ntens
          ddsdde(i,j) = props(1)/detf
        end do
      end do
      statev(1) = detf
      return
      end
"""


def test_a_routine_without_dstran_is_not_given_a_dstran_seed(tmp_path):
    """DSTRAN_OTI cannot be seeded where DSTRAN is not an argument.

    The material routine below is reached through the Abaqus wrapper and takes
    the deformation gradient. Emitting the strain-increment copy there read a
    dummy argument the routine does not have and assigned a shadow that was
    never declared; gfortran called both undeclared functions, in thirteen of
    the discovered sources.
    """
    summary = _transform(tmp_path, NO_STRAIN_INCREMENT, "nodstran")
    assert not summary.get("blockers"), summary
    text = (tmp_path / "out" / "nodstran_oti.f").read_text(encoding="utf-8")
    body = text[text.upper().index("SUBROUTINE THE_MODEL_VARIANT"):]
    assert "DSTRAN_OTI" not in body.upper(), [
        line for line in body.splitlines() if "DSTRAN_OTI" in line.upper()]
    # The deformation gradient is seeded instead, and the ordering checks are
    # then asked about the variable that was actually seeded.
    assert "DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1" in body
    checks = summary.get("semantic_checks") or {}
    assert checks.get("dstran_initialization_before_seed") is True, checks
    assert checks.get("dstran_seed_before_transformed_stress_update") is True, checks
    assert summary.get("transform_success") is True, summary.get("warnings")
