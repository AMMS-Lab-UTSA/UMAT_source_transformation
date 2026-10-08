"""Vera's B17 ruling: GREEN only in a green verdict's banner; the Abaqus command sentence never promises verification."""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.abaqus.terminal_states import ALL                            # noqa: E402
from umat_oti.app import check_command as check                            # noqa: E402
from umat_oti.app.refusal_cards import RULES, STATE_CARDS, card_for        # noqa: E402
from umat_oti.app.verdict_page import (TRIAL_SENTENCE, abaqus_hint,        # noqa: E402
                                       elsewhere_texts, render_verdict, verdict_for)

pytestmark = pytest.mark.unit
GATES = ("abaqus_job_completed", "all_requested_outputs_present", "complete_history_finite",
         "derivatives_verified", "primal_agreed", "mechanically_informative")
COMMAND = "umat-oti all /x/u.for --dependency-root /x/lib --out /x/o_abaqus --abaqus"
UNSUPPORTED = "Automatic material configuration failed: Discovered model is not supported by the small-strain NTENS=6 sensitivity provider."


def _records():
    for state in ALL:
        evidence = {g: True for g in GATES} if state == "fully_verified" else {}
        yield {"terminal_state": state, "reason": "", "evidence": evidence}
    yield {"terminal_state": "missing_material_data", "reason": UNSUPPORTED}
    yield {"stages": {"sensitivities": {"verification": {"result": {"verdict": "verified"}}}}}
    yield {"evidence": {g: True for g in GATES}}
    yield {"terminal_state": "tangent_not_verified", "evidence": {g: True for g in GATES}}


def _pages():
    for record in _records():
        for elsewhere, deck in ((None, None), ("pass23", None), ("pass23", "ShearUMAT.inp")):
            for command in (None, COMMAND):
                yield render_verdict(record, elsewhere, command, deck)


def test_the_word_green_occurs_only_in_the_banner_of_a_green_verdict():
    seen_green = 0
    for page in _pages():
        lines = page.splitlines()
        assert lines[0].startswith("=" * 70) and lines[2].startswith("=" * 70)
        banner = lines[1]
        for number, line in enumerate(lines):
            if "GREEN" in line:
                assert number == 1 and banner.startswith("GREEN: "), (number, line)
                seen_green += 1
        if banner.startswith("GREEN: "):
            assert "GREEN" not in "\n".join(lines[2:])
    assert seen_green, "the green banner is still produced for a fully verified record"


def test_no_card_or_text_that_is_not_a_verdict_banner_says_green():
    texts = []
    for sentence, whose, action in STATE_CARDS.values():
        texts += [sentence, action]
    for name, pattern, build in RULES:
        for probe in ("callee ABC", "[ABC]", "module XYZ"):
            s, w, a = build(probe, "transform_refused")
            texts += [s, a]
    texts += list(elsewhere_texts("pass23", None, COMMAND)) + list(elsewhere_texts("pass23", "ShearUMAT.inp", COMMAND))
    texts += [abaqus_hint(COMMAND), TRIAL_SENTENCE]
    for state in ALL:
        c = card_for(state, "")
        texts += [c.sentence, c.next_action]
    assert [t for t in texts if "GREEN" in t] == []


def test_the_command_sentence_says_what_the_command_does_and_never_promises_a_verified_result():
    assert TRIAL_SENTENCE == ("That command runs the file in Abaqus and records whether the job finished. The six-check "
                              "comparison that makes a file verified is not part of it yet.")
    for text in (abaqus_hint(COMMAND), *elsewhere_texts("pass23", None, COMMAND), *elsewhere_texts("pass23", "d.inp", COMMAND)):
        for sentence in re.split(r"(?<=[.])\s+", text):
            if COMMAND in sentence:
                assert "verif" not in sentence.lower(), sentence
        if COMMAND in text:
            assert TRIAL_SENTENCE in text and "not part of it yet" in text
    for page in _pages():
        if COMMAND in page:
            assert "not part of it yet" in page
            assert "will verify" not in page and "to verify it" not in page and "verifies" not in page


def test_check_prints_the_command_sentence_after_an_amber_verdict_and_passes_the_dependency_roots_through(tmp_path, capsys):
    check._RUN.clear()
    check._RUN.update(source=tmp_path / "u.for", deck=None, out=tmp_path / "o", final="amber", match=None, elsewhere=None,
                      roots=[tmp_path / "lib1", tmp_path / "lib2"])
    check.print_corpus_record()
    out = capsys.readouterr().out
    assert "GREEN" not in out and TRIAL_SENTENCE in out
    assert f"--dependency-root {tmp_path / 'lib1'} --dependency-root {tmp_path / 'lib2'}" in out
    assert out.index("--dependency-root") < out.index("--out") < out.index("--abaqus")
    helped = __import__("subprocess").run([sys.executable, str(REPO / "umat-oti"), "all", "--help"], capture_output=True, text=True, cwd="/").stdout
    for flag in set(re.findall(r"--[a-z-]+", out)):
        assert flag in helped, flag


def test_check_passes_the_users_dependency_root_into_its_own_run_record(tmp_path, monkeypatch, capsys):
    import shutil
    folder = tmp_path / "w"
    folder.mkdir()
    shutil.copy(REPO / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f", folder / "j2_props.f")
    lib = tmp_path / "lib"
    lib.mkdir()
    monkeypatch.chdir(tmp_path)
    check.main([str(folder / "j2_props.f"), "--dependency-root", str(lib)])
    assert check._RUN["roots"] == [lib.resolve()]
    assert f"--dependency-root {lib.resolve()}" in check.abaqus_command()
