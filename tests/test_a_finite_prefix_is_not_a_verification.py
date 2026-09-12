"""A finite prefix is what discovery learns from. It is not a result.

A run that produces good increments and then returns values that are not
numbers has told the search where the edge of this material's numerical
domain is. That is what a search is for, and the prefix should be used.

What it must not do is carry a verdict. A UMAT marked fully_verified on a
history that later becomes non-finite has been verified on a truncated
failed analysis: the comparison drops everything after the break, and the
frozen regression fixture inherits a deck that does not run to completion, so
every future replay begins by reproducing a failure.

Measured on BodyForce-Growth-2Stages.for: 280 records, non-finite from record
23, primal agreement to 1.16e-11 over the first 22 -- and a verdict of
"verified". The prefix was real evidence and the verdict was not earned.

Three things are kept apart here on purpose, because collapsing them is how
the truncated history became a verdict:

* discovery_usable_prefix -- how far a run got, and where the edge is;
* safe_loading_reconstructed -- the loading rebuilt to stop short of it;
* complete_finite_verification_run -- a rerun that finished with nothing
  non-finite anywhere. Only this one may be verified on.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from umat_oti.abaqus.manifest import simple_shear, uniaxial
from umat_oti.abaqus.safe_loading import (CHECKED, MARGIN, REBUILDS, examine,
                                          reconstruct)

TOOL = (pathlib.Path(__file__).resolve().parents[1]
        / "tools" / "verify_store_in_abaqus.py").read_text()


def _history(good_increments: int, points: int = 8, bad_points: int = 0):
    """A run of whole increments, optionally breaking part way through one.

    Every record carries the element and integration point it belongs to: a
    count of records is not a count of increments, and the grouping depends
    on being told which point each record is.
    """
    records = []
    for increment in range(1, good_increments + 1):
        for point in range(1, points + 1):
            records.append({"step": 1, "increment": increment, "element": 1,
                            "point": point, "time": increment * 0.1,
                            "STRESS": [1.0], "STATEV": [0.0], "DDSDDE": [1.0]})
    for point in range(1, bad_points + 1):
        records.append({"step": 1, "increment": good_increments + 1,
                        "element": 1, "point": point,
                        "time": (good_increments + 1) * 0.1,
                        "STRESS": [float("nan") if point == bad_points else 1.0],
                        "STATEV": [0.0], "DDSDDE": [1.0]})
    return records


# ---- the prefix is read, and read honestly -------------------------------
def test_a_run_that_is_finite_throughout_is_complete():
    prefix = examine(_history(10), expected_points=8)
    assert prefix.complete is True
    assert prefix.usable == 10, "ten increments, not eighty records"
    assert prefix.records == 80
    assert "is a verification and not only a probe" in prefix.reason()


def test_a_run_that_breaks_is_not_complete_however_long_its_prefix():
    prefix = examine(_history(2, bad_points=7), expected_points=8)
    assert prefix.complete is False
    assert prefix.usable == 2, "two complete increments, not sixteen records"
    assert prefix.records == 23
    assert "not where the comparison has to start ignoring it" in prefix.reason()


def test_a_partly_broken_increment_is_not_a_safe_increment():
    """An element has a record per integration point. An increment whose
    seventh point returned NaN is not safe because its first six did -- the
    solver's answer for that increment is already contaminated."""
    prefix = examine(_history(2, bad_points=7), expected_points=8)
    assert prefix.first_bad == (1, 3)
    assert prefix.last_safe == (1, 2), (
        "the bound must be the last increment every record of which is finite")


def test_a_tangent_that_is_not_finite_counts_too():
    assert "DDSDDE" in CHECKED
    records = _history(1)
    records[-1]["DDSDDE"] = [float("nan")]
    assert examine(records, expected_points=8).complete is False


# ---- and it is used to rebuild, not to excuse ----------------------------
def test_the_prefix_rebuilds_a_loading_that_stops_short_of_the_edge():
    prefix = examine(_history(2, bad_points=7), expected_points=8)
    rebuilt = reconstruct(prefix, 0.04, [uniaxial(0.04, 10), simple_shear(0.04, 10)])
    assert rebuilt.possible
    # two of ten increments were proved safe, and the margin puts the
    # endpoint below that rather than against it
    assert rebuilt.amplitude == 0.04 * 0.2 * MARGIN
    assert rebuilt.amplitude < 0.04
    assert "proved safe" in rebuilt.reason


