"""Tests for the derivative manifest, driver contract, and corpus toolkit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.core.derivative_request import DerivativeRequest, KIND_PARAMETER_SENSITIVITY
from umat_oti.reports.driver_contract import (
    CONTRACT_SCHEMA,
    DriverContract,
    build_softwarex_j2_contract,
    write_j2_stream,
)
from umat_oti.reports.manifest import (
    MANIFEST_SCHEMA,
    build_manifest,
    sha256_of_file,
    write_manifest,
)
from umat_oti.corpus import (
    FAILURE_CATEGORIES,
    STAGE_DERIVATIVE_VERIFIED,
    STAGE_TRANSFORMED,
    CorpusCandidate,
    CorpusRecord,
    build_github_search_urls,
    classify_license,
    content_hash,
    deduplicate,
    detect_entry_routines,
    detect_source_form,
    discover_via_github_api,
    round_metrics,
)
from umat_oti.corpus.cli import _build_run_provenance


# --- Manifest ---------------------------------------------------------------

def test_manifest_sha256_stable(tmp_path: Path):
    src = tmp_path / "u.for"
    src.write_bytes(b"SUBROUTINE UMAT\nEND\n")
    a = sha256_of_file(src)
    b = sha256_of_file(src)
    assert a == b
    assert len(a) == 64


def test_manifest_records_all_required_fields(tmp_path: Path):
    src = tmp_path / "j2.for"
    src.write_text("SUBROUTINE UMAT\nEND\n", encoding="utf-8")
    requests = [
        DerivativeRequest(
            id="material_tangent",
            target="DDSDDE",
            seed=("DSTRAN",),
            response="STRESS",
            order=1,
        ),
        DerivativeRequest(
            id="higher_order",
            target="DDSDDE3",
            seed=("DSTRAN",),
            response="STRESS",
            order=3,
        ),
        DerivativeRequest(
            id="dsigma_dp",
            target="DSIGMA_DP",
            seed=("E", "NU", "SIGY0", "H"),
            response="STRESS",
            order=1,
            kind=KIND_PARAMETER_SENSITIVITY,
            parameter_map=(("E", 1), ("NU", 2), ("SIGY0", 3), ("H", 4)),
        ),
    ]
    manifest = build_manifest(
        source_path=src,
        entry_routine="UMAT",
        ntens=6,
        nstatv=1,
        nprops=4,
        requests=requests,
        parameters=[("E", 1), ("NU", 2), ("SIGY0", 3), ("H", 4)],
        state_variables=[("EQPLAS", 1)],
        compiler_name="gfortran",
        compiler_version="12.2.0",
        direction_count=4,
    )
    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["source"]["sha256"]
    assert manifest["source"]["entry_routine"] == "UMAT"
    assert manifest["dimensions"] == {"ntens": 6, "nstatv": 1, "nprops": 4}
    assert manifest["parameters"] == [
        {"name": "E", "props_index": 1},
        {"name": "NU", "props_index": 2},
        {"name": "SIGY0", "props_index": 3},
        {"name": "H", "props_index": 4},
    ]
    # recovery factor for order-3 request must be 3! = 6.
    higher = next(d for d in manifest["derivatives"] if d["id"] == "higher_order")
    assert higher["recovery_factor"] == 6
    tangent = next(d for d in manifest["derivatives"] if d["id"] == "material_tangent")
    assert tangent["recovery_factor"] == 1
    # convention block spells out the factorial rule.
    assert "factorial" in manifest["convention"]["coefficient_vs_derivative"].lower()


def test_manifest_write_roundtrip(tmp_path: Path):
    src = tmp_path / "u.for"
    src.write_bytes(b"X\n")
    m = build_manifest(
        source_path=src,
        entry_routine="UMAT",
        ntens=6, nstatv=1, nprops=4,
        requests=[],
    )
    out = write_manifest(m, tmp_path / "manifest.json")
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == MANIFEST_SCHEMA


# --- Driver contract --------------------------------------------------------

def test_driver_contract_schema_and_roundtrip(tmp_path: Path):
    contract = build_softwarex_j2_contract(stream_path="stream.jsonl")
    assert contract.schema == CONTRACT_SCHEMA
    assert contract.ntens == 6
    assert [p.name for p in contract.parameters] == ["E", "NU", "SIGY0", "H"]
    assert [s.name for s in contract.state_variables] == ["EQPLAS"]
    out = contract.write(tmp_path / "contract.json")
    replayed = DriverContract.read(out)
    assert replayed.to_dict() == contract.to_dict()


def test_driver_contract_rejects_wrong_schema(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "wrong", "driver_id": "x", "ntens": 6, "nstatv": 1, "nprops": 4}))
    with pytest.raises(ValueError):
        DriverContract.read(bad)


def test_write_j2_stream_produces_jsonl(tmp_path: Path):
    records = [
        {"increment": 1, "stress": [0.0] * 6, "statev": [0.0], "dsigma_dp": [[0.0] * 4] * 6, "dstatev_dp": [[0.0] * 4]},
        {"increment": 2, "stress": [10.0] + [0.0] * 5, "statev": [0.1], "dsigma_dp": [[0.0] * 4] * 6, "dstatev_dp": [[0.0] * 4]},
    ]
    path = write_j2_stream(records, tmp_path / "stream.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["increment"] == 1
    assert parsed[1]["stress"][0] == 10.0


# --- Corpus -----------------------------------------------------------------

@pytest.mark.parametrize(
    "spdx,expected",
    [
        ("MIT", "permissive"),
        ("BSD-3-Clause", "permissive"),
        ("GPL-3.0-only", "copyleft"),
        ("AGPL-3.0", "copyleft"),
        (None, "unknown"),
        ("", "unknown"),
        ("custom-non-spdx-thing", "unknown"),
    ],
)
def test_classify_license(spdx, expected):
    assert classify_license(spdx) == expected


def test_content_hash_dedups_whitespace_and_case():
    a = "SUBROUTINE UMAT\n  IMPLICIT NONE\nEND\n"
    b = "subroutine   umat\nimplicit none\nend\n\n\n"
    c = "SUBROUTINE UMAT\nimplicit none\nend\n"
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) == content_hash(c)


def test_detect_entry_routines_finds_all_kinds():
    src = """
    subroutine umat(stress)
    end
    SUBROUTINE UHYPER
    END
    SUBROUTINE UEL()
    END
    """
    detected = detect_entry_routines(src)
    assert "UMAT" in detected
    assert "UHYPER" in detected
    assert "UEL" in detected


def test_detect_source_form_free_vs_fixed():
    free = "subroutine umat\n  implicit none\nend subroutine\n"
    fixed = "C  fixed-form comment\n      SUBROUTINE UMAT\n      END\n"
    assert detect_source_form(free) == "free"
    assert detect_source_form(fixed) == "fixed"


def test_deduplicate_removes_hash_dupes_preserving_order():
    def _rec(name: str, h: str) -> CorpusRecord:
        return CorpusRecord(
            candidate=CorpusCandidate(
                repository=name,
                file_path=f"{name}.for",
                commit_sha="sha",
                retrieved_at="now",
                license_spdx="MIT",
                normalized_hash=h,
            ),
        )

    records = [_rec("A", "h1"), _rec("B", "h2"), _rec("C", "h1"), _rec("D", "h3")]
    deduped = deduplicate(records)
    assert [r.candidate.repository for r in deduped] == ["A", "B", "D"]


def test_build_github_search_urls_are_all_api_endpoints():
    urls = build_github_search_urls()
    assert urls
    for u in urls:
        assert u.startswith("https://api.github.com/search/code?")
        assert "language%3AFortran" in u.replace("+", "%20") or "language:Fortran" in u


def test_discover_via_github_api_refuses_implicit_network():
    with pytest.raises(RuntimeError, match="allow_network=True"):
        discover_via_github_api(token=None, allow_network=False)


def test_round_metrics_counts_only_actual_states():
    records = [
        CorpusRecord(
            candidate=CorpusCandidate(
                repository="a",
                file_path="a.for",
                commit_sha="sha",
                retrieved_at="now",
                license_spdx="MIT",
                normalized_hash="h1",
            ),
            stage=STAGE_DERIVATIVE_VERIFIED,
            outcome="passed",
        ),
        CorpusRecord(
            candidate=CorpusCandidate(
                repository="b",
                file_path="b.for",
                commit_sha="sha",
                retrieved_at="now",
                license_spdx="GPL-3.0-only",
                normalized_hash="h2",
            ),
            stage="license_classified",
            outcome="failed",
            failure_category="unsupported_license",
            failure_message="copyleft; reference only",
        ),
        CorpusRecord(
            candidate=CorpusCandidate(
                repository="c",
                file_path="c.for",
                commit_sha="sha",
                retrieved_at="now",
                license_spdx="MIT",
                normalized_hash="h3",
            ),
            stage=STAGE_TRANSFORMED,
            outcome="passed",
        ),
    ]
    metrics = round_metrics(records)
    assert metrics.corpus_size == 3
    assert metrics.unique_umat_count == 3
    assert metrics.transform_success == 2
    assert metrics.compile_success == 1
    assert metrics.numerical_validation_success == 1
    assert metrics.failure_counts == {"unsupported_license": 1}
    assert set(FAILURE_CATEGORIES).issuperset(metrics.failure_counts.keys())


def test_corpus_run_provenance_preserves_all_denominators():
    index = {
        "schema": "umat-oti-corpus-index/1",
        "generated_at": "2026-08-21T00:00:00+00:00",
        "source": "manifest",
        "candidates": [
            {
                "repository": "owner/a",
                "cache_path": "/cache/a.for",
                "content_hash": "same",
                "entry_routines": ["UMAT"],
            },
            {
                "repository": "owner/a",
                "cache_path": "/cache/a-copy.for",
                "content_hash": "same",
                "entry_routines": ["UMAT"],
            },
            {
                "repository": "owner/b",
                "cache_path": "/cache/helper.f90",
                "content_hash": "helper",
                "entry_routines": [],
            },
        ],
    }

    provenance = _build_run_provenance(index, [{"id": "same"}, {"id": "helper"}])

    assert provenance["acquired_source_count"] == 3
    assert provenance["snapshotted_source_count"] == 3
    assert provenance["unique_source_count"] == 2
    assert provenance["unique_umat_count"] == 1
    assert provenance["processed_source_count"] == 2
    assert provenance["repositories"] == ["owner/a", "owner/b"]
