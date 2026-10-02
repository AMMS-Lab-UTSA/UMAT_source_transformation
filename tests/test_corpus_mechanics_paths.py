"""Loading paths for corpus UMATs: layout, conventions, family coverage, provenance."""

from __future__ import annotations

import math

import numpy as np
import pytest

from umat_oti.corpus_features.loading_paths import (
    LoadingPath,
    amplitudes,
    identify_constants,
    is_isotropic,
    kinematics_between,
    layout,
    paths_for,
    rotation,
    total_strain,
)

pytestmark = pytest.mark.unit

J2_SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD)
      EMOD  = PROPS(1)
      ENU   = PROPS(2)
      SYIELD = PROPS(3)
      HARD  = PROPS(4)
      RETURN
      END
"""


def _entry(**kw):
    base = {
        "family": "plasticity",
        "ntens": 6,
        "kinematics": "small strain",
        "props": [200000.0, 0.3, 250.0, 1000.0],
        "source_text": J2_SOURCE,
        "source_id": "someone__repo/umat_j2.f",
    }
    base.update(kw)
    return base


@pytest.mark.parametrize("ntens,ndi,nshr", [(6, 3, 3), (4, 3, 1), (3, 2, 1)])
def test_every_increment_carries_exactly_ntens_components(ntens, ndi, nshr):
    for family in (
        "plasticity",
        "elasticity",
        "hyperelasticity",
        "viscoelasticity / rate dependent",
        "growth / morphoelasticity",
    ):
        for kin in ("small strain", "finite"):
            for path in paths_for(_entry(family=family, ntens=ntens, kinematics=kin)):
                assert (path.ntens, path.ndi, path.nshr) == (ntens, ndi, nshr)
                for inc in path.increments:
                    assert inc.dstran is not None and len(inc.dstran) == ntens


def test_an_ntens_that_is_not_a_continuum_layout_is_refused_not_guessed():
    with pytest.raises(ValueError):
        layout(5)
    with pytest.raises(ValueError):
        paths_for(_entry(ntens=2))


def test_a_source_that_is_not_a_umat_gets_no_path():
    assert paths_for(_entry(family="not a UMAT")) == []


def test_shear_is_engineering_in_dstran():
    """Simple shear F = I + g e1 x e2 has D12 = g/2 per unit time, so the
    ENGINEERING shear increment DSTRAN(4) is g, not g/2."""
    f1 = np.eye(3) + np.array([[0, 0.01, 0], [0, 0, 0], [0, 0, 0]])
    dstran, drot = kinematics_between(np.eye(3), f1, 6)
    assert dstran[3] == pytest.approx(0.01, rel=1e-4)
    assert np.allclose(dstran[:3], 0.0, atol=1e-4)
    assert drot[0, 1] == pytest.approx(0.005, rel=1e-3)  # spin = -D12 sign aside


def test_a_rigid_rotation_strains_nothing_and_rotates_by_drot():
    q = rotation((0, 0, 1), math.radians(5))
    dstran, drot = kinematics_between(np.eye(3), q, 6)
    assert np.allclose(dstran, 0.0, atol=1e-14)
    assert np.allclose(drot, q, atol=1e-5)


def test_plasticity_gets_monotonic_unload_reload_and_two_full_cycles():
    paths = {p.name: p for p in paths_for(_entry())}
    assert {"elastic_uniaxial", "plastic_uniaxial", "unload_reload", "cyclic"} <= set(
        paths
    )
    eps = [e[0] for e in total_strain(paths["cyclic"])]
    turns = sum(1 for a, b, c in zip(eps, eps[1:], eps[2:]) if (b - a) * (c - b) < 0)
    assert turns >= 3, (
        "two full tension-compression cycles reverse at least three times"
    )
    assert paths["cyclic"].closed and abs(eps[-1]) < 1e-15


def test_elasticity_is_not_driven_through_regimes_it_does_not_have():
    names = {p.regime for p in paths_for(_entry(family="elasticity"))}
    assert names == {"elastic"}


def test_rate_dependence_gets_a_hold_and_two_rates():
    paths = {
        p.name: p for p in paths_for(_entry(family="viscoelasticity / rate dependent"))
    }
    hold = [i for i in paths["relaxation"].increments if not any(i.dstran)]
    assert len(hold) >= 10
    slow, fast = paths["rate_slow"], paths["rate_fast"]
    assert slow.twin == "rate_fast" and fast.twin == "rate_slow"
    assert slow.increments[0].dtime == pytest.approx(100 * fast.increments[0].dtime)


def test_growth_is_driven_by_the_clock_with_no_deformation():
    paths = {
        p.name: p
        for p in paths_for(
            _entry(
                family="growth / morphoelasticity", kinematics="finite", total_time=50.0
            )
        )
    }
    free = paths["growth_free"]
    assert free.regime == "growth"
    assert all(not any(i.dstran) for i in free.increments)
    assert sum(i.dtime for i in free.increments) == pytest.approx(50.0)


def test_finite_strain_gets_shear_stretch_and_objectivity_twins_at_two_resolutions():
    paths = {
        p.name: p
        for p in paths_for(_entry(family="hyperelasticity", kinematics="finite"))
    }
    for name in (
        "finite_simple_shear",
        "finite_uniaxial_stretch",
        "objectivity_reference",
        "objectivity_rotated",
        "objectivity_reference_fine",
        "objectivity_rotated_fine",
    ):
        assert name in paths and paths[name].kinematics == "finite"
    ref, rot = paths["objectivity_reference"], paths["objectivity_rotated"]
    assert ref.twin == rot.name and rot.twin == ref.name
    assert len(paths["objectivity_reference_fine"].increments) == 4 * len(
        ref.increments
    )
    q = np.asarray(rot.rotation)
    assert np.allclose(
        np.asarray(rot.increments[-1].dfgrd1), q @ np.asarray(ref.increments[-1].dfgrd1)
    )


def test_amplitudes_come_from_identified_constants_with_provenance():
    amps = amplitudes(_entry())
    assert amps.inelastic == pytest.approx(5 * 250.0 / 200000.0)
    assert "SYIELD = PROPS(3)" in amps.provenance["yield_strain"]
    assert not amps.ladder


def test_registry_activation_is_used_when_no_yield_is_identified():
    amps = amplitudes(_entry(source_text="", activation_amplitude=0.01))
    assert amps.inelastic == pytest.approx(0.02)
    assert "activation_amplitude" in amps.provenance["inelastic"]


def test_an_unknown_scale_is_said_to_be_unknown_and_searched_by_a_ladder():
    entry = _entry(source_text="", activation_amplitude=None)
    amps = amplitudes(entry)
    assert amps.ladder and amps.inelastic is None
    assert "UNKNOWN" in amps.provenance["inelastic"]
    names = {p.name for p in paths_for(entry)}
    assert "plastic_ladder" in names and "plastic_uniaxial" not in names


def test_a_qualified_name_is_not_read_as_the_plain_quantity():
    text = (
        "      E=props(1) ! Young's modulus\n"
        "      Sy=props(3) ! Yield stress multiplier\n"
    )
    found = identify_constants(text, [1.0, 0.3, 345.0])
    assert "E" in found and "sigma_y" not in found


def test_isotropy_reads_the_file_not_the_repository_name():
    iso, why = is_isotropic(
        _entry(
            family="elasticity",
            source_id="BristolCompositesInstitute__abaci/test/data/umat.f",
            source_text="",
        )
    )
    assert iso is True, why
    iso, _ = is_isotropic(
        _entry(
            family="hyperelasticity", source_id="x__y/umat_transverse.f", source_text=""
        )
    )
    assert iso is False
    iso, _ = is_isotropic(
        _entry(
            family="growth / morphoelasticity",
            source_id="x__y/BodyForce-Growth.for",
            source_text="",
        )
    )
    assert iso is None


def test_unload_reload_starts_with_an_increment_below_every_transition():
    path = next(
        p
        for p in paths_for(_entry(source_text="", activation_amplitude=0.01))
        if p.name == "unload_reload"
    )
    assert isinstance(path, LoadingPath)
    assert path.increments[0].dstran[0] <= 1e-4 + 1e-18