def test_the_margin_puts_the_endpoint_outside_the_measured_bracket():
    """The run brackets the edge between the last finite increment and the
    first that is not -- one increment, a tenth of the segment. Ending at the
    last safe increment sits on the near edge of that bracket."""
    assert 0.0 < MARGIN < 1.0
    prefix = examine(_history(2, bad_points=7), expected_points=8)
    rebuilt = reconstruct(prefix, 0.04, [uniaxial(0.04, 10)])
    at_the_edge = 0.04 * 0.2
    assert rebuilt.amplitude < at_the_edge


def test_a_run_that_broke_in_its_first_increment_cannot_be_rebuilt_from():
    prefix = examine(_history(0, bad_points=3), expected_points=8)
    rebuilt = reconstruct(prefix, 0.04, [uniaxial(0.04, 10)])
    assert not rebuilt.possible
    assert "before completing a single increment" in rebuilt.reason


def test_breaking_after_the_first_segment_scales_the_whole_amplitude():
    """A shear, a reversal and a hold all run at the peak the first segment
    reached, so breaking in one of them says the amplitude is too large."""
    records = _history(10)
    records += [{"step": 2, "increment": 1, "element": 1, "point": point,
                 "STRESS": [float("nan")], "STATEV": [], "DDSDDE": []}
                for point in range(1, 9)]
    prefix = examine(records, expected_points=8)
    rebuilt = reconstruct(prefix, 0.04, [uniaxial(0.04, 10), simple_shear(0.04, 10)])
    assert rebuilt.amplitude == 0.04 * MARGIN


def test_a_complete_run_is_not_rebuilt():
    rebuilt = reconstruct(examine(_history(10), expected_points=8), 0.04,
                          [uniaxial(0.04, 10)])
    assert not rebuilt.possible
    assert "already finite throughout" in rebuilt.reason


# ---- and the verdict is gated on the rerun, not on the prefix ------------
def test_the_verifier_refuses_a_verdict_on_a_history_that_is_not_finite():
    assert 'grouping.get("both_finite_throughout")' in TOOL
    assert "may be frozen on" in TOOL
    assert "is not finite " in TOOL and "throughout" in TOOL


def test_the_three_concepts_are_recorded_separately():
    for name in ("discovery_usable_prefix", "safe_loading_reconstructed",
                 "complete_finite_verification_run"):
        assert f'record["{name}"]' in TOOL, name


def test_discovery_reruns_the_whole_loading_before_handing_it_on():
    assert "settle_on_safe_loading(" in TOOL
    block = TOOL[TOOL.index("def settle_on_safe_loading("):]
    block = block[:block.index("def _rescaled(")]
    assert 'job="original"' in block, (
        "the rebuilt loading must be proved on the ORIGINAL; consulting the "
        "converted build would be choosing a loading to agree")
    assert "prefix.complete" in block, (
        "completion of the job is not enough -- every record has to be finite")
    assert f"safe_loading.REBUILDS" in block


def test_the_rebuild_gives_up_rather_than_shrinking_for_ever():
    assert REBUILDS >= 1
    assert "left its domain inside every one of them" in TOOL


