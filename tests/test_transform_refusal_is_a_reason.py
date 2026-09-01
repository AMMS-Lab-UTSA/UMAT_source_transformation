"""When the transformation service refuses, say why, not what it was given.

Eight sources in one batch reported their own contract as their blocker: the
harness stringified the whole summary dict when it found no ``error`` key, so
the report showed a configuration echo where a diagnosis belongs. Nothing was
wrong with those transforms that the summary did not already name -- it named
it in ``blockers`` and ``status_category``, and nobody read them.

A blocker line is the only thing a reader gets about a source that did not
make it. It has to be about the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.validation.tangent_validation import _transform_refusal  # noqa: E402

#: What the service actually hands back when it stops without an ``error``.
BLOCKED = {
    "config": "/somewhere/tangent_contract.json",
    "transform_success": False,
    "status_category": "transform_blocked",
    "blockers": ["DDSDDE assignment is not covered by an old tangent region"],
    "compilation": {"status": "not_requested"},
}


class TestItNamesTheCause:
    def test_an_explicit_error_wins(self):
        assert _transform_refusal({"error": "Source file not found: x.f"}) \
            == "Source file not found: x.f"

    def test_a_list_of_request_errors_is_joined(self):
        assert _transform_refusal({"errors": ["bad order", "bad direction"]}) \
            == "bad order; bad direction"

    def test_a_blocked_transform_reports_its_blockers(self):
        reason = _transform_refusal(BLOCKED)
        assert "transform_blocked" in reason
        assert "not covered by an old tangent region" in reason

    def test_a_compile_failure_reports_the_compiler(self):
        reason = _transform_refusal({
            "status_category": "transform_succeeded",
            "compilation": {"status": "compile_failed",
                            "stderr": "u.f:12: Error: Symbol 'q' has no IMPLICIT type"},
        })
        assert "Symbol 'q' has no IMPLICIT type" in reason

    def test_a_successful_compile_is_not_reported_as_the_reason(self):
        reason = _transform_refusal({"status_category": "transform_failed",
                                     "compilation": {"status": "compiled"}})
        assert "compiled" not in reason


class TestItNeverEchoesTheContract:
    def test_the_config_path_does_not_appear(self):
        assert "tangent_contract.json" not in _transform_refusal(BLOCKED)

    def test_a_silent_summary_says_so_rather_than_dumping_itself(self):
        reason = _transform_refusal({"config": "/somewhere/c.json",
                                     "transform_success": False})
        assert "/somewhere/c.json" not in reason
        assert "named no" in reason

    def test_it_is_always_a_string(self):
        for summary in ({}, BLOCKED, {"errors": []}, {"blockers": []}):
            assert isinstance(_transform_refusal(summary), str)
            assert _transform_refusal(summary).strip()


class TestAFailureWithNoBlocker:
    """A semantic check can refuse after the fact, leaving `blockers` empty.

    Two sources reported the bare words "transform_failed" because the reason
    sat in a field nobody read -- the same shape of bug as the config echo,
    one field further along.
    """

    SILENT = {
        "config": "/somewhere/c.json",
        "transform_success": False,
        "status_category": "transform_failed",
        "blockers": [],
        "warnings": ["Semantic check failed: stress_path_consumes_the_seed."],
        "semantic_checks": {"ddsdde_extraction_after_selected_stress_regions": True,
                            "stress_path_consumes_the_seed": False},
    }

    def test_the_failing_check_is_named(self):
        assert "stress_path_consumes_the_seed" in _transform_refusal(self.SILENT)

    def test_a_passing_check_is_not_named(self):
        assert "ddsdde_extraction_after" not in _transform_refusal(self.SILENT)

    def test_a_warning_stands_in_when_no_check_failed(self):
        assert "odd" in _transform_refusal(
            {"status_category": "transform_failed", "warnings": ["odd"]})

    def test_a_blocker_is_not_drowned_by_warnings(self):
        reason = _transform_refusal({"status_category": "transform_blocked",
                                     "blockers": ["no anchor"],
                                     "warnings": ["something chatty"]})
        assert "no anchor" in reason
        assert "chatty" not in reason
