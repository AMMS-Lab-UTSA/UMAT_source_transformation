"""B2 mechanics checks: elastic-only gating, unrepresentable layouts, and the
plasticity coverage (Bauschinger shift, back-stress sign, evolving modulus).

Every check is shown to PASS on a model that has the property and to FAIL on
one that lacks it (a mutant), with closed-form 1D materials driven along the
real ``reverse_yield`` / ``cyclic`` / ``unload_reload`` paths. The corpus
validation on original UMATs is in
corpus_campaign/batches/B2/curie/plasticity/ (results.json).
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
from _workspace import WORKSPACE

from umat_oti.corpus_features.loading_paths import paths_for, total_strain
from umat_oti.corpus_features.mechanics_checks import (
    CheckResult,
    check_back_stress_sign,
    check_bauschinger_shift,
    check_elastic_unloading_slope,
    check_initial_tangent_pd,
    first_increment_elastic,
    layout_unsupported,
    modulus_evolves,
    run_checks,
    summarise,
    yield_function_for,
)

pytestmark = pytest.mark.unit

E, SY = 200000.0, 500.0
SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD)
      STATEV(1) = EQPLAS
      RETURN
      END
"""


def _entry(**kw):
    base = {
        "family": "plasticity",
        "ntens": 6,
        "kinematics": "small strain",
        "props": [E, 0.3, SY, 1000.0],
        "source_text": SOURCE,
        "source_id": "someone__repo/umat.f",
        "activation_amplitude": 0.01,
    }
    base.update(kw)
    return base


def _path(name, **kw):
    return {p.name: p for p in paths_for(_entry(**kw))}[name]


