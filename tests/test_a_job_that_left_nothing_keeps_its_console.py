"""For a job that wrote no .dat, no .msg and no .odb, the console is all there is.

Three pass9 entries -- 284fb12379dea8b621d13b6e, 519007db0b76febb2791fb82,
e01147e629b4288418b80109 -- left `original.com`, `original.inp` and
`original_user.f` and nothing else: a two-byte history file, no diagnostics of
any kind. Each was recorded as

    original.sta was not written, so the analysis left no record;
    original.msg was not written; expected output is missing or empty:
    original.odb

which says what is absent and nothing about why. The compiler's own error
list WAS captured, by runner.run_job, and then dropped: job_evidence reduces
a run report to six fields and the console was not one of them. All three
were diagnosable afterwards only by reproducing the compile offline with each
job's own flags, which happened to be possible here and will not always be.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import verify_store_in_abaqus as verify  # noqa: E402

TOOL = (pathlib.Path(__file__).resolve().parents[1]
        / "tools" / "verify_store_in_abaqus.py").read_text()
RUNNER = (pathlib.Path(__file__).resolve().parents[1]
          / "tools" / "run_abaqus_verification.py").read_text()


def test_the_reduction_keeps_the_console():
    evidence = verify.job_evidence(
        {"completed": False, "console": "error #6236: A specification "
                                        "statement cannot appear here"})
    assert "error #6236" in evidence.console_tail


def test_a_job_that_completed_needs_no_console():
    """Kept only where it is evidence. A completed job's console is noise."""
    evidence = verify.job_evidence({"completed": True, "console": "chatter"})
    assert evidence.console_tail == "chatter"
    assert '"console_tail": ("" if original_job.completed' in TOOL, (
        "and the record stores it only for a job that did not complete")


def test_both_builds_keep_it():
    for side in ("original", "transformed"):
        assert f'else {side}_job.console_tail)' in TOOL, side


def test_the_tail_is_long_enough_for_a_compiler_error_list():
    """2000 characters cut the diagnostic off all three. An ifort error list
    runs longer than that."""
    assert "result.console[-20000:]" in RUNNER
    assert "result.console[-2000:]" not in RUNNER
