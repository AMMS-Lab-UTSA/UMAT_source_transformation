"""Abaqus passes a UMAT its arguments by POSITION; the transform must too.

sahmotaman's TMM-FE sources declare ``subroutine umat(sigma, sv, C, sse, ...)``:
the 37 arguments Abaqus passes, under the author's own names. The transform
used to look STRESS and DDSDDE up by name, found neither, and refused. The rule
(B17 notes, written before the code): with exactly 37 dummies and neither
STRESS nor DDSDDE among them, dummy k IS the k-th Abaqus argument; inside that
routine the dummies take the Abaqus names and any other identifier already
carrying an Abaqus name moves to NAME_USR first.

Planted-error canary: the same check, run against a table with two positions
swapped, must FAIL.
"""
import shutil
from pathlib import Path

import pytest

from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.fortran.symbols import find_routine
from umat_oti.transform import interface_by_position as ibp

#: The Abaqus UMAT argument order, written out independently of the module
#: under test (Abaqus User Subroutines Reference Guide, UMAT).
ORACLE = ("STRESS STATEV DDSDDE SSE SPD SCD RPL DDSDDT DRPLDE DRPLDT STRAN DSTRAN "
          "TIME DTIME TEMP DTEMP PREDEF DPRED CMNAME NDI NSHR NTENS NSTATV PROPS "
          "NPROPS COORDS DROT PNEWDT CELENT DFGRD0 DFGRD1 NOEL NPT LAYER KSPT "
          "KSTEP KINC").split()

AUTHOR = ("sig sv dd sse_ spd_ scd_ rpl_ ddt dre drt eps deps tm dt tmp dtmp pf dpf "
          "cmn ndi_ nshr_ nt nsv pr npr xc drot_ pnew cel f0 f1 nel npt_ lay kspt_ "
          "kstep_ kinc_").split()

FREE = """subroutine umat(%(args)s)
  implicit none
  character(len=80) :: cmn
  integer :: ndi_, nshr_, nt, nsv, npr, nel, npt_, lay, kspt_, kstep_, kinc_
  real(8) :: sig(nt), sv(nsv), dd(nt,nt), sse_, spd_, scd_, rpl_, ddt(nt), dre(nt), drt
  real(8) :: eps(nt), deps(nt), tm(2), dt, tmp, dtmp, pf(1), dpf(1), pr(npr), xc(3)
  real(8) :: drot_(3,3), pnew, cel, f0(3,3), f1(3,3)
  real(8) :: temp, layer
  integer :: i, j
  temp = pr(2)
  layer = 2.0d0
  dd = 0.0d0
  do i = 1, 3
    do j = 1, 3
      dd(i,j) = pr(1)*temp*0.1d0
    end do
    dd(i,i) = pr(1)
  end do
  do i = 4, 6
    dd(i,i) = pr(1)*layer*0.25d0
  end do
  do i = 1, nt
    do j = 1, nt
      sig(i) = sig(i) + dd(i,j)*deps(j)
    end do
  end do
  sv(1) = sv(1) + sig(1)*0.0d0
  write (*, '(a)') 'x .f. t'  ! tm dt temp
end subroutine umat
"""


def _args():
    return ", ".join(AUTHOR)


def _routine(tmp_path, text, name="m.f90"):
    path = tmp_path / name
    path.write_text(text)
    parsed = parse_fortran_file(path)
    return parsed, find_routine(parsed, "UMAT")


def _rewrite(tmp_path, text, name="m.f90"):
    parsed, routine = _routine(tmp_path, text, name)
    return ibp.rewrite_umat_interface_by_position(
        parsed.text, parsed.form, routine)


def _dummies_after(tmp_path, outcome, name="after.f90"):
    path = tmp_path / name
    path.write_text(outcome.text)
    return tuple(a.upper() for a in find_routine(parse_fortran_file(path), "UMAT").args)


def test_the_table_is_the_abaqus_argument_order():
    assert tuple(ibp.ABAQUS_UMAT_ARGUMENTS) == tuple(ORACLE)
    assert len(ORACLE) == 37 and len(set(ORACLE)) == 37


def test_each_dummy_takes_the_name_of_its_position(tmp_path):
    outcome = _rewrite(tmp_path, FREE % {"args": _args()})
    assert outcome.applied and not outcome.refused
    assert _dummies_after(tmp_path, outcome) == tuple(ORACLE)


def test_a_local_that_already_carries_an_abaqus_name_is_moved_aside(tmp_path):
    outcome = _rewrite(tmp_path, FREE % {"args": _args()})
    assert outcome.clash_map == {"TEMP": "TEMP_USR", "LAYER": "LAYER_USR"}
    text = outcome.text.lower()
    assert "temp_usr = props(2)" in text.replace("pr(2)", "props(2)")
    assert "layer_usr = 2.0d0" in text


def test_strings_comments_and_dotted_operators_are_left_alone(tmp_path):
    outcome = _rewrite(tmp_path, FREE % {"args": _args()})
    assert "write (*, '(a)') 'x .f. t'  ! tm dt temp" in outcome.text