def one_d(path, *, c_kin=0.0, h_iso=0.0, e_unload=None):
    """1D return mapping driven by eps11: kinematic modulus ``c_kin`` (negative:
    the centre moves AGAINST the flow), isotropic modulus ``h_iso``.
    STATEV = [p, alpha11..alpha33, alpha12..] (back stress in Voigt slots 2..7)."""
    rows = []
    eps_p = alpha = p = 0.0
    e_now = E
    for eps in (e[0] for e in total_strain(path)):
        if e_unload is not None and p > 0:
            e_now = e_unload
        trial = e_now * (eps - eps_p)
        xi = trial - alpha
        f = abs(xi) - (SY + h_iso * p)
        sigma = trial
        if f > 0:
            sign = 1.0 if xi > 0 else -1.0
            dg = f / (e_now + c_kin + h_iso)
            eps_p += dg * sign
            alpha += c_kin * dg * sign
            p += dg
            sigma = e_now * (eps - eps_p)
        stress = np.zeros(path.ntens)
        stress[0] = sigma
        back = np.zeros(path.ntens)
        back[0] = alpha
        rows.append(
            {
                "stress": stress,
                "statev": [p, *back],
                "ddsdde": np.eye(path.ntens) * E,
                "sse": 0.0,
                "spd": 0.0,
                "scd": 0.0,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Bauschinger shift and back-stress sign
# ---------------------------------------------------------------------------
def test_kinematic_hardening_shows_a_positive_shift():
    path = _path("reverse_yield")
    r = check_bauschinger_shift(_entry(), path, one_d(path, c_kin=20000.0))
    assert r.passed is True and r.value > 1e-3
    assert "Bauschinger shift" in r.detail


def test_isotropic_hardening_shows_no_shift_and_passes():
    path = _path("reverse_yield")
    r = check_bauschinger_shift(_entry(), path, one_d(path, h_iso=20000.0))
    assert r.passed is True
    assert "isotropic" in r.detail


def test_a_centre_moving_against_the_flow_fails():
    path = _path("reverse_yield")
    r = check_bauschinger_shift(_entry(), path, one_d(path, c_kin=-20000.0))
    assert r.passed is False
    assert "AGAINST" in r.detail


def test_a_declared_back_stress_with_no_shift_fails():
    path = _path("reverse_yield")
    entry = _entry(back_stress_slots=[2, 3, 4, 5, 6, 7], back_stress_evidence="test")
    r = check_bauschinger_shift(entry, path, one_d(path, h_iso=20000.0))
    assert r.passed is False
    assert "back stress" in r.detail


def test_bauschinger_is_judged_on_the_fine_reverse_path_only():
    path = _path("cyclic")
    r = check_bauschinger_shift(_entry(), path, one_d(path, c_kin=20000.0))
    assert r.passed is None


def test_back_stress_sign_passes_with_the_flow_and_fails_against_it():
    path = _path("cyclic")
    entry = _entry(back_stress_slots=[2, 3, 4, 5, 6, 7], back_stress_evidence="test")
    good = check_back_stress_sign(entry, path, one_d(path, c_kin=20000.0))
    assert good.passed is True and good.value > 0.99
    bad_rows = one_d(path, c_kin=20000.0)
    for row in bad_rows:  # mutant: the stored back stress has the wrong sign
        row["statev"] = [row["statev"][0]] + [-v for v in row["statev"][1:]]
    bad = check_back_stress_sign(entry, path, bad_rows)
    assert bad.passed is False


def test_back_stress_sign_is_not_applicable_without_identified_slots():
    path = _path("cyclic")
    assert check_back_stress_sign(_entry(), path, one_d(path)).passed is None


# ---------------------------------------------------------------------------
# elastic-only checks gated on demonstrated elastic increments (Vera F)
# ---------------------------------------------------------------------------
def test_pd_check_is_not_applicable_when_increment_one_moved_the_state():
    path = _path("elastic_uniaxial")
    rows = [
        {
            "stress": np.zeros(6),
            "statev": [1e-3],
            "ddsdde": -np.eye(6),
            "sse": 0.0,
            "spd": 0.0,
            "scd": 0.0,
        }
        for _ in path.increments
    ]
    r = check_initial_tangent_pd(_entry(), path, rows)
    assert r.passed is None
    assert "internal variables moved" in r.detail


def test_pd_check_still_fails_a_nonpd_tangent_on_a_demonstrated_elastic_increment():
    path = _path("elastic_uniaxial")
    rows = [
        {
            "stress": np.zeros(6),
            "statev": [0.0],
            "ddsdde": -np.eye(6),
            "sse": 0.0,
            "spd": 0.0,
            "scd": 0.0,
        }
        for _ in path.increments
    ]
    assert check_initial_tangent_pd(_entry(), path, rows).passed is False


def test_unnamed_state_movement_is_not_demonstrated_elastic():
    path = _path("elastic_uniaxial")
    rows = [
        {
            "stress": np.zeros(6),
            "statev": [0.0, 1.0],
            "ddsdde": np.eye(6),
            "sse": 0.0,
            "spd": 0.0,
            "scd": 0.0,
        }
        for _ in path.increments
    ]
    entry = _entry(source_text="      SUBROUTINE UMAT\n      END\n")
    ok, why = first_increment_elastic(entry, path, rows)
    assert ok is None and "not demonstrated" in why


def test_dissipation_at_increment_one_is_inelastic():
    path = _path("elastic_uniaxial")
    rows = [
        {
            "stress": np.zeros(6),
            "statev": [0.0],
            "ddsdde": np.eye(6),
            "sse": 0.0,
            "spd": 1.0,
            "scd": 0.0,
        }
        for _ in path.increments
    ]
    ok, why = first_increment_elastic(_entry(), path, rows)
    assert ok is False and "dissipated" in why


# ---------------------------------------------------------------------------
# a layout the source cannot represent is unsupported, not failed
# ---------------------------------------------------------------------------
#: Synthetic, standing for awhelanUCD .../lemaitreDamageNonLocal.f: an
#: isotropic tangent written as a direct block over ``do k=1,3`` and a shear
#: diagonal from index 4. No corpus text is copied.
LEMAITRE = """\
      subroutine umat(stress,statev,ddsdde)
      do k=1,3
       do l=1,3
        ddsdde(l,k)=alam
       end do
       ddsdde(k,k)=alam+2.d0*gmod
      end do
      do k=4,ntens
       ddsdde(k,k)=gmod
      end do
      end
"""


def test_plane_stress_of_a_shear_from_four_routine_is_unsupported():
    entry = _entry(family="damage / phase field", ntens=3, source_text=LEMAITRE)
    path = _path("elastic_uniaxial", ntens=3)
    assert "at least NTENS=4" in layout_unsupported(entry, path)
    rows = [
        {
            "stress": np.zeros(3),
            "statev": [0.0],
            "ddsdde": np.eye(3),
            "sse": 0.0,
            "spd": 0.0,
            "scd": 0.0,
        }
        for _ in path.increments
    ]
    results = run_checks(entry, path, rows)
    statuses = {r.name: r.status for r in results}
    assert statuses["history_finite"] == "passed"
    assert {s for n, s in statuses.items() if n != "history_finite"} == {"unsupported"}
    assert (
        summarise(results)[
            "isotropy"
            if "isotropy" in statuses
            else "initial_tangent_positive_definite"
        ]["unsupported"]
        == 1
    )


def test_the_same_routine_at_its_own_layout_is_supported():
    entry = _entry(family="damage / phase field", ntens=4, source_text=LEMAITRE)
    assert layout_unsupported(entry, _path("elastic_uniaxial", ntens=4)) == ""


def test_a_routine_that_tests_for_the_layout_handles_it():
    # abaci test/data/umat.f: an explicit `ndi==2 .and. nshr==1` branch
    text = (
        "      subroutine umat(stress,ddsdde)\n"
        "      if (ndi==2 .and. nshr==1) then\n        ddsdde(3,3) = 1.d0\n"
        "      else\n        ddsdde(6,6) = 1.d0\n      endif\n      end\n"
    )
    entry = _entry(ntens=3, source_text=text)
    assert layout_unsupported(entry, _path("elastic_uniaxial", ntens=3)) == ""


def test_status_defaults_from_passed():
    assert CheckResult("x", True, 0, 0, "").status == "passed"
    assert CheckResult("x", False, 0, 0, "").status == "failed"
    assert CheckResult("x", None, None, None, "").status == "not_applicable"


# ---------------------------------------------------------------------------
# evolving elastic modulus (theysy MML_U3: EMOD=STATEV(3))
# ---------------------------------------------------------------------------
MML_LINE = "      EMOD=STATEV(3)\n      STATEV(1)=EQPLAS\n"


def test_modulus_read_from_state_is_identified():
    assert "EMOD=STATEV(3)" in modulus_evolves(MML_LINE)
    assert modulus_evolves(SOURCE) == ""


def test_a_degraded_unloading_modulus_passes_only_when_the_source_evolves_it():
    path = _path("unload_reload")
    rows = one_d(path, h_iso=20000.0, e_unload=0.94 * E)
    plain = check_elastic_unloading_slope(_entry(), path, rows)
    assert plain.passed is False
    evolving = check_elastic_unloading_slope(
        _entry(source_text=SOURCE + MML_LINE), path, rows
    )
    assert evolving.passed is True
    assert "state variable" in evolving.detail
    stiffer = one_d(path, h_iso=20000.0, e_unload=1.06 * E)
    assert (
        check_elastic_unloading_slope(
            _entry(source_text=SOURCE + MML_LINE), path, stiffer
        ).passed
        is False
    )


# ---------------------------------------------------------------------------
# yield functions identified from corpus text
# ---------------------------------------------------------------------------
#: Synthetic, standing for jasonanewcoder .../umat_mises_plasticity_official.f
#: (a republished Abaqus example, so none of its text is used): a yield stress
#: read from PROPS(3) and a hardening modulus from PROPS(4), the stress
#: returned radially onto the yield stress plus the hydrostatic part, and the
#: equivalent plastic strain stored after the two NTENS blocks.
JASON = """\
      SIG0=PROPS(3)
      HMOD=PROPS(4)
      DO I=1,NDI
        STRESS(I)=DIRN(I)*SIG0+PHYD
      END DO
      STATEV(1+2*NTENS)=PEEQ
"""


def test_the_official_example_is_identified_and_its_stress_sits_off_its_surface():
    entry = _entry(source_text=JASON)
    yf = yield_function_for(entry)
    assert yf is not None and yf.plastic_slot(6) == 13
    # the routine returns |s| = SYIELD while EQPLAS grows: f = -HARD * p
    stress = np.array([SY, 0, 0, 0, 0, 0]) * 1.0
    statev = np.zeros(13)
    statev[12] = 0.01
    f, sy = yf.residual(stress, statev, entry["props"], 6)
    assert f == pytest.approx(-1000.0 * 0.01) and sy == pytest.approx(SY + 10.0)


def test_mml_yield_function_needs_the_von_mises_isotropic_options():
    text = (
        "      SUBROUTINE FLOW_STRESS(STAT_VAR, EQPLAS, FLOW_SIG, DHDE)\n"
        "      STATEV(1)=EQPLAS\n      PEC0= PROPS(6)\n"
    )
    props = [0.0, 1.0, 5.0, 0, 2, 0.0, 197360, 0.33, 7284, 1040, 0.135, 0.436, 0.0]
    assert yield_function_for(_entry(source_text=text, props=props)) is not None
    hah = [5.0, 3.0] + props[2:]
    assert yield_function_for(_entry(source_text=text, props=hah)) is None
    with_pressure = props[:5] + [3e-5] + props[6:]
    assert yield_function_for(_entry(source_text=text, props=with_pressure)) is None


def test_a_one_increment_overshoot_of_a_saturating_back_stress_is_admissible():
    """MML_U3 Yoshida-Uemori (author deck TR1180_YU0_U3), cyclic increments
    47->48: ALPHA11 191.88 -> 187.23 while flowing in tension -- a discrete
    step overshot the saturation of the recovery term and relaxed back. The
    NET change over the plastic segment is with the flow, and that is judged."""
    path = _path("cyclic")
    entry = _entry(back_stress_slots=[2, 3, 4, 5, 6, 7], back_stress_evidence="test")
    rows = one_d(path, c_kin=20000.0)
    k = next(
        i
        for i in range(12, len(rows))
        if rows[i]["statev"][0] > rows[i - 1]["statev"][0]
        and rows[i + 1]["statev"][0] > rows[i]["statev"][0]
    )
    rows[k + 1]["statev"][1] = rows[k]["statev"][1] + 0.02 * abs(
        rows[k]["statev"][1]
    ) * (1 if rows[k]["statev"][1] < rows[k - 1]["statev"][1] else -1)
    assert check_back_stress_sign(entry, path, rows).passed is True


def test_the_official_example_needs_its_yield_stress_in_the_returned_stress():
    # the radial return onto a variable that is NOT the PROPS(3) yield stress
    other = JASON.replace("DIRN(I)*SIG0", "DIRN(I)*SEFF")
    assert yield_function_for(_entry(source_text=other)) is None
    # no PROPS(4) hardening modulus
    no_modulus = JASON.replace("PROPS(4)", "PROPS(5)")
    assert yield_function_for(_entry(source_text=no_modulus)) is None
    # the plastic strain stored somewhere else
    moved = JASON.replace("STATEV(1+2*NTENS)", "STATEV(1)")
    assert yield_function_for(_entry(source_text=moved)) is None


#: Synthetic, standing for the Lemaitre power-hardening law: the flow stress
#: Sy * (1e-4 + p) ** n of the plastic strain stored after two NTENS blocks.
LEMAITRE_HARDENING = """\
      SFLOW=SYLD*(0.0001+PEEQ)**XEXP
      STATEV(1+2*NTENS)=PEEQ
"""


def test_the_power_hardening_law_is_identified_on_its_stored_strain():
    yf = yield_function_for(_entry(source_text=LEMAITRE_HARDENING))
    assert yf is not None and yf.plastic_slot(6) == 13
    assert "power hardening" in yf.description
    # the hardening argument is not the strain the routine stores
    other = LEMAITRE_HARDENING.replace("(0.0001+PEEQ)", "(0.0001+PTRIAL)")
    assert yield_function_for(_entry(source_text=other)) is None


_CACHE = WORKSPACE / "discovery_cache"


def _cached(relative: str, sha256: str) -> str:
    path = _CACHE / relative
    if not path.is_file():
        pytest.skip(f"acquisition cache not present: {relative}")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha256, f"cache changed: {relative}"
    return data.decode("utf-8", "replace")


@pytest.mark.parametrize(
    "relative, sha256, description",
    [
        (
            (
                "jasonanewcoder__abaqus_skills/abaqus_subroutine_skills/"
                "official_examples/umat/umat_mises_plasticity_official.f"
            ),
            "465001b5ec044aba04119d8013406f3f367c38d404d9b0026e8f5fc55155e24a",
            "von Mises, linear isotropic hardening (as the header documents)",
        ),
        (
            (
                "awhelanUCD__Lemaitre-damage-UMAT-Public/nonLocalLemaitre/"
                "lemaitreDamageNonLocal.f"
            ),
            "f841c77b3c7687f1ff8696a4758f9198aeb85dbd06c97d409c400baaa4f87a38",
            "von Mises of undegraded stress, power hardening Sy(1e-4+p)^n",
        ),
    ],
)
def test_the_full_corpus_files_are_identified(relative, sha256, description):
    yf = yield_function_for(_entry(source_text=_cached(relative, sha256)))
    assert yf is not None and yf.description == description
    assert yf.plastic_slot(6) == 13


def test_the_full_lemaitre_file_needs_four_components():
    text = _cached(
        "awhelanUCD__Lemaitre-damage-UMAT-Public/nonLocalLemaitre/"
        "lemaitreDamageNonLocal.f",
        "f841c77b3c7687f1ff8696a4758f9198aeb85dbd06c97d409c400baaa4f87a38",
    )
    entry = _entry(family="damage / phase field", ntens=3, source_text=text)
    assert "at least NTENS=4" in layout_unsupported(
        entry, _path("elastic_uniaxial", ntens=3)
    )
