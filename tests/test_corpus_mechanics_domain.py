"""Loading paths stay inside the domain the author documented (D-12 item 1).

``Jeff97 .../BodyForce-Growth-2Stages.for`` (the 2.2 variant) defines its
growth stretch G11 by an IF / ELSE IF chain on total time with no ELSE. After
TIME(2)+DTIME = 2.2 G11 is an uninitialised local: built with zero-initialised
locals the routine returns G11 = 0 and NaN stress, with SNaN-initialised
locals NaN -- measured in corpus_campaign/batches/B2b/curie/bodyforce/. The
B1 ``growth_held_stretch`` path ended at 1.1 x the period (2.42) and so
asked the original an undefined question.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest
from _workspace import WORKSPACE  # noqa: E402

from umat_oti.corpus_features.loading_paths import (
    OUTSIDE_MODEL_DOMAIN,
    _within_domain,
    model_domain,
    paths_for,
    piecewise_chains,
)
from umat_oti.corpus_features.mechanics_checks import run_checks

pytestmark = pytest.mark.unit

#: Synthetic, standing for Jeff97 .../BodyForce-Growth-2Stages.for (2.2
#: variant): the standard UMAT interface, then a two-stage growth stretch G11
#: defined by an IF / ELSE IF chain on TIME(2)+DTIME up to 2.2 with no ELSE
#: (lines 11-16, the second branch continued over two lines), and G11 stored.
#: No corpus text is copied; ``test_the_full_corpus_file`` reads the real file.
BODYFORCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
        STAGE1=1.0

        GA = 1.0 + 0.2*PROPS(1)
        GB = 1.0 + 0.5*PROPS(1)

        IF ((TIME(2)+DTIME) .LE. 1.0) THEN
          G11 = 1.0 + (GA-1.0)*(TIME(2)+DTIME)/STAGE1
        ELSE IF ((TIME(2)+DTIME) .LE. 2.2) THEN
          G11 = GA
     &        + (GB-GA)*((TIME(2)+DTIME)-STAGE1)/1.2
        END IF
C       growth stretch, held in state
        G22 = 1.0
        STATEV(1) = G11
      RETURN
      END
"""


def _entry(**kw):
    base = {
        "source_id": "Jeff97__.../BodyForce-Growth-2Stages.for",
        "family": "growth / morphoelasticity",
        "ntens": 6,
        "kinematics": "finite",
        "props": [1.0e6],
        "total_time": 2.2,
        "deck_periods": [1.0, 1.2],
        "activation_amplitude": 0.01,
        "source_text": BODYFORCE,
    }
    base.update(kw)
    return base


def test_the_g11_chain_is_read_with_its_range():
    (chain,) = piecewise_chains(BODYFORCE)
    assert chain.defines == ("G11",)
    assert chain.on_time and chain.upper == pytest.approx(2.2)
    assert chain.initialised_before == ()
    assert (chain.first_line, chain.last_line) == (11, 16)


def test_the_domain_has_both_witnesses_and_the_tighter_wins():
    dom = model_domain(_entry(deck_periods=[1.0, 1.2, 1.0]))
    assert dom["time_max"] == pytest.approx(2.2)
    assert "source UMAT lines 11-16" in dom["time_provenance"]
    assert any("author's deck" in w for w in dom["witnesses"])


def test_every_path_ends_inside_the_domain_and_says_so():
    paths = paths_for(_entry())
    assert paths
    for path in paths:
        end = sum(inc.dtime for inc in path.increments)
        assert end <= 2.2 * (1 + 1e-9), (path.name, end)
        assert path.purpose != OUTSIDE_MODEL_DOMAIN
        assert "total time <= 2.2" in path.provenance["model_domain"]
    held = {p.name: p for p in paths}["growth_held_stretch"]
    assert sum(i.dtime for i in held.increments) == pytest.approx(2.2)


def test_a_clock_longer_than_the_domain_is_shortened_and_recorded():
    paths = {p.name: p for p in paths_for(_entry(total_time=3.0))}
    held = paths["growth_held_stretch"]
    assert sum(i.dtime for i in held.increments) == pytest.approx(2.2)
    assert "shortened from 3 to 2.2" in held.provenance["period"]


