"""Canonical source identity, and the double counting it exists to prevent."""

from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

import pytest

from umat_oti.corpus.identity import (
    IdentityRegistry, closure_identity, content_identity, normalise_source,
    strip_comments,
)
from umat_oti.transform.dependency_resolution import resolve_closure

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX = REPO_ROOT / "paper_results" / "generality" / "generality_matrix.csv"
REGISTRY = REPO_ROOT / "paper_results" / "generality" / "source_identity.json"
ICP = REPO_ROOT / "UMATs" / "UMATs" / "ICP"
UPSTREAM = (REPO_ROOT.parent / "Residual_Assembler" / "sources" / "permissive"
            / "jgomezc1_ABAQUS-US" / "UMATS")


def test_normalisation_ignores_line_endings_and_trailing_space():
    assert normalise_source("A  \r\nB\r\n") == normalise_source("A\nB\n")


def test_comment_stripping_is_reported_separately_not_used_for_identity(tmp_path):
    """Comments do not change behaviour but do distinguish a fork from its parent."""
    a = tmp_path / "a.for"
    b = tmp_path / "b.for"
    a.write_text("      SUBROUTINE UMAT(X)\nC  a comment\n      X=1.0D0\n      END\n")
    b.write_text("      SUBROUTINE UMAT(X)\nC  different comment\n      X=1.0D0\n      END\n")
    ia, ib = content_identity(a), content_identity(b)
    assert ia.canonical_source_id != ib.canonical_source_id
    assert ia.code_only_sha256 == ib.code_only_sha256


@pytest.mark.skipif(not (UPSTREAM / "UMAT_PCO.for").is_file(),
                    reason="pinned upstream snapshot is not checked out")
def test_local_and_upstream_copies_are_one_implementation():
    """Every ICP UMAT is normalised-identical to its upstream original.

    They differ only in line endings. Counting both would turn one
    implementation validated twice into two implementations.
    """
    for name in ("UMAT_PCL", "UMAT_PCLK", "UMAT_NKH_1.02", "UMAT_VPDCL"):
        local = content_identity(ICP / f"{name}.for")
        upstream = content_identity(UPSTREAM / f"{name}.for")
        assert local.canonical_source_id == upstream.canonical_source_id, name


@pytest.mark.skipif(not (UPSTREAM / "UMAT_PCO.for").is_file(),
                    reason="pinned upstream snapshot is not checked out")
def test_closure_identity_ignores_layout():
    """The same closure lives at different relative paths in different origins."""
    for name in ("UMAT_PCO", "UMAT_VPDCO", "UMAT_ECO"):
        local = closure_identity(resolve_closure(ICP / f"{name}.for", roots=[ICP]))
        upstream = closure_identity(
            resolve_closure(UPSTREAM / f"{name}.for", roots=[UPSTREAM]))
        assert local.canonical_source_id == upstream.canonical_source_id, name
        assert local.kind == "dependency_closure"


def test_registry_separates_identity_origin_and_validation_event():
    registry = IdentityRegistry()
    identity = content_identity(ICP / "UMAT_PCL.for")
    registry.record(identity, origin="local archive", label="UMAT_PCL",
                    validation_event="TABLE-3", verified=True)
    registry.record(identity, origin="upstream snapshot", label="jgomezc1_UMAT_PCL",
                    validation_event="TABLE-3", verified=True)
    counts = registry.counts(raw_discovered=2)
    assert counts["content_deduplicated_sources"] == 1
    assert counts["sources_found_at_more_than_one_origin"] == 1
    entry = next(iter(registry.by_id.values()))
    assert len(entry["origins"]) == 2
    assert len(entry["validation_events"]) == 2


@pytest.mark.skipif(not MATRIX.is_file(), reason="matrix not generated")
def test_no_two_generality_rows_share_a_canonical_identity():
    """The requirement this whole layer exists to satisfy.

    Two rows with one identity would be the same implementation counted twice.
    Extra appearances belong beneath the canonical row as origins and validation
    events, which is what the merged columns carry.
    """
    rows = list(csv.DictReader(MATRIX.open(encoding="utf-8")))
    duplicates = [identity for identity, count in collections.Counter(
        row["canonical_source_id"] for row in rows).items() if count > 1]
    assert not duplicates, f"duplicated canonical identities: {duplicates}"


@pytest.mark.skipif(not MATRIX.is_file(), reason="matrix not generated")
def test_merged_rows_keep_every_origin_and_event():
    rows = list(csv.DictReader(MATRIX.open(encoding="utf-8")))
    merged = [row for row in rows if ";" in row["origin"]]
    assert merged, "the ICP and upstream copies should have merged"
    for row in merged:
        assert ";" in row["aliases"], row["canonical_source_id"]
        assert row["validation_events"]


@pytest.mark.skipif(not REGISTRY.is_file(), reason="registry not generated")
def test_registry_reports_every_required_count():
    counts = json.loads(REGISTRY.read_text(encoding="utf-8"))["counts"]
    for key in ("raw_discovered_files", "content_deduplicated_sources",
                "unique_dependency_closures", "unique_constitutive_models",
                "independent_upstream_repositories", "verified_unique_sources"):
        assert key in counts, key
    assert counts["content_deduplicated_sources"] <= counts["raw_discovered_files"]
    assert "verified_unique_sources_by_event" in counts, \
        "a bare verified count hides what did the verifying"
