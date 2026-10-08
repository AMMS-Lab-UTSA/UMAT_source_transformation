"""A STATEV that received a shadow is copied in and written back.

awhelanUCD's Lemaitre UMAT hands STATEV to ROTSIG beside promoted arrays, so
the emitter gave STATEV a shadow; the shadow was neither loaded from STATEV nor
stored back, and the semantic check state_shadow_carries_the_state refused the
file (the 'HETVAL-style routine' reading was wrong: the file holds a full UMAT
after the HETVAL). Rule (B20 RULES.md R3): a state array with a shadow is
promoted like any other, so it is loaded at entry and stored at exit.
Canary: the check that refuses a state shadow that is never loaded stays in
force (tested by its own existing tests); here the emitted text must show both
the load and the store-back, not merely the absence of the refusal.
"""
import re
from pathlib import Path

import pytest

from _b20_support import transform_text, failed_checks

SOURCE = (Path(__file__).resolve().parents[2] / "discovery_cache" /
          "awhelanUCD__Lemaitre-damage-UMAT-Public" / "HETVAL_nonLocalLemaitre" /
          "HETVAL_lemaitreDamageNonLocal.f")


@pytest.mark.skipif(not SOURCE.is_file(), reason="needs the discovery cache")
def test_the_state_shadow_is_loaded_and_stored_back(tmp_path):
    report = transform_text(tmp_path, SOURCE.read_text(), ".f")
    assert report["transform_success"], failed_checks(report)
    text = Path(report["transformed_source"]).read_text()
    assert re.search(r"STATEV_OTI\(OTI_I\)\s*=\s*STATEV\(OTI_I\)", text, re.IGNORECASE)
    assert re.search(r"STATEV\(OTI_I\)\s*=\s*REAL\(STATEV_OTI\(OTI_I\)\)", text, re.IGNORECASE)
