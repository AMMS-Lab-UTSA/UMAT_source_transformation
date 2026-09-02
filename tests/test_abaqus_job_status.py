"""What an Abaqus job did, decided from its records rather than its exit code.

Abaqus 2021.HF5 aborts in post-analysis wrap-up on this installation --
``*** buffer overflow detected ***`` and ``terminated by signal 6`` -- and exits
non-zero *after* writing THE ANALYSIS HAS COMPLETED SUCCESSFULLY. A control job
with no user subroutine at all aborts identically, so it is not the model, not
a UMAT, and not anything this pipeline emits.

That makes the exit code useless as a verdict and dangerous as a filter. It is
recorded, reported, and never rewritten to zero; the verdict comes from the
records, and only when every applicable check agrees. One marker is not enough
either: a .sta can say the analysis completed while the increments asked for
were never run.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.abaqus.job_status import COMPLETED_MARKER, classify_job  # noqa: E402

MSG_OK = """
     TOTAL OF         10  INCREMENTS
                       0  WARNING MESSAGES DURING ANALYSIS
                       0  ERROR MESSAGES
"""


def _job(tmp_path: Path, *, sta: str = COMPLETED_MARKER, msg: str = MSG_OK,
         odb: bytes = b"x" * 32) -> Path:
    (tmp_path / "j.sta").write_text(f"  1  1\n {sta}\n", encoding="utf-8")
    (tmp_path / "j.msg").write_text(msg, encoding="utf-8")
    if odb is not None:
        (tmp_path / "j.odb").write_bytes(odb)
    return tmp_path


class TestACompletedAnalysis:
    def test_every_check_agreeing_is_completion(self, tmp_path):
        status = classify_job(_job(tmp_path), "j", exit_code=0,
                              expected_increments=10, required_files=("j.odb",))
        assert status.analysis_completed
        assert status.reasons == ()
        assert all(status.checks.values())

    def test_a_wrapup_abort_does_not_change_the_verdict(self, tmp_path):
        status = classify_job(
            _job(tmp_path), "j", exit_code=1, expected_increments=10,
            console="*** buffer overflow detected ***: terminated\n"
                    "*** ABAQUS/standard rank 0 terminated by signal 6 (Aborted)",
            required_files=("j.odb",))
        assert status.analysis_completed, "the analysis did complete"
        assert "post_analysis_wrapup_failure" in status.warnings
        assert "process_exit_code_1" in status.warnings

    def test_the_exit_code_is_preserved_exactly(self, tmp_path):
        status = classify_job(_job(tmp_path), "j", exit_code=1,
                              expected_increments=10, required_files=("j.odb",))
        assert status.exit_code == 1, "never rewritten to zero"
        assert status.as_dict()["exit_code"] == 1


class TestWhatStopsItBeingCompletion:
    def test_a_missing_sta(self, tmp_path):
        (tmp_path / "j.msg").write_text(MSG_OK, encoding="utf-8")
        status = classify_job(tmp_path, "j", exit_code=0)
        assert not status.analysis_completed
        assert any("left no record" in reason for reason in status.reasons)

    def test_no_completion_marker(self, tmp_path):
        status = classify_job(_job(tmp_path, sta="THE ANALYSIS HAS NOT BEEN COMPLETED"),
                              "j", exit_code=0, required_files=("j.odb",))
        assert not status.analysis_completed

    def test_analysis_errors(self, tmp_path):
        status = classify_job(
            _job(tmp_path, msg=MSG_OK.replace("0  ERROR", "3  ERROR")),
            "j", exit_code=0, required_files=("j.odb",))
        assert not status.analysis_completed
        assert status.error_messages == 3

    def test_fewer_increments_than_were_asked_for(self, tmp_path):
        # The marker is present and the errors are zero, and the run is still
        # not the run that was requested.
        status = classify_job(_job(tmp_path), "j", exit_code=0,
                              expected_increments=25, required_files=("j.odb",))
        assert not status.analysis_completed
        assert any("25 were requested" in reason for reason in status.reasons)

    def test_missing_output(self, tmp_path):
        status = classify_job(_job(tmp_path, odb=None), "j", exit_code=0,
                              expected_increments=10, required_files=("j.odb",))
        assert not status.analysis_completed

    def test_an_empty_output_file_is_not_output(self, tmp_path):
        status = classify_job(_job(tmp_path, odb=b""), "j", exit_code=0,
                              expected_increments=10, required_files=("j.odb",))
        assert not status.analysis_completed

    def test_a_zero_exit_code_does_not_rescue_a_failed_analysis(self, tmp_path):
        status = classify_job(_job(tmp_path, sta="INCOMPLETE"), "j", exit_code=0,
                              required_files=("j.odb",))
        assert not status.analysis_completed


class TestAStatementThatWaitsForInput:
    """PAUSE hangs a solver instead of failing it, so it is named.

    Found the way these things are found: a transformed crystal-plasticity job
    sat for twelve minutes having spent two seconds of processor time, in the
    kernel's pause() call, holding a licence token and looking exactly like a
    long analysis. The source carries a Numerical Recipes LU decomposition that
    announces a singular matrix with PAUSE.
    """

    def test_a_pause_is_reported(self):
        from umat_oti.abaqus.job_status import blocking_statements

        source = ("      SUBROUTINE UMAT(STRESS)\n"
                  "      IF (AAMAX.EQ.0.) PAUSE 'Singular matrix.'\n"
                  "      RETURN\n      END\n")
        found = blocking_statements(source)
        assert len(found) == 1 and "Singular matrix" in found[0]

    def test_a_pause_in_a_comment_is_not_a_statement(self):
        from umat_oti.abaqus.job_status import blocking_statements

        assert blocking_statements("C     PAUSE here if it goes singular\n") == ()

    def test_a_source_without_one_reports_nothing(self):
        from umat_oti.abaqus.job_status import blocking_statements

        assert blocking_statements("      X = 1.0\n      RETURN\n") == ()

    def test_the_statement_is_reported_and_not_removed(self):
        """It is the model author's, and it announces a real failure.

        Deleting it would be editing scientific code to make a run finish. The
        fix is to give the solver no terminal to wait on, which is the runner's
        business, not the source's.
        """
        from umat_oti.abaqus import runner

        assert "stdin=subprocess.DEVNULL" in \
            Path(runner.__file__).read_text(encoding="utf-8")
