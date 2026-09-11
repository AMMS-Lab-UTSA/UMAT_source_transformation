"""A search that looked in one direction cannot report the whole answer.

The amplitude search starts at 1e-4 and steps DOWN when that returns values
that are not numbers, on the reasoning that a model whose smallest probe
already fails has a domain that does not reach it. That reasoning is sound
and it is not complete: a model can be ill-posed at a strain too small to
move it and perfectly well behaved at one that does.

Measured on sixteen BodyForce-Growth-2Stages entries. The search reported

    the model produced no numbers at any amplitude from 8e-07 to 0.0001;
    there is no loading here this harness can drive it at

and the same model then ran twenty-two increments at 0.005 with no non-finite
value in either build, a primal agreement of 1.16e-11 and a tangent verified
at two smooth states. The verification had reached that amplitude only by
falling back to a fixed probe after the search gave up -- luck, not a
search. Take the fallback away, as honesty about the refusal requires, and
sixteen real verifications go with it.
"""
from umat_oti.abaqus.amplitude_search import (ACTIVATED, CEILING,
                                              LEFT_ITS_DOMAIN,
                                              LINEAR_TO_THE_CEILING,
                                              search_amplitude)




def _increments(count: int, value: float = 1.0, bad: bool = False):
    """``count`` whole increments of one material point each.

    A count of records is not a count of increments, so a history has to say
    which increment and which point each record belongs to. One point per
    increment here, so the two counts coincide and these fixtures stay
    readable.
    """
    return [{"step": 1, "increment": number, "element": 1, "point": 1,
             "time": number * 0.1,
             "STRESS": [float("nan") if bad else value], "STATEV": [0.0]}
            for number in range(1, count + 1)]


def _nan_below(threshold: float):
    """A model that returns NaN below ``threshold`` and is linear above it."""
    tried: list = []

    def run(amplitude: float):
        tried.append(amplitude)
        if amplitude < threshold:
            return True, _increments(6, bad=True), ""
        return True, _increments(6, amplitude * 1000.0), ""

    return run, tried


def test_the_search_climbs_when_the_descent_finds_nothing():
    run, tried = _nan_below(1e-3)
    result = search_amplitude(run)
    assert result.outcome != LEFT_ITS_DOMAIN, result.reason
    assert max(tried) > 1e-3, "the search never looked above where it started"
    assert result.amplitude > 0.0


def test_the_descent_is_still_tried_first():
    """It is the cheapest thing to try and it is often right."""
    run, tried = _nan_below(1e-3)
    search_amplitude(run)
    assert tried[0] == 1e-4
    assert tried[1] < tried[0], "down before up"


def test_the_loading_this_harness_was_given_is_tried_before_it_gives_up():
    """The search climbs by fives from its own 1e-4, so a viable window
    narrower than a factor of five falls between two of its steps -- and the
    amplitude the manifest declares is not one of them.

    Measured on sixteen BodyForce-Growth-2Stages entries: NaN at 2.5e-03 and
    at 1.25e-02, and twenty-two finite increments at the declared 0.005 that
    sits between them, agreeing to 1.16e-11 with a tangent verified at two
    smooth states. Those verifications were real; reaching them by falling
    back to a fixed probe after the search gave up was not a search.
    """
    seen: list = []

    def coarse(amplitude: float):
        return True, _increments(6, bad=True), ""

    def fine(amplitude: float):
        seen.append(amplitude)
        if 0.004 < amplitude < 0.006:
            return True, _increments(6), ""
        return True, _increments(6, bad=True), ""

    result = search_amplitude(coarse, run_fine=fine, declared=0.005)
    assert 0.005 in seen, "the declared amplitude was never tried"
    assert result.amplitude == 0.005
    # and the caller reads a non-zero amplitude as an amplitude to use
    assert result.amplitude != 0.0


def test_the_declared_amplitude_is_only_reached_after_the_search_fails():
    """It is a last resort, not a shortcut past the search."""
    seen: list = []

    def run(amplitude: float):
        seen.append(amplitude)
        return True, [{"STRESS": [amplitude * 1000.0], "STATEV": [0.0]}], ""

    search_amplitude(run, run_fine=run, declared=0.005)
    assert seen[0] == 1e-4, "the search still starts where it starts"


def test_a_model_with_no_domain_anywhere_still_says_so():
    def run(amplitude: float):
        return True, _increments(6, bad=True), ""

    result = search_amplitude(run, run_fine=run, declared=0.005)
    assert result.outcome == LEFT_ITS_DOMAIN
    assert "downward" in result.reason and "upward" in result.reason
    assert result.amplitude == 0.0


