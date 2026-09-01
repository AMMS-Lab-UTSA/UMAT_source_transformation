"""The consistent tangent must be checked, and the check must be able to fail.

A verification that cannot fail is not a verification, so most of this file is
about the adjudicator refusing to bless values that are wrong -- including at
the structural zeros, which are the easiest place for a check to become
vacuous.
"""
from __future__ import annotations

import pytest

from umat_oti.validation.actual_umat_higher_order import (
    TANGENT_RELATIVE_TOLERANCE, TANGENT_ZERO_FRACTION, _tangent_row,
)

SCALE = 2.3e5


def _row(oti, analytic, numeric, scale=SCALE):
    return _tangent_row(1, "elastic", 1, 1, oti, analytic, numeric, scale)


def test_matching_value_agrees():
    row = _row(1.5e5, 1.5e5, 1.5e5)
    assert row["agrees"] is True
    assert row["judged_by"] == "relative"


def test_value_outside_the_tolerance_disagrees():
    exact = 1.5e5
    row = _row(exact * (1 + 1e-6), exact, exact)
    assert row["agrees"] is False
    assert row["relative_error"] > TANGENT_RELATIVE_TOLERANCE


def test_rounding_dust_at_a_structural_zero_is_a_zero_not_a_disagreement():
    """The 80-digit reference leaves ~1e-75 where the closed form gives 0.

    Divided by itself that is a 100% relative spread, which once made 26 exact
    zeros report as entries the references could not adjudicate.
    """
    row = _row(0.0, 0.0, 2.5e-76)
    assert row["reference_classification"] == "resolved"
    assert row["judged_by"] == "structural_zero"
    assert row["agrees"] is True


def test_a_nonzero_value_at_a_structural_zero_still_fails():
    """Giving the zero test a scale must not turn it into a blanket pass."""
    row = _row(1.0, 0.0, 2.5e-76)
    assert row["judged_by"] == "structural_zero"
    assert row["agrees"] is False


def test_the_zero_floor_scales_with_the_matrix():
    """The same absolute value is dust in a stiff tangent and a defect in a soft one.

    Both references put the entry at zero either way, so it is a structural
    zero either way. What the scale decides is whether the value the build
    returned is close enough to zero to count as zero.
    """
    value = SCALE * TANGENT_ZERO_FRACTION / 10.0
    stiff = _row(value, 0.0, 0.0)
    soft = _row(value, 0.0, 0.0, scale=SCALE / 1e6)
    assert stiff["judged_by"] == soft["judged_by"] == "structural_zero"
    assert stiff["agrees"] is True
    assert soft["agrees"] is False


def test_references_that_disagree_with_each_other_adjudicate_nothing():
    row = _row(1.0e5, 1.0e5, 1.2e5)
    assert row["reference_classification"] == "reference_unresolved"
    assert row["agrees"] is None


def test_a_missing_value_is_unresolved_not_zero():
    row = _row(None, 1.5e5, 1.5e5)
    assert row["reference_classification"] == "unresolved"
    assert row["agrees"] is None
    assert row["oti"] is None


@pytest.mark.parametrize("field", ["analytic_reference",
                                   "extended_precision_reference",
                                   "reference_spread", "matrix_scale",
                                   "structural_zero_floor", "justification"])
def test_every_row_records_what_it_was_judged_against(field):
    assert field in _row(1.5e5, 1.5e5, 1.5e5)


# --------------------------------------------------------------------------- #
# The generic path, which adjudicates against a compiled reference rather than
# a closed form, and so must decide when its reference is too coarse to speak.
# --------------------------------------------------------------------------- #
from umat_oti.validation.reference_resolution import ResolutionLadder  # noqa: E402
from umat_oti.validation.tangent_validation import (  # noqa: E402
    ZERO_FRACTION, _adjudicate, _summarise,
)


def _ladder(values):
    ladder = ResolutionLadder(props_index=1, array="DDSDDE",
                              steps=tuple(range(len(values))))
    ladder.values[(1, 1)] = tuple(values)
    return ladder


def _generic(values, oti, scale=SCALE, tolerance=1e-6):
    return _adjudicate(_ladder(values), 1, 1, 1, oti, tolerance, scale)


def test_a_value_the_reference_straddles_needs_no_tolerance():
    row = _generic([1.0e5, 1.1e5, 1.05e5], 1.06e5)
    assert row["agrees"] is True
    assert row["judged_by"] == "within_reference_resolution"