def test_a_path_that_cannot_fit_is_labelled_with_its_twin_and_gets_no_verdict():
    paths = {
        p.name: p
        for p in paths_for(_entry(family="plasticity", kinematics="small strain"))
    }
    pair = [paths["isotropy_reference"], paths["isotropy_rotated"]]
    domain = {
        "time_max": 1.0,
        "time_provenance": "test",
        "witnesses": [],
        "unbounded_branches": [],
    }
    out = {p.name: p for p in _within_domain(pair, domain)}
    assert {p.purpose for p in out.values()} == {OUTSIDE_MODEL_DOMAIN}
    ref = out["isotropy_reference"]
    assert ref.provenance["intended_purpose"] == "isotropy_reference"
    assert "> 1 documented" in ref.provenance["outside_model_domain"]
    rows = [
        {
            "stress": np.full(6, np.nan),
            "statev": [0.0],
            "ddsdde": np.eye(6),
            "sse": 0.0,
            "spd": 0.0,
            "scd": 0.0,
        }
        for _ in ref.increments
    ]
    results = run_checks(_entry(family="plasticity"), ref, rows)
    assert all(r.passed is None for r in results)
    assert all(OUTSIDE_MODEL_DOMAIN in r.detail for r in results)


def test_no_documented_range_means_no_bound():
    dom = model_domain(
        _entry(deck_periods=[], source_text="      SUBROUTINE UMAT(A)\n      END\n")
    )
    assert dom["time_max"] is None
    assert "no documented time range" in dom["time_provenance"]


#: Synthetic, standing for MCM-QMUL__PhaseFieldComp/Subroutine/
#: UELUMATPhaseField_AT2.for: a first-call initialisation inside UMAT, a
#: one-branch IF on TIME(1)-DTIME < 0 holding an IF / ELSE on a flag.
MCM_INIT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,TIME,DTIME,NOEL)
      IF ((TIME(1)-DTIME) .LT. 0.D0) THEN
        IF (INITED .NE. 7) THEN
          NCALLS=0
          NFIRST=1
          NMAX=NOEL
          WORK=0.D0
          INITED=7
        ELSE
          CALL LOCKIT(1)
          IF (NOEL .GT. NMAX) NMAX=NOEL
          CALL UNLOCKIT(1)
        END IF
      END IF
      END
"""


def test_a_first_call_initialisation_is_not_a_domain():
    dom = model_domain(_entry(deck_periods=[], source_text=MCM_INIT))
    assert dom["time_max"] is None


def test_assigning_a_dummy_argument_on_a_range_is_not_undefined():
    text = (
        "      SUBROUTINE UMAT(STATEV,TIME)\n"
        "      IF (TIME(2) .LE. 1.0) THEN\n        STATEV(1) = 1.0\n"
        "      ELSE IF (TIME(2) .LE. 2.0) THEN\n        STATEV(1) = 2.0\n"
        "      END IF\n      END\n"
    )
    assert piecewise_chains(text) == []


_CACHE = (WORKSPACE / "discovery_cache")
_SOURCE = (
    "Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/"
    "Examples-In-Section-3/ArcDown/Th001/BodyForce-Growth-2Stages.for"
)
_SHA256 = "866a451e1520fe7bf0242a992f1333e755c06c54bb021efaaf6b1861d6f49627"


def test_the_full_corpus_file():
    path = _CACHE / _SOURCE
    if not path.is_file():
        pytest.skip("acquisition cache not present")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == _SHA256, "cache changed"
    text = data.decode("utf-8", "replace")
    (chain,) = [c for c in piecewise_chains(text) if c.on_time]
    assert chain.defines == ("G11",) and chain.upper == pytest.approx(2.2)
    assert (chain.first_line, chain.last_line) == (219, 224)
    for path in paths_for(_entry(source_text=text)):
        assert sum(i.dtime for i in path.increments) <= 2.2 * (1 + 1e-9)


def test_the_full_first_call_initialisation():
    path = _CACHE / "MCM-QMUL__PhaseFieldComp/Subroutine/UELUMATPhaseField_AT2.for"
    if not path.is_file():
        pytest.skip("acquisition cache not present")
    data = path.read_bytes()
    assert (
        hashlib.sha256(data).hexdigest()
        == "dc42b776c4c9d32ca5ea9b782dc04bcbf59a65f2837f6dac0906abdba368230b"
    ), "cache changed"
    text = data.decode("utf-8", "replace")
    dom = model_domain(_entry(deck_periods=[], source_text=text))
    assert dom["time_max"] is None
