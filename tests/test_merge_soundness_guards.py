"""Two ways a change can turn a loud build failure into a quiet wrong number.

Both were found by adversarial review of fixes that were otherwise correct,
and both share a shape: the transform reports success, the file compiles, no
warning is emitted, and a number the UMAT returns is wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.core.diagnostics import (
    _commented_line_numbers, scan_unsupported_features,
)
from umat_oti.fortran.scanner import analyze_fortran_source
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.transform.source_transform import _claimed_lines_whose_result_is_dead


class TestALiveAssignmentIsNotCommentedOut:
    """The old-tangent classification is a guess; where it is too wide it
    covers a statement the rest of the routine still depends on."""

    SOURCE = "\n".join(f"      line{n}" for n in range(1, 4))

    def test_a_claimed_line_read_later_is_released(self):
        source = ("      detf = dfgrd1(1,1)\n"
                  "      ddsdde(1,1) = detf\n"
                  "      sse = detf * 2.d0\n")
        # Line 1 assigns detf; line 3 is outside the claim and reads it.
        released = _claimed_lines_whose_result_is_dead(source, {1, 2}, (1, 3))
        assert 1 not in released, "detf is still read live and must stay transformed"

    def test_a_claimed_line_read_only_inside_the_claim_stays_claimed(self):
        """An intermediate feeding only the old tangent is genuinely dead."""
        source = ("      vol = k * detfe\n"
                  "      ddsdde(1,1) = vol\n"
                  "      stress(1) = detfe\n")
        released = _claimed_lines_whose_result_is_dead(source, {1, 2}, (1, 3))
        assert released == {1, 2}, "vol feeds only the tangent block"

    def test_a_line_outside_the_span_is_untouched(self):
        source = "      a = 1.d0\n      b = a\n"
        assert _claimed_lines_whose_result_is_dead(source, {1}, (2, 2)) == {1}

    def test_nothing_claimed_returns_nothing_claimed(self):
        assert _claimed_lines_whose_result_is_dead("      a = 1.d0\n", set(), (1, 1)) == set()


GROWTH = Path("/home/ammslab3/softwarex_work/discovery_cache/mholla__growth/umats")


@pytest.mark.skipif(not GROWTH.exists(), reason="discovery cache is not present")
@pytest.mark.parametrize("name", ["umat_iso_morph_Abaqus.f",
                                  "umat_area_morph_Abaqus.f",
                                  "umat_fiber_morph_Abaqus.f"])
def test_detf_keeps_an_active_assignment(tmp_path, name):
    """SSE was being computed from a variable whose only assignment was commented."""
    from umat_oti.corpus.cli import _write_aba_param_stub
    src = tmp_path / name
    src.write_text((GROWTH / name).read_text(errors="replace"), encoding="utf-8")
    _write_aba_param_stub(tmp_path)
    (tmp_path / "out").mkdir()
    _write_aba_param_stub(tmp_path / "out")
    config, _ = _build_contract("g", "auto", "STRESS", "DDSDDE", 6, 1, src)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    run_transformation(cfg, tmp_path / "out", TransformationOptions(compile_generated=False))
    text = next((tmp_path / "out").glob("*_oti.f")).read_text(encoding="utf-8")
    active = [l for l in text.splitlines() if not l.lstrip().upper().startswith("C")]
    assigns = [l for l in active
               if l.split("=")[0].strip().lower() == "detf" and "=" in l]
    reads = [l for l in active if "detf" in l.lower()
             and "detfe" not in l.lower() and l not in assigns]
    if reads:
        assert assigns, f"{name}: detf is read but never assigned in an active line"


class TestACommentIsNotAConstruct:
    """The logical line has already lost its comment marker by the time these
    patterns see it, so prose reads as a statement."""

    def test_prose_containing_the_word_use_is_not_a_module_import(self):
        source = "      x = 1.d0\n!I use Newton-Raphson to retrieve the state\n"
        lines = tuple(_logical(source))
        features = scan_unsupported_features(lines, (), source, "fixed")
        assert not [f for f in features if f.code == "module_use"]

    def test_a_real_use_statement_is_still_reported(self):
        source = "      use materials\n      x = 1.d0\n"
        lines = tuple(_logical(source))
        features = scan_unsupported_features(lines, (), source, "fixed")
        assert [f for f in features if f.code == "module_use"]

    def test_a_commented_out_data_statement_is_not_a_data_statement(self):
        source = "C     data x/1.0/\n      y = 1.d0\n"
        lines = tuple(_logical(source))
        assert not [f for f in scan_unsupported_features(lines, (), source, "fixed")
                    if f.code == "data"]

    def test_the_column_one_rule_is_fixed_form_only(self):
        """Free-form "c = 1.0" assigns to a variable named c."""
        assert 1 not in _commented_line_numbers("c = 1.0\n", "free")
        assert 1 in _commented_line_numbers("c a fixed-form comment\n", "fixed")

    def test_a_use_of_a_module_defined_in_the_same_file_is_resolvable(self, tmp_path):
        source = (
            "module matprops\n"
            "  implicit none\n"
            "  real(8), parameter :: half = 0.5d0\n"
            "end module matprops\n"
            "\n"
            "subroutine umat(stress, dstran, props, ntens, nprops)\n"
            "  use matprops\n"
            "  implicit none\n"
            "  integer :: ntens, nprops, k1\n"
            "  real(8) :: stress(ntens), dstran(ntens), props(nprops)\n"
            "  do k1 = 1, ntens\n"
            "    stress(k1) = stress(k1) + props(1)*dstran(k1)*half\n"
            "  end do\n"
            "end subroutine umat\n")
        path = tmp_path / "selfmod.f90"
        path.write_text(source, encoding="utf-8")
        analysis = analyze_fortran_source(path)
        codes = {f.get("code") for f in (analysis.get("unsupported_features") or [])}
        assert "module_use" not in codes


def _logical(source: str):
    from umat_oti.core.model import FortranLogicalLine
    for number, raw in enumerate(source.splitlines(), start=1):
        text = raw
        if raw[:1] in ("c", "C", "*"):
            text = raw[1:]
        elif raw.lstrip().startswith("!"):
            text = raw.lstrip()[1:]
        yield FortranLogicalLine(text=text, line_numbers=(number,))