def test_a_value_outside_a_tight_reference_is_judged_on_relative_error():
    tight = [1.0e5, 1.0e5 + 1.0, 1.0e5 + 2.0]
    row = _generic(tight, 1.5e5)
    assert row["judged_by"] == "relative"
    assert row["agrees"] is False


def test_an_empty_ladder_is_unresolved_not_zero():
    """A reference that could not be evaluated must not read as a zero derivative."""
    row = _generic([], 1.5e5)
    assert row["reference_classification"] == "unresolved"
    assert row["agrees"] is None
    assert row["absolute_error"] is None


def test_a_nonzero_value_where_the_reference_says_zero_disagrees():
    row = _generic([0.0, 0.0, 0.0], SCALE * ZERO_FRACTION * 10)
    assert row["judged_by"] == "structural_zero"
    assert row["agrees"] is False


def test_the_summary_keeps_every_entry_in_the_denominator():
    rows = [_generic([1.0e5] * 3, 1.0e5), _generic([], 1.0e5),
            _generic([0.0] * 3, SCALE)]
    summary = _summarise(rows)
    assert summary["entries"] == 3
    assert summary["resolved"] + summary["unresolved"] == 3
    assert summary["disagreeing"] == 1


# --------------------------------------------------------------------------- #
# The finite-strain driver. A UMAT that computes its stress from the
# deformation gradient sees nothing at all if the driver holds F at the
# identity, so the tangent comparison there is between two zeros. What these
# check is that the driver perturbs the SAME thing the transform seeded, and
# that a reference which resolved nothing is not read as agreement.
# --------------------------------------------------------------------------- #
from pathlib import Path  # noqa: E402

from umat_oti.transform.source_transform import (  # noqa: E402
    _finite_dfgrd1_seed_lines, seeded_kinematics,
)
from umat_oti.validation.parameter_sensitivity_validation import (  # noqa: E402
    ReplayResult, _driver_payload, deformation_gradient_rows,
)
from umat_oti.validation.tangent_validation import (  # noqa: E402
    TangentCase, _driven_through, _driver_source, _gradient_increment,
    _gradient_perturbation, _kinematic_drive, _nontriviality, _sweep,
)


def _finite_drive(ntens=6):
    """The drive a finite-strain source gets, read off the transform's own seed."""
    return seeded_kinematics("\n".join(_finite_dfgrd1_seed_lines("free", ntens)))


def _small_strain_drive(ntens=6):
    return seeded_kinematics("\n".join(
        f"      DSTRAN_OTI({i}) = DSTRAN_OTI({i}) + OTI_E{i}"
        for i in range(1, ntens + 1)))


def _case(**kwargs):
    defaults = dict(name="probe", source_path=Path("/nonexistent.f"),
                    props=(1.0,), dstran_per_increment=(1e-4, 0, 0, 0, 0, 0),
                    n_increments=2, ntens=6, nstatv=1)
    defaults.update(kwargs)
    return TangentCase(**defaults)


def test_the_driver_perturbs_the_map_the_transform_seeded():
    """The reference is only a reference if it differentiates the same thing.

    The map is not re-implemented here: it is read back out of the seed lines
    the transform emits, so the two cannot drift apart.
    """
    drive = _finite_drive()
    assert drive.dfgrd1[1] == ((1, 1, 1.0),)
    assert drive.dfgrd1[4] == ((1, 2, 0.5), (2, 1, 0.5))
    # A unit step in direction 4 puts half of it in each off-diagonal member.
    assert _gradient_perturbation(drive, 4, 1.0) == [0, 0.5, 0, 0.5, 0, 0, 0, 0, 0]
    assert _gradient_perturbation(drive, 3, 2.0) == [0, 0, 0, 0, 0, 0, 0, 0, 2.0]


def test_the_base_advance_uses_the_same_map_as_the_perturbation():
    """Driving the path and perturbing it must be one operation at two sizes."""
    drive = _finite_drive()
    increment = _gradient_increment(drive, (1e-4, 0.0, 0.0, 2e-4, 0.0, 0.0))
    flat = [v for row in increment for v in row]
    expected = [a + b for a, b in zip(_gradient_perturbation(drive, 1, 1e-4),
                                      _gradient_perturbation(drive, 4, 2e-4))]
    assert flat == expected


def test_a_finite_strain_driver_advances_the_deformation_gradient():
    drive = _finite_drive()
    source = _driver_source(_case(), drive)
    assert "DFGRD1=DFGRD1+DFGRDINC" in source
    assert "DFGRD0=DFGRD1" in source
    # Row-major, matching the nine numbers the reference driver reshapes.
    assert "DFGRDINC(1,1)=0.0001_8" in source


