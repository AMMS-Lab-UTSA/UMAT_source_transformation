""""Different iterate" is a claim about a loop; here is how to watch the loop.

The ordinary probe writes what went into a call and what came out. The author's
convergence loop runs between those two records and leaves no trace, so the
hypothesis that the two builds took different passes through it was being
carried on a regular expression matching ``newton|converg|do while`` somewhere
in the file.

On ``huang_umat_97.for`` that match is the word "converg" in a comment. The
routine's actual iteration is ``1000 CONTINUE`` at line 702 and ``GO TO 1000``
at line 1352, guarded by ``IF (IDBACK.NE.0.AND.NITRTN.LT.ITRMAX)``, with the
residual ``RESIDU`` tested against ``GAMERR`` at line 1338. No search for
``DO WHILE`` finds any of it.
"""
import pytest

from umat_oti.abaqus.internal_iteration import (
    TraceRecord, compare_passes, instrument_internal_loops, parse_trace,
    passes_per_call, residuals_per_call, trace_points, watched_scalars)

pytestmark = pytest.mark.unit


def _discovery_cache():
    """Where the downloaded corpus sources live on this machine.

    Configurable, and skipped when absent. Written as a bare relative path
    (``discovery_cache/...``) it resolved only when pytest happened to be run
    from one particular directory, so the test skipped everywhere instead of
    running anywhere -- which reads exactly like a passing suite.
    """
    import os
    import pathlib as _pathlib

    import pytest as _pytest

    where = _pathlib.Path(
        os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
        or _pathlib.Path.home() / "softwarex_work" / "discovery_cache")
    if not where.is_dir():
        _pytest.skip(f"no discovery cache at {where}; "
                     f"set UMAT_OTI_DISCOVERY_CACHE")
    return where


def _abaqus_public_interfaces():
    """Abaqus's own header directory, or a skip."""
    import os
    import pathlib as _pathlib

    import pytest as _pytest

    where = _pathlib.Path(
        os.environ.get("UMAT_OTI_ABAQUS_HEADERS")
        or "/usr/SIMULIA/EstProducts/2021/SMAUsubs/PublicInterfaces")
    if not where.is_dir():
        _pytest.skip(f"no Abaqus headers at {where}; "
                     f"set UMAT_OTI_ABAQUS_HEADERS")
    return where

F77_LOOP = """\
      SUBROUTINE UMAT(STRESS,STATEV,PROPS,NOEL,NPT,KINC)
      DIMENSION STRESS(6),STATEV(4)
      NITRTN=-1
      STRESS(1)=0.D0
1000  CONTINUE
      NITRTN=NITRTN+1
      RESIDU=STRESS(1)-1.D0
      IF (ABS(RESIDU).GT.GAMERR) IDBACK=1
      IF (IDBACK.NE.0.AND.NITRTN.LT.ITRMAX) THEN
         GO TO 1000
      END IF
      RETURN
      END
"""

NO_LOOP = """\
      SUBROUTINE UMAT(STRESS,STATEV,PROPS,NOEL,NPT,KINC)
      DIMENSION STRESS(6),STATEV(4)
      STRESS(1)=2.D0*STATEV(1)
      RETURN
      END
"""


def test_a_backward_go_to_is_an_authors_loop_and_a_do_while_search_misses_it():
    points, _ = trace_points(F77_LOOP)
    kinds = {point.kind for point in points}
    assert "loop_back" in kinds
    assert any("GO TO 1000" in point.statement for point in points)


def test_a_forward_go_to_is_not_a_loop():
    """A jump to a label that has not been seen yet leaves the loop, it does
    not close one, and counting it would report an escape as an iteration."""
    forward = F77_LOOP.replace("1000  CONTINUE\n", "").replace(
        "         GO TO 1000\n", "         GO TO 9000\n") + "9000  CONTINUE\n"
    points, _ = trace_points(forward)
    assert not [point for point in points if point.kind == "loop_back"]


def test_the_residual_the_routine_tests_is_found_without_being_named():
    """``IF (ABS(RESIDU).GT.GAMERR)`` names the per-iteration residual norm.
    An experiment whose watch list has to be filled in per file is one nobody
    runs over forty entries."""
    assert watched_scalars(F77_LOOP) == ["RESIDU"]


def test_an_iteration_count_is_not_mistaken_for_a_residual():
    """``NITRTN`` is compared against ``ITRMAX`` in the same routine. Writing
    DBLE(NITRTN) into the residual column would put an iteration number where
    a norm is read."""
    assert "NITRTN" not in watched_scalars(F77_LOOP)


def test_a_routine_with_no_loop_is_reported_as_having_none_to_trace():
    """Which is itself the answer: a routine with no internal iteration cannot
    have converged to a different iterate, and the hypothesis should never have
    been raised for it."""
    instrumentation = instrument_internal_loops(NO_LOOP, "original")
    assert not instrumentation.usable
    assert "no internal iteration" in instrumentation.reason


