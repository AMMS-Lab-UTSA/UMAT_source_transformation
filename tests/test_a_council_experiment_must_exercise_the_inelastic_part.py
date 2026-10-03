"""Informativeness of a council experiment, R4 (G7, D-19a rev 2).

An inelastic council row (reviewed family plasticity / damage / crystal /
viscous / concrete, or a routine that writes STATEV) is informative only if
residual_after_reversal fired, or tangent_change under small strain.
departure_from_linearity and state_change never count alone, and under
finite kinematics tangent_change alone does not count.
"""
import pytest

from umat_oti.abaqus.activation import Activation, Indicator, council_informative

pytestmark = pytest.mark.unit


def _act(*fired):
    names = ("state_change", "departure_from_linearity", "tangent_change",
             "residual_after_reversal")
    return Activation([Indicator(n, n in fired, 1.0 if n in fired else 0.0) for n in names], 40)


def test_a_plasticity_toy_below_yield_is_not_informative():
    r = council_informative(_act(), family="rate-independent plasticity",
                            demanded_nstatv=7, finite=False)
    assert r["inelastic"] and not r["informative"]


def test_state_movement_or_nonlinearity_alone_never_counts():
    r = council_informative(_act("state_change", "departure_from_linearity"),
                            family="damage / phase field", demanded_nstatv=2, finite=False)
    assert not r["informative"] and "alone never count" in r["reason"]


def test_a_finite_hyperelastic_toy_with_only_tangent_change_is_not_informative():
    r = council_informative(_act("tangent_change"), family="other (incl. hyperelastic)",
                            demanded_nstatv=1, finite=True)
    assert r["inelastic"] and r["by_state"] and not r["by_family"]
    assert not r["informative"]
    assert "resolved to inelastic" in r["disagreement"]


def test_the_counting_indicators_make_it_informative():
    assert council_informative(_act("residual_after_reversal"), family="crystal plasticity",
                               demanded_nstatv=0, finite=True)["informative"]
    assert council_informative(_act("tangent_change"), family="concrete / geomaterial",
                               demanded_nstatv=3, finite=False)["informative"]


def test_an_elastic_source_is_not_held_to_an_inelastic_event():
    r = council_informative(_act(), family="linear elastic", demanded_nstatv=0, finite=False)
    assert not r["inelastic"] and r["informative"]


WRITE_ONLY = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV,PROPS,DSTRAN)
      DIMENSION STRESS(NTENS),STATEV(NSTATV)
      STRESS(1) = STRESS(1) + PROPS(1)*DSTRAN(1)
      STATEV(1) = STRESS(1)
      STATEV(2) = PROPS(1)*DSTRAN(1)
      END
"""


def test_write_only_statev_is_elastic_with_output_state_only_with_both_witnesses():
    from umat_oti.abaqus.activation import statev_is_write_only
    assert statev_is_write_only(WRITE_ONLY)[0]
    reads = WRITE_ONLY.replace("STATEV(2) = PROPS(1)*DSTRAN(1)", "STATEV(2) = STATEV(2) + 1.0")
    assert not statev_is_write_only(reads)[0]
    in_condition = WRITE_ONLY.replace("STATEV(1) = STRESS(1)",
                                      "IF (STATEV(1) .GT. 0) STRESS(1) = 0.0")
    assert not statev_is_write_only(in_condition)[0]
    both = council_informative(_act(), family="linear elastic", demanded_nstatv=2, finite=False,
                               statev_write_only_static=True, statev_write_only_dynamic=True)
    assert not both["inelastic"] and both["informative"]
    assert "elastic with output state" in both["statev"]
    one = council_informative(_act(), family="linear elastic", demanded_nstatv=2, finite=False,
                              statev_write_only_static=True)
    assert one["inelastic"] and not one["informative"]
