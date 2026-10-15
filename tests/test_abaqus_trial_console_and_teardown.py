"""The jacobian command's Abaqus trial on a UMAT that writes to the console.

A UMAT with WRITE(*,*) in it aborts an ``interactive`` Abaqus job inside the
Intel Fortran runtime (unit 6 is a pipe there); FOR_PRINT sends that output to
a file. Abaqus 2021 can then still abort in its own clean-up after the solve,
with the ODB written and closed: a completed analysis, not a failed one. And a
trial job can be given a name, so the ODB a later step reads is predictable.
"""
import json
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.services.abaqus_trial import run_abaqus_trial

FAKE = """import os, sys
from pathlib import Path
job = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('job='))
if Path('mode.txt').read_text().strip() == 'dead':
    print('licence unavailable', file=sys.stderr)
    sys.exit(1)
Path(job + '.dat').write_text('THE ANALYSIS HAS BEEN COMPLETED\\n')
Path(job + '_seen_for_print.txt').write_text(os.environ.get('FOR_PRINT', ''))
mode = Path('mode.txt').read_text().strip() if Path('mode.txt').exists() else 'clean'
if mode == 'teardown':
    Path(job + '.00.4242.exception').write_text(
        '<Callstack>\\n  17) libABQSMAAspSupport.so 0x0 ! SMAAspBcu_finalize ??:?\\n'
        '  18) libABQSMAAspSupport.so 0x0 ! SMAAspSupport_finalize ??:?\\n</Callstack>\\n')
    sys.exit(1)
if mode == 'crash':
    sys.exit(1)
"""


@pytest.fixture
def trial(tmp_path):
    source = tmp_path / "candidate.f90"
    source.write_text("subroutine umat\nend subroutine\n")
    (tmp_path / "compile_order.txt").write_text("candidate.f90\n")
    deck = tmp_path / "model.inp"
    deck.write_text("*Heading\nSynthetic trial\n")
    fake = tmp_path / "fake_abaqus.py"
    fake.write_text(FAKE)
    run = SimpleNamespace(contract_path=tmp_path / "jacobian_contract.json", transformed_source=source,
                          summary={"transform_success": True, "blockers": [], "semantic_checks": {}})

    def go(mode="clean", **kwargs):
        (tmp_path / "mode.txt").write_text(mode)
        return run_abaqus_trial(run, deck, abaqus_command=shlex.join([sys.executable, str(fake)]),
                                abaqus_modules="", run_prefix="", **kwargs)
    return go, tmp_path


def test_console_output_goes_to_a_file_named_after_the_job(trial, monkeypatch):
    go, folder = trial
    monkeypatch.delenv("FOR_PRINT", raising=False)
    report = go(job_name="bar")
    assert report["status"] == "completed" and report["job"] == "bar"
    assert report["console_output"] == str(folder / "bar_console.txt")
    assert (folder / "bar_seen_for_print.txt").read_text() == str(folder / "bar_console.txt")
    assert "job=bar" in report["command"][-1]


def test_a_for_print_the_user_set_is_kept(trial, monkeypatch, tmp_path):
    go, folder = trial
    monkeypatch.setenv("FOR_PRINT", str(tmp_path / "mine.txt"))
    report = go()
    assert report["console_output"] == str(tmp_path / "mine.txt")


def test_a_teardown_abort_after_a_completed_analysis_is_not_a_failure(trial):
    go, _ = trial
    report = go("teardown", job_name="single")
    assert report["returncode"] == 1 and report["analysis_completed"] is True
    assert report["status"] == "completed"
    assert "SMAAspSupport_finalize" in report["teardown_abort"] or "SMAAspBcu_finalize" in report["teardown_abort"]
    assert report["verified"] is False


def test_a_non_zero_exit_without_that_evidence_still_fails(trial):
    go, _ = trial
    report = go("crash", job_name="single")
    assert report["status"] == "failed" and "teardown_abort" not in report


@pytest.mark.parametrize("name", ["../escape", "a b", "", "x" * 81])
def test_a_job_name_that_is_not_a_plain_name_is_refused(trial, name):
    go, _ = trial
    report = go(job_name=name)
    assert report["status"] == "blocked" and "job name" in report["error"]


def test_the_job_option_needs_an_analysis_trial(tmp_path, capsys):
    from umat_oti.cli import main

    source = tmp_path / "u.f"
    source.write_text("      SUBROUTINE UMAT\n      END\n")
    with pytest.raises(SystemExit):
        main(["jacobian", str(source), "--ntens", "6", "--out", str(tmp_path / "o"), "--abaqus-job", "bar"])
    assert "--abaqus-job" in capsys.readouterr().err


def test_files_of_an_earlier_run_of_the_same_job_are_not_evidence(trial):
    """A run that wrote nothing was reported completed, with a teardown abort,
    from the .dat and .exception an earlier run of the same name left in --out."""
    go, folder = trial
    first = go("teardown", job_name="bar")
    assert first["status"] == "completed"
    assert "ask_delete=OFF" in first["command"][-1]
    second = go("dead", job_name="bar")
    assert (folder / "bar.dat").is_file()          # the old files are still there
    assert second["returncode"] == 1 and second["status"] == "failed"
    assert second["analysis_completed"] is False and "teardown_abort" not in second


@pytest.mark.parametrize("trial_status, combined, says_trial", [
    ("failed", "/x/u_oti_combined.f90", True), ("failed", "", True), ("completed", "/x/u_oti_combined.f90", False)])
def test_the_front_door_names_a_failed_trial_only(monkeypatch, capsys, tmp_path, trial_status, combined, says_trial):
    from umat_oti.app import front_door

    summary = {"transform_success": True, "blockers": [], "combined_source": combined,
               "abaqus_trial": {"status": trial_status, "report": "r.json", "stdout": "o.log"}}

    def fake_main(argv):
        print(json.dumps(summary))
        return 1
    monkeypatch.setattr("umat_oti.cli.main", fake_main)
    code = front_door.run_with_cards("jacobian", ["u.f", "--out", str(tmp_path)])
    err = capsys.readouterr()
    assert code == 1
    text = err.out + err.err
    assert ("the Abaqus trial did not complete" in text) is says_trial
    assert "wrote None" not in text and "wrote  " not in text
    if says_trial and not combined:
        assert "the conversion succeeded;" in text
