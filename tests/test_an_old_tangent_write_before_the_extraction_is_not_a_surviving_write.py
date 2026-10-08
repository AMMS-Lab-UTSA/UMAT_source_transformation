"""old_ddsdde_assignments_disabled looks only at the selected routine, and only at writes that survive.

The guard refuses a source in which an original assignment to DDSDDE survives
after the OTI extraction, because that write would overwrite the OTI tangent.
Two things made it refuse sources it should not: it matched ``DDSDDE=DE`` by
text in other routines of the file, whose DDSDDE is that routine's own
variable, and it counted a write that comes BEFORE the full-array extraction
as surviving, though the extraction overwrites every entry of DDSDDE after it.
Rule (B20 notes, written first): only the selected routine is searched; a write
between the last stress update and the extraction is harmless when nothing
between them can leave the routine early (RETURN, any GO TO, ENTRY, STOP,
arithmetic IF, alternate RETURN, ERR=/END=/EOR=); writes at or after the
extraction are still refused.

Real sources: cfietek's JC-damage UMAT (plastic-branch tangent written after
the last stress update). Planted errors: the same source with an early exit
planted before that tangent must still be refused.
"""
from pathlib import Path

import pytest

from _b20_support import transform_text, failed_checks

CACHE = Path(__file__).resolve().parents[2] / "discovery_cache"
CFIETEK = (CACHE / "cfietek__Damage-Modeling-in-Metal-Additive-Manufacturing-Process-Simulations"
           / "UMAT-JC-C-T-Damage.for")
PLASTIC_TANGENT = "      DO 220 K1=1,NDI"

needs_cache = pytest.mark.skipif(not CFIETEK.is_file(), reason="needs the discovery cache")


def _with_exit_before_the_plastic_tangent(exit_statement, label=None):
    text = CFIETEK.read_text()
    assert text.count(PLASTIC_TANGENT) == 1
    text = text.replace(PLASTIC_TANGENT, exit_statement + "\n" + PLASTIC_TANGENT)
    if label:
        text = text.replace("      ENDIF !Yield Criterian If Statement",
                            f"  {label} CONTINUE\n      ENDIF !Yield Criterian If Statement")
    return text


@needs_cache
def test_the_published_source_is_no_longer_refused(tmp_path):
    report = transform_text(tmp_path, CFIETEK.read_text(), ".for")
    assert report["transform_success"], failed_checks(report)


MANDEL = CACHE / "mholla__growth" / "umats" / "umat_iso_Mandel_v2.f"


@pytest.mark.skipif(not MANDEL.is_file(), reason="needs the discovery cache")
def test_mhollas_growth_umat_is_no_longer_refused(tmp_path):
    report = transform_text(tmp_path, MANDEL.read_text(), ".f")
    assert report["transform_success"], failed_checks(report)


@needs_cache
@pytest.mark.parametrize("exit_statement,label", [
    ("      IF (DTIME.LT.0.D0) RETURN", None),
    ("      IF (DTIME.LT.0.D0) GO TO 777", "777"),
    ("      IF (DTIME.LT.0.D0) STOP", None),
])
def test_canary_an_early_exit_before_the_tangent_is_still_refused(tmp_path, exit_statement, label):
    report = transform_text(tmp_path, _with_exit_before_the_plastic_tangent(exit_statement, label), ".for")
    assert not report["transform_success"]
    assert "old_ddsdde_assignments_disabled" in failed_checks(report)
