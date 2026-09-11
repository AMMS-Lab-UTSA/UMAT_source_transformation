"""An amplitude the model cannot be driven to is not an amplitude it reached.

The resolution ladder raises the amplitude until a run succeeds, and it
adopted any amplitude whose job "ran". A job that returns NaN at its fourth
increment runs: Abaqus writes the history and exits. Adopting that amplitude
hands the verification a path the model has already left -- and the amplitude
search itself rejects exactly such a run, so this is the same test applied in
the one place that was not applying it.

Deliberately NOT extended into "raising the amplitude must change the
response". Measured across the corpus: 121 entries took the resolution
extension and 61 of the 64 verified ones are among them, 31 of those with a
stress that barely moves across the amplitudes tried. The perturbation a
finite difference takes is relative to the strain increment, so a larger
amplitude buys resolution even where the TOTAL stress is set by time and
internal state rather than by the boundary -- refusing to escalate on that
evidence would have withdrawn verifications that stand.
"""
from umat_oti.abaqus.amplitude_search import Attempt, first_non_finite


def test_a_run_that_returned_nan_is_not_a_run_that_ran():
    records = [{"STRESS": [1.0, 2.0], "STATEV": [0.0]},
               {"STRESS": [1.0, 2.0], "STATEV": [0.0]},
               {"STRESS": [float("nan"), 2.0], "STATEV": [0.0]}]
    assert first_non_finite(records) == 3
    assert first_non_finite(records[:2]) is None


def test_a_state_that_returned_nan_counts_too():
    assert first_non_finite([{"STRESS": [1.0], "STATEV": [float("inf")]}]) == 1


def test_a_value_that_is_not_a_number_at_all_counts_too():
    assert first_non_finite([{"STRESS": ["-"], "STATEV": []}]) == 1


def test_an_empty_history_has_nothing_wrong_with_it():
    assert first_non_finite([]) is None
    assert first_non_finite([{"STRESS": [], "STATEV": []}]) is None


def test_the_extension_applies_that_test_before_adopting_an_amplitude():
    import ast
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    names = {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)}
    assert "first_non_finite" in names, (
        "the extension still adopts an amplitude on 'the job ran' alone")
    # and it is applied to the extension's own run, not only the search's
    block = text[text.index("ladder = RESOLUTION_FACTORS"):]
    block = block[:block.index("record[\"chosen_amplitude\"]")]
    assert "first_non_finite(_records)" in block


def test_the_extension_proves_itself_at_the_resolution_it_decides_for():
    """A coarse path can reach a strain a fine one cannot.

    The search walks coarsely on purpose -- four increments per segment
    answer "did anything happen?" as well as thirty, and every step is a real
    Abaqus job. But what the EXTENSION decides is the amplitude the
    verification runs at. Measured on Growth-Alex.for: 0.01 completed at
    three increments per segment, was adopted on that evidence, and the
    verification at ten put 2800 of 3990 compared values past the end of the
    model's domain -- reported as a primal disagreement.
    """
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    block = text[text.index("ladder = RESOLUTION_FACTORS"):]
    block = block[:block.index("record[\"chosen_amplitude\"]")]
    assert "run_at(wanted, steps=increments)" in block, (
        "the extension is still validated on the search's coarse path")
    # the search itself keeps its discount
    search = text[text.index("found = search_amplitude(") - 200:
                  text.index("found = search_amplitude(") + 80]
    assert "steps=" not in search.split("search_amplitude(")[1]


def test_an_attempt_records_what_it_was_asked_and_what_happened():
    attempt = Attempt(amplitude=1e-3, ran=True, largest_stress=42.0)
    assert attempt.as_dict()["amplitude"] == 1e-3
    assert attempt.activated is False
