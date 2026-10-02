"""The author's SDVINI is honoured when the paired deck states no starting state."""
import sys
from pathlib import Path

import pytest

from umat_oti.abaqus.deck import generate_deck
from umat_oti.abaqus.manifest import VerificationManifest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import verify_store_in_abaqus as V  # noqa: E402

WITH = "      SUBROUTINE SDVINI(STATEV,COORDS,NSTATV,NCRDS,NOEL,NPT,LAYER,KSPT)\n      END\n"


def manifest(**kw):
    base = dict(name="M", source=Path("x.for"), element_type="C3D8", kinematics="small",
                ntens=6, ndi=3, nshr=3, nprops=1, props=(1.0,), nstatv=2)
    base.update(kw)
    return VerificationManifest(**base)


def test_a_source_with_sdvini_and_a_silent_deck_asks_for_user(tmp_path):
    (tmp_path / "s.for").write_text(WITH)
    m = V.honour_author_sdvini(manifest(), tmp_path / "s.for")
    assert m.initial_state_from_user_subroutine
    assert "SDVINI" in m.initial_statev_provenance
    assert "*INITIAL CONDITIONS, TYPE=SOLUTION, USER" in generate_deck(m)


def test_a_deck_that_states_values_is_left_alone(tmp_path):
    (tmp_path / "s.for").write_text(WITH)
    m = V.honour_author_sdvini(manifest(initial_statev=(1.0, 2.0),
                                        initial_statev_provenance="deck"),
                               tmp_path / "s.for")
    assert not m.initial_state_from_user_subroutine
    assert m.initial_statev == (1.0, 2.0)


def test_a_source_without_sdvini_is_left_alone(tmp_path):
    (tmp_path / "s.for").write_text("      SUBROUTINE UMAT\n      END\n")
    assert not V.honour_author_sdvini(manifest(), tmp_path / "s.for").initial_state_from_user_subroutine


CACHE = Path("/home/ammslab3/softwarex_work/discovery_cache")
CURING = "Worlthen__20220314-abqus-simulation/abaqus/simplified/simplified_curing.for"


@pytest.mark.skipif(not (CACHE / CURING).is_file(), reason="needs the discovery cache")
def test_worlthen_curing_now_starts_from_the_authors_sdvini_state():
    rows = V.triage_rows(REPO / "paper_results/discovery/discovery_triage.csv")
    proposals = V.proposal_entries(REPO / "paper_results/discovery/proposed_corpus_entries.json")
    plan = V.build_manifest(CURING, rows.get(CURING), proposals.get(CURING), CACHE)
    assert plan.manifest.initial_state_from_user_subroutine
    assert "*INITIAL CONDITIONS, TYPE=SOLUTION, USER" in generate_deck(plan.manifest)
