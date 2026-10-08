"""``umat-oti verify UMAT DECK``: the six checks on a file outside the corpus, in a scratch folder.

Offline: no Abaqus is run here. The tools are replaced by stand-ins or the cards are read.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app import verify_command as verify                      # noqa: E402
from umat_oti.app.verdict_page import render_verdict                    # noqa: E402

GATES = ["abaqus_job_completed", "all_requested_outputs_present", "complete_history_finite", "primal_agreed",
         "derivatives_verified", "mechanically_informative"]
SOURCE = REPO / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"
GOOD_DECK = "*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS=2\n210000., 0.3\n*DEPVAR\n1\n"


def _files(tmp_path, deck_text=GOOD_DECK):
    umat = tmp_path / "u.for"
    umat.write_text("      SUBROUTINE UMAT(STRESS)\n      INCLUDE 'ABA_PARAM.INC'\n      RETURN\n      END\n")
    deck = tmp_path / "d.inp"
    deck.write_text(deck_text)
    return umat, deck


def test_every_path_given_to_the_tools_is_under_the_scratch_folder_and_none_is_the_real_store(tmp_path):
    layout = verify.Layout(tmp_path / "scratch")
    tools = REPO / "tools"
    steps = verify.commands(layout, "u.for", tools, 100)
    assert [name for name, _ in steps][0] == "reading your files"
    flags_with_paths = {"--cache-dir", "--work-dir", "--results-dir", "--triage", "--store-root", "--proposals",
                        "--store"}
    seen = set()
    for _, argv in steps:
        for flag, value in zip(argv, argv[1:]):
            if flag in flags_with_paths:
                seen.add(flag)
                assert Path(value).is_absolute() and Path(value).is_relative_to(layout.root), (flag, value)
        assert "--only" not in argv or argv[argv.index("--only") + 1] == "yourfiles/u.for"
    assert seen == flags_with_paths
    for path in layout.all_paths():
        assert path.is_relative_to(layout.root)


def test_the_scratch_corpus_holds_the_file_and_the_deck_and_an_empty_proposal_list(tmp_path):
    umat, deck = _files(tmp_path)
    (tmp_path / "helper.f").write_text("      SUBROUTINE H\n      END\n")
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "extra.f90").write_text("subroutine e\nend\n")
    layout = verify.Layout(tmp_path / "scratch")
    verify.build_scratch(layout, umat, deck, [lib])
    assert sorted(p.name for p in layout.repository.iterdir()) == ["d.inp", "extra.f90", "u.for"]
    assert layout.proposals.read_text().strip() == '{"entries": []}'
    assert not (REPO / "yourfiles").exists()


def _main(monkeypatch, capsys, tmp_path, deck_text=GOOD_DECK, which=None, extra=()):
    umat, deck = _files(tmp_path, deck_text)
    monkeypatch.setattr(verify.shutil, "which", which or (lambda name: None))
    code = verify.main([str(umat), str(deck), "--out", str(tmp_path / "o"), *extra])
    return code, capsys.readouterr().out


def test_without_abaqus_it_stops_with_a_blue_card_that_says_whose_move_and_one_next_step(tmp_path, monkeypatch, capsys):
    code, out = _main(monkeypatch, capsys, tmp_path)
    assert code == 3 and "Abaqus" in out and "Whose move: you" in out
    assert "Next:" in out and "GREEN" not in out
    assert not (tmp_path / "o").exists()


def test_without_a_deck_it_asks_for_one_and_defaults_nothing(tmp_path, monkeypatch, capsys):
    umat, _ = _files(tmp_path)
    monkeypatch.setattr(verify.shutil, "which", lambda name: "/bin/true")
    assert verify.main([str(umat)]) == 3
    out = capsys.readouterr().out
    assert "deck" in out and "Whose move: you" in out and "GREEN" not in out


@pytest.mark.parametrize("deck_text", ["", "*MATERIAL, NAME=M\n*ELASTIC\n1., 0.3\n",
                                       "*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS=2\n*DEPVAR\n1\n"])
def test_a_deck_without_constants_is_refused_and_no_constant_is_filled_in(tmp_path, monkeypatch, capsys, deck_text):
    code, out = _main(monkeypatch, capsys, tmp_path, deck_text, which=lambda name: "/bin/true")
    assert code == 3 and "Whose move: you" in out and "GREEN" not in out
    assert not (tmp_path / "o").exists()


def test_the_launcher_lists_verify_and_its_help_names_the_scratch_folder(tmp_path):
    helped = subprocess.run([sys.executable, str(REPO / "umat-oti"), "--help"], capture_output=True, text=True, cwd="/").stdout
    assert "umat-oti verify UMAT.for DECK.inp" in helped
    own = subprocess.run([sys.executable, str(REPO / "umat-oti"), "verify", "--help"], capture_output=True, text=True,
                         cwd="/").stdout
    assert "scratch" in own and "--dependency-root" in own and "--out" in own


def _fake_run(monkeypatch, tmp_path, record):
    """Run the whole command with the tools replaced by one that writes the given record."""
    umat, deck = _files(tmp_path)
    monkeypatch.setattr(verify.shutil, "which", lambda name: "/bin/true")
    monkeypatch.setattr(verify, "_run", lambda *a, **k: 0)
    monkeypatch.setattr(verify, "_row_of", lambda *a, **k: {"stage": "transformed"})
    monkeypatch.setattr(verify, "_record_of", lambda layout: record)
    monkeypatch.setattr("umat_oti.app.check_command.load_scanner", lambda: None)
    return verify.main([str(umat), str(deck), "--out", str(tmp_path / "o")])


def test_the_run_is_green_only_when_every_one_of_the_six_gates_held(tmp_path, monkeypatch, capsys):
    full = {"terminal_state": "fully_verified", "reason": "", "evidence": {g: True for g in GATES}}
    (tmp_path / "a").mkdir()
    assert _fake_run(monkeypatch, tmp_path / "a", full) == 0
    out = capsys.readouterr().out
    assert "GREEN: VERIFIED" in out
    for gate in GATES:
        (tmp_path / gate).mkdir()
        record = {"terminal_state": "fully_verified", "reason": "", "evidence": {g: g != gate for g in GATES}}
        assert _fake_run(monkeypatch, tmp_path / gate, record) != 0, gate
        assert "GREEN" not in capsys.readouterr().out, gate
    (tmp_path / "t").mkdir()
    record = {"terminal_state": "tangent_not_verified", "reason": "", "evidence": {g: True for g in GATES}}
    assert _fake_run(monkeypatch, tmp_path / "t", record) != 0
    assert "GREEN" not in capsys.readouterr().out
    assert render_verdict(full).splitlines()[1].startswith("GREEN")
