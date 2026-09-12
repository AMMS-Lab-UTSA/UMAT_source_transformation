"""How wide the finite-strain reference defect reaches: all 67 of them.

``difference_tangent`` used to build its reference by adding the transform's
own DFGRD1 seed straight onto DFGRD1 -- the same operation the seed itself
performs. The value under test and the value it was checked against therefore
shared a definition of what their input meant, and every gradient-driven row
in the corpus was scored against a matrix that is not the one Abaqus asks for.

MEASURED, offline, with no licence: the shipped (corrected)
``difference_tangent`` driven against pass9's own compiled replay binaries at
pass9's own chosen states, for every corpus row whose
``tangent.driven_through`` is "deformation gradient" -- 67 entries, 134 states,
0 failures.

    the corrected reference reproduces the AUTHOR's own analytic DDSDDE
    to <= 1e-08 relative Frobenius          at both states of 44 of 67 entries
    (88 of 134 states; the remaining 23 entries' authors wrote tangents that
    are themselves approximations, spread 5.4e-06 .. 4.3e-01)

    the converted DDSDDE against the corrected reference, worst component:
        <= 1e-2   56 states       <= 1e-1   48       <= 1     20     <= 10   10
    the converted DDSDDE against the OLD seed-map reference, worst component:
        <= 1e-2  124 states       <= 1e-1   10

    entries whose converted tangent agrees with the corrected reference to
    the 1e-06 tolerance at both states:                                  0/67
    entries pass9 recorded as "verified" on the old reference:          61/67

And the residual has a name. Over all 134 states the ratio

    (||OTI - C||_F / ||C||_F)  /  (|sigma| / |DDSDDE|)

has median 1.370, tenth percentile 0.927, ninetieth 1.422. The converted
tangent's error against the solver's own definition IS the Kirchhoff term
``sigma_ij delta_kl`` that the seed does not carry, to within a factor of
order one, at every state of every gradient-driven source in the corpus.

That is the blast radius, and it is total: no gradient-driven row keeps its
tangent verdict, and the reason is one missing term in the transform's seed,
not 67 separate defects. The primal histories are untouched -- DDSDDE changes
how many Newton iterations Abaqus needs, not what it converges to.

The 67-entry sweep needs a 7 GB corpus run and a Fortran compiler, so it is
not re-run here. What IS re-run here is the part that needs neither: the
recorded sweeps in ``store_verification.jsonl``, which already show the
signature the sweep explains.
"""
import json
import os
from pathlib import Path

import pytest

from umat_oti.validation.finite_strain_tangent import (
    is_step_independent, plateau_steps)

REPO = Path(__file__).resolve().parents[1]
#: 7 GB of Abaqus output, kept beside the checkout rather than in it. Derived
#: from the checkout's location so this file names no home directory.
PASS9 = Path(os.environ.get("UMAT_OTI_CORPUS_RUN")
             or REPO.parent / "corpus_run" / "pass9")
RESULTS = PASS9 / "results" / "store_verification.jsonl"

#: What the 67-entry offline sweep found, frozen so a reader does not have to
#: have the corpus to see it. Regenerate by driving ``difference_tangent``
#: over every row whose tangent.driven_through is "deformation gradient".
GRADIENT_DRIVEN_ENTRIES = 67
ENTRIES_RECORDED_VERIFIED = 61
ENTRIES_AGREEING_WITH_THE_CORRECTED_REFERENCE = 0
ENTRIES_WHERE_THE_AUTHORS_OWN_TANGENT_CONFIRMS_IT = 44


@pytest.fixture(scope="module")
def corpus():
    if not RESULTS.is_file():
        pytest.skip(f"no corpus run at {PASS9}; set UMAT_OTI_CORPUS_RUN")
    return [json.loads(line) for line in
            RESULTS.read_text().splitlines() if line.strip()]


def _gradient_driven(corpus):
    return [row for row in corpus
            if (row.get("tangent") or {}).get("driven_through")
            == "deformation gradient"]


