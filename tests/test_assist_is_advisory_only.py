"""A model may propose. It may never decide, and it may never supply a number.

Everything else in this repository rests on being able to say where a number
came from. These pin the boundary that keeps that true: a proposal is inert
until deterministic code agrees with it, the verdict does not depend on a model
being reachable, and no value in the evidence originates from one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.assist.deck_pairing import check_pairing, pair_source_with_deck
from umat_oti.assist.local_model import (
    LocalModel, ModelUnavailable, model_from_environment,
)
from umat_oti.assist.proposals import Proposal, ProposalNotConfirmed, Verdict


def _repo(tmp_path: Path, *, constants: int, depvar: int) -> tuple[Path, Path]:
    source = tmp_path / "umat.for"
    source.write_text("      SUBROUTINE UMAT(STRESS,STATEV,PROPS)\n      END\n",
                      encoding="utf-8")
    deck = tmp_path / "job.inp"
    values = ", ".join(str(float(i + 1)) for i in range(constants))
    deck.write_text(
        f"*Material, name=M\n*User Material, constants={constants}\n"
        f"{values}\n*Depvar\n{depvar}\n", encoding="utf-8")
    return source, deck


def test_an_unchecked_proposal_cannot_be_used():
    proposal = Proposal(subject="deck", proposed="job.inp", model="m")
    assert proposal.verdict is Verdict.UNVERIFIED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_a_contradicted_proposal_cannot_be_used():
    proposal = Proposal(subject="deck", proposed="job.inp", model="m")
    proposal.contradict(checked_by="parser", evidence="supplies 3, expects 4")
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_the_verdict_does_not_depend_on_a_model_being_reachable(tmp_path: Path):
    """The property that makes this safe to ship.

    A model changes which file is examined first and nothing else. Run the
    same pairing with a model, with a model that answers nonsense, and with no
    model at all, and the confirmed answer has to be the same file every time.
    """
    source, deck = _repo(tmp_path, constants=4, depvar=1)

    class Liar(LocalModel):
        def ask(self, prompt, *, temperature=0.0, max_tokens=256):
            return "definitely-not-a-real-deck.inp", "0" * 64

    class Dead(LocalModel):
        def ask(self, prompt, *, temperature=0.0, max_tokens=256):
            raise ModelUnavailable("no server")

    answers = []
    for model in (None, Liar(name="liar"), Dead(name="dead")):
        proposal = pair_source_with_deck(
            source, [deck], expected_nprops=4, expected_nstatv=1, model=model)
        assert proposal.verdict is Verdict.CONFIRMED
        answers.append(proposal.confirmed_value())
    assert len(set(answers)) == 1, (
        f"the confirmed deck changed with the model: {answers}")


def test_a_model_naming_the_wrong_deck_is_overruled(tmp_path: Path):
    """A wrong proposal must not become a wrong answer."""
    source, good = _repo(tmp_path, constants=4, depvar=1)
    bad = tmp_path / "wrong.inp"
    bad.write_text("*Material, name=W\n*User Material, constants=2\n1.0, 2.0\n",
                   encoding="utf-8")

    class NamesTheWrongOne(LocalModel):
        def ask(self, prompt, *, temperature=0.0, max_tokens=256):
            return str(bad), "0" * 64

    proposal = pair_source_with_deck(
        source, [bad, good], expected_nprops=4, expected_nstatv=1,
        model=NamesTheWrongOne(name="wrong"))
    assert proposal.verdict is Verdict.CONFIRMED
    assert proposal.confirmed_value() == str(good)
    assert proposal.metadata["model_was_right"] is False, (
        "the record has to say the model was overruled, not hide it")


def test_no_deck_fitting_means_contradicted_not_a_guess(tmp_path: Path):
    source, deck = _repo(tmp_path, constants=2, depvar=1)
    proposal = pair_source_with_deck(
        source, [deck], expected_nprops=9, expected_nstatv=1, model=None)
    assert proposal.verdict is Verdict.CONTRADICTED
    with pytest.raises(ProposalNotConfirmed):
        proposal.confirmed_value()


def test_the_check_is_arithmetic_on_counts_both_sides_declare(tmp_path: Path):
    source, deck = _repo(tmp_path, constants=4, depvar=10)
    ok, detail = check_pairing(source, deck, expected_nprops=4, expected_nstatv=10)
    assert ok and "supplies 4 constants" in detail
    ok, detail = check_pairing(source, deck, expected_nprops=5, expected_nstatv=10)
    assert not ok and "reads PROPS up to 5" in detail

    # State variables are resolved, not refused. The harness allocates the
    # larger of the deck's *Depvar and the source's own count -- see
    # build_validation_workspace, which has done that since the out-of-bounds
    # write it guards against -- so a short *Depvar costs nothing, while
    # refusing on it threw away six constants UEL8_PCLK's author had
    # published and then recorded the refusal as a constants shortfall.
    # Constants remain the one arm that can refuse; that is pinned above and
    # in test_too_few_constants_is_still_refused.
    ok, detail = check_pairing(source, deck, expected_nprops=4, expected_nstatv=999)
    assert ok, "a short *Depvar must not discard constants that were published"
    assert "state variables resolve to 999" in detail, (
        "and the resolved count has to be visible in the evidence")
    ok, _ = check_pairing(source, deck, expected_nprops=4, expected_nstatv=999,
                          refuse_short_depvar=True)
    assert not ok, (
        "the stricter rule pair_source_with_deck runs first still refuses, "
        "which is what keeps a pairing that already worked from moving")


def test_a_deck_that_supplies_more_than_the_source_reads_is_capable(tmp_path: Path):
    """Capable of driving it, which is the property this check exists to test.

    Abaqus hands the UMAT the deck's whole constant list and sets NPROPS to its
    length; the subroutine reads the indices it needs and the rest go unread.
    Demanding exact equality rejected decks that drive the source perfectly
    well -- among them the one three crystal-plasticity UMATs ship in their own
    repository, declaring 168 constants where the source reads 160.
    """
    source, deck = _repo(tmp_path, constants=168, depvar=150)
    ok, detail = check_pairing(source, deck, expected_nprops=160, expected_nstatv=None)
    assert ok
    assert "supplies 168 constants" in detail
    assert "reads the first 160" in detail, "the surplus has to be visible"


def test_too_few_constants_is_still_refused(tmp_path: Path):
    """The loosening is one-sided. Short is short."""
    source, deck = _repo(tmp_path, constants=48, depvar=10)
    ok, _ = check_pairing(source, deck, expected_nprops=160, expected_nstatv=None)
    assert not ok


def test_an_exact_deck_wins_over_a_merely_sufficient_one(tmp_path: Path):
    """So loosening the rule can only add pairings, never move one.

    Both decks fit under "at least". If the larger one could win, a source
    already paired with its exact deck would silently change which material it
    is driven by -- and the provenance column would change with it.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    source, big = _repo(tmp_path / "a", constants=200, depvar=10)
    _, exact = _repo(tmp_path / "b", constants=6, depvar=10)
    proposal = pair_source_with_deck(
        source, [big, exact], expected_nprops=6, expected_nstatv=10, model=None)
    assert proposal.verdict is Verdict.CONFIRMED
    assert proposal.confirmed_value() == str(exact)