def test_a_source_that_names_stress_or_ddsdde_is_returned_untouched(tmp_path):
    named = FREE % {"args": ", ".join(ORACLE)}
    parsed, routine = _routine(tmp_path, named)
    outcome = ibp.rewrite_umat_interface_by_position(parsed.text, parsed.form, routine)
    assert not outcome.applied and not outcome.refused and outcome.text == parsed.text


def test_a_routine_that_is_not_37_arguments_long_is_not_rewritten(tmp_path):
    parsed, routine = _routine(
        tmp_path, "subroutine umat(a, b, c, d)\n  real(8) :: a, b, c, d\nend subroutine umat\n")
    outcome = ibp.rewrite_umat_interface_by_position(parsed.text, parsed.form, routine)
    assert not outcome.applied and not outcome.refused


def test_a_name_used_as_a_keyword_argument_is_refused_not_guessed(tmp_path):
    text = FREE % {"args": _args()}
    text = text.replace("  temp = pr(2)\n", "  temp = pr(2)\n  call helper(dt=1.0d0)\n")
    outcome = _rewrite(tmp_path, text)
    assert not outcome.applied and "keyword" in outcome.refused


def test_fixed_form_that_would_pass_column_72_is_refused(tmp_path):
    names = ["sig", "sv", "dd"] + [f"a{k}" for k in range(4, 38)]
    head = "      subroutine umat(" + ", ".join(names[:5]) + ",\n"
    rest = [f"     1 {n}," for n in names[5:-1]] + [f"     1 {names[-1]})"]
    body = ("      real*8 sig(6), sv(2), dd(6,6)\n"
            "      sig(1) = dd(1,1)*sv(1) + dd(1,2)*sv(2) + dd(1,3)*sv(1) + 1.0d0\n"
            "      end\n")
    outcome = _rewrite(tmp_path, head + "\n".join(rest) + "\n" + body, "m.f")
    assert not outcome.applied and "column 72" in outcome.refused


def test_the_checking_oracle_can_fail(tmp_path, monkeypatch):
    """Planted error: two positions swapped in the table must be caught."""
    wrong = list(ORACLE)
    wrong[0], wrong[1] = wrong[1], wrong[0]          # STATEV where STRESS belongs
    monkeypatch.setattr(ibp, "ABAQUS_UMAT_ARGUMENTS", tuple(wrong))
    assert tuple(ibp.ABAQUS_UMAT_ARGUMENTS) != tuple(ORACLE)
    outcome = _rewrite(tmp_path, FREE % {"args": _args()})
    assert outcome.applied
    assert _dummies_after(tmp_path, outcome) != tuple(ORACLE)


def _build_contract_transform(tmp_path, text, suffix):
    """The corpus recipe: stage, scaffold the contract from the scan, transform."""
    import json

    from umat_oti.app.engine import _build_contract
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / f"material{suffix}"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    config, _finite = _build_contract("material", "auto", "STRESS", "DDSDDE", 6, 1, source)
    (tmp_path / "contract.json").write_text(json.dumps(config))
    return run_transformation(tmp_path / "contract.json", tmp_path / "out")


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_the_renamed_umat_transforms_and_its_tangent_matches_the_authors(tmp_path, monkeypatch):
    """Behavioural: primal bit-identical to the author's routine, DDSDDE against its FD."""
    import _transform_vs_original as harness

    monkeypatch.setattr(harness, "transform", _build_contract_transform)
    text = FREE % {"args": _args()}
    output = harness.check_against_original(
        tmp_path, text, ".f90", [("subroutine umat(", "subroutine umatorig("),
                                 ("end subroutine umat", "end subroutine umatorig")],
        ["1000.0d0", "0.3d0"])
    generated = (output / "material_oti.f90") if (output / "material_oti.f90").exists() else None
    assert output.is_dir() and (generated is None or generated.is_file())


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_wrong_position_table_makes_the_behavioural_gate_fail(tmp_path, monkeypatch):
    """Planted error, end to end: DSTRAN and STRAN swapped in the table.

    The transform seeds the wrong input, so the tangent (or the transform
    itself) no longer agrees with the author's routine and the same gate that
    passes above must not.
    """
    import _transform_vs_original as harness

    wrong = list(ORACLE)
    i, j = wrong.index("STRAN"), wrong.index("DSTRAN")
    wrong[i], wrong[j] = wrong[j], wrong[i]
    monkeypatch.setattr(ibp, "ABAQUS_UMAT_ARGUMENTS", tuple(wrong))
    monkeypatch.setattr(harness, "transform", _build_contract_transform)
    with pytest.raises(Exception):
        harness.check_against_original(
            tmp_path, FREE % {"args": _args()}, ".f90",
            [("subroutine umat(", "subroutine umatorig("),
             ("end subroutine umat", "end subroutine umatorig")],
            ["1000.0d0", "0.3d0"])