def test_a_small_strain_driver_is_left_exactly_as_it_was():
    """The six sources that verify today must not be driven differently."""
    source = _driver_source(_case(), _small_strain_drive())
    assert "DFGRDINC" not in source
    assert "DFGRD1=DFGRD1+" not in source
    assert _driven_through(_small_strain_drive()) == "DSTRAN"


def test_a_direction_seeded_into_nothing_gets_no_reference():
    """Not a zero derivative -- no derivative. It must read as unresolved."""
    drive = seeded_kinematics("      DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1")

    def _never_called(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("nothing should be replayed for an unseeded direction")

    ladder = _sweep(_case(), Path("/nonexistent"), [[0.0] * 6, [0.0] * 6],
                    None, drive, 1, 5, _never_called)
    assert ladder.steps == ()
    assert _adjudicate(ladder, 1, 1, 5, 0.0, 1e-6, 0.0)["agrees"] is None


def test_a_reference_that_is_all_zeros_is_not_an_agreement():
    """A driver that leaves the model undeformed makes every entry vacuous."""
    case = _case()
    undeformed = ReplayResult(stress=[[0.0] * 6] * 2, statev=[[0.0]] * 2)
    rows = [{"reference": 0.0} for _ in range(36)]
    verdict = _nontriviality(case, undeformed, rows)
    assert verdict["nontrivial"] is False
    assert verdict["noise_floor"] > 0.0


def test_a_reference_carrying_signal_passes_the_same_gate():
    case = _case()
    loaded = ReplayResult(stress=[[2.0e2] + [0.0] * 5] * 2, statev=[[0.0]] * 2)
    rows = [{"reference": 1.0e5}] + [{"reference": 0.0} for _ in range(35)]
    assert _nontriviality(case, loaded, rows)["nontrivial"] is True


def test_the_reference_can_be_perturbed_on_one_increment_only():
    """A perturbation spread over every increment is a different derivative."""
    rows = deformation_gradient_rows([[float(i)] * 9 for i in range(3)], 3)
    assert rows[1] == [1.0] * 9
    payload = _driver_payload([1.0], [[0.0] * 6] * 3, rows)
    assert payload.count("\n") == 1 + 1 + 6  # props, count, 3 x (strain + F)
    assert "2.00000000000000000e+00" in payload


def test_one_gradient_row_means_the_same_advance_every_increment():
    assert deformation_gradient_rows([1.0] * 9, 3) == [[1.0] * 9] * 3
    assert deformation_gradient_rows(None, 3) is None


@pytest.mark.parametrize("bad", [[1.0] * 8, [[1.0] * 9] * 2])
def test_a_gradient_path_of_the_wrong_shape_is_refused(bad):
    with pytest.raises(ValueError):
        deformation_gradient_rows(bad, 3)


def test_the_drive_is_read_from_the_transformed_file(tmp_path):
    """Which driver a source gets is decided by its interface, not its name."""
    emitted = tmp_path / "transformed_umat.f90"
    emitted.write_text("\n".join(_finite_dfgrd1_seed_lines("free", 6)),
                       encoding="utf-8")
    drive = _kinematic_drive(emitted)
    assert drive.drives_deformation_gradient
    assert not drive.drives_strain_increment
    assert _driven_through(drive) == "DFGRD1"


def test_a_stress_that_is_not_a_number_fails_parity(tmp_path):
    """NaN passes every comparison written as a difference, so it is caught here.

    Both builds returning NaN would otherwise agree, and the run would go on
    to difference NaN against NaN and report that as a derivative.
    """
    from umat_oti.validation.tangent_validation import _primal_parity

    primal = tmp_path / "tangent_primal.csv"
    primal.write_text(
        "increment,stress_1,statev_1\n1,NaN,0.0\n", encoding="utf-8")
    original = ReplayResult(stress=[[float("nan")]], statev=[[0.0]])
    parity = _primal_parity(original, primal, _case(ntens=1))
    assert parity["agrees"] is False
    assert "not a finite number" in parity["reason"]


def test_two_builds_that_agree_on_a_real_stress_still_pass(tmp_path):
    from umat_oti.validation.tangent_validation import _primal_parity

    primal = tmp_path / "tangent_primal.csv"
    primal.write_text(
        "increment,stress_1,statev_1\n1,2.5e2,0.0\n", encoding="utf-8")
    original = ReplayResult(stress=[[250.0]], statev=[[0.0]])
    assert _primal_parity(original, primal, _case(ntens=1))["agrees"] is True
