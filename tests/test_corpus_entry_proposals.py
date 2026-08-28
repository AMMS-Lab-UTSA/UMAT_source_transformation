"""Proposing a corpus entry must never become inventing one.

A material vector is the thing this project refuses to guess at. Reading one
out of the deck its author shipped is legitimate and is what makes an
externally authored source verifiable at all; producing one any other way is
the failure these guard against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from propose_corpus_entries import _default_probe, propose  # noqa: E402


def _repo(tmp_path: Path, *, source_props: int, deck_props: int,
          deck_depvar: int) -> Path:
    cache = tmp_path / "cache"
    repo = cache / "owner__project"
    repo.mkdir(parents=True)
    reads = "\n".join(f"      X{i} = PROPS({i})" for i in range(1, source_props + 1))
    (repo / "umat.for").write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS)\n"
        "      DIMENSION STRESS(6),STATEV(3),PROPS(NPROPS)\n"
        f"{reads}\n"
        "      STATEV(3) = X1\n"
        "      STRESS(1) = X1\n"
        "      END\n", encoding="utf-8")
    values = ", ".join(str(float(i + 1)) for i in range(deck_props))
    (repo / "job.inp").write_text(
        f"*Material, name=MAT\n*User Material, constants={deck_props}\n"
        f"{values}\n*Depvar\n{deck_depvar}\n", encoding="utf-8")
    return cache


def test_a_source_with_no_deck_gets_no_material(tmp_path: Path):
    cache = _repo(tmp_path, source_props=4, deck_props=4, deck_depvar=3)
    (cache / "owner__project" / "job.inp").unlink()
    entry = propose(cache / "owner__project" / "umat.for", cache, None)
    assert entry["status"] == "no_deck"
    assert "material" not in entry
    assert "may be invented" in entry["reason"]


def test_a_deck_with_too_few_constants_is_refused(tmp_path: Path):
    cache = _repo(tmp_path, source_props=9, deck_props=4, deck_depvar=3)
    entry = propose(cache / "owner__project" / "umat.for", cache, None)
    assert entry["status"] == "no_matching_deck"
    assert "material" not in entry, (
        "a source indexing PROPS(9) must not be given a four-constant vector")


def test_a_matching_deck_supplies_the_vector_with_provenance(tmp_path: Path):
    cache = _repo(tmp_path, source_props=4, deck_props=4, deck_depvar=3)
    entry = propose(cache / "owner__project" / "umat.for", cache, None)
    assert entry["status"] == "proposed_needs_review"
    material = entry["material"]
    assert material["props"] == [1.0, 2.0, 3.0, 4.0]
    assert "job.inp" in material["provenance"]
    assert "*Material" in material["provenance"]
    assert not material["provenance"].startswith("/"), (
        "provenance records the deck relative to the cache root")


def test_the_meaning_of_the_constants_is_never_asserted(tmp_path: Path):
    cache = _repo(tmp_path, source_props=4, deck_props=4, deck_depvar=3)
    entry = propose(cache / "owner__project" / "umat.for", cache, None)
    assert "not established" in entry["material"]["meaning"], (
        "a deck gives values, not names; claiming to know what they mean "
        "would be inventing the part that matters")


def test_the_loading_path_is_offered_as_a_suggestion_only(tmp_path: Path):
    cache = _repo(tmp_path, source_props=4, deck_props=4, deck_depvar=3)
    entry = propose(cache / "owner__project" / "umat.for", cache, None)
    probe = entry["loading_path"]
    assert probe["accepted_by_reviewer"] is False
    assert "suggested only" in probe["provenance"]
    assert "not this source's own loading history" in probe["provenance"]


def test_the_default_probe_names_where_it_came_from():
    probe = _default_probe()
    if not probe:
        pytest.skip("loading_paths.json is absent")
    assert "loading_paths.json" in probe["provenance"]
    assert probe["accepted_by_reviewer"] is False


def test_no_entry_is_ever_marked_verified(tmp_path: Path):
    cache = _repo(tmp_path, source_props=4, deck_props=4, deck_depvar=3)
    entry = propose(cache / "owner__project" / "umat.for", cache, None)
    blob = json.dumps(entry).lower()
    assert "verified" not in blob.replace("needs_review", ""), (
        "proposing an entry says nothing about whether its derivatives are right")
    assert entry["status"].startswith("proposed")
