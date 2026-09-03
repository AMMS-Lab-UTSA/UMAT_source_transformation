"""What must not reach "verified", and what must not be blamed on a model.

Adversarial review of the Abaqus batch verifier found four ways up the ladder
that should not exist. Each is a rule this project works under, broken:

* material data invented -- a deck's published initial state ignored, so a
  growth model whose author declared an initial stretch of 1.0 ran from zeros
  and could still be called verified
* material data invented -- an anisotropic material run in a frame nobody
  published, because the deck's *ORIENTATION was read and then dropped
* a machine-state failure recorded as a finding about a UMAT, and then frozen
  by --resume so it was republished forever
* a deck selected by basename, in the function written to stop exactly that
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from verify_store_in_abaqus import (                       # noqa: E402
    HARNESS_ERROR, initial_solution_state, is_terminal,
    looks_like_a_harness_failure, paired_block_name)


# ---- a deck's own initial state ----------------------------------------
DECK_WITH_STATE = """\
*HEADING
a deck whose author published where the material starts
*MATERIAL, NAME=GROWTH
*DEPVAR
9,
*USER MATERIAL, CONSTANTS=2
1.0, 0.3
*INITIAL CONDITIONS, TYPE=SOLUTION
ALL, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0
ALL, 1.0
*STEP, NLGEOM=YES
*STATIC
*END STEP
"""


def test_a_declared_initial_state_is_read():
    """Running a growth model from zeros is a different model.

    Thirteen of the paired decks in this corpus declare TYPE=SOLUTION state.
    """
    values = initial_solution_state(DECK_WITH_STATE)
    assert values == (1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)


def test_a_deck_that_declares_none_yields_none():
    """Zeros are then the deck's own statement, which is not a problem."""
    assert initial_solution_state(
        "*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS=1\n1.0\n") == ()


def test_the_element_set_name_is_not_read_as_a_number():
    values = initial_solution_state(DECK_WITH_STATE)
    assert all(isinstance(v, float) for v in values)
    assert len(values) == 9          # not 11: "ALL" twice is not data


def test_a_commented_initial_condition_is_not_read():
    """`**` is a comment in an Abaqus deck."""
    assert initial_solution_state(
        "**INITIAL CONDITIONS, TYPE=SOLUTION\n1.0, 2.0\n") == ()


def test_the_block_ends_at_the_next_keyword():
    values = initial_solution_state(
        "*INITIAL CONDITIONS, TYPE=SOLUTION\nALL, 5.0\n*STEP\n1.0, 2.0\n")
    assert values == (5.0,)


def test_a_different_type_of_initial_condition_is_not_solution_state():
    """TYPE=TEMPERATURE is not state variables."""
    assert initial_solution_state(
        "*INITIAL CONDITIONS, TYPE=TEMPERATURE\nALL, 293.0\n") == ()


# ---- a harness failure is not a finding about a model -------------------
def test_a_timeout_is_a_harness_failure_not_a_model_failure():
    """The licence server here is shared and multi-minute waits are measured.

    Recording a timeout as original_job_failed attributes a licence problem to
    somebody's UMAT, and every rung of the ladder is settled, so --resume then
    republished that verdict for as long as the results file lived.
    """
    reason = looks_like_a_harness_failure(
        {"completed": False, "console": "TIMEOUT", "converged_records": 0})
    assert reason and "retries" in reason


def test_a_missing_abaqus_is_a_harness_failure():
    assert looks_like_a_harness_failure(
        {"completed": False, "converged_records": 0,
         "console": "FileNotFoundError: abaqus"})


def test_a_licence_wait_is_a_harness_failure():
    assert looks_like_a_harness_failure(
        {"completed": False, "converged_records": 0,
         "console": "No licenses available for feature"})


def test_a_real_solver_error_is_not_excused_as_a_harness_failure():
    """A model that ran and failed is a finding, and must stay one."""
    assert not looks_like_a_harness_failure(
        {"completed": False, "converged_records": 0,
         "console": "***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT"})


def test_a_run_that_produced_records_is_never_a_harness_failure():
    """It reached the material and computed something; that is the model."""
    assert not looks_like_a_harness_failure(
        {"completed": False, "converged_records": 3, "console": "TIMEOUT"})


def test_a_completed_run_is_never_a_harness_failure():
    assert not looks_like_a_harness_failure(
        {"completed": True, "console": "TIMEOUT"})


def test_a_harness_error_is_retried_on_a_resumed_batch():
    """This is the whole point: a machine artifact must not be permanent."""
    assert not is_terminal(HARNESS_ERROR)


def test_every_rung_of_the_ladder_is_settled():
    from verify_store_in_abaqus import STAGES

    assert all(is_terminal(stage) for stage in STAGES)


# ---- a deck is identified by its path ----------------------------------
def test_a_provenance_about_another_repositorys_deck_does_not_select_here():
    """job.inp and input.inp are the commonest deck names in this cache.

    A basename test let a provenance about another repository's job.inp choose
    which *MATERIAL block feeds this one -- identity by basename, inside the
    function written to prevent it. The old guard used a *different* basename,
    so it passed with the bug present.
    """
    assert paired_block_name(
        "other__repo/inputs/job.inp *Material name=TITANIUM",
        "owner__name/decks/job.inp") is None


def test_a_provenance_about_this_deck_selects_its_block():
    assert paired_block_name(
        "owner__name/decks/job.inp *Material name=STEEL supplies 4 constants",
        "owner__name/decks/job.inp") == "STEEL"


def test_no_provenance_selects_nothing():
    assert paired_block_name("", "owner__name/decks/job.inp") is None
    assert paired_block_name("something", "") is None
