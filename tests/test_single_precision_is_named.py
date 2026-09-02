"""A source that declares single precision is reference-limited, not wrong.

``real E, nu, lambda, mu, S(6), D1(6,6)`` is a request for single precision,
and a UMAT that makes it computes its stress to about seven digits. The OTI
type is built over doubles, so a promoted variable comes back in double
precision and the two builds stop computing the same function. The difference
is real and it is around 1e-8 -- close enough to nothing that it reads as a
rounding mystery, and far enough from nothing that it fails every parity test.

Eight sources in one batch reported it as "the builds disagree by 4.043e-08",
which is true and tells a reader nothing about whether the transform is
broken. The verdict does not change here: these sources are still not
verified, because a single-precision original cannot resolve a derivative
finely enough to check a double-precision one. What changes is that the report
says so.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.validation.tangent_validation import (  # noqa: E402
    TangentCase, _single_precision_explanation, single_precision_names,
)


class TestReadingTheDeclaration:
    def test_a_bare_real_is_single_precision(self):
        assert single_precision_names("      real E, nu, S(6)\n") == ("E", "NU", "S")

    def test_real_star_eight_is_not(self):
        assert single_precision_names("      real*8 E, nu\n") == ()

    def test_a_kind_selector_is_not(self):
        assert single_precision_names("      real(8) :: E\n") == ()
        assert single_precision_names("      real(kind=8) :: E\n") == ()

    def test_double_precision_is_not(self):
        assert single_precision_names("      double precision E\n") == ()

    def test_a_comment_is_not_a_declaration(self):
        assert single_precision_names("c     real E, nu\n") == ()

    def test_a_trailing_comment_is_stripped(self):
        assert single_precision_names("      real E   ! the modulus\n") == ("E",)

    def test_each_name_is_reported_once(self):
        assert single_precision_names("      real E\n      real E, F\n") == ("E", "F")


class TestExplainingTheDivergence:
    def _case(self, tmp_path, text: str) -> TangentCase:
        source = tmp_path / "u.f"
        source.write_text(text, encoding="utf-8")
        return TangentCase(name="u", source_path=source, props=(1.0,),
                           dstran_per_increment=(1.0e-4, 0, 0, 0, 0, 0),
                           n_increments=2, ntens=6, nstatv=1)

    def test_a_divergence_at_that_scale_is_explained(self, tmp_path):
        case = self._case(tmp_path, "      real E, S(6)\n")
        reason = _single_precision_explanation(case, 4.043e-08)
        assert "single precision" in reason
        assert "reference-limited rather than verified" in reason

    def test_a_divergence_far_beyond_it_is_not_explained_away(self, tmp_path):
        # A defect must not borrow this excuse. 1e-3 is not rounding.
        case = self._case(tmp_path, "      real E, S(6)\n")
        assert _single_precision_explanation(case, 1.0e-3) == ""

    def test_a_double_precision_source_gets_no_excuse(self, tmp_path):
        case = self._case(tmp_path, "      real*8 E, S(6)\n")
        assert _single_precision_explanation(case, 4.043e-08) == ""

    def test_an_unreadable_source_gets_no_excuse(self, tmp_path):
        case = TangentCase(name="u", source_path=tmp_path / "missing.f",
                           props=(1.0,), dstran_per_increment=(1.0e-4,) + (0,) * 5,
                           n_increments=2, ntens=6, nstatv=1)
        assert _single_precision_explanation(case, 4.043e-08) == ""

    def test_it_names_the_variables_it_read(self, tmp_path):
        case = self._case(tmp_path, "      real LAMBDA, MU\n")
        assert "LAMBDA" in _single_precision_explanation(case, 1.0e-8)


class TestTheVerdictIsUnchanged:
    """Naming a cause is not forgiving it. The gate keeps its threshold."""

    def _parity(self, tmp_path, worst_relative: float, declaration: str):
        import csv  # noqa: PLC0415

        from umat_oti.validation.tangent_validation import _primal_parity  # noqa: PLC0415
        source = tmp_path / "u.f"
        source.write_text(declaration, encoding="utf-8")
        case = TangentCase(name="u", source_path=source, props=(1.0,),
                           dstran_per_increment=(1.0e-4,) + (0.0,) * 5,
                           n_increments=1, ntens=1, nstatv=1)
        primal = tmp_path / "primal.csv"
        with primal.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["increment", "stress_1", "statev_1"])
            writer.writerow([1, repr(1.0 + worst_relative), "0.0"])

        class _Original:
            stress = [[1.0]]
        return _primal_parity(_Original(), primal, case)

    def test_a_single_precision_source_still_fails_parity(self, tmp_path):
        verdict = self._parity(tmp_path, 4.0e-08, "      real E, S(6)\n")
        assert verdict["agrees"] is False
        assert verdict["reference_limited_by"] == "source_declared_single_precision"

    def test_a_double_precision_source_fails_the_same_way(self, tmp_path):
        verdict = self._parity(tmp_path, 4.0e-08, "      real*8 E, S(6)\n")
        assert verdict["agrees"] is False
        assert "reference_limited_by" not in verdict

    def test_agreement_below_the_threshold_is_unaffected(self, tmp_path):
        verdict = self._parity(tmp_path, 1.0e-12, "      real E, S(6)\n")
        assert verdict["agrees"] is True
        assert "reference_limited_by" not in verdict


class TestAComponentTooSmallToCompare:
    """A structural zero holds rounding, and two roundings differ by 100%.

    One source's shear component is exactly 0.0 in both builds for five
    increments, then reads -9.3e-11 in one and 1.9e-2 in the other -- two
    parts in ten billion of that increment's largest stress. Scored against
    its own magnitude that is a 100% disagreement, and it was the whole of
    that source's headline "worst relative difference 1.000e+00" while every
    component large enough to compare agreed to eight digits.

    The verdict does not change: a parity this weak is not evidence either
    way, and the source stays unverified. What changes is that the report
    distinguishes "the builds disagree about the response" from "the builds
    differ only where neither of them resolves anything".
    """

    def _parity(self, tmp_path, components, original):
        import csv  # noqa: PLC0415

        from umat_oti.validation.tangent_validation import _primal_parity  # noqa: PLC0415
        source = tmp_path / "u.f"
        source.write_text("      real*8 X\n", encoding="utf-8")
        case = TangentCase(name="u", source_path=source, props=(1.0,),
                           dstran_per_increment=(1.0e-4,) + (0.0,) * 5,
                           n_increments=1, ntens=len(components), nstatv=1)
        primal = tmp_path / "primal.csv"
        with primal.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["increment"]
                            + [f"stress_{i}" for i in range(1, len(components) + 1)]
                            + ["statev_1"])
            writer.writerow([1] + [repr(v) for v in components] + ["0.0"])

        class _Original:
            stress = [list(original)]
        return _primal_parity(_Original(), primal, case)

    def test_a_negligible_component_is_named_as_unresolvable(self, tmp_path):
        verdict = self._parity(tmp_path,
                               [3.0e8, -9.28e-11], [3.0e8, 1.85e-2])
        assert verdict["agrees"] is False
        assert verdict["reference_limited_by"] == "components_below_the_resolved_response"
        assert "too small to compare" in verdict["reason"]

    def test_a_real_disagreement_is_not_excused_by_it(self, tmp_path):
        # Both components are a large fraction of the response, so the
        # difference is about the response and must not borrow this reason.
        verdict = self._parity(tmp_path, [3.0e8, 1.0e8], [3.0e8, 1.2e8])
        assert verdict["agrees"] is False
        assert "reference_limited_by" not in verdict

    def test_a_negligible_component_does_not_make_it_agree(self, tmp_path):
        verdict = self._parity(tmp_path, [3.0e8, -9.28e-11], [3.0e8, 1.85e-2])
        assert verdict["agrees"] is False

    def test_the_headline_number_still_reports_the_worst(self, tmp_path):
        verdict = self._parity(tmp_path, [3.0e8, -9.28e-11], [3.0e8, 1.85e-2])
        assert verdict["worst_relative"] > 0.99
        assert verdict["worst_relative_resolvable"] < 1.0e-9

    def test_agreement_everywhere_is_still_agreement(self, tmp_path):
        verdict = self._parity(tmp_path, [3.0e8, 1.0], [3.0e8, 1.0])
        assert verdict["agrees"] is True
