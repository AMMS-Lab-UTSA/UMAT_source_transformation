"""A file that states its own source form is believed over its extension.

Intel's ifort -- which is what Abaqus uses -- honours !DIR$ FREEFORM whatever
the file is called, so a .f carrying that directive really is free form.
Reading it as fixed finds no statements at all: every line begins in column 1,
so the whole file looks like a label field, and a source declaring
SUBROUTINE UMAT on its sixth line is recorded as not being a UMAT.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.fortran.normalize import declared_source_form, detect_source_form

FREE_BODY = (
    "!> Example UMAT\n"
    "subroutine umat(stress, statev, ddsdde, dstran, props) &\n"
    "  bind(c)\n"
    "  stress(1) = props(1) * dstran(1)\n"
    "end subroutine umat\n")


class TestAnExplicitDirectiveWins:
    def test_a_dot_f_declaring_freeform_is_free(self, tmp_path):
        text = "#include 'x.f90'\n!DIR$ FREEFORM\n" + FREE_BODY
        assert detect_source_form(tmp_path / "umat.f", text) == "free"

    def test_a_dot_f90_declaring_fixedform_is_fixed(self, tmp_path):
        text = "!DIR$ FIXEDFORM\n      SUBROUTINE UMAT(STRESS)\n      END\n"
        assert detect_source_form(tmp_path / "umat.f90", text) == "fixed"

    def test_the_c_prefixed_spelling_is_read_too(self, tmp_path):
        text = "CDIR$ FREEFORM\n" + FREE_BODY
        assert detect_source_form(tmp_path / "umat.f", text) == "free"

    def test_the_directive_is_matched_case_insensitively(self, tmp_path):
        text = "!dir$ freeform\n" + FREE_BODY
        assert detect_source_form(tmp_path / "umat.for", text) == "free"


class TestWithoutADirectiveNothingChanges:
    def test_a_plain_dot_f_is_still_fixed(self, tmp_path):
        text = "      SUBROUTINE UMAT(STRESS)\n      STRESS(1) = 1.D0\n      END\n"
        assert detect_source_form(tmp_path / "umat.f", text) == "fixed"

    def test_a_plain_dot_f90_is_still_free(self, tmp_path):
        assert detect_source_form(tmp_path / "umat.f90", FREE_BODY) == "free"

    def test_a_continuation_ampersand_alone_does_not_override_the_extension(self, tmp_path):
        """Guessing from an "&" would put the fixed-form corpus at risk.

        Fixed-form Fortran may legally end a line with & inside a character
        literal, and the two hundred genuinely fixed-form sources must not be
        reclassified to rescue the handful that say what they are.
        """
        text = "      WRITE(6,*) 'ends with an ampersand &'\n      END\n"
        assert detect_source_form(tmp_path / "umat.f", text) == "fixed"

    def test_declared_source_form_reports_none_when_nothing_is_declared(self):
        assert declared_source_form("      SUBROUTINE UMAT(X)\n      END\n") is None


def test_a_directive_far_below_the_header_is_still_found():
    """These files put #include lines above the directive."""
    text = "\n".join(f"#include 'mod{i}.f90'" for i in range(12)) + "\n!DIR$ FREEFORM\n" + FREE_BODY
    assert declared_source_form(text) == "free"


CACHE = Path("/home/ammslab3/softwarex_work/discovery_cache")


@pytest.mark.skipif(not CACHE.is_dir(), reason="no discovery cache on this machine")
def test_a_real_source_that_declares_freeform_is_read_as_a_umat():
    from umat_oti.fortran.scanner import analyze_fortran_source

    candidate = CACHE / "BristolCompositesInstitute__abaci" / "example" / "src" / "umat.f"
    if not candidate.is_file():
        pytest.skip("that source is not in this cache")
    analysis = analyze_fortran_source(candidate)
    assert analysis.get("has_subroutine_umat") is True
