"""A material vector must belong to the source it is driven with.

Proposals were indexed by the source's FILE NAME. Twenty-one transformed
sources share a basename with another -- three separate projects ship a
"umat.f" -- so the index silently collapsed them and handed whichever entry
happened to be last to every source of that name. Eighteen cases were driven
with another project's material constants, across repositories in some cases,
and two of those reached "verified": the OTI tangent agreed with a derivative
of a stress that was never the one the source's author meant to compute.

Nothing failed. The numbers were self-consistent and wrong, and the
material_provenance column recorded, in good faith, a deck from the wrong
repository. That is the failure mode this project cares about most, so the key
is tested rather than assumed.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovered_verification import (  # noqa: E402
    _cache_relative_source, cases_from,
)

TRIAGE_COLUMNS = ["source", "repository", "stage", "ntens", "nstatv_hint",
                  "kinematics"]


def _triage(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRIAGE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in TRIAGE_COLUMNS})


def _proposals(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps({"entries": entries, "summary": {}}),
                    encoding="utf-8")


#: Two projects, each shipping a file called umat.f, with different materials.
ONE = {"status": "proposed_needs_review", "repository": "owner/alpha",
       "source": "src/umat.f", "material": {"props": [1.0, 2.0]}}
TWO = {"status": "proposed_needs_review", "repository": "owner/beta",
       "source": "src/umat.f", "material": {"props": [9.0, 8.0]}}


class TestTheKeyIdentifiesAFileNotAFilename:
    def test_a_repository_slash_becomes_the_cache_separator(self):
        assert _cache_relative_source(ONE) == "owner__alpha/src/umat.f"

    def test_two_projects_with_the_same_filename_get_different_keys(self):
        assert _cache_relative_source(ONE) != _cache_relative_source(TWO)

    def test_an_entry_with_no_repository_keeps_its_own_path(self):
        assert _cache_relative_source({"source": "u.f"}) == "u.f"


class TestEachSourceGetsItsOwnMaterial:
    def test_neither_project_is_given_the_others_constants(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [
            {"source": "owner__alpha/src/umat.f", "stage": "transformed",
             "ntens": "6", "nstatv_hint": "4"},
            {"source": "owner__beta/src/umat.f", "stage": "transformed",
             "ntens": "6", "nstatv_hint": "4"},
        ])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [ONE, TWO])

        items = cases_from(triage, proposals, tmp_path)
        assert len(items) == 2
        paired = {item["row"]["source"]: item["entry"]["material"]["props"]
                  for item in items}
        assert paired["owner__alpha/src/umat.f"] == [1.0, 2.0]
        assert paired["owner__beta/src/umat.f"] == [9.0, 8.0]

    def test_a_source_with_no_proposal_of_its_own_is_not_attempted(self, tmp_path):
        # Under the basename key this row was handed beta's constants and run.
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "owner__gamma/src/umat.f",
                          "stage": "transformed", "ntens": "6",
                          "nstatv_hint": "4"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [TWO])
        assert cases_from(triage, proposals, tmp_path) == []

    def test_an_unreviewed_proposal_is_still_ignored(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "owner__alpha/src/umat.f",
                          "stage": "transformed", "ntens": "6",
                          "nstatv_hint": "4"}])
        proposals = tmp_path / "p.json"
        _proposals(proposals, [{**ONE, "status": "no_matching_deck"}])
        assert cases_from(triage, proposals, tmp_path) == []


class TestAgainstTheRealCorpus:
    def test_no_case_is_paired_with_a_different_source(self):
        """The property that failed on the real data, asserted on it."""
        triage = REPO_ROOT / "paper_results/discovery/discovery_triage.csv"
        proposals = REPO_ROOT / "paper_results/discovery/proposed_corpus_entries.json"
        if not (triage.is_file() and proposals.is_file()):
            return
        for item in cases_from(triage, proposals, Path(".")):
            assert item["row"]["source"] == _cache_relative_source(item["entry"])
