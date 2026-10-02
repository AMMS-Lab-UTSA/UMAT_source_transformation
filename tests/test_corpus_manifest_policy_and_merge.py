"""Unit tests for the manifest's licence policy, cell validator and merge.

Pure Python on synthetic data; no corpus, cache or compiler needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.corpus_features.manifest import (
    FEATURES,
    STAGES,
    detect_licence_text,
    merge_feature_results,
    redistribution_policy,
    summarise,
    validate_cell,
)

pytestmark = pytest.mark.unit

FILE = {"path": "discovery_cache:x__y/LICENSE", "detected_spdx": None}


@pytest.mark.parametrize("spdx", ["MIT", "BSD-2-Clause", "BSD-3-Clause",
                                  "Apache-2.0", "GPL-3.0", "GPL-3.0-or-later",
                                  "LGPL-3.0"])
def test_a_compatible_licence_file_permits_redistribution(spdx):
    p = redistribution_policy(spdx, {**FILE, "detected_spdx": spdx})
    assert p["redistribution"] == "permitted"
    assert p["attribution_required"] is True
    assert "discovery_cache:x__y/LICENSE" in p["redistribution_basis"]


@pytest.mark.parametrize("spdx", ["MIT", "Apache-2.0", "GPL-3.0"])
def test_metadata_alone_does_not_permit(spdx):
    p = redistribution_policy(spdx, None, metadata_source="GitHub licence API")
    assert p["redistribution"] == "unknown"
    assert "absent from the acquisition cache" in p["redistribution_basis"]
    assert "does not mean the repository has none" in p["redistribution_basis"]


@pytest.mark.parametrize("spdx", ["", None, "NOASSERTION", "NONE"])
def test_no_licence_is_not_permitted(spdx):
    p = redistribution_policy(spdx, None)
    assert p["redistribution"] == "not_permitted"
    assert "all rights reserved" in p["redistribution_basis"]


@pytest.mark.parametrize("spdx", ["GPL-2.0", "GPL-2.0-only", "CC-BY-NC-4.0",
                                  "CC-BY-ND-4.0"])
def test_incompatible_licences_are_not_permitted(spdx):
    assert redistribution_policy(spdx, None)["redistribution"] == "not_permitted"
    assert redistribution_policy(spdx, {**FILE, "detected_spdx": spdx})[
        "redistribution"] == "not_permitted"


@pytest.mark.parametrize("spdx", ["AGPL-3.0", "ISC", "Zlib"])
def test_licences_off_the_lead_list_need_a_decision(spdx):
    assert redistribution_policy(spdx, {**FILE, "detected_spdx": spdx})[
        "redistribution"] == "unknown"


def test_an_unreadable_licence_file_is_unknown():
    assert redistribution_policy("MIT", FILE)["redistribution"] == "unknown"


def test_copyleft_and_attribution_are_recorded():
    assert redistribution_policy("MIT", None)["copyleft"] == "none"
    assert redistribution_policy("GPL-3.0", None)["copyleft"] == "strong"
    assert redistribution_policy("LGPL-3.0", None)["copyleft"] == "weak"
    assert redistribution_policy("AGPL-3.0", None)["copyleft"] == "network"


def test_a_gpl3_licence_file_is_not_read_as_agpl():
    """GPL-3.0 s.13 names the Affero licence; the title decides, not the body."""
    text = ("GNU GENERAL PUBLIC LICENSE\n Version 3, 29 June 2007\n" + "x\n" * 50
            + "13. Use with the GNU Affero General Public License.\n")
    assert detect_licence_text(text) == "GPL-3.0"
    assert detect_licence_text("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3") == \
        "AGPL-3.0"
    assert detect_licence_text("Permission is hereby granted, free of charge, to") \
        == "MIT"


# ---- validator / merge (the merge contract, docs/CORPUS_MANIFEST.md) --------

@pytest.fixture
def roots(tmp_path: Path) -> dict:
    (tmp_path / "ev.jsonl").write_text("{}\n")
    (tmp_path / "other.jsonl").write_text("{}\n")
    return {"t": str(tmp_path)}


def _good(**over):
    cell = {"status": "verified", "reason": "", "evidence": "t:ev.jsonl#k",
            "reference": "fd", "max_error": 0.2, "tolerance": 1.0,
            "tolerance_rule_id": "entrywise/1", "rtol": 1e-6, "atol": 1e-12,
            "fd_steps": [1e-3, 3e-4, 1e-4, 3e-5], "min_plateau_observed": 3,
            "plateau_basis": "fd_only", "quantity": "d STRESS/d PROPS",
            "wrt": "PROPS(1)", "held_fixed": "incoming STATEV", "scope": "local",
            "build": {"kind": "store", "fingerprint": "dbe9f928191e1d43",
                      "sha256": ""}}
    cell.update(over)
    return cell


def test_the_validator_accepts_a_complete_derivative_claim(roots):
    assert validate_cell("stress_param_sens_local", _good(), roots=roots) == []


@pytest.mark.parametrize("over,expected", [
    ({"evidence": ""}, "evidence"),
    ({"evidence": "t:missing.json"}, "does not resolve"),
    ({"evidence": "nowhere:does/not/exist.json"}, "not one of"),
    ({"evidence": "t:../../etc/passwd"}, "leaves its root"),
    ({"reference": "oti"}, "reference"),
    ({"max_error": 1.5}, "above tolerance"),
    ({"max_error": float("nan")}, "finite"),
    ({"tolerance": 1e300}, "must be 1.0"),
    ({"tolerance_rule_id": None}, "not registered"),
    ({"tolerance_rule_id": "legacy_column_norm"}, "not accepted"),
    ({"tolerance_rule_id": "vector_max_norm"}, "not accepted"),
    ({"tolerance_rule_id": "primal_row_scaled/1"}, "does not apply"),
    ({"rtol": 0.5}, "exceeds the bound"),
    ({"rtol": None}, "rtol"),
    ({"fd_steps": [1e-3, 1e-4]}, "three step sizes"),
    ({"min_plateau_observed": None}, "min_plateau_observed"),
    ({"min_plateau_observed": 2}, "D-4"),
    ({"min_plateau_observed": 9}, "longer than the step ladder"),
    ({"plateau_basis": "oti_vs_fd"}, "plateau_basis"),
    ({"held_fixed": ""}, "held_fixed"),
    ({"held_fixed": "-"}, "held_fixed"),
    ({"quantity": "q"}, "quantity"),
    ({"scope": "both"}, "scope"),
    ({"build": None}, "without a build"),
    ({"build": {"kind": "magic", "sha256": "abc123"}}, "kind is one of"),
    ({"build": {"kind": "store", "fingerprint": "", "sha256": ""}},
     "neither a fingerprint"),
])
def test_the_validator_refuses_an_incomplete_verified(roots, over, expected):
    problems = validate_cell("stress_param_sens_total", _good(**over), roots=roots)
    assert any(expected in p for p in problems), problems


def test_a_non_verified_cell_needs_a_reason_and_a_known_status(roots):
    assert validate_cell("ddsdde", {"status": "failed", "reason": ""}, roots=roots)
    assert validate_cell("ddsdde", {"status": "skipped", "reason": "x"}, roots=roots)
    assert validate_cell("ddsdde", {"status": "plausible", "reason": "x"}, roots=roots)
    assert validate_cell("nope", {"status": "failed", "reason": "x"}, roots=roots)


def _tiny_manifest(roots):
    def row(sid):
        return {"row_kind": "acquired", "source_id": sid,
                "license": {"redistribution": "unknown", "spdx": "MIT",
                            "spdx_metadata": "MIT", "license_class": "permissive",
                            "attribution_required": True, "copyleft": "none",
                            "licence_file": None},
                "model": {"family": {"family": "plasticity", "review": "keyword_only",
                                     "human_reviewed": False}},
                "pipeline": {s: {"status": "verified" if s in ("discovered",
                                                               "eligible") else
                                 "not_attempted", "reason": "r", "evidence": "t:ev.jsonl",
                                 **({"layouts": {}} if s == "compiled" else {})}
                             for s in STAGES},
                "features": {f: {"status": "not_attempted", "reason": "none yet",
                                 "evidence": "", "reference": None, "max_error": None,
                                 "tolerance": None, "history": []} for f in FEATURES},
                "features_other_builds": {"lifted": {}, "provider": {}},
                "ddsdde_legacy_gate": {"gate": "not_run", "counts_as_verified": False,
                                       "rule": "legacy"}}
    m = {"roots": dict(roots), "rows": [row("a/1.f"), row("b/2.f")]}
    m["summary"] = summarise(m)
    return m


def _primal(status="verified", **over):
    c = {"status": status, "reason": "primal", "evidence": "t:ev.jsonl",
         "reference": "original", "max_error": 0.1, "tolerance": 1.0,
         "tolerance_rule_id": "primal_row_scaled/1", "rtol": 1e-10,
         "quantity": "STRESS, STATEV", "scope": "history"}
    c.update(over)
    return c


def test_merge_replaces_cells_keeps_history_and_recounts(tmp_path: Path, roots):
    m = _tiny_manifest(roots)
    lines = [
        {"source_id": "a/1.f", "feature": "primal_stress_state", **_primal()},
        {"source_id": "a/1.f", "feature": "stress_param_sens_local", **_good(),
         "producer": "gauss/B2"},
        {"source_id": "b/2.f", "feature": "global_sens", "status": "failed",
         "reason": "residual did not converge", "evidence": "t:other.jsonl",
         "build": {"kind": "store", "fingerprint": "abc"}},
        {"source_id": "a/1.f", "feature": "ddsdde", **_good(evidence="")},
        {"source_id": "zzz", "feature": "ddsdde", "status": "failed", "reason": "x"},
    ]
    path = tmp_path / "results.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    report = merge_feature_results(m, path)
    assert report["merged"] == 3
    assert report["unmatched"] == ["zzz"]
    assert len(report["rejected"]) == 1 and report["rejected"][0]["feature"] == "ddsdde"
    cell = m["rows"][0]["features"]["stress_param_sens_local"]
    assert cell["status"] == "verified" and cell["producer"] == "gauss/B2"
    assert cell["history"][0]["status"] == "not_attempted"
    assert m["rows"][0]["features"]["ddsdde"]["status"] == "not_attempted"
    f = m["summary"]["features"]["D1_acquired"]
    assert f["stress_param_sens_local"]["verified"] == 1
    assert f["global_sens"]["failed"] == 1
    assert sum(f["global_sens"].values()) == 2
    assert m["merges"][-1]["merged"] == 3


def test_a_failed_cell_is_never_overwritten_by_verified(roots):
    m = _tiny_manifest(roots)
    merge_feature_results(m, [{"source_id": "a/1.f", "feature": "primal_stress_state",
                               **_primal()}])
    merge_feature_results(m, [{"source_id": "a/1.f", "feature": "ddsdde",
                               "status": "failed", "reason": "re-run disagreed",
                               "evidence": "t:other.jsonl",
                               "build": {"kind": "store", "fingerprint": "abc"}}])
    merge_feature_results(m, [{"source_id": "a/1.f", "feature": "ddsdde", **_good()}])
    cell = m["rows"][0]["features"]["ddsdde"]
    assert cell["status"] == "conflict"
    assert sorted(c["status"] for c in cell["conflicting"]) == ["failed", "verified"]
    assert m["summary"]["features"]["D1_acquired"]["ddsdde"]["verified"] == 0
    assert m["summary"]["features"]["D1_acquired"]["ddsdde"]["conflict"] == 1