def test_the_refusal_names_the_whole_range_it_searched():
    def run(amplitude: float):
        return True, _increments(6, bad=True), ""

    reason = search_amplitude(run).reason
    assert f"{CEILING:.3g}" in reason, (
        "a refusal has to say how far up it looked, not only how far down")


def test_a_model_that_answers_the_first_probe_is_unaffected():
    def run(amplitude: float):
        return True, _increments(6, amplitude * 1000.0), ""

    result = search_amplitude(run)
    assert result.outcome == LINEAR_TO_THE_CEILING
    assert result.amplitude > 0.0


def test_the_climb_stops_at_the_ceiling():
    run, tried = _nan_below(1e6)
    result = search_amplitude(run)
    assert result.outcome == LEFT_ITS_DOMAIN
    assert max(tried) <= CEILING


def test_activation_above_the_dead_zone_is_still_found():
    tried: list = []

    def run(amplitude: float):
        tried.append(amplitude)
        if amplitude < 1e-3:
            return True, _increments(6, bad=True), ""
        moved = 1.0 if amplitude > 5e-3 else 0.0
        history = _increments(6, amplitude * 1000.0)
        history[-1]["STATEV"] = [moved]
        return True, history, ""

    result = search_amplitude(run)
    assert result.outcome in (ACTIVATED, LINEAR_TO_THE_CEILING)
    assert max(tried) > 5e-3


# ---------------------------------------------------------------------------
# and a non-finite tail bounds the escalation without discarding the history
# ---------------------------------------------------------------------------
def test_an_amplitude_that_produced_a_history_is_kept():
    """The footing search and the escalation have to agree about what counts.

    A run of 240 records that is finite through 22 IS a history: the
    verification truncates at the first non-finite record and compares what
    came before, which on BodyForce-Growth-2Stages.for meant 22 increments
    agreeing to 1.16e-11 with the tangent confirmed at two smooth states.
    The footing search accepts such a run. The escalation used to reject it
    and hand back an amplitude of zero for a model it had just driven
    successfully -- and the caller then fell back to a fixed probe, which is
    how those verifications were being reached at all.
    """
    def run(amplitude: float):
        good = _increments(22, amplitude * 1000.0)
        return True, good + [{"step": 1, "increment": 23, "element": 1,
                              "point": 1, "STRESS": [float("nan")],
                              "STATEV": []}], ""

    result = search_amplitude(run)
    assert result.outcome == LEFT_ITS_DOMAIN, "the tail still bounds the climb"
    assert result.amplitude == 1e-4, "but the amplitude that ran is kept"
    assert "are a history" in result.reason


def test_climbing_past_the_tail_was_tried_and_measured_worse():
    """A larger amplitude with a long enough prefix SOUNDS better -- it
    reaches further into the material. It was implemented and reverted.

    Measured on BodyForce-Growth-2Stages.for, whose usable prefix is
    twenty-two increments at every amplitude because the break is driven by
    its own stage switch and not by the loading: the climb ran to the
    ceiling, drove the model at 31% strain, and turned a tangent one smooth
    state short of coverage into a primal disagreement of 3.35e-08.
    """
    def run(amplitude: float):
        return True, (_increments(22, amplitude * 1000.0)
                      + [{"step": 1, "increment": 23, "element": 1,
                          "point": 1, "STRESS": [float("nan")],
                          "STATEV": []}]), ""

    result = search_amplitude(run)
    assert result.outcome == LEFT_ITS_DOMAIN
    assert result.amplitude == 1e-4, "the tail bounds the climb"
    assert "are a history" in result.reason, "and the amplitude is still kept"


def test_a_run_that_broke_too_early_still_falls_back():
    """Two finite records is not a history, and must not be kept as one."""
    def run(amplitude: float):
        good = _increments(2, amplitude * 1000.0)
        return True, good + [{"step": 1, "increment": 3, "element": 1,
                              "point": 1, "STRESS": [float("nan")],
                              "STATEV": []}], ""

    result = search_amplitude(run)
    assert result.outcome == LEFT_ITS_DOMAIN
    assert result.amplitude == 0.0
    # It never reaches the escalation: no amplitude anywhere leaves enough
    # finite records to be a footing, so the refusal is the whole-range one.
    assert "searched downward" in result.reason
    assert "upward to the ceiling" in result.reason
