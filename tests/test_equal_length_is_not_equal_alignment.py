"""``compare_primal`` pairs two histories with a positional ``zip``.

Its only structural guard is that the two have the same LENGTH. It does not go
through :mod:`umat_oti.abaqus.frames`, which groups by
``(step, increment, element, point)`` so that record i of one build cannot be a
different increment of the other. Two histories can have the same number of
records and still be offset -- an extra step at the front, integration points
emitted in a different order, a record dropped in one place and gained in
another -- and the comparison would report a number just the same.

Measured over pass10: 142 entries have both histories on disk at equal length,
and zero of them are misaligned. So neither
``UMAT_Tissue_2d_plane_strain.f``'s 1.4294492700071145e-06 nor
``From-2D-to-2D-Axe.for``'s 1.920e-04 is an alignment artefact; both survive
the check, and the mechanisms behind them were diagnosed on that footing.

That is a fact about this corpus and not a property of the comparison. These
tests exist so the next pass is not covered by this one's luck.
"""
import json
import os
import pathlib

import pytest

from umat_oti.abaqus.call_isolation import history_misalignments


def test_two_aligned_histories_report_nothing():
    same = [{"step": 1, "increment": 1, "element": 1, "point": 1},
            {"step": 1, "increment": 1, "element": 1, "point": 2}]
    assert history_misalignments(same, list(same)) == []


def test_an_extra_step_at_the_front_is_caught_despite_equal_length():
    """The exact shape that produced a large spurious difference between two
    runs of the SAME material: same record count, different increments."""
    original = [{"step": 1, "increment": i, "element": 1, "point": 1}
                for i in (1, 2, 3)]
    shifted = [{"step": 1, "increment": i, "element": 1, "point": 1}
               for i in (2, 3, 4)]
    assert len(original) == len(shifted)
    off = history_misalignments(original, shifted)
    assert len(off) == 3
    assert off[0] == (0, (1, 1, 1, 1), (1, 2, 1, 1))


def test_points_emitted_in_a_different_order_are_caught():
    """Same increment, same count, different integration point at each slot."""
    a = [{"step": 1, "increment": 1, "element": 1, "point": p} for p in (1, 2)]
    b = [{"step": 1, "increment": 1, "element": 1, "point": p} for p in (2, 1)]
    assert len(history_misalignments(a, b)) == 2


@pytest.mark.integration
def test_no_pass10_entry_is_compared_at_misaligned_records():
    """If this ever fails, every number in that entry's row is meaningless
    and the entry must be re-read, not re-tolerated."""
    root = pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or pathlib.Path.home() / "softwarex_work" / "corpus_run") / "pass10"
    results = root / "results" / "store_verification.jsonl"
    if not results.is_file():
        pytest.skip(f"no pass10 results at {results}")
    checked = 0
    offenders = []
    for line in results.read_text().splitlines():
        record = json.loads(line)
        work = root / "work" / str(record.get("key"))
        left = work / "original" / "original_history.json"
        right = work / "transformed" / "transformed_history.json"
        if not (left.is_file() and right.is_file()):
            continue
        try:
            o, t = json.loads(left.read_text()), json.loads(right.read_text())
        except ValueError:
            continue
        if len(o) != len(t):
            continue          # compare_primal refuses these outright
        checked += 1
        if history_misalignments(o, t):
            offenders.append(record.get("source"))
    if not checked:
        pytest.skip("no pass10 work directories with both histories on disk")
    assert offenders == []


@pytest.mark.integration
def test_not_every_primal_disagreed_entry_carries_a_claim_about_the_routine():
    """28 of pass10's 62 do not, and the code that says so is already here.

    ``compare_primal`` scores the two CONVERGED histories and never asks
    whether the builds were still being handed the same arguments by the time
    they parted. ``isolate_first_divergence`` does ask. Over the 62 it returns
    ``same_inputs_different_outputs`` for 34, ``inputs_already_diverged`` for
    16, and ``no_divergence_in_paired_calls`` -- bit-identical outputs beyond
    rounding at every recorded call -- for 12.

    This test does not pin those counts; they move as the transform and the
    experiments change. It pins the thing that must stay true: the two
    questions are different, and an entry whose probe records show no
    divergence at all is not evidence that the routine disagrees.
    """
    from umat_oti.abaqus.call_isolation import (isolate_first_divergence,
                                                read_pair)
    root = pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or pathlib.Path.home() / "softwarex_work" / "corpus_run") / "pass10"
    results = root / "results" / "store_verification.jsonl"
    if not results.is_file():
        pytest.skip(f"no pass10 results at {results}")
    seen = {}
    for line in results.read_text().splitlines():
        record = json.loads(line)
        if record.get("stage") != "primal_disagreed":
            continue
        work = root / "work" / str(record.get("key"))
        if not (work / "original" / "original_probe.txt").is_file():
            continue
        original, transformed = read_pair(work)
        verdict = isolate_first_divergence(
            original, transformed, require_beyond_rounding=True).verdict
        seen[verdict] = seen.get(verdict, 0) + 1
    if not seen:
        pytest.skip("no pass10 probe records on this machine")
    # The whole point: the stage label does not distinguish these, and it must
    # not be read as though it did.
    assert len(seen) > 1, (
        "every primal_disagreed entry reached the same isolation verdict, so "
        "either the corpus changed shape or the isolation stopped "
        f"discriminating: {seen}")
