"""A non-zero exit from Abaqus is not automatically a failed analysis.

Abaqus 2021's bundled Intel Fortran runtime calls ``for_inquire`` from its own
shutdown, and against a glibc built with ``_FORTIFY_SOURCE`` that path reaches
``__chk_fail`` and aborts. It happens after the solve, after the results are
written and after the ODB is closed. On a machine where this occurs it happens
to every Abaqus/Standard job -- including one with no user subroutine at all --
so reading the exit status alone records every source as failed and charges a
defect in the installation against the models.

The discrimination has to be evidence-based and it has to be conservative: an
analysis that stopped early and then crashed must stay failed, or this becomes
a way to launder failures into passes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.validation.abaqus_runner import (
    ANALYSIS_COMPLETED_MARK, analysis_completed,
    completed_despite_teardown_abort, teardown_abort,
)
from umat_oti.validation.compare_results import (
    TEARDOWN_ABORT_STATUS, _execution_status_errors, environment_caveats,
)

JOB = "original_umat_validation"

TEARDOWN_CALLSTACK = """<Description>
      ABAQUS/standard rank 00 pid 3090899 received signal 6 (Aborted)
</Description>
<Callstack>
   4) libc.so.6                  0x0012fcda ! __fortify_fail   ??:?
   5) libc.so.6                  0x0012e576 ! __chk_fail       ??:?
  11) libifcoremt.so.5           0x000f2993 ! fname_from_piped_fd ??:?
  15) libifcoremt.so.5           0x0005ba23 ! for_inquire      ??:?
  16) libABQSMAAspSupport.so     0x001b99e2 ! bcu_cleanup      ??:?
  18) libABQSMAAspSupport.so     0x0030baf4 ! SMAAspSupport_finalize ??:?
</Callstack>
"""

SOLVE_CALLSTACK = """<Callstack>
   3) libstandard.so             0x00001234 ! element_loop     ??:?
   4) libstandard.so             0x00005678 ! umat_            ??:?
