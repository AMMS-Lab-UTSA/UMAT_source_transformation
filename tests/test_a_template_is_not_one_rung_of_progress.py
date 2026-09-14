"""A published template did not climb a rung. It is off the ladder.

``STATUSES`` in the corpus report is documented as the states an entry can be
in "in the order they are reached", where "the one it is in is the furthest it
got". Every name in it is a rung.

``published_stub_no_constitutive_content`` was first mapped to
``metadata_resolved`` -- the first rung above acquired -- on the reasoning that
there is no model to transform so the metadata is as far as it goes. That is
wrong for the same reason every other borrowed name was wrong: a template is
not one step's progress toward verifying a model that does not exist. Agent 6
declined to guess it and escalated instead, which is why it is right now.

The three alternatives and why each fails:

    BLOCKED             what the map's own guard exists to prevent
    NOT_A_UMAT          false about it -- a stub DOES present the 37-argument
                        interface, which is the whole of what it is
    metadata_resolved   a rung, and this is not progress toward one
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from corpus_report import (BLOCKED, FROM_ABAQUS_STAGE, NOT_A_UMAT,  # noqa: E402
                           OFF_THE_LADDER, PUBLISHED_STUB, STATUSES)

STAGE = "published_stub_no_constitutive_content"


def test_a_template_is_not_on_the_ladder():
    assert PUBLISHED_STUB not in STATUSES
    assert PUBLISHED_STUB in OFF_THE_LADDER


def test_it_did_not_borrow_a_rung():
    assert FROM_ABAQUS_STAGE[STAGE] == PUBLISHED_STUB
    assert FROM_ABAQUS_STAGE[STAGE] not in STATUSES


def test_it_is_not_blocked_and_it_is_not_something_other_than_a_umat():
    """Both were available and both say something false."""
    assert FROM_ABAQUS_STAGE[STAGE] != BLOCKED
    assert FROM_ABAQUS_STAGE[STAGE] != NOT_A_UMAT


def test_the_off_ladder_statuses_are_named_once():
    """They were written out by hand in three places -- the guard, the counts
    and the tables -- so adding a fourth could be half-done and the new status
    would be counted in one table and dropped from another."""
    source = (Path(__file__).resolve().parents[1]
              / "tools" / "corpus_report.py").read_text()
    assert "(NOT_A_UMAT, BLOCKED)" not in source
    assert source.count("OFF_THE_LADDER") >= 4


def test_every_off_ladder_status_is_distinct_from_every_rung():
    assert not set(OFF_THE_LADDER) & set(STATUSES)
    assert len(set(OFF_THE_LADDER)) == len(OFF_THE_LADDER)


def test_the_state_keeps_its_owner_in_the_other_vocabulary():
    """Off the ladder here, EXTERNAL there: the report says how far it got and
    terminal_states says whose work is missing. Neither answers the other's
    question, and the two must not drift."""
    from umat_oti.abaqus import terminal_states as ts

    assert ts.from_stage(STAGE).kind == "external"
    assert ts.from_stage(STAGE).finished is True
    assert "assigns no stress" in ts.meaning_of(STAGE)