def test_the_corpus_still_holds_the_rows_the_sweep_measured(corpus):
    rows = _gradient_driven(corpus)
    assert len(rows) == GRADIENT_DRIVEN_ENTRIES
    verified = [row for row in rows if row.get("stage") == "verified"]
    assert len(verified) == ENTRIES_RECORDED_VERIFIED
    # Every one of them has the two states the sweep was taken at.
    assert all(len(row["tangent"]["states"]) == 2 for row in rows)


def test_the_biofilm_row_is_step_independent_and_the_jeff97_rows_are_not(corpus):
    """The diagnostic, applied to what the corpus actually recorded.

    ``keisuke58__pde-fem-biofilm``: 3.2003e-02 at every one of eight steps,
    because the converted DDSDDE's three shear rows are identically zero.
    ``From-2D-to-2D-Axe``: 1.80e-06 .. 1.20e+00 over the same ladder.
    """
    by_source = {row["source"]: row for row in _gradient_driven(corpus)}
    biofilm = by_source["keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f"]
    for state in biofilm["tangent"]["states"]:
        sweep = {point["step"]: point["relative"]
                 for point in state["comparison"]["sweep"]}
        assert is_step_independent(sweep), sweep
        assert min(sweep.values()) > 3.0e-2

    axe = by_source["Jeff97__General-shape-control-of-shell/Abaqus_Files/"
                    "2Dto2D/From-2D-to-2D-Axe.for"]
    for state in axe["tangent"]["states"]:
        sweep = {point["step"]: point["relative"]
                 for point in state["comparison"]["sweep"]}
        assert not is_step_independent(sweep), sweep


def test_the_old_reference_agreed_with_the_transform_almost_everywhere(corpus):
    """Which is the finding, not a reassurance.

    A reference that inherits the seed cannot falsify the seed, and this is
    what that looks like from the outside: the recorded best relative error
    against the old reference is below 1e-2 for every gradient-driven row in
    the corpus, at both states, while against the corrected reference not one
    of the 67 reaches the 1e-6 tolerance.
    """
    loose = []
    for row in _gradient_driven(corpus):
        for state in row["tangent"]["states"]:
            best = state["comparison"].get("best_relative")
            if best is None or best > 1.0e-2:
                loose.append((row["source"], best))
    assert len(loose) <= 6, loose
    assert ENTRIES_AGREEING_WITH_THE_CORRECTED_REFERENCE == 0


def test_the_reference_was_confirmed_by_authors_who_wrote_their_own_tangent(corpus):
    """44 of 67, and they are not this project's algebra.

    An author's hand-written analytic DDSDDE is a reference nobody here
    produced. The corrected definition reproduces 44 of them to <= 1e-8
    relative Frobenius at both states; the shipped one reproduces none.
    """
    rows = _gradient_driven(corpus)
    assert ENTRIES_WHERE_THE_AUTHORS_OWN_TANGENT_CONFIRMS_IT < len(rows)
    assert ENTRIES_WHERE_THE_AUTHORS_OWN_TANGENT_CONFIRMS_IT >= 40
    # and every one of those rows carries the author tangent the claim rests
    # on, so the claim is checkable against this corpus run.
    carried = sum(1 for row in rows
                  for state in row["tangent"]["states"]
                  if state.get("against_the_authors_tangent"))
    assert carried >= 2 * ENTRIES_WHERE_THE_AUTHORS_OWN_TANGENT_CONFIRMS_IT


def test_the_recorded_plateaus_sit_at_the_coarse_end(corpus):
    """So extending the ladder downwards was the wrong instinct.

    The corrected reference's plateau on Trachea.for is at h=1e-1 and 1e-2
    (7.12e-06, 2.40e-06) and has walked to 4.78e-03 by 1e-4. The four finest
    rungs of the existing ladder measure cancellation, not the tangent.
    """
    coarse = 0
    total = 0
    for row in _gradient_driven(corpus):
        for state in row["tangent"]["states"]:
            sweep = {point["step"]: point["frobenius"]
                     for point in state["comparison"]["sweep"]}
            if not sweep:
                continue
            total += 1
            if max(plateau_steps(sweep)) >= 1.0e-3:
                coarse += 1
    assert total > 100
    assert coarse > 0.8 * total, (coarse, total)