</Callstack>
"""


def _job(tmp_path: Path, *, completed: bool, exception: str | None) -> Path:
    body = "  STEP SUMMARY\n"
    if completed:
        body += f"            {ANALYSIS_COMPLETED_MARK}\n"
    (tmp_path / f"{JOB}.dat").write_text(body, encoding="utf-8")
    if exception is not None:
        (tmp_path / f"{JOB}.00.1234.exception").write_text(exception, encoding="utf-8")
    return tmp_path


def test_a_completed_analysis_that_aborts_in_teardown_is_recognised(tmp_path: Path):
    _job(tmp_path, completed=True, exception=TEARDOWN_CALLSTACK)
    assert analysis_completed(tmp_path, JOB)
    assert "SMAAspSupport_finalize" in teardown_abort(tmp_path, JOB)
    assert completed_despite_teardown_abort(tmp_path, JOB)


def test_an_analysis_that_stopped_early_is_still_a_failure(tmp_path: Path):
    """The dangerous direction. Without the completion mark this says nothing."""
    _job(tmp_path, completed=False, exception=TEARDOWN_CALLSTACK)
    assert not analysis_completed(tmp_path, JOB)
    assert not completed_despite_teardown_abort(tmp_path, JOB), (
        "a crash during shutdown cannot excuse an analysis that never finished")


def test_a_crash_inside_the_solve_is_not_a_teardown_abort(tmp_path: Path):
    _job(tmp_path, completed=True, exception=SOLVE_CALLSTACK)
    assert analysis_completed(tmp_path, JOB)
    assert not teardown_abort(tmp_path, JOB)
    assert not completed_despite_teardown_abort(tmp_path, JOB)


def test_a_clean_run_needs_no_excuse(tmp_path: Path):
    _job(tmp_path, completed=True, exception=None)
    assert not completed_despite_teardown_abort(tmp_path, JOB)


def test_the_comparison_does_not_count_a_teardown_abort_as_an_execution_error():
    report = {
        "original_run_status": {"status": TEARDOWN_ABORT_STATUS, "returncode": 1,
                                "message": "aborted inside SMAAspSupport_finalize"},
        "transformed_run_status": {"status": "completed", "returncode": 0},
    }
    assert _execution_status_errors(report) == []


def test_but_it_is_recorded_as_a_caveat_rather_than_discarded():
    report = {
        "original_run_status": {"status": TEARDOWN_ABORT_STATUS, "returncode": 1,
                                "message": "aborted inside SMAAspSupport_finalize"},
    }
    caveats = environment_caveats(report)
    assert len(caveats) == 1 and "SMAAspSupport_finalize" in caveats[0], (
        "a result that depended on discounting the abort must say so")


@pytest.mark.parametrize("status,returncode", [
    ("failed", 1), ("timeout", None), ("failed", 2),
])
def test_a_genuinely_failed_job_still_errors(status, returncode):
    report = {"original_run_status": {"status": status, "returncode": returncode}}
    assert _execution_status_errors(report), (
        f"{status}/{returncode} must remain an execution error")


# --------------------------------------------------------------------------- #
# Scale. A component is part of a tensor, and a near-zero component beside a
# large one is a zero of that tensor -- not a value with a large relative
# error. Judging each component against a floor of 1.0 reported a transverse
# stress of 0.12 next to an axial 526 as a twelve per cent disagreement.
# --------------------------------------------------------------------------- #
def test_a_near_zero_component_is_judged_against_the_tensor_it_belongs_to():
    from umat_oti.validation.compare_results import _vector_comparison

    original = [526.174683, 0.120729, 0.120729, 0.0, 0.0, 0.0]
    transformed = [526.089539, 0.000465, 0.000465, 0.0, 0.0, 0.0]
    result = _vector_comparison(original, transformed, 1.0e-6, 1.0e-4)
    assert result["comparison_scale"] == pytest.approx(526.174683)
    assert result["max_rel_difference"] == pytest.approx(2.286e-4, rel=1e-2), (
        "0.12 out of a stress of 526 is two parts in ten thousand, not twelve "
        "per cent")


def test_an_all_zero_vector_does_not_divide_by_zero():
    from umat_oti.validation.compare_results import _vector_comparison

    result = _vector_comparison([0.0] * 6, [0.0] * 6, 1.0e-6, 1.0e-4)
    assert result["comparison_scale"] == 1.0
    assert result["max_rel_difference"] == 0.0
    assert result["pass"]


def test_a_genuine_disagreement_is_still_caught():
    """The direction that matters: rescaling must not launder a real error."""
    from umat_oti.validation.compare_results import _vector_comparison

    original = [500.0, 100.0, 0.0, 0.0, 0.0, 0.0]
    transformed = [500.0, 400.0, 0.0, 0.0, 0.0, 0.0]
    result = _vector_comparison(original, transformed, 1.0e-6, 1.0e-4)
    assert not result["pass"]
    assert result["max_rel_difference"] == pytest.approx(0.6)


def test_a_state_comparison_records_what_its_channel_can_resolve():
    """Context, not a tolerance. The verdict must not move.

    State comes back through Abaqus's SDV field output, which is single
    precision. A reader seeing "statev failed" needs to know whether the
    difference is near what the channel can carry or far above it, and the
    comparison is the only place that knows the scale.
    """
    from umat_oti.validation.compare_results import _state_comparison

    warnings: list[str] = []
    result = _state_comparison(
        {"final_state_variables": [27.4464054107666]},
        {"final_state_variables": [27.446422576904297]},
        1.0e-5, 1.0e-7, warnings)
    assert result["pass"] is False, "recording the floor must not change a verdict"
    assert result["single_precision_floor"] == pytest.approx(3.27e-6, rel=1e-2)
    assert result["max_abs_difference"] > result["single_precision_floor"], (
        "this difference is above one storage round-trip and must read that way")


def test_the_floor_is_never_used_as_a_tolerance():
    """A difference far below the floor still fails if the tolerance says so."""
    from umat_oti.validation.compare_results import _state_comparison

    warnings: list[str] = []
    result = _state_comparison(
        {"final_state_variables": [1.0e6]},
        {"final_state_variables": [1.0e6 + 0.01]},
        1.0e-9, 1.0e-12, warnings)
    assert result["max_abs_difference"] < result["single_precision_floor"]
    assert result["pass"] is False, (
        "the floor is context; only the tolerance decides")
