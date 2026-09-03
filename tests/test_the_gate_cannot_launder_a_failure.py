"""What the offline gate must not turn into a pass, or into a claim about a UMAT.

Adversarial review of the gate found that a transformed build returning NaN for
every stress component was scored AGREED with a worst relative difference of
0.0, and was then queued for Abaqus licence time while dragging the headline
"worst difference among agreeing rows" toward zero. The mechanism: every
comparison against NaN is False, so the running maximum never moved; and the
gate's own guard used max(abs(...)), which returns NaN, and bool(NaN) is True.

The comparison primitive is fixed upstream. These cover the gate's own share:
the response guard, the outcome vocabulary, the report's validity as JSON, and
the line between a failure of a source and a failure of this machine.
"""
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from verify_store_offline import (                             # noqa: E402
    AGREED, DISAGREED, HARNESS_ERROR, NON_FINITE_RESPONSE, NO_RESPONSE,
    OUTCOMES, _json_safe, broke_on_the_machine, non_finite_count, outcome_for,
    stress_response)


def _decided(**overrides):
    """A record that got as far as a comparison, so the later guards apply."""
    record = {
        "original_available": True, "material_provenance": "a paired deck",
        "built_original": True, "built_transformed": True,
        "ran_original": True, "ran_transformed": True,
        "response": True, "non_finite_components": 0,
    }
    record.update(overrides)
    return record


# ---- the response guard --------------------------------------------------
def test_the_response_ignores_a_non_finite_component():
    """max() over a list holding NaN returns NaN, and bool(NaN) is True.

    That is how a build returning NaN for every component satisfied the
    "did anything move?" guard and went on to be scored as agreement.
    """
    assert stress_response([math.nan, 16.15]) == 16.15
    assert stress_response([math.nan] * 6) == 0.0
    assert stress_response([math.inf]) == 0.0


def test_an_empty_stress_has_no_response():
    assert stress_response([]) == 0.0
    assert stress_response(None) == 0.0


def test_non_finite_values_are_counted_across_both_builds():
    assert non_finite_count([math.nan, 1.0], [2.0, math.inf]) == 2
    assert non_finite_count([1.0], [2.0]) == 0


# ---- the outcome vocabulary ---------------------------------------------
def test_a_non_finite_response_is_never_agreement():
    """Even with the comparison claiming agreement, which it once did.

    With no stress arrays recorded the row cannot be attributed to a build, and
    it defaults to the transformed one -- the pessimistic reading about our own
    work rather than about somebody's UMAT.
    """
    outcome, reason = outcome_for(_decided(non_finite_components=6, agreed=True))
    assert outcome == NON_FINITE_RESPONSE
    assert outcome != AGREED and "non-finite" in reason


def test_a_non_finite_response_is_its_own_outcome_not_a_disagreement():
    """Folding it into "disagreed" hides a build that produced nothing usable
    among builds that produced a different answer -- two different findings."""
    assert NON_FINITE_RESPONSE in OUTCOMES
    assert outcome_for(_decided(non_finite_components=1))[0] != DISAGREED


def test_an_all_zero_response_is_not_agreement():
    outcome, reason = outcome_for(_decided(response=False, agreed=True))
    assert outcome == NO_RESPONSE
    assert "agree about nothing measurable" in reason


def test_a_genuine_agreement_still_passes():
    """The guards must not reject the case the gate exists to certify."""
    assert outcome_for(_decided(agreed=True))[0] == AGREED


def test_a_genuine_disagreement_is_still_a_disagreement():
    assert outcome_for(
        _decided(agreed=False, comparison_reason="worst 1.6e-07"))[0] == DISAGREED


# ---- a machine failure is not a finding about a source ------------------
def test_a_build_timeout_is_a_harness_error_not_a_claim_about_the_source():
    """RECONSIDERED did not list the build failures, so a timeout under load
    became a published claim that somebody's UMAT does not build, and every
    later --resume reproduced it verbatim rather than retrying."""
    outcome, reason = outcome_for(_decided(
        built_original=False,
        original_build_reason="TimeoutExpired: gfortran exceeded 900s"))
    assert outcome == HARNESS_ERROR
    assert "retries" in reason


