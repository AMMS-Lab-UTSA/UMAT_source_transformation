"""What corroborates a finite-difference tangent, and what only looks like it.

The plateau rule exists because one step cannot tell a truncation error from a
cancellation one: a single step landing on the right answer while its
neighbours do not is a coincidence, and calling that verification lets a
finite-difference check say whatever its author wants.

But a plateau is not the only shape a good sweep takes. An exact tangent on a
locally linear model has no truncation error to lose, so its centred difference
is already at round-off at the largest step and only degrades as the step
shrinks. Its plateau is one step wide by construction. Measured on
BristolCompositesInstitute__abaci: 8.08e-14 at 1e-3 rising monotonically to
5.49e-09 at 1e-8 -- six steps, every one agreeing better than 1e-8, recorded as
"the difference agreed at 1 step size".

Accepting that shape is stricter than the plateau, not weaker: it asks of every
step what the plateau asks only of the best one. The tolerance is unchanged.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from verify_store_in_abaqus import TANGENT_TOLERANCE, tangent_verdict  # noqa: E402


def sweep(*points):
    """A comparison shaped like compare_tangent's as_dict()."""
    rows = [{"step": step, "relative": relative, "frobenius": frobenius}
            for step, relative, frobenius in points]
    best = min(rows, key=lambda r: r["frobenius"])
    return {"sweep": rows, "best_relative": best["relative"],
            "best_frobenius": best["frobenius"], "best_step": best["step"]}


# ---- the monotone sweep, which used to be rejected ----------------------
MONOTONE = sweep(
    (1e-3, 8.0793e-14, 1.3342e-10),
    (1e-4, 1.4588e-12, 1.9752e-09),
    (1e-5, 6.8986e-12, 1.1431e-08),
    (1e-6, 5.6881e-11, 1.0142e-07),
    (1e-7, 8.6682e-10, 1.4354e-06),
    (1e-8, 5.4854e-09, 5.1523e-06),
)


def test_a_sweep_that_agrees_at_every_step_is_corroborated():
    verified, reason = tangent_verdict(MONOTONE)
    assert verified, reason
    assert "every one of 6 step sizes" in reason


def test_that_sweep_has_a_plateau_of_one_and_is_still_accepted():
    """The plateau rule alone rejected it; the reason must say what did not."""
    verified, reason = tangent_verdict(MONOTONE)
    assert verified
    assert "no truncation error left to lose" in reason


# ---- the classic plateau still passes -----------------------------------
def test_a_plateau_is_still_what_a_nonlinear_model_gives():
    verified, reason = tangent_verdict(sweep(
        (1e-2, 3.4787e-04, 1.2999e+00),
        (1e-3, 3.4789e-06, 1.2998e-02),
        (1e-4, 3.4803e-08, 1.3054e-04),
        (1e-5, 4.2510e-09, 1.8430e-05),
        (1e-6, 2.3682e-08, 1.5615e-04),
    ))
    assert verified and "plateau" in reason


# ---- what must still be rejected ----------------------------------------
def test_one_lucky_step_among_bad_neighbours_is_not_verification():
    """The coincidence the plateau rule exists to catch."""
    verified, reason = tangent_verdict(sweep(
        (1e-3, 5.0e-01, 5.0e+00),
        (1e-4, 1.0e-09, 1.0e-08),
        (1e-5, 8.0e-01, 8.0e+00),
        (1e-6, 9.0e-01, 9.0e+00),
    ))
    assert not verified
    assert "1 step size(s) on a plateau" in reason


def test_a_best_step_outside_the_tolerance_fails_whatever_its_shape():
    verified, reason = tangent_verdict(sweep(
        (1e-3, 4.9e-02, 9.1e+02),
        (1e-4, 4.9e-02, 9.1e+02),
        (1e-5, 4.9e-02, 9.1e+02),
    ))
    assert not verified and "against a tolerance" in reason


def test_a_sweep_with_one_step_is_never_enough():
    """Whatever it agreed to, nothing corroborates it."""
    verified, _ = tangent_verdict(sweep((1e-5, 1e-14, 1e-12)))
    assert not verified


def test_an_empty_sweep_is_not_verification():
    assert not tangent_verdict({"sweep": []})[0]
    assert not tangent_verdict({"sweep": [{"step": 1e-5}]})[0]


def test_a_point_with_no_recorded_error_is_not_read_as_agreement():
    """Absence of a number is not a zero, and must not corroborate."""
    verified, _ = tangent_verdict({
        "sweep": [{"step": 1e-3, "relative": 1e-14, "frobenius": 1e-12},
                  {"step": 1e-4},
                  {"step": 1e-5}],
        "best_relative": 1e-14, "best_frobenius": 1e-12, "best_step": 1e-3})
    assert not verified


def test_the_tolerance_itself_is_unchanged():
    """The rule gained a second shape; it did not loosen the threshold."""
    assert TANGENT_TOLERANCE == 1e-6
    verified, _ = tangent_verdict(sweep(
        (1e-3, 2e-6, 1e-3), (1e-4, 3e-6, 2e-3), (1e-5, 4e-6, 3e-3)))
    assert not verified, "every step agrees only to 2e-6, outside 1e-6"
