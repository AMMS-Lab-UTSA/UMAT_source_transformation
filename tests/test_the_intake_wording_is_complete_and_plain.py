"""The plain-language wording the intake scan reads (app/intake_text.py)."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app.intake_text import NEEDS                    # noqa: E402
from umat_oti.app.refusal_cards import FLAGS_USED             # noqa: E402
from umat_oti.app.unified_app import jargon_in                # noqa: E402

pytestmark = pytest.mark.unit
FIELDS = {"routine": {"why"}, "element": {"why"}, "props_values": {"slots"},
          "helpers": {"names"}, "includes": {"names"}, "modules": {"names"}}
WHOSE = {"you or the author", "you", "the author of this UMAT", "this program"}


def _scanner_needs():
    spec = importlib.util.spec_from_file_location(
        "intake_scan_for_text_test", REPO / "tools" / "intake_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.NEEDS


def test_same_keys_as_the_scanners_defaults_with_all_three_fields():
    assert set(NEEDS) == set(_scanner_needs())
    for key, entry in NEEDS.items():
        assert set(entry) == {"ask", "default", "whose"}, key
        assert all(str(v).strip() for v in entry.values()), key
        assert entry["whose"] in WHOSE, key


def test_only_the_fields_the_scanner_fills_in_appear_and_formatting_works():
    for key, entry in NEEDS.items():
        allowed = FIELDS.get(key, set())
        for part in ("ask", "default"):
            used = set(re.findall(r"\{(\w*)\}", entry[part]))
            assert used <= allowed, (key, part, used)
            assert entry[part].count("{") == entry[part].count("}") == len(used)
            entry[part].format(**{f: "X" for f in allowed})


def test_no_expert_vocabulary():
    texts = [re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", "NAME", v)
             for e in NEEDS.values() for v in (e["ask"], e["default"])]
    assert jargon_in(texts) == []


def test_constants_are_never_defaulted_and_the_flags_are_real():
    assert "never" in NEEDS["props_values"]["default"].lower()
    cli = (REPO / "src" / "umat_oti" / "cli.py").read_text()
    for e in NEEDS.values():
        for flag in set(re.findall(r"--[a-z][a-z-]+", e["default"] + e["ask"])):
            assert f'"{flag}"' in cli, flag
    assert set(FLAGS_USED) <= {f for e in NEEDS.values()
                               for f in re.findall(r"--[a-z][a-z-]+", e["default"])} | set(FLAGS_USED)
