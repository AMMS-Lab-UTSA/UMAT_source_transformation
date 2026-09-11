"""An error the step size cannot move is not "the closest step agreed only to".

A centred difference that is measuring something has an error that falls as
the step shrinks until cancellation takes over and it rises again. An error
that is the same number at every step size is not a truncation error at all:
it is a fixed disagreement about WHAT is being differentiated, and reporting
its smallest value as "the closest step agreed only to 3.200e-02, against a
tolerance of 1e-06" describes it as though a finer ladder might have helped.

MEASURED, from pass9's recorded sweeps
(``corpus_run/pass9/results/store_verification.jsonl``) and reproduced offline
against pass9's own compiled replay binaries.

``keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f``, row
``0eb82e2b175e1d50122acefb``, worst-component relative error of the OTI
tangent against the difference, at both chosen states:

    step    1e-1     1e-2     1e-3     1e-4     1e-5     1e-6     1e-7     1e-8
    inc 4   3.2003e-02 at every one of the eight, to five figures
    inc 2   3.2129e-02 at every one of the eight, to five figures

The cause is structural and the componentwise table says so: the converted
build's DDSDDE has its three shear rows identically zero -- DDSDDE(4,4) = 0
where the author's is 1.021165e+02 and the difference gives 1.019123e+02 --
and 3.2e-02 is that shear stiffness divided by the size of the matrix.

Against the same quantity on the four Jeff97 rows in the same batch, which
DO converge:

    c14b3e1b... inc 2: 1.80e-06, 6.03e-06, 2.41e-04, 1.20e-03, 1.80e-02, ...
    8b6b82c2... inc 4: 5.80e-05, 8.05e-04, 1.22e-02, 3.23e-02, 4.24e-01, ...

Four decades of movement against five figures of stillness. The two are not
the same finding and were reported as though they were.
"""
import pytest

from umat_oti.validation.finite_strain_tangent import (
    is_step_independent, plateau_steps)


#: pass9 row 0eb82e2b175e1d50122acefb, increment 4, the tangent comparison
#: sweep as recorded.
BIOFILM = {0.1: 3.2003e-02, 0.01: 3.2003e-02, 1e-3: 3.2003e-02,
           1e-4: 3.2003e-02, 1e-5: 3.2003e-02, 1e-6: 3.2003e-02,
           1e-7: 3.2003e-02, 1e-8: 3.2003e-02}

#: pass9 row c14b3e1b76081216b57abbf8, increment 2, the same field.
JEFF97 = {0.1: 1.8013861063013595e-06, 0.01: 6.033790599420604e-06,
          1e-3: 2.409447618858215e-04, 1e-4: 1.2026272029721733e-03,
          1e-5: 1.803206992198333e-02, 1e-6: 9.177490126177295e-04,
          1e-7: 1.2038555941562226, 1e-8: 7.874647163553265e-02}


def test_the_biofilm_sweep_is_reported_as_step_independent():
    assert is_step_independent(BIOFILM)


def test_a_sweep_that_moves_four_decades_is_not():
    assert not is_step_independent(JEFF97)


def test_a_two_point_sweep_cannot_establish_either():
    # Two points that happen to agree are not a ladder. Three is the fewest
    # that can show a trend, and the default asks for three.
    assert not is_step_independent({0.1: 1.0, 0.01: 1.0})
    assert is_step_independent({0.1: 1.0, 0.01: 1.0, 1e-3: 1.0})


def test_a_sweep_with_nothing_in_it_says_nothing():
    assert not is_step_independent({})
    assert not is_step_independent({0.1: float("nan"), 0.01: float("inf")})
    assert not is_step_independent({0.1: 0.0, 0.01: 0.0, 1e-3: 0.0})


def test_the_plateau_is_the_shape_of_the_sweep_not_its_best_point():
    # The Jeff97 sweep bottoms out at 1e-1 and 1e-2 and walks away from there.
    within = plateau_steps(JEFF97)
    assert 0.1 in within and 0.01 in within
    assert 1e-5 not in within and 1e-7 not in within


def test_a_flat_sweep_has_every_step_in_its_plateau():
    # Which is exactly why a plateau on its own cannot be the whole test: the
    # biofilm row has an eight-step "plateau" and has measured nothing.
    assert len(plateau_steps(BIOFILM)) == 8
    assert is_step_independent(BIOFILM), "and this is what says so"


def test_one_step_agreeing_is_not_a_plateau():
    lucky = {0.1: 1.0, 0.01: 1e-9, 1e-3: 1.0, 1e-4: 1.0}
    assert plateau_steps(lucky) == [0.01]


def test_the_tolerance_is_a_fraction_of_the_largest_error():
    drifting = {0.1: 1.0, 0.01: 0.999, 1e-3: 0.998}
    assert is_step_independent(drifting, tolerance=1e-2)
    assert not is_step_independent(drifting, tolerance=1e-4)


def test_a_plateau_of_exact_zeros_is_still_a_plateau():
    assert plateau_steps({0.1: 0.0, 0.01: 0.0, 1e-3: 1.0}) == [0.01, 0.1]


@pytest.mark.parametrize("width", [10.0, 100.0])
def test_a_wider_window_admits_more_steps(width):
    assert len(plateau_steps(JEFF97, width=width)) >= 2
