"""Records written under the pre-publication vocabulary are still readable.

The reviewer-designed experiments used to be written as ``council_*`` and a
hold-out selection used to name its reviewer; the code now writes
``reviewer_*`` and ``review_accepted``. :mod:`umat_oti.corpus_features.legacy_names`
renames an old record on read, and finds an old plan file on disk.
"""
from __future__ import annotations

import json

import pytest

from umat_oti.corpus_features.legacy_names import existing_path, upgrade, upgrade_text

pytestmark = pytest.mark.unit


def test_keys_and_values_are_renamed_recursively():
    old = {"experiment_origin": "council_deck", "council_deck_ref": "x/council_plan.json",
           "sets": [{"origin": "council_chosen"}], "vera_accepted": True,
           "selected_by": "Vera", "verdict": "held_for_vera_review", "n": 3}
    new = upgrade(old)
    assert new == {"experiment_origin": "reviewer_deck", "reviewer_deck_ref": "x/reviewer_plan.json",
                   "sets": [{"origin": "reviewer_chosen"}], "review_accepted": True,
                   "selected_by": "reviewer", "verdict": "held_for_review", "n": 3}


def test_a_current_record_is_unchanged():
    current = {"experiment_origin": "reviewer_deck", "review_accepted": False,
               "selected_by": "reviewer", "values": [1.0, None, "text"]}
    assert upgrade(current) == current
    assert upgrade_text("REVIEWER_PLANS") == "REVIEWER_PLANS"


def test_an_old_plan_file_is_found_under_its_old_name(tmp_path):
    old = tmp_path / "council_plans" / "k1" / "council_plan.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"council_fingerprint": "abc"}))
    wanted = tmp_path / "reviewer_plans" / "k1" / "reviewer_plan.json"
    assert existing_path(wanted) == old
    assert upgrade(json.loads(existing_path(wanted).read_text())) == {"reviewer_fingerprint": "abc"}


def test_the_new_name_wins_and_a_missing_path_keeps_its_new_name(tmp_path):
    new = tmp_path / "reviewer_plans" / "k2" / "reviewer_plan.json"
    assert existing_path(new) == new
    new.parent.mkdir(parents=True)
    new.write_text("{}")
    (tmp_path / "council_plans" / "k2").mkdir(parents=True)
    (tmp_path / "council_plans" / "k2" / "council_plan.json").write_text("{}")
    assert existing_path(new) == new
