"""Unit tests for the local-solve probe injection."""

from __future__ import annotations

import pytest

from umat_oti.transform.internal_jacobian import LocalSolve, discover_local_solves
from umat_oti.transform.local_jacobian_probe import (
    ProbeInjectionError,
    inject_local_solve_probe,
    plan_probe_slots,
)

FIXED_SOURCE = """\
      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL,
     1 DDSDDT, DRPLDE, DRPLDT, STRAN, DSTRAN, TIME, DTIME, TEMP,
     2 DTEMP, PREDEF, DPRED, CMNAME, NDI, NSHR, NTENS, NSTATV, PROPS,
     3 NPROPS, COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, NOEL,
     4 NPT, LAYER, KSPT, KSTEP, KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS), STATEV(NSTATV), PROPS(NPROPS)
      GAM=0.0D0
      DO
        FGAM=GAM-1.0D0
        FJAC=1.0D0
        GAM=GAM-FGAM/FJAC
      END DO
      RETURN
      END
"""


def _solve() -> LocalSolve:
    solves = discover_local_solves(FIXED_SOURCE)
    assert len(solves) == 1
    return solves[0]


def test_slots_are_appended_past_the_declared_sizes():
    """Reusing an unused gap would break sources that sweep DO K=1,NSTATV."""
    slots = plan_probe_slots(nstatv=16, nprops=24)
    assert (slots.iterate, slots.residual, slots.jacobian) == (17, 18, 19)
    assert slots.nstatv == 20 and slots.seed_props == 25 and slots.nprops == 25


def test_observing_injection_keeps_the_newton_update_intact():
    solve = _solve()
    injected = inject_local_solve_probe(
        FIXED_SOURCE, solve, plan_probe_slots(nstatv=2, nprops=3),
        target_increment=1, override_iterate=False)
    assert "GAM=GAM-FGAM/FJAC" in injected.source
    assert "PROPS(4)" not in injected.source
    assert injected.source.count("STATEV(3)=GAM") == 1
    assert not injected.forced_exit


def test_records_are_placed_before_the_update_not_after():
    """Recording after the update would report the residual against the wrong iterate."""
    solve = _solve()
    lines = inject_local_solve_probe(
        FIXED_SOURCE, solve, plan_probe_slots(nstatv=2, nprops=3),
        target_increment=1, override_iterate=False).source.splitlines()
    record = next(i for i, line in enumerate(lines) if "STATEV(4)=FGAM" in line)
    update = next(i for i, line in enumerate(lines) if "GAM=GAM-FGAM/FJAC" in line)
    assert record < update


def test_seeding_injection_gates_on_the_target_increment():
    solve = _solve()
    injected = inject_local_solve_probe(
        FIXED_SOURCE, solve, plan_probe_slots(nstatv=2, nprops=3),
        target_increment=7, override_iterate=True)
    source = injected.source
    assert "IF (KINC.EQ.7) THEN" in source
    assert "GAM=PROPS(4)" in source
    # the original update survives on every other increment
    assert "ELSE" in source and "GAM=GAM-FGAM/FJAC" in source
    assert injected.forced_exit


def test_counter_reset_precedes_the_loop_so_it_does_not_reset_each_iteration():
    solve = _solve()
    lines = inject_local_solve_probe(
        FIXED_SOURCE, solve, plan_probe_slots(nstatv=2, nprops=3),
        target_increment=1, override_iterate=True).source.splitlines()
    reset = next(i for i, line in enumerate(lines) if "STATEV(6)=0.0D0" in line)
    loop = next(i for i, line in enumerate(lines) if line.strip() == "DO")
    assert reset < loop


def test_continuation_markers_do_not_fuse_onto_argument_names():
    """A dummy argument on a continuation line must still be found in scope.

    Column 6 holds the marker; failing to strip it yields names like "1 DDSDDT"
    and PROPS/KINC appear to be out of scope when they are not.
    """
    solve = _solve()
    injected = inject_local_solve_probe(
        FIXED_SOURCE, solve, plan_probe_slots(nstatv=2, nprops=3),
        target_increment=1, override_iterate=True)
    assert injected.enclosing_routine == "UMAT"


def test_labelled_update_is_refused_rather_than_silently_broken():
    """Moving a labelled statement into an IF makes any branch to it illegal."""
    source = FIXED_SOURCE.replace(
        "        GAM=GAM-FGAM/FJAC", "  901   GAM=GAM-FGAM/FJAC")
    solve = discover_local_solves(source)[0]
    with pytest.raises(ProbeInjectionError) as excinfo:
        inject_local_solve_probe(
            source, solve, plan_probe_slots(nstatv=2, nprops=3),
            target_increment=1, override_iterate=True)
    assert excinfo.value.code == "labelled_newton_update"


def test_solve_outside_a_umat_signature_is_refused():
    """A local solve in a helper without KINC/PROPS cannot be probed."""
    source = """\
      SUBROUTINE LOCAL(GAM, STATEV)
      DIMENSION STATEV(4)
      DO
        FGAM=GAM-1.0D0
        FJAC=1.0D0
        GAM=GAM-FGAM/FJAC
      END DO
      END
"""
    solve = discover_local_solves(source)[0]
    with pytest.raises(ProbeInjectionError) as excinfo:
        inject_local_solve_probe(
            source, solve, plan_probe_slots(nstatv=2, nprops=3),
            target_increment=1, override_iterate=True)
    assert excinfo.value.code == "probe_channel_not_in_scope"
    assert "KINC" in excinfo.value.detail
