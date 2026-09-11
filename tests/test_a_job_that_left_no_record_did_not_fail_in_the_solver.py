"""Ten pass9 entries were recorded as ``original_job_failed``; three never ran.

``284fb12379dea8b621d13b6e``, ``519007db0b76febb2791fb82`` and
``e01147e629b4288418b80109`` left ``original.com``, ``original.inp`` and
``original_user.f`` and nothing else -- no .dat, no .msg, no .odb, and a
two-byte history file. Abaqus writes the .dat while processing the input file,
which it does after building the user subroutine, so no .dat at all does not
mean "the analysis left no record": it means there was no analysis.

Recompiled offline with the flags from each job's own ``original.com``:

* ``umat_elastic_official.f`` -- ``error #6410: This name has not been declared
  as an array or a function. [PROPS]``. The downloaded file's DIMENSION
  statement omits ``PROPS(NPROPS)``, so under ABA_PARAM.INC's IMPLICIT REAL*8
  ``PROPS(1)`` parses as a function reference. Author-side.
* ``UMAT_KLP_RK5_hybrid.f`` -- ``#error: can't find include file:
  SMAASPUSERSUBROUTINES.HDR``. The author wrote ``#INCLUDE`` in upper case and
  Abaqus ships only ``SMAAspUserSubroutines.hdr``. It compiles cleanly against
  a case-insensitive include directory.
* ``array_with_two_pixel_z.for`` -- eleven ``error #6236``, caused by this
  package: see
  test_a_probe_call_must_not_step_over_a_preprocessor_include.py.

What the harness recorded instead was "original.msg was not written", plus a
warning that the solver "cut back and recovered: None increments where 30 were
requested" -- a recovery attributed to a run that never started.
"""
import pytest

from umat_oti.abaqus.job_status import classify_job

pytestmark = pytest.mark.unit

IFORT_CONSOLE = """\
Abaqus JOB original
Abaqus 2021
Begin Compiling Abaqus/Standard User Subroutines
original_user.f(38): error #6410: This name has not been declared as an array or a function.   [PROPS]
      EMOD=PROPS(1)
-----------^
compilation aborted for original_user.f (code 1)
Abaqus Error: Problem during compilation - original_user.f
Abaqus/Analysis exited with error(s).
"""


def test_no_dat_and_no_msg_is_reported_as_a_build_failure_not_a_solver_one(tmp_path):
    (tmp_path / "original.com").write_text("compile_fortran = [...]\n")
    status = classify_job(tmp_path, "original", exit_code=1,
                          console=IFORT_CONSOLE, expected_increments=30)
    assert not status.analysis_completed
    assert any("never reached its input processor" in reason
               for reason in status.reasons)


def test_the_compilers_own_words_are_carried_into_the_reason(tmp_path):
    """The console is the only evidence such a job leaves. It was captured and
    dropped, so all ten entries came back saying the same nothing."""
    status = classify_job(tmp_path, "original", exit_code=1,
                          console=IFORT_CONSOLE, expected_increments=30)
    reason = " ".join(status.reasons)
    assert "error #6410" in reason and "PROPS" in reason


def test_the_console_is_kept_when_the_job_did_not_complete(tmp_path):
    status = classify_job(tmp_path, "original", exit_code=1,
                          console=IFORT_CONSOLE)
    assert "compilation aborted" in status.console_tail


def test_the_console_is_not_kept_for_a_job_that_completed(tmp_path):
    """A completed run's console is megabytes of increment banners and says
    nothing the .sta and .msg do not."""
    (tmp_path / "j.sta").write_text(
        "  1  1   1     1     0     1  0.100 THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
    (tmp_path / "j.msg").write_text(
        "\n     TOTAL OF     10 INCREMENTS\n\n     0 ERROR MESSAGES\n")
    (tmp_path / "j.odb").write_bytes(b"x" * 16)
    status = classify_job(tmp_path, "j", exit_code=0, console="lots of output",
                          expected_increments=10, required_files=("j.odb",))
    assert status.analysis_completed
    assert status.console_tail == ""


def test_a_run_that_never_started_is_not_reported_as_having_recovered(tmp_path):
    """All ten failures carried "the solver cut back and recovered: None
    increments where 30 were requested". There is no increment count, because
    there is no .msg, because there was no analysis."""
    status = classify_job(tmp_path, "original", exit_code=1,
                          console=IFORT_CONSOLE, expected_increments=30)
    assert not any("cut back and recovered" in warning
                   for warning in status.warnings)
    assert status.checks["increments_completed"] is False


def test_a_cutback_that_really_happened_is_still_reported(tmp_path):
    """BodyForce-Growth-2Stages.for: ten increments for the original and
    sixteen for the converted build, both completing. That is a solver doing
    its job and it still has to be said."""
    (tmp_path / "j.sta").write_text("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
    (tmp_path / "j.msg").write_text(
        "\n     TOTAL OF     16 INCREMENTS\n\n     0 ERROR MESSAGES\n")
    status = classify_job(tmp_path, "j", exit_code=0, expected_increments=10)
    assert any("cut back and recovered: 16 increments" in warning
               for warning in status.warnings)
