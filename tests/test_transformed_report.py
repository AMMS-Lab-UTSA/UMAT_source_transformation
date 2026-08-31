"""What the report on transformed sources is allowed to say.

The count it carries is read as an achievement, so the artefact has to carry
its own limits: "transformed" means the generated Fortran compiles, and that
is one of the three things verification needs, not verification.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from build_transformed_report import (  # noqa: E402
    CAVEAT, COLUMNS, main, material_index, provenance_index, rows_for, summarise,
)


def _triage(path: Path, rows):
    fields = ["source", "repository", "form", "kinematics", "lines", "bytes",
              "helper_routines", "ntens", "nstatv_hint", "declared_unsupported",
              "original_compiles", "compiled", "stage", "seconds"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def _manifest(path: Path, rows):
    fields = ["repository", "commit", "license_spdx", "outcome", "cached_as", "found_by"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TestProvenance:
    def test_the_run_that_admitted_a_source_supplies_its_licence(self, tmp_path):
        """A later run that skipped it as a duplicate read no licence."""
        first, second = tmp_path / "a.csv", tmp_path / "b.csv"
        _manifest(first, [{"repository": "o/r", "commit": "a" * 40, "license_spdx": "MIT",
                           "outcome": "candidate", "cached_as": "o__r/u.f", "found_by": "q1"}])
        _manifest(second, [{"repository": "o/r", "commit": "b" * 40, "license_spdx": "GPL-3.0",
                            "outcome": "candidate", "cached_as": "o__r/u.f", "found_by": "q2"}])
        index = provenance_index([first, second])
        assert index["o__r/u.f"]["license_spdx"] == "MIT"
        assert index["o__r/u.f"]["commit"] == "a" * 12

    def test_a_refused_row_supplies_nothing(self, tmp_path):
        path = tmp_path / "m.csv"
        _manifest(path, [{"repository": "o/r", "commit": "c" * 40, "license_spdx": "",
                          "outcome": "licence_absent", "cached_as": "o__r/u.f", "found_by": ""}])
        assert provenance_index([path]) == {}

    def test_an_unreadable_manifest_is_skipped_not_fatal(self, tmp_path):
        assert provenance_index([tmp_path / "missing.csv"]) == {}


class TestTheReportStatesItsLimits:
    def test_a_source_without_a_manifest_row_is_marked_not_cleared(self, tmp_path):
        """A licence nobody read is not a licence that cleared."""
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "repository": "r", "stage": "transformed",
                          "compiled": "yes"}])
        rows = rows_for(triage, {}, {})
        assert rows[0]["license_spdx"] == "not in an available manifest"

    def test_a_compiling_source_with_a_vector_still_needs_a_loading_path(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed", "compiled": "yes"}])
        rows = rows_for(triage, {}, {"u.f": {"count": "6", "provenance": "d.inp"}})
        assert rows[0]["verifiable_today"] == "needs an accepted loading path"

    def test_a_compiling_source_without_a_vector_says_so(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed", "compiled": "yes"}])
        rows = rows_for(triage, {}, {})
        assert rows[0]["verifiable_today"] == "no material vector"

    def test_no_row_is_ever_marked_verified(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "o__r/u.f", "stage": "transformed", "compiled": "yes"}])
        rows = rows_for(triage, {}, {"u.f": {"count": "6", "provenance": "d.inp"}})
        assert "verified" not in json.dumps(rows).lower()

    def test_the_caveat_separates_compiling_from_verification(self):
        assert "compiles" in CAVEAT.lower()
        assert "not a claim about a derivative" in CAVEAT
        assert "accepted by a reviewer" in CAVEAT

    def test_the_summary_carries_the_caveat(self):
        assert summarise([])["caveat"] == CAVEAT


class TestSelection:
    def test_only_transformed_sources_are_reported(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [
            {"source": "a/u.f", "stage": "transformed", "compiled": "yes"},
            {"source": "b/u.f", "stage": "blocked", "compiled": "no"},
        ])
        rows = rows_for(triage, {}, {})
        assert [r["source"] for r in rows] == ["a/u.f"]

    def test_every_declared_column_is_present_in_every_row(self, tmp_path):
        triage = tmp_path / "t.csv"
        _triage(triage, [{"source": "a/u.f", "stage": "transformed", "compiled": "yes"}])
        assert set(rows_for(triage, {}, {})[0]) == set(COLUMNS)


def test_the_written_artefacts_agree_with_each_other(tmp_path):
    triage = tmp_path / "t.csv"
    _triage(triage, [{"source": "o__r/u.f", "repository": "o/r", "stage": "transformed",
                      "compiled": "yes", "lines": "10", "form": "fixed"}])
    manifest = tmp_path / "m.csv"
    _manifest(manifest, [{"repository": "o/r", "commit": "d" * 40, "license_spdx": "MIT",
                          "outcome": "candidate", "cached_as": "o__r/u.f", "found_by": "q"}])
    out = tmp_path / "out"
    main(["--triage", str(triage), "--manifest", str(manifest), "--out-dir", str(out)])
    written = json.loads((out / "transformed_sources.json").read_text())
    with (out / "transformed_sources.csv").open(newline="", encoding="utf-8") as handle:
        from_csv = list(csv.DictReader(handle))
    assert written["summary"]["transformed_sources"] == len(from_csv) == 1
    assert from_csv[0]["license_spdx"] == "MIT"
    assert written["summary"]["caveat"] == CAVEAT
