"""A large-deformation or plane-stress file the corpus record calls verified: said up front, amber, never red."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app import check_command as check                      # noqa: E402
from umat_oti.app.verdict_page import render_verdict, verdict_for     # noqa: E402

pytestmark = pytest.mark.unit
REASON = "Automatic material configuration failed: Discovered model is not supported by the small-strain NTENS=6 sensitivity provider."
RECORD = {"terminal_state": "missing_material_data", "reason": REASON}


def test_without_a_corpus_result_an_unsupported_model_stays_a_program_side_red_card():
    assert verdict_for(RECORD)["colour"] == "red"


def test_with_a_corpus_result_it_is_amber_says_why_and_names_the_run():
    v = verdict_for(RECORD, "pass23")
    assert v["colour"] == "amber" and v["headline"].startswith("AMBER: VERIFIED ANOTHER WAY")
    page = render_verdict(RECORD, "pass23")
    assert "covers small-deformation solid models only" in page and "(run pass23)" in page
    assert "RED" not in page and "Nothing to do" in page
    assert "NTENS" not in page and "provider" not in page


def test_a_real_failure_stays_red_even_when_the_corpus_verified_the_file():
    rec = {"terminal_state": "transform_refused", "reason": "anchors not located: missing_stress_update_regions"}
    assert verdict_for(rec, "pass23")["colour"] == "red"


class _Found:
    def __init__(self, kinematics="small strain", ntens=6, element_status="FOUND"):
        self.facts = {"kinematics": kinematics, "ntens": ntens}
        self._element = SimpleNamespace(status=element_status)

    def item(self, key):
        return self._element if key == "element" else None


@pytest.mark.parametrize("found,says", [(_Found(kinematics="finite"), True), (_Found(ntens=4), True),
                                        (_Found(element_status="MISSING"), True), (_Found(), False)])
def test_the_limit_is_said_up_front_only_for_such_a_file_and_only_with_a_corpus_result(found, says, capsys):
    check._RUN.clear()
    check._RUN["elsewhere"] = "pass23"
    check.say_unsupported_up_front(found)
    out = capsys.readouterr().out
    assert ("this quick check covers small-deformation solid models only" in out) is says
    if says:
        assert "(run pass23)" in out and "finite-strain" in out
    check._RUN.clear()
    check.say_unsupported_up_front(_Found(kinematics="finite"))
    assert capsys.readouterr().out == "", "no corpus result: nothing is claimed"


def test_the_request_for_an_element_this_check_cannot_run_is_amber_when_the_corpus_verified_the_file(capsys):
    item = SimpleNamespace(key="element", ask="This kind of material or element is not one this program can run yet: x.",
                           default="The run cannot go on.", whose="this program")
    check._RUN.clear()
    check._RUN["elsewhere"] = "pass23"
    check.print_need(item)
    out = capsys.readouterr().out
    assert "AMBER: VERIFIED ANOTHER WAY, NOT BY THIS QUICK CHECK" in out and "RED" not in out
    assert check._RUN["final"] == "amber"
    check._RUN.clear()
    check.print_need(item)
    assert "RED: REFUSED" in capsys.readouterr().out


def test_print_card_for_the_unsupported_model_is_amber_with_a_corpus_result_and_red_without(capsys):
    check._RUN.clear()
    check._RUN["elsewhere"] = "pass23"
    check.print_card("missing_material_data", REASON)
    assert "AMBER: VERIFIED ANOTHER WAY" in capsys.readouterr().out
    check._RUN.clear()
    check.print_card("missing_material_data", REASON)
    assert "RED: REFUSED" in capsys.readouterr().out