def test_the_counter_is_incremented_before_the_jump_not_after_it():
    """A statement placed after ``GO TO`` is unreachable, and a trace that
    never fires reads as a loop that never ran."""
    instrumentation = instrument_internal_loops(F77_LOOP, "original")
    lines = instrumentation.text.splitlines()
    jump = next(i for i, line in enumerate(lines) if line.strip() == "GO TO 1000")
    above = "\n".join(lines[max(0, jump - 4):jump])
    assert "OTIS_TRACE" in above and "DBLE(RESIDU)" in above


def test_the_counter_restarts_every_call():
    """The hypothesis is about how many passes THIS call took. A counter that
    accumulated over the run would report the total and hide the difference."""
    instrumentation = instrument_internal_loops(F77_LOOP, "original")
    assert "OTI_TC0 = 0" in instrumentation.text


def test_a_logical_if_on_the_state_is_reported_as_not_traced():
    """A trace placed after ``IF (ABS(RESIDU).GT.GAMERR) IDBACK=1`` fires
    whether the branch was taken or not. "the branches agreed" and "the
    branches this could see agreed" are different claims."""
    _, skipped = trace_points(F77_LOOP)
    assert any("IDBACK=1" in point.statement for point in skipped)


def test_equal_pass_counts_in_every_call_are_what_refutes_the_hypothesis():
    left = [TraceRecord("original", "G1352.RESIDU", 1, 1, 1, n, 1e-3 / n)
            for n in (1, 2)]
    right = [TraceRecord("transformed", "G1352.RESIDU", 1, 1, 1, n, 1e-3 / n)
             for n in (1, 2)]
    result = compare_passes(left, right)
    assert result["differ"] == {}
    assert "same number of times" in result["verdict"]


def test_a_difference_in_pass_count_is_reported_per_call_not_as_a_total():
    left = [TraceRecord("original", "G.R", 1, 1, 1, n, 0.0) for n in (1, 2)]
    right = [TraceRecord("transformed", "G.R", 1, 1, 1, n, 0.0)
             for n in (1, 2, 3)]
    result = compare_passes(left, right)
    assert result["differ"] == {"('G.R', 1, 1, 1)": (2, 3)}


def test_a_trace_line_round_trips_through_the_reader(tmp_path):
    path = tmp_path / "original_trace.txt"
    path.write_text(
        "TRACE original G1352.RESIDU        1        1        1        2"
        "   0.12345678901234567E-003\n"
        "TRACE original B710        1        1        1        1 not_measured\n")
    records = parse_trace(path)
    assert len(records) == 2
    assert records[0].ordinal == 2
    assert records[0].value == pytest.approx(1.2345678901234567e-4)
    assert records[1].value is None
    assert passes_per_call(records)[("G1352.RESIDU", 1, 1, 1)] == 2
    assert residuals_per_call(records)[("G1352.RESIDU", 1, 1, 1)] == \
        [pytest.approx(1.2345678901234567e-4)]


def test_a_point_with_nothing_to_report_writes_not_measured_not_zero():
    """A trace that substituted zero for "not measured" would read as
    convergence."""
    instrumentation = instrument_internal_loops(F77_LOOP, "original")
    assert "not_measured" in instrumentation.text


@pytest.mark.fortran
def test_the_traced_crystal_plasticity_source_compiles():
    """Compiled with the pass9 flags from
    corpus_run/pass9/work/0d97f9db648d23a064062989/original/original.com."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    ifort = shutil.which("ifort")
    if ifort is None:
        pytest.skip("no ifort on PATH")
    include = _abaqus_public_interfaces()
    source = _discovery_cache() / (
        "RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for")
    if not source.is_file():
        pytest.skip(f"{source.name} is not in the discovery cache")
    instrumentation = instrument_internal_loops(
        source.read_text(errors="replace"), "original")
    assert instrumentation.usable
    with tempfile.TemporaryDirectory() as work:
        shim = Path(work) / "inc"
        shim.mkdir()
        for header in include.iterdir():
            (shim / header.name).symlink_to(header)
            (shim / header.name.upper()).symlink_to(header)
        target = Path(work) / "traced.f"
        target.write_text(instrumentation.text)
        finished = subprocess.run(
            [ifort, "-c", "-fpp", "-fPIC", "-extend-source", "-DABQ_LNX86_64",
             "-DABQ_FORTRAN", "-auto", "-pc64", "-fp-model", "precise",
             f"-I{shim}", "-o", str(Path(work) / "traced.o"), str(target)],
            capture_output=True, text=True, cwd=work)
        assert finished.returncode == 0, finished.stdout + finished.stderr
