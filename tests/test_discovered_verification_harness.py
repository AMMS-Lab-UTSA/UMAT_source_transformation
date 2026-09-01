"""What the batch tangent verification is allowed to claim.

The count it produces will be read as "these UMATs are verified", so the
harness has to carry the two things that bound that: the material constants
are real and read from a deck, and the loading path is a probe this harness
chose. A verified row says the OTI tangent equals the derivative of that
source's own stress along the probe. It says nothing about the model under
its author's intended loading, and nothing at all about a source with no
material vector.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovered_verification import (  # noqa: E402
    CAVEAT, COLUMNS, PROBE_INCREMENT, PROBE_INCREMENTS, PROBE_PROVENANCE,
    _case, cases_from, summarise,
)


def _triage(path: Path, rows):
    fields = ["source", "repository", "kinematics", "ntens", "nstatv_hint", "stage"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def _proposals(path: Path, entries):
    path.write_text(json.dumps({"entries": entries}), encoding="utf-8")


class TestOnlyVerifiableSourcesAreAttempted:
    def test_a_source_with_no_material_vector_is_not_attempted(self, tmp_path):
        """Verifying it would mean inventing constants."""
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed", "ntens": "6"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [])
        assert cases_from(triage, proposals, tmp_path) == []

    def test_a_source_that_does_not_transform_is_not_attempted(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "blocked", "ntens": "6"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [{"status": "proposed_needs_review", "source": "o__r/u.f",
                                "material": {"props": [1.0, 2.0]}}])
        assert cases_from(triage, proposals, tmp_path) == []

    def test_an_unreviewed_proposal_supplies_no_constants(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed", "ntens": "6"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [{"status": "no_matching_deck", "source": "o__r/u.f",
                                "material": {"props": [1.0]}}])
        assert cases_from(triage, proposals, tmp_path) == []

    def test_a_transformed_source_with_a_vector_is_attempted(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed",
                          "ntens": "6", "nstatv_hint": "4"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [{"status": "proposed_needs_review", "source": "o__r/u.f",
                                "material": {"props": [1.0, 2.0]}}])
        items = cases_from(triage, proposals, tmp_path)
        assert len(items) == 1
        case = _case(items[0])
        assert case.props == (1.0, 2.0)
        assert case.ntens == 6 and case.nstatv == 4

    def test_kinematics_can_be_restricted(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [
            {"source": "a/u.f", "stage": "transformed", "kinematics": "finite", "ntens": "6"},
            {"source": "b/u.f", "stage": "transformed", "kinematics": "small strain", "ntens": "6"},
        ])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [
            {"status": "proposed_needs_review", "source": "a/u.f", "material": {"props": [1.0]}},
            {"status": "proposed_needs_review", "source": "b/u.f", "material": {"props": [1.0]}},
        ])
        items = cases_from(triage, proposals, tmp_path, kinematics="finite")
        assert [i["row"]["source"] for i in items] == ["a/u.f"]


class TestTheProbeDeclaresItself:
    def test_the_case_is_driven_by_the_declared_probe(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed", "ntens": "6"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [{"status": "proposed_needs_review", "source": "o__r/u.f",
                                "material": {"props": [1.0]}}])
        case = _case(cases_from(triage, proposals, tmp_path)[0])
        assert case.dstran_per_increment == PROBE_INCREMENT
        assert case.n_increments == PROBE_INCREMENTS

    def test_the_probe_says_it_is_not_from_a_deck(self):
        assert "not read from a deck" in PROBE_PROVENANCE
        assert "not this source's own loading history" in PROBE_PROVENANCE

    def test_every_row_records_the_probe_and_the_material_provenance(self):
        assert "loading_probe" in COLUMNS
        assert "material_provenance" in COLUMNS

    def test_the_caveat_separates_the_two_sides_and_names_the_probe(self):
        assert "share no code path" in CAVEAT
        assert "DECLARED PROBE" in CAVEAT
        assert "never as agreement" in CAVEAT

    def test_the_summary_carries_the_caveat_and_the_probe(self):
        summary = summarise([])
        assert summary["caveat"] == CAVEAT
        assert summary["loading_probe"]["provenance"] == PROBE_PROVENANCE


class TestTheSummaryCountsHonestly:
    ROWS = [
        {"furthest_stage": "tangent_verified", "rows_total": "10", "rows_agreeing": "10",
         "rows_disagreeing": "0", "rows_unresolved": "0", "structural_zeros": "4"},
        {"furthest_stage": "reference_resolved", "rows_total": "10", "rows_agreeing": "7",
         "rows_disagreeing": "3", "rows_unresolved": "0", "structural_zeros": "2"},
        {"furthest_stage": "original_executed", "rows_total": "0", "rows_agreeing": "0",
         "rows_disagreeing": "0", "rows_unresolved": "0", "structural_zeros": "0"},
    ]

    def test_only_a_case_that_reached_the_last_gate_counts_as_verified(self):
        assert summarise(self.ROWS)["reached_tangent_verified"] == 1

    def test_disagreeing_entries_are_reported_not_absorbed(self):
        assert summarise(self.ROWS)["rows_disagreeing"] == 3

    def test_a_case_that_never_ran_contributes_no_agreement(self):
        summary = summarise(self.ROWS)
        assert summary["rows_total"] == 20
        assert summary["rows_agreeing"] == 17


def test_every_row_says_what_was_actually_differentiated():
    """A finite-strain row and a small-strain row are not the same claim.

    One establishes a derivative with respect to a strain increment, the other
    with respect to the same increment mapped into the deformation gradient.
    A reader scanning the table has to see which without going back to the
    module docstring, so the fields travel per row rather than sitting in a
    per-case summary.
    """
    assert "driven_through" in COLUMNS
    assert "reference_perturbation" in COLUMNS
