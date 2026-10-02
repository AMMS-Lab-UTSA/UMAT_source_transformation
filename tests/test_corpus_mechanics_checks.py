"""Mechanics checks: each one passes on a model that has the property, fails on
one that lacks it, and is NOT APPLICABLE (None) where the family is not
supposed to have it. Models here are small numpy materials, so every verdict
is checked against a case whose answer is known in closed form."""

from __future__ import annotations

import math

import numpy as np
import pytest

from umat_oti.corpus_features.loading_paths import (
    hooke_matrix,
    paths_for,
    tensor_to_voigt,
    voigt_to_tensor,
)
from umat_oti.corpus_features.mechanics_checks import (
    CATALOGUE,
    check_pair,
    monotone_state_slots,
    run_all,
    run_checks,
)

pytestmark = pytest.mark.unit

E, NU, SY, H = 200000.0, 0.3, 250.0, 1000.0
J2_SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD)
      EMOD  = PROPS(1)
      ENU   = PROPS(2)
      SYIELD = PROPS(3)
      HARD  = PROPS(4)
      STATEV(1) = EQPLAS
      RETURN
      END
"""


def _entry(**kw):
    base = {
        "family": "plasticity",
        "ntens": 6,
        "kinematics": "small strain",
        "props": [E, NU, SY, H],
        "source_text": J2_SOURCE,
        "source_id": "someone__repo/umat_j2.f",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# reference materials
# ---------------------------------------------------------------------------
def elastic_history(path, *, prestress=0.0, skew=0.0, d=None):
    d = hooke_matrix(E, NU, path.ntens) if d is None else d
    d = d + skew * (np.triu(np.ones_like(d), 1))
    rows, eps = [], np.zeros(path.ntens)
    for inc in path.increments:
        eps = eps + np.asarray(inc.dstran)
        s = d @ eps + prestress
        rows.append(
            {
                "stress": s,
                "statev": [0.0],
                "ddsdde": d,
                "sse": 0.5 * float(s @ eps),
                "spd": 0.0,
                "scd": 0.0,
            }
        )
    return rows


def j2_history(path, *, unload_stiffening=1.0, spd_factor=1.0):
    """Small-strain radial return, linear isotropic hardening (Simo-Hughes)."""
    ntens = path.ntens
    mu = E / (2 * (1 + NU))
    k = E / (3 * (1 - 2 * NU))
    sig = np.zeros((3, 3))
    p = 0.0
    spd = 0.0
    rows = []
    last_d = None
    for inc in path.increments:
        de = voigt_to_tensor(inc.dstran, ntens, engineering=True)
        trial = (
            sig
            + 2 * mu * (de - np.trace(de) / 3 * np.eye(3))
            + k * np.trace(de) * np.eye(3)
        )
        dev = trial - np.trace(trial) / 3 * np.eye(3)
        q = math.sqrt(1.5 * np.sum(dev * dev))
        f = q - (SY + H * p)
        d = hooke_matrix(E, NU, ntens)
        if f > 0:
            dg = f / (3 * mu + H)
            n = 1.5 * dev / q
            sig = trial - 2 * mu * dg * n
            spd += (SY + H * p + 0.5 * H * dg) * dg
            p += dg
        else:
            sig = trial
            if last_d is not None and unload_stiffening != 1.0:
                # a defect: unloading stiffer than the elastic modulus
                sig = sig + (unload_stiffening - 1.0) * (trial - rows[-1]["_t"])
        last_d = d
        s = tensor_to_voigt(sig, ntens, engineering=False)
        rows.append(
            {
                "stress": s,
                "statev": [p],
                "ddsdde": d,
                "sse": 0.0,
                "spd": spd * spd_factor,
                "scd": 0.0,
                "_t": sig.copy(),
            }
        )
    return rows


def neo_hookean(f, c10=0.5, d1=0.1, objective=True):
    j = np.linalg.det(f)
    b = f @ f.T if objective else f.T @ f  # F^T F is not objective
    bb = j ** (-2 / 3) * b
    return 2 * c10 / j * (bb - np.trace(bb) / 3 * np.eye(3)) + 2 / d1 * (
        j - 1
    ) * np.eye(3)


def nh_history(path, objective=True):
    rows = []
    for inc in path.increments:
        s = neo_hookean(np.asarray(inc.dfgrd1), objective=objective)
        rows.append(
            {
                "stress": tensor_to_voigt(s, path.ntens, engineering=False),
                "statev": [0.0],
                "ddsdde": np.eye(path.ntens),
                "sse": 0.0,
            }
        )
    return rows


def by_name(entry):
    return {p.name: p for p in paths_for(entry)}


def verdicts(results, name):
    return [r.passed for r in results if r.name == name]


# ---------------------------------------------------------------------------
def test_every_check_states_where_it_applies_and_what_it_assumes():
    for name, (applies, assumptions) in CATALOGUE.items():
        assert applies and assumptions, name


def test_a_correct_j2_material_passes_every_check_that_applies_to_it():
    # associative=True: von Mises flow is associative, so the symmetric
    # tangent is expected (without it the symmetry check is not applicable)
    entry = _entry(associative=True)
    runs = {n: (p, j2_history(p)) for n, p in by_name(entry).items()}
    results = run_all(entry, runs)
    failed = [(r.name, r.path, r.detail) for r in results if r.passed is False]
    assert not failed, failed
    assert all(isinstance(r.passed, (bool, type(None))) for r in results)
    for name in (
        "isotropy",
        "elastic_unloading_slope",
        "closed_cycle_work",
        "internal_variable_monotone",
        "initial_tangent_matches_identified_moduli",
        "ddsdde_major_symmetry",
    ):
        assert True in verdicts(results, name), name
    assert set(verdicts(run_all(_entry(), runs), "ddsdde_major_symmetry")) == {None}


def test_unloading_stiffer_than_elastic_fails():
    entry = _entry()
    path = by_name(entry)["unload_reload"]
    results = run_checks(entry, path, j2_history(path, unload_stiffening=1.3))
    assert verdicts(results, "elastic_unloading_slope") == [False]


def test_a_prestress_at_zero_strain_fails_and_a_hooke_material_does_not():
    entry = _entry(family="elasticity")
    path = by_name(entry)["elastic_uniaxial"]
    good = run_checks(entry, path, elastic_history(path))
    bad = run_checks(entry, path, elastic_history(path, prestress=5.0))
    assert verdicts(good, "stress_free_reference") == [True]
    assert verdicts(bad, "stress_free_reference") == [False]
    assert verdicts(bad, "closed_cycle_returns_stress_free") == [False]


def test_symmetry_is_required_of_elasticity_and_not_of_damage():
    path = by_name(_entry(family="elasticity"))["elastic_uniaxial"]
    hist = elastic_history(path, skew=1000.0)
    assert verdicts(
        run_checks(_entry(family="elasticity"), path, hist), "ddsdde_major_symmetry"
    ) == [False]
    assert verdicts(
        run_checks(_entry(family="damage / phase field"), path, hist),
        "ddsdde_major_symmetry",
    ) == [None]


def test_a_wrong_plane_stress_modulus_is_caught():
    """E/(1+nu^2) where E/(1-nu^2) belongs -- the abaci umat.f defect."""
    entry = _entry(family="elasticity", ntens=3)
    path = by_name(entry)["elastic_uniaxial"]
    d_bad = hooke_matrix(E, NU, 3)
    d_bad[:2, :2] *= (1 - NU * NU) / (1 + NU * NU)
    assert verdicts(
        run_checks(entry, path, elastic_history(path)),
        "initial_tangent_matches_identified_moduli",
    ) == [True]
    assert verdicts(
        run_checks(entry, path, elastic_history(path, d=d_bad)),
        "initial_tangent_matches_identified_moduli",
    ) == [False]


def test_an_anisotropic_response_fails_isotropy_only_when_isotropy_is_expected():
    entry = _entry(family="elasticity")
    paths = by_name(entry)
    d = hooke_matrix(E, NU, 6)
    d[0, 0] *= 1.5  # stiffer along x: not isotropic
    ref, rot = paths["isotropy_reference"], paths["isotropy_rotated"]
    iso = check_pair(entry, ref, elastic_history(ref), rot, elastic_history(rot))
    aniso = check_pair(
        entry, ref, elastic_history(ref, d=d), rot, elastic_history(rot, d=d)
    )
    assert iso.passed is True and aniso.passed is False
    transverse = dict(entry, source_id="x__y/umat_transverse.f")
    assert (
        check_pair(
            transverse, ref, elastic_history(ref, d=d), rot, elastic_history(rot, d=d)
        ).passed
        is None
    )


def test_objectivity_separates_b_from_c():
    entry = _entry(
        family="hyperelasticity", kinematics="finite", source_text="", props=[0.5, 0.1]
    )
    runs = {n: (p, nh_history(p)) for n, p in by_name(entry).items()}
    good = [r for r in run_all(entry, runs) if r.name == "objectivity"]
    runs_bad = {
        n: (p, nh_history(p, objective=False)) for n, p in by_name(entry).items()
    }
    bad = [r for r in run_all(entry, runs_bad) if r.name == "objectivity"]
    assert [r.passed for r in good] == [True]
    assert [r.passed for r in bad] == [False]


def test_a_healing_damage_variable_fails_monotonicity():
    text = "      STATEV(2+2*NTENS)=DAMAGE\n"
    assert monotone_state_slots(text, 4, 3, 1) == {
        10: ("damage", "line 1: STATEV(2+2*NTENS)=DAMAGE")
    }
    entry = _entry(family="damage / phase field", ntens=4, source_text=text)
    path = by_name(entry)["cyclic"]
    rows = [
        {"stress": [0.0] * 4, "statev": [0.0] * 9 + [d], "ddsdde": np.eye(4)}
        for d in np.concatenate([np.linspace(0, 0.5, 25), np.linspace(0.5, 0.4, 25)])
    ]
    assert verdicts(run_checks(entry, path, rows), "internal_variable_monotone") == [
        False
    ]


def test_a_dissipation_reported_twice_over_breaks_the_energy_balance():
    entry = _entry()
    path = by_name(entry)["plastic_uniaxial"]
    rows = j2_history(path)
    # add the stored energy so SSE is reported: 1/2 sigma : C^-1 sigma
    c_inv = np.linalg.inv(hooke_matrix(E, NU, 6))
    for row in rows:
        row["sse"] = 0.5 * float(row["stress"] @ c_inv @ row["stress"])
    assert verdicts(run_checks(entry, path, rows), "energy_balance") == [True]
    for row, bad in zip(rows, j2_history(path, spd_factor=2.0)):
        row["spd"] = bad["spd"]
    assert verdicts(run_checks(entry, path, rows), "energy_balance") == [False]


def test_a_reversible_material_that_dissipates_in_a_closed_cycle_fails():
    entry = _entry(family="elasticity")
    path = by_name(entry)["elastic_uniaxial"]
    rows = elastic_history(path)
    for k, row in enumerate(rows):  # hysteresis: stress lags on the way back
        if k >= 10:
            row["stress"] = np.asarray(row["stress"]) * 0.8
    assert verdicts(run_checks(entry, path, rows), "closed_cycle_work") == [False]
    # the same history is admissible for a dissipative family (W >= 0)
    assert verdicts(
        run_checks(_entry(family="plasticity"), path, rows), "closed_cycle_work"
    ) == [True]
