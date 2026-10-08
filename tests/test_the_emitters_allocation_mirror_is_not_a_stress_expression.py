"""The shadow's own ALLOCATE and zeroing loop are not stress expressions.

For an allocatable array the emitter mirrors the author's ALLOCATE for the
shadow and zeroes it with ``DO OTI_HI = LBOUND(X_OTI,1), ...``. Those lines
name a shadow but compute nothing, and when the author allocates before the
strain increment is complete they sat ahead of the seed and tripped
dstran_initialization_before_stress_use (mkhadijeh's ViscoelasticityCode3).
Rule (B20 RULES.md R4): ALLOCATE/DEALLOCATE of a shadow and the emitter's
OTI_H* zeroing loops are skipped by the stress-expression scan; nothing else is.
Canaries: a real use of a promoted value on the stress path is still found,
including one that merely follows an ALLOCATE.
"""
from pathlib import Path

import pytest

from _b20_support import transform_text, failed_checks
from umat_oti.transform.source_transform import _stress_expression_lines

ROLES = {"seed": {"DSTRAN"}, "promote": {"STRESS", "EPS"}, "constant": set(), "real": set()}
MAPPINGS = {"dstran": "DSTRAN", "stress": "STRESS", "dfgrd1": "DFGRD1"}

SOURCE = (Path(__file__).resolve().parents[2] / "discovery_cache" / "mkhadijeh26__UMAT_for_Viscoelastictiy" /
          "Fortran Code_Basic_Viscoelasticity" / "ABAQUS_DSR_EXAMPLE" / "ViscoelasticityCode3.f")


def _scan(*lines):
    return _stress_expression_lines(list(enumerate(lines, start=1)), ROLES, MAPPINGS)


def test_the_emitters_allocate_and_zeroing_loop_are_skipped():
    assert _scan(
        "      ALLOCATE (EPS_OTI(SIZE(EPS)))",
        "      IF (ALLOCATED(EPS)) ALLOCATE (EPS_OTI(SIZE(EPS)))",
        "      DO OTI_HI = LBOUND(EPS_OTI,1), UBOUND(EPS_OTI,1)",
        "      DEALLOCATE (EPS_OTI)",
    ) == []


def test_canary_a_real_use_on_the_stress_path_is_still_found():
    found = _scan(
        "      ALLOCATE (EPS_OTI(SIZE(EPS)))",
        "      STRESS_OTI(1) = EPS_OTI(1)*2.D0",
        "      CALL UPDATE_OTI(STRESS_OTI, EPS_OTI)",
    )
    assert [n for n, _ in found] == [2, 3]


@pytest.mark.skipif(not SOURCE.is_file(), reason="needs the discovery cache")
def test_the_viscoelastic_source_is_no_longer_refused_by_the_seed_order_guards(tmp_path):
    report = transform_text(tmp_path, SOURCE.read_text(), ".f")
    assert report["transform_success"], failed_checks(report)
