"""The compile hint must name the form the transform actually wrote.

A free-form source is rewritten as free-form and was being handed to gfortran
with ``-ffixed-form``, which reads columns 1 to 5 as a statement label field.
The failure lands on line 1, column 1, against a subroutine header that is
perfectly correct:

    1 | SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, ...
      | 1
    Error: Non-numeric character in statement label at (1)

Four discovered sources failed this way, and the message points at the source
rather than at the flag that caused it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

FREE_FORM_UMAT = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsdct, &
    drplde, drpldt, stran, dstran, time, dtime, temp, dtemp, predef, dpred, &
    cmname, ndi, nshr, ntens, nstatv, props, nprops, coords, drot, pnewdt, &
    celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  implicit none
  character(80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens)
  real(8) :: sse, spd, scd, rpl, ddsdct(ntens), drplde(ntens), drpldt
  real(8) :: stran(ntens), dstran(ntens), time(2), dtime, temp, dtemp
  real(8) :: predef(1), dpred(1), props(nprops), coords(3), drot(3, 3)
  real(8) :: pnewdt, celent, dfgrd0(3, 3), dfgrd1(3, 3)
  integer :: i, j
  real(8) :: emod, enu, ebulk3, eg2, eg, elam
  emod = props(1)
  enu = props(2)
  ebulk3 = emod / (1.0d0 - 2.0d0 * enu)
  eg2 = emod / (1.0d0 + enu)
  eg = eg2 / 2.0d0
  elam = (ebulk3 - eg2) / 3.0d0
  do i = 1, ntens
    do j = 1, ntens
      ddsdde(j, i) = 0.0d0
    end do
  end do
  do i = 1, ndi
    do j = 1, ndi
      ddsdde(j, i) = elam
    end do
    ddsdde(i, i) = eg2 + elam
  end do
  do i = ndi + 1, ntens
    ddsdde(i, i) = eg
  end do
  do i = 1, ntens
    do j = 1, ntens
      stress(i) = stress(i) + ddsdde(i, j) * dstran(j)
    end do
  end do
  return
end subroutine umat
"""


def _run_transform(tmp_path: Path) -> Path:
    from umat_oti.services.transformation import (  # noqa: PLC0415
        TransformationOptions, run_transformation,
    )
    from umat_oti.validation.tangent_validation import (  # noqa: PLC0415
        TangentCase, _contract,
    )
    source = tmp_path / "free_umat.f90"
    source.write_text(FREE_FORM_UMAT, encoding="utf-8")
    case = TangentCase(name="free_umat", source_path=source,
                       props=(210000.0, 0.3),
                       dstran_per_increment=(1.0e-4,) + (0.0,) * 5,
                       n_increments=2, ntens=6, nstatv=1)
    contract = tmp_path / "c.json"
    contract.write_text(json.dumps(_contract(case, source), indent=2),
                        encoding="utf-8")
    out = tmp_path / "oti"
    run_transformation(contract, out, TransformationOptions(compile_generated=False))
    return out / "compile_hint.sh"


class TestAFreeFormSourceIsCompiledAsFreeForm:
    def test_the_hint_does_not_say_fixed(self, tmp_path):
        hint = _run_transform(tmp_path)
        assert hint.is_file()
        line = [row for row in hint.read_text().splitlines()
                if "transformed_umat.o" in row]
        assert line, "the hint names no transformed unit"
        assert "-ffixed-form" not in line[0]
        assert "-ffree-form" in line[0]

    def test_the_generated_file_really_is_free_form(self, tmp_path):
        # If this ever emitted fixed-form text the test above would be
        # asserting the wrong flag rather than the right one.
        from umat_oti.fortran.normalize import detect_source_form  # noqa: PLC0415

        hint = _run_transform(tmp_path)
        generated = next(p for p in hint.parent.glob("*_oti.f90"))
        assert detect_source_form(generated, generated.read_text()) == "free"
