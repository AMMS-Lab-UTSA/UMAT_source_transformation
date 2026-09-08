"""What arrangement of agreeing step sizes corroborates a tangent.

The verdict asks two things of a finite-difference sweep: that the best step
agree within the tolerance, and that the agreement be corroborated by more
than one step -- because one step cannot separate truncation error from
cancellation error, and a single step landing on the right answer while its
neighbours do not is a coincidence.

The implementation used to accept only two arrangements: a contiguous plateau
within 10x the best Frobenius error, or agreement at EVERY step in the sweep.
Between those extremes sits the commonest shape, and neither accepted it.
Measured on PureGravity.for, whose sweep is reproduced below, five of six
steps agree and four of them by three orders of magnitude or better -- and it
was rejected. Thirty-three rows of one batch agreed to 1e-6 or better, some
to 6e-11, and were reported unverified for this reason alone.

These tests fix the criterion at the one the docstring states, and pin the
tolerance so a later change cannot quietly trade accuracy for pass rate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_store_in_abaqus import tangent_verdict  # noqa: E402


def sweep(*triples):
    """A sweep of (step, relative, frobenius) points.

    Both errors are given explicitly. Deriving one from the other would make
    the plateau rule and the agreement rule agree by construction, and the
    whole question here is what happens when they do not: the plateau is
    measured on the Frobenius error and the tolerance on the relative one.
    """
    relatives = [r for _, r, _ in triples]
    frobenii = [f for _, _, f in triples]
    return {"best_relative": min(relatives), "best_frobenius": min(frobenii),
            "sweep": [{"step": s, "relative": r, "frobenius": f}
                      for s, r, f in triples]}


#: The real sweep this fix came from, relative and Frobenius errors both as
#: measured: the error is at round-off at the largest step and grows
#: monotonically as cancellation takes over. Five of six steps agree within
#: 1e-6, and the plateau counts ONE, because 1.3862e+03 is 14.7x the best
#: Frobenius error and the plateau threshold is 10x.
PURE_GRAVITY = sweep(
    (1e-3, 9.9230e-11, 9.4566e+01), (1e-4, 6.9310e-10, 1.3862e+03),
    (1e-5, 1.0619e-08, 2.1190e+04), (1e-6, 1.0785e-07, 2.1520e+05),
    (1e-7, 7.0359e-07, 1.4074e+06), (1e-8, 5.7930e-06, 1.1557e+07))


# ---- what must now pass -------------------------------------------------
def test_five_of_six_steps_agreeing_over_four_decades_corroborates():
    ok, why = tangent_verdict(PURE_GRAVITY)
    assert ok
    assert "5 of 6" in why and "decades" in why


def test_two_steps_a_decade_apart_are_enough():
    ok, _ = tangent_verdict(sweep((1e-3, 1e-9, 1e2), (1e-4, 1e-3, 1e8),
                              (1e-5, 1e-8, 1e4)))
    assert ok


# ---- what must still fail ------------------------------------------------
def test_the_tolerance_is_not_negotiable():
    """Every step counted has to be within it; corroboration cannot buy
    accuracy that is not there."""
    ok, why = tangent_verdict(sweep((1e-3, 1e-5, 1e3), (1e-4, 2e-5, 2e3),
                                (1e-5, 3e-5, 3e3)))
    assert not ok and "1.000e-05" in why


def test_one_lucky_step_is_still_a_coincidence():
    ok, why = tangent_verdict(sweep((1e-3, 1e-9, 1e2), (1e-4, 1e-2, 1e9),
                                (1e-5, 1e-1, 1e10)))
    assert not ok and "1 step size" in why


def test_two_neighbouring_steps_do_not_corroborate_each_other():
    """They can sit inside one cancellation regime. A decade apart they
    cannot, because truncation and cancellation error scale oppositely in h."""
    ok, why = tangent_verdict(sweep(
        (2e-5, 1e-9, 1e2), (1e-5, 2e-9, 1e4), (1e-6, 1e-2, 1e16)))
    assert not ok and "decades" in why


def test_an_empty_sweep_is_not_agreement():
    assert not tangent_verdict({"sweep": []})[0]


def test_a_sweep_with_no_best_step_is_not_agreement():
    assert not tangent_verdict({"sweep": [{"step": 1e-3}]})[0]


def test_a_point_with_no_recorded_error_is_not_evidence():
    """The absence of a measurement must not count as a perfect one."""
    ok, _ = tangent_verdict({
        "best_relative": 1e-9, "best_frobenius": 1e9,
        "sweep": [{"step": 1e-3, "relative": 1e-9, "frobenius": 1e9},
                  {"step": 1e-8}]})
    assert not ok


# ---- the shapes that already worked keep working -------------------------
def test_a_plateau_still_corroborates():
    ok, why = tangent_verdict(sweep((1e-3, 1e-2, 1e9), (1e-4, 1.0e-9, 1e2),
                                    (1e-5, 1.4e-9, 1.4e2), (1e-6, 1e-3, 1e8)))
    assert ok and "plateau" in why


def test_every_step_agreeing_still_corroborates():
    ok, _ = tangent_verdict(sweep(
        (1e-3, 1e-13, 1e0), (1e-4, 1e-12, 1e1), (1e-5, 1e-11, 1e2),
        (1e-6, 1e-10, 1e3), (1e-7, 1e-9, 1e4), (1e-8, 1e-8, 1e5)))
    assert ok
