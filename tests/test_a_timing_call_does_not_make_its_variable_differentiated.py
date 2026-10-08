"""A variable that only receives a clock reading is not part of the response.

bennifuchs/TsaiWu-Fortran keeps ``real :: comp_time(2)`` and calls
``CPU_TIME(comp_time(1))``. The role classifier promoted it, and the transform
then (correctly) refused to hand a hypercomplex element to CPU_TIME. Rule (B17
notes, written first): a name whose every executable occurrence is an argument
of a timing call (CPU_TIME, SYSTEM_CLOCK, DATE_AND_TIME, DTIME, ETIME, SECOND,
CLOCK, ITIME, IDATE, TIMER) stays real. Any other use keeps the old behaviour.
Vendor timers DTIME/ETIME/SECOND... also pass through helper lifting.

Planted-error canaries: a timing variable that is also used in arithmetic stays
promotable, and a differentiated value handed to a timing call is still refused.
"""
from umat_oti.core.roles import timer_only_names
from umat_oti.transform import helper_lifting
from umat_oti.transform.source_transform import oti_arguments_into_untransformed_calls

SOURCE = """      subroutine umat(stress, ddsdde)
      real*8 stress(6), ddsdde(6,6), comp_time(2), t0, t1, scratch
      call cpu_time(comp_time(1))
      stress(1) = stress(1) + 1.0d0
      call cpu_time(comp_time(2))
      call system_clock(count)
      call dtime(t0, t1)
      scratch = 2.0d0
      call etime(scratch)
      stress(2) = scratch*stress(1)
c     comp_time(2)-comp_time(1) is only in a comment
      write(*,*) 'comp_time'
      end
"""


def test_a_name_that_only_receives_a_clock_reading_is_timer_only():
    names = timer_only_names(SOURCE)
    assert {"COMP_TIME", "T0", "T1", "COUNT"} <= names


def test_canary_a_timing_variable_that_is_also_computed_with_is_not_timer_only():
    names = timer_only_names(SOURCE)
    assert "SCRATCH" not in names          # SCRATCH feeds STRESS(2)
    assert "STRESS" not in names


def test_canary_a_differentiated_value_handed_to_a_timer_is_still_refused():
    transformed = ("      subroutine umat(stress_oti)\n"
                   "      call cpu_time(stress_oti(1))\n"
                   "      end\n")
    found = oti_arguments_into_untransformed_calls(transformed, "fixed")
    assert ("CPU_TIME", "STRESS_OTI") in found


def test_vendor_timers_pass_through_helper_lifting():
    for name in ("DTIME", "ETIME", "SECOND", "CLOCK", "CPU_TIME", "SYSTEM_CLOCK",
                 "DATE_AND_TIME"):
        assert name in helper_lifting.PASS_THROUGH_CALLS
    assert "SPRINC" not in helper_lifting.PASS_THROUGH_CALLS   # returns into the stress path


def test_the_classifier_keeps_a_timer_variable_real():
    from umat_oti.core.roles import suggest_variable_roles
    analysis = {"detected_variables": [
        {"variable_name": "COMP_TIME", "detected_type": "real", "detected_usage": ["write"],
         "detected_shape": "(2)", "read_write": "write"}]}
    row = suggest_variable_roles(analysis, SOURCE)[0]
    assert row["suggested OTIS role"] == "Keep real"
    row_without = suggest_variable_roles(analysis, SOURCE.replace("call cpu_time(comp_time(1))", "x = comp_time(1)*stress(1)"))[0]
    assert row_without["suggested OTIS role"] != "Keep real"