def test_rescaling_keeps_the_shape_of_the_path():
    from umat_oti.abaqus.manifest import reverse
    original = [uniaxial(0.04, 10), simple_shear(0.04, 10)]
    original.append(reverse(original[0]))
    scaled = [type(s)(**{**s.__dict__,
                         "strain": tuple(v * 0.16 for v in s.strain)})
              for s in original]
    for before, after in zip(original, scaled):
        assert after.name == before.name
        assert after.increments == before.increments
        assert after.period == before.period
        for b, a in zip(before.strain, after.strain):
            assert math.isclose(a, b * 0.16, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# and the repair is chosen from what the failure responds to
# ---------------------------------------------------------------------------
def test_a_failure_that_moves_with_the_amplitude_is_amplitude_limited():
    from umat_oti.abaqus.safe_loading import AMPLITUDE_LIMITED, classify

    mechanism = classify([
        {"varied": "amplitude", "value": 0.04, "reached": 0.2, "step": 1},
        {"varied": "amplitude", "value": 0.02, "reached": 0.9, "step": 1}])
    assert mechanism.kind == AMPLITUDE_LIMITED
    assert "moved with amplitude" in mechanism.reason


def test_a_failure_that_moves_with_the_step_size_is_resolution_limited():
    from umat_oti.abaqus.safe_loading import (INCREMENT_RESOLUTION_LIMITED,
                                              classify)

    mechanism = classify([
        {"varied": "amplitude", "value": 0.04, "reached": 0.2, "step": 1},
        {"varied": "amplitude", "value": 0.02, "reached": 0.2, "step": 1},
        {"varied": "increments", "value": 10, "reached": 0.2, "step": 1},
        {"varied": "increments", "value": 40, "reached": 0.9, "step": 1}])
    assert mechanism.kind == INCREMENT_RESOLUTION_LIMITED
    assert "amplitude did not move it" in mechanism.reason


def test_a_failure_that_moves_with_nothing_is_not_repaired_by_shrinking():
    """The measured trap. If the break does not move when the amplitude is
    halved, the amplitude does not control it, and halving it again is the
    same experiment driven less far and failing in the same place."""
    from umat_oti.abaqus.safe_loading import UNKNOWN_DOMAIN_FAILURE, classify

    mechanism = classify([
        {"varied": "amplitude", "value": 0.04, "reached": 0.2, "step": 0},
        {"varied": "amplitude", "value": 0.01, "reached": 0.2, "step": 0}])
    assert mechanism.kind == UNKNOWN_DOMAIN_FAILURE
    assert "shrinking the amplitude again" in mechanism.reason


def test_the_repair_probes_before_it_changes_anything():
    block = TOOL[TOOL.index("def settle_on_safe_loading("):]
    block = block[:block.index("def _refined(")]
    assert '"varied": "amplitude"' in block and '"varied": "increments"' in block
    assert "safe_loading.classify(probes)" in block
    assert "INCREMENT_RESOLUTION_LIMITED" in block, (
        "a resolution-limited failure must be refined, not shrunk -- "
        "shrinking removes the behaviour the experiment exists to exercise")


def test_an_unrepairable_failure_is_not_silently_shrunk():
    block = TOOL[TOOL.index("def settle_on_safe_loading("):]
    block = block[:block.index("def _refined(")]
    assert "the repair is not an amplitude" in block


def test_the_margin_is_a_proposal_that_a_rerun_has_to_confirm():
    import pathlib as _p
    source = _p.Path(__file__).resolve().parents[1].joinpath(
        "src", "umat_oti", "abaqus", "safe_loading.py").read_text()
    assert "FIRST PROPOSAL" in source
    assert "not a proof of safety" in source.lower()
    block = TOOL[TOOL.index("def settle_on_safe_loading("):]
    block = block[:block.index("def _refined(")]
    assert "safety_distance" in block, (
        "the distance between the endpoint settled on and the failure "
        "observed has to be recorded, not assumed")


def test_refining_keeps_the_amplitude_and_multiplies_the_increments():
    import pathlib as _p, re
    source = _p.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    block = source[source.index("def _refined("):]
    block = block[:block.index("\n\n", block.index("return [replace("))]
    assert "increments=max(1, int(segment.increments) * factor)" in block
    assert "strain" not in block, "refining must not touch the amplitude"


def test_abaqus_completing_is_recorded_apart_from_the_history_being_finite():
    """Abaqus prints THE ANALYSIS HAS COMPLETED SUCCESSFULLY about the
    solver, not about the routine it called. Measured on
    BodyForce-Growth-2Stages.for: both builds "completed" thirty-five
    increments and both were non-finite from the third."""
    block = TOOL[TOOL.index('record["evidence"] = {'):]
    block = block[:block.index('record["complete_finite_verification_run"]')]
    for name in ("abaqus_job_completed", "all_requested_outputs_present",
                 "complete_history_finite", "primal_agreed",
                 "derivatives_verified"):
        assert f'"{name}"' in block, name
    assert '"complete_history_finite": bool(grouping.get(' in block
    assert '"derivatives_verified"] = bool(' in TOOL, (
        "the tangent has to set its own flag where it is decided")


# ---------------------------------------------------------------------------
# a fraction of the path, not a count of increments
# ---------------------------------------------------------------------------
def test_refining_the_resolution_does_not_look_like_a_moved_failure():
    """Measured trap. Refining fourfold turns "broke after 22 of 40
    increments" into "broke after 88 of 160" -- both 55% of the same path.
    Comparing the COUNTS called it increment-resolution-limited and sent the
    repair to refine a path whose breaking point had not shifted by a single
    increment of real loading."""
    from umat_oti.abaqus.safe_loading import PATH_SEGMENT_LIMITED, classify

    mechanism = classify([
        {"varied": "amplitude", "value": 0.04, "reached": 22 / 40, "step": 3},
        {"varied": "amplitude", "value": 0.02, "reached": 22 / 40, "step": 3},
        {"varied": "increments", "value": 40, "reached": 22 / 40, "step": 3},
        {"varied": "increments", "value": 160, "reached": 88 / 160, "step": 3}])
    assert mechanism.kind == PATH_SEGMENT_LIMITED
    assert "same place along the path" in mechanism.reason
    assert "it is that SEGMENT the model will not do" in mechanism.reason


def test_a_genuinely_resolution_limited_failure_is_still_caught():
    from umat_oti.abaqus.safe_loading import (INCREMENT_RESOLUTION_LIMITED,
                                              classify)

    mechanism = classify([
        {"varied": "amplitude", "value": 0.04, "reached": 0.2, "step": 1},
        {"varied": "amplitude", "value": 0.02, "reached": 0.2, "step": 1},
        {"varied": "increments", "value": 40, "reached": 0.2, "step": 1},
        {"varied": "increments", "value": 160, "reached": 0.9, "step": 1}])
    assert mechanism.kind == INCREMENT_RESOLUTION_LIMITED


def test_a_rounding_is_not_a_moved_failure():
    from umat_oti.abaqus.safe_loading import SAME_PLACE, classify

    assert 0.0 < SAME_PLACE < 0.05
    mechanism = classify([
        {"varied": "amplitude", "value": 0.04, "reached": 0.550, "step": 2},
        {"varied": "amplitude", "value": 0.02, "reached": 0.554, "step": 2}])
    assert mechanism.kind != "amplitude_limited"


def test_a_dropped_segment_says_which_behaviour_was_given_up():
    """An experiment that stopped testing reversal must not be reported as
    though it still did."""
    block = TOOL[TOOL.index("def _shortened("):]
    block = block[:block.index("def _refined(")]
    assert "no longer exercises that path" in block
    assert "less far" in block, (
        "shortening is preferred to dropping: the path should still go that "
        "way where the model will go there at all")


def test_the_probes_report_a_fraction_of_the_path():
    block = TOOL[TOOL.index("def settle_on_safe_loading("):]
    block = block[:block.index("def _shortened(")]
    assert '"reached": reached' in block
    assert "prefix.usable / total" in block, (
        "how far a run got has to be a fraction of the path it was given")


# ---------------------------------------------------------------------------
# "not truncated" and "finite" are different facts
# ---------------------------------------------------------------------------
def test_two_builds_that_parted_company_are_not_a_finite_pair():
    """common_finite_prefix returns -1 for TWO different reasons: both
    histories are finite, or the two parted company at different increments
    and no truncation could be applied. Reading the verdict off that flag
    reported complete_finite_verification_run = True for ten HelixUp entries
    whose ORIGINAL build carries NaN in all six stresses of 72 of its 80
    records -- while original.sta said THE ANALYSIS HAS COMPLETED
    SUCCESSFULLY.
    """
    import verify_store_in_abaqus as verify

    def rec(increment, value):
        return {"step": 1, "increment": increment, "element": 1, "point": 1,
                "STRESS": [value], "STATEV": [0.0]}

    whole = [rec(n, 1.0) for n in range(1, 6)]
    broken = [rec(1, 1.0)] + [rec(n, float("nan")) for n in range(2, 6)]

    _l, _r, stopped, grouping = verify.common_finite_prefix(whole, broken)
    assert stopped == -1, "they parted company, so nothing was truncated"
    assert grouping["both_finite_throughout"] is False, (
        "and that is not the same as being finite")

    _l, _r, stopped, grouping = verify.common_finite_prefix(whole, list(whole))
    assert stopped == -1 and grouping["both_finite_throughout"] is True


def test_the_verdict_reads_finiteness_and_not_the_truncation_flag():
    assert 'grouping.get("both_finite_throughout")' in TOOL
    block = TOOL[TOOL.index('record["complete_finite_verification_run"] ='):]
    block = block[:block.index("\n\n")]
    assert "stopped_at" not in block
