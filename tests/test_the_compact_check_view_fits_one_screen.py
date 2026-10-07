"""The compact default view of the intake: short, plain, nothing hidden that needs you."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app.check_compact import DETAILS_HINT, compact_intake   # noqa: E402
from umat_oti.app.unified_app import jargon_in                         # noqa: E402

pytestmark = pytest.mark.unit

TOY = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1 DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,
     2 NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,
     3 NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),PROPS(NPROPS),
     1 DSTRAN(NTENS)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)
      END DO
      RETURN
      END
"""


def _scan(tmp_path, deck=None):
    spec = importlib.util.spec_from_file_location("scan_for_compact", REPO / "tools" / "intake_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    src = tmp_path / "toy.for"
    src.write_text(TOY)
    return mod.scan(src, deck)


def test_the_view_is_short_and_points_to_the_details(tmp_path):
    found = _scan(tmp_path)
    text = compact_intake(found)
    lines = text.splitlines()
    assert len(lines) <= 14, lines
    assert lines[0].startswith("Files: toy.for")
    assert DETAILS_HINT in text and "--details" in text


def test_what_still_needs_the_user_is_never_hidden(tmp_path):
    found = _scan(tmp_path)
    text = compact_intake(found)
    assert found.needs_user(), "the toy has no deck, so the constants are needed"
    assert "Needs you:" in text and found.item("props_values").ask in text


def test_found_constants_show_names_values_and_where_from(tmp_path):
    found = _scan(tmp_path)
    scan = sys.modules["scan_for_compact"]
    ev = [{"file": "toy.inp", "line": 7, "text": "200000.0, 0.3"}]
    for item in found.items:
        if item.key == "props_values":
            item.status, item.value, item.evidence = "FOUND", [200000.0, 0.3], ev
            item.needs_user = False
    text = compact_intake(found)
    assert "Constants (2): EMOD=200000, ENU=0.3 (toy.inp:7)" in text


def test_no_expert_vocabulary_in_the_compact_view(tmp_path):
    text = compact_intake(_scan(tmp_path))
    text = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", "NAME", text)
    assert jargon_in([text]) == []