def test_a_proposal_records_that_it_supplied_no_number():
    proposal = Proposal(subject="deck", proposed="job.inp", model="m")
    proposal.confirm(checked_by="parser", evidence="counts agree")
    record = proposal.as_dict()
    assert "No value here was generated by it" in record["note"]
    assert record["checked_by"] == "parser"
    assert isinstance(record["proposed"], str), (
        "a proposal names an artefact; it never carries a numeric value")


def test_no_published_evidence_mentions_the_assist_package():
    """The load-bearing check: nothing in paper_results can trace to a model."""
    import subprocess

    results = Path(__file__).resolve().parents[1] / "paper_results"
    if not results.is_dir():
        pytest.skip("no published evidence in this tree")
    found = subprocess.run(
        ["grep", "-rl", "-e", "umat_oti.assist", "-e", "qwen2.5",
         "-e", "ollama", str(results)],
        capture_output=True, text=True)
    assert not found.stdout.strip(), (
        "published evidence references a model:\n" + found.stdout)


def test_the_package_is_optional():
    """Absence is an ordinary outcome, reported as None rather than raising."""
    unreachable = LocalModel(name="nothing", host="http://127.0.0.1:1")
    assert unreachable.available() is False
    with pytest.raises(ModelUnavailable):
        unreachable.tags()
    # And the environment helper never raises, whatever is or is not running.
    assert model_from_environment() is None or model_from_environment().name