def test_a_real_compiler_error_is_still_a_build_failure():
    """A source that genuinely does not compile is a finding, and stays one."""
    outcome, _ = outcome_for(_decided(
        built_original=False,
        original_build_reason="Error: Symbol 'x' at (1) has no IMPLICIT type"))
    assert outcome != HARNESS_ERROR


def test_the_machine_signatures_are_recognised():
    assert broke_on_the_machine("TimeoutExpired")
    assert broke_on_the_machine("process was Killed")
    assert not broke_on_the_machine("Error: Expected expression at (1)")
    assert not broke_on_the_machine("")


# ---- the report has to be readable by anything that reads JSON ----------
def test_a_non_finite_value_survives_into_the_report_as_valid_json():
    """The NaN is real evidence and must not be dropped -- but json.dumps
    writes it as a bare NaN token that is not JSON. jq and most non-Python
    parsers reject the artifact while Python's own loads accepts it, which is
    why nothing noticed."""
    payload = _json_safe({"stress": [math.nan, math.inf, -math.inf, 1.5]})
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["stress"][3] == 1.5
    assert "nan" in text and "inf" in text


def test_ordinary_numbers_are_untouched():
    assert _json_safe({"a": [1.0, 2.5], "b": {"c": 3}}) == {"a": [1.0, 2.5],
                                                            "b": {"c": 3}}


# ---- which build failed decides what the row is evidence of --------------
def test_both_builds_non_finite_is_not_evidence_against_the_transform():
    """Measured: of the 27 rows the gate first reported as non_finite_response,
    27 had BOTH builds returning NaN and none had only the transformed one.
    A category whose name asserted a transform defect contained no instance
    of one, and it was the largest single block of apparent defects in the
    corpus."""
    from verify_store_offline import BOTH_NON_FINITE

    nan = [float("nan")] * 6
    outcome, reason = outcome_for(_decided(
        non_finite_components=6, stress_original=nan, stress_transformed=nan))
    assert outcome == BOTH_NON_FINITE
    assert "says nothing about the transform" in reason


def test_only_the_transformed_build_failing_is_evidence():
    outcome, reason = outcome_for(_decided(
        non_finite_components=6, stress_original=[1.0] * 6,
        stress_transformed=[float("nan")] * 6))
    assert outcome == NON_FINITE_RESPONSE
    assert "where the original returned finite numbers" in reason


def test_the_original_failing_leaves_no_reference():
    from verify_store_offline import ORIGINAL_NON_FINITE

    outcome, reason = outcome_for(_decided(
        non_finite_components=6, stress_original=[float("nan")] * 6,
        stress_transformed=[1.0] * 6))
    assert outcome == ORIGINAL_NON_FINITE
    assert "no reference" in reason


def test_the_labelled_strings_a_report_writes_are_read_back_the_same_way():
    """Non-finite values are written to JSON as 'nan'/'inf' so the artifact
    parses; a row read back from a previous run must be judged identically."""
    from verify_store_offline import BOTH_NON_FINITE, _has_non_finite

    assert _has_non_finite(["nan", "nan"])
    assert _has_non_finite(["inf"])
    assert not _has_non_finite([1.0, 2.0])
    assert outcome_for(_decided(
        non_finite_components=6, stress_original=["nan"] * 6,
        stress_transformed=["nan"] * 6))[0] == BOTH_NON_FINITE


def test_all_three_are_in_the_outcome_vocabulary():
    from verify_store_offline import BOTH_NON_FINITE, ORIGINAL_NON_FINITE

    for name in (NON_FINITE_RESPONSE, BOTH_NON_FINITE, ORIGINAL_NON_FINITE):
        assert name in OUTCOMES
