"""Promotion freezes the experiment a regression replays, so it has the same
bar a fixture does.

``umat/<material>/contract.json`` is not a report. It is the manifest a later
run is driven by and the states that run's tangent is measured at, and a
regression compares against it. A contract frozen from a history that stopped
being numbers part way through makes every later run a comparison against
that, and the run that should have caught it is the one being compared.

So the refusal is the same one ``export_residual_fixture.py`` applies, imported
rather than reimplemented -- two copies of a rule are two rules, and they drift.

The second thing here: a promoted contract has to carry the same evidence the
page shows. A reader of ``umat/`` and a reader of the corpus tab are looking at
the same run, and if the two show different things one of them is a second
opinion nobody can cite.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from promote_verified_umats import (PromotionRefused,  # noqa: E402
                                    contract_from, promote,
                                    why_this_may_not_be_promoted)
from umat_oti.app.corpus_view import EVIDENCE_GATES  # noqa: E402

CORPUS = REPO / "tests" / "fixtures" / "corpus"
WORK = CORPUS / "work"


@pytest.fixture(scope="module")
def control():
    return json.loads(
        (CORPUS / "results" / "store_verification.jsonl").read_text().strip())


def test_the_bundled_control_may_be_promoted(control):
    assert why_this_may_not_be_promoted(control, WORK) == []


def test_a_contract_carries_the_gates_the_page_shows(control):
    """One run, one account of it. The contract names every gate the corpus
    page names, so a reader of ``umat/`` is not shown a shorter story."""
    frozen = contract_from(control)["finite_verification_run"]
    assert set(frozen["evidence"]) == {
        name for name, _, _ in EVIDENCE_GATES} - {"mechanically_informative"}, (
        "the control predates the informativeness gate; every gate the run "
        "did measure is carried")
    assert frozen["complete_finite_verification_run"] is True
    assert set(frozen["history_grouping"]) == {"original", "transformed"}
    for name in ("discovery_usable_prefix", "safe_loading_reconstructed",
                 "failure_mechanism", "segment_repair", "coverage_given_up",
                 "time_scale_coverage", "mechanically_informative"):
        assert name in frozen, name


def test_what_the_experiment_gave_up_travels_with_the_contract():
    """A regression replaying a repaired experiment is replaying the repair.
    The contract says which segment went and why, so a later reader is not
    told the reversal is being tested when it was dropped."""
    contract = contract_from({
        "stage": "verified", "source": "s.for",
        "discovery": {
            "complete_finite_verification_run": True,
            "coverage_given_up": "'uniaxial_reversed' was dropped: the model "
                                 "left its domain inside it",
            "segment_repair": "'uniaxial_reversed' was cut from 10 increments "
                              "to 1",
            "failure_mechanism": {"kind": "path_segment_limited"},
            "safe_loading_reconstructed": {"amplitude": 0.008,
                                           "fraction": 0.8}}})
    frozen = contract["finite_verification_run"]
    assert "dropped" in frozen["coverage_given_up"]
    assert frozen["failure_mechanism"]["kind"] == "path_segment_limited"
    assert frozen["safe_loading_reconstructed"]["fraction"] == 0.8


def test_a_run_that_was_not_finite_is_refused_promotion(control, tmp_path: Path):
    row = dict(control, complete_finite_verification_run=False)
    row["discovery"] = dict(row["discovery"],
                            complete_finite_verification_run=False)
    with pytest.raises(PromotionRefused) as raised:
        promote(row, tmp_path / "umat", WORK, tmp_path / "cache")
    assert "complete_finite_verification_run" in str(raised.value)
    assert not (tmp_path / "umat").exists(), (
        "a refused promotion writes nothing, so a half-written contract "
        "cannot be replayed later as though it were whole")


def test_a_history_that_stops_being_numbers_is_refused_promotion(
        control, tmp_path: Path):
    grouping = json.loads(json.dumps(control["history_grouping"]))
    grouping["transformed"]["first_non_finite_material_point"] = {
        "element": 1, "point": 5, "increment": 12}
    with pytest.raises(PromotionRefused) as raised:
        promote(dict(control, history_grouping=grouping), tmp_path / "umat",
                WORK, tmp_path / "cache")
    assert "element 1 point 5 of increment 12" in str(raised.value)


def test_a_nan_in_the_probe_history_is_refused_even_when_the_record_is_clean(
        control, tmp_path: Path):
    """The reading that cannot be talked out of: the numbers a regression will
    actually be compared against."""
    key = control["key"]
    for job in ("original", "transformed"):
        history = json.loads(
            (WORK / key / job / f"{job}_history.json").read_text())
        folder = tmp_path / "work" / key / job
        folder.mkdir(parents=True)
        if job == "original":
            history[2]["STRESS"][1] = float("nan")
        (folder / f"{job}_history.json").write_text(json.dumps(history))
    with pytest.raises(PromotionRefused) as raised:
        promote(control, tmp_path / "umat", tmp_path / "work", tmp_path / "cache")
    assert "STRESS[1]" in str(raised.value)


def test_a_material_that_did_not_verify_is_refused_promotion(control, tmp_path: Path):
    with pytest.raises(PromotionRefused) as raised:
        promote(dict(control, stage="tangent_not_verified"), tmp_path / "umat",
                WORK, tmp_path / "cache")
    assert "tangent_not_verified" in str(raised.value)


def test_promotion_writes_the_four_things_it_says_it_does(control, tmp_path: Path):
    entry = promote(control, tmp_path / "umat", WORK, tmp_path / "cache")
    folder = tmp_path / "umat" / entry["id"]
    assert (folder / "contract.json").is_file()
    assert (folder / "results.json").is_file()
    assert (folder / "source.json").is_file()
    assert (folder / "README.md").is_file()
    assert "original_history.json" in entry["artifacts"]
    source = json.loads((folder / "source.json").read_text())
    assert source["redistributed_here"] is False, (
        "the bundled control's source_id is recorded from the discovery cache "
        "rather than from UMATs/, so it is fetched rather than copied")
    contract = json.loads((folder / "contract.json").read_text())
    assert contract["frozen_manifest"]["loading"], "the experiment, whole"
    assert contract["frozen_states"], "the states the tangent was measured at"


# ---------------------------------------------------------------------------
# and the record the repository keeps counts the same things
# ---------------------------------------------------------------------------
def test_the_batch_record_counts_every_gate_three_ways():
    """True, false, and never measured. A gate added after a run was made was
    not measured on that run, and reporting it as a false invents failures
    nobody found.

    Measured on pass9: 121 of 250 records carry an evidence block at all, so
    the first three gates read 121 true and 129 not measured; ``primal_agreed``
    reads 61 true and 60 false; ``derivatives_verified`` 67 true and 54 false;
    and ``mechanically_informative`` 250 not measured, because the gate is
    newer than the run.
    """
    from record_batch_evidence import EVIDENCE_GATES as RECORDED, gate_tally

    assert RECORDED == tuple(name for name, _, _ in EVIDENCE_GATES), (
        "the record and the page count the same six things in the same order")
    rows = [{"evidence": {"primal_agreed": True, "derivatives_verified": False}},
            {"evidence": {"primal_agreed": False}},
            {}]
    counts = gate_tally(rows)
    assert counts["primal_agreed"] == {"true": 1, "false": 1, "not_measured": 1}
    assert counts["derivatives_verified"] == {"true": 0, "false": 1,
                                              "not_measured": 2}
    assert counts["mechanically_informative"]["not_measured"] == 3


def test_the_batch_record_counts_what_the_experiments_gave_up():
    """Counted over the whole selection rather than over the entries that
    verified, because an agreement rate over the runs that happened to finish
    is not a statement about the corpus."""
    from record_batch_evidence import experiment_tally

    rows = [
        {"complete_finite_verification_run": True},
        {"discovery": {"complete_finite_verification_run": True,
                       "coverage_given_up": "'uniaxial_reversed' was dropped",
                       "segment_repair": "cut from 10 increments to 1",
                       "failure_mechanism": {"kind": "path_segment_limited"}}},
        {"discovery": {"complete_finite_verification_run": False,
                       "failure_mechanism": {"kind": "increment_resolution_limited"},
                       "safe_loading_reconstructed": {"amplitude": 0.008}}},
    ]
    tally = experiment_tally(rows)
    assert tally["complete_finite_verification_run"] == 2
    assert tally["experiment_gave_up_coverage"] == 1
    assert tally["a_segment_was_shortened_or_dropped"] == 1
    assert tally["loading_rebuilt_inside_the_proved_safe_part"] == 1
    assert tally["failure_mechanisms"] == {"path_segment_limited": 1,
                                           "increment_resolution_limited": 1}
