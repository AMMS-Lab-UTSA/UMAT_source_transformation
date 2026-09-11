"""A prescribed-displacement deck is the wrong question for some UMATs.

A plate growing under its own weight is driven by a force per unit volume
that a SUBROUTINE DLOAD in the same file computes, and the UMAT reads what
DLOAD wrote through a COMMON block. Prescribe every node's displacement and
DLOAD is never called, the COMMON holds whatever it held, and the routine
returns values that are not numbers at any amplitude the search can reach.

Measured on the twenty-two entries that came back as "both builds went
non-finite": every one carries a SUBROUTINE DLOAD beside its UMAT, and the
amplitude search had already established that the model produces no numbers
from 8e-07 to 1e-04 of strain -- before the fixed 0.005 probe was run anyway
and the result reported as though the two builds disagreed.

Nothing in the replacement experiment is invented. Which components carry
the force, what reference magnitude each takes and which degrees of freedom
are held all come from the author's own deck.
"""
from dataclasses import replace
from pathlib import Path

from umat_oti.abaqus.body_force import (defines_dload, held_directions,
                                        read_loads)
from umat_oti.abaqus.deck import generate_deck
from umat_oti.abaqus.manifest import VerificationManifest, under_body_force

DECK = """\
*Heading
** a cantilever plate under gravity
*Boundary
Plate-1.LeftEnd, 1, 1
Plate-1.LeftEnd, 2, 2
*Boundary
Plate-1.WholeRegion, 3, 3
*Dload
Plate-1.WholeRegion, BXNU, 0.
Plate-1.WholeRegion, BYNU, 1.
*End Step
"""


def test_a_source_that_defines_dload_is_driven_by_a_body_force():
    assert defines_dload("      SUBROUTINE DLOAD(F,KSTEP,KINC,TIME,NOEL,\n")
    assert not defines_dload("      SUBROUTINE UMAT(STRESS,STATEV)\n")
    assert not defines_dload("C     SUBROUTINE DLOAD is described here\n")


def test_the_components_are_read_from_the_author_s_deck(tmp_path: Path):
    deck = tmp_path / "beam.inp"
    deck.write_text(DECK)
    loads = read_loads(deck)
    assert loads.components == (("BXNU", 0.0), ("BYNU", 1.0))
    assert loads.driven == (("BYNU", 1.0),)
    assert "beam.inp" in loads.provenance and "BYNU 1" in loads.provenance


def test_a_uniform_body_force_never_reaches_the_routine(tmp_path: Path):
    """BX takes its magnitude from the deck and does not call DLOAD, so it
    says nothing about how this source is meant to be driven."""
    deck = tmp_path / "u.inp"
    deck.write_text("*Dload\nSet, BY, 9.81\n")
    assert read_loads(deck).components == ()


def test_the_held_directions_are_read_too(tmp_path: Path):
    deck = tmp_path / "beam.inp"
    deck.write_text(DECK)
    assert held_directions(deck) == (1, 2, 3)


def test_no_deck_means_no_invented_force(tmp_path: Path):
    assert read_loads(tmp_path / "absent.inp").found is False
    assert held_directions(tmp_path / "absent.inp") == ()


def _manifest() -> VerificationManifest:
    return VerificationManifest(name="g", source=Path("x.f"), props=(1.0, 2.0),
                                nstatv=4, element_type="C3D8", ntens=6)


def test_the_deck_holds_only_the_face_the_author_holds():
    segment = under_body_force((("BXNU", 0.0), ("BYNU", 1.0)), held=(1, 2, 3))
    text = generate_deck(replace(_manifest(), loading=(segment,)))
    body = text[text.index("*BOUNDARY"):text.index("*OUTPUT")]
    # The x = 0 face is held in 1, 2 and 3; every other node only in 3, which
    # is the plane-strain condition rather than a support.
    assert "1, 1, 1, 0.0" in body and "1, 2, 2, 0.0" in body
    assert "2, 1, 1," not in body, "the free face must be free to move in x"
    assert "2, 3, 3, 0.0" in body


def test_the_deck_applies_the_author_s_own_reference_magnitudes():
    segment = under_body_force((("BXNU", 0.0), ("BYNU", 1.0)), held=(1, 2, 3))
    text = generate_deck(replace(_manifest(), loading=(segment,)))
    assert "*DLOAD, OP=NEW" in text
    assert "ONE, BXNU, 0.0" in text
    assert "ONE, BYNU, 1.0" in text


def test_a_body_force_segment_prescribes_no_strain():
    segment = under_body_force((("BYNU", 1.0),))
    assert segment.strain == (0.0,) * 6
    assert segment.body_force == (("BYNU", 1.0),)


def test_the_ordinary_deck_is_unchanged():
    """Every other UMAT in the corpus is still driven by displacement."""
    from umat_oti.abaqus.manifest import uniaxial
    text = generate_deck(replace(_manifest(), loading=(uniaxial(0.01, 4),)))
    assert "*DLOAD" not in text
    # every node prescribed, which is what makes the strain history known
    assert text.count(", 1, 1, ") == 8


def test_the_verifier_reaches_for_it_only_after_the_search_refuses():
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    block = text[text.index("if found.outcome == LEFT_ITS_DOMAIN:"):]
    block = block[:block.index("amplitude = manifest.loading[0].strain[0]")]
    assert "body_force_loading(" in block, (
        "a source with no experiment should be offered the one its author "
        "published before it is given up on")


def test_a_refusal_still_names_what_was_missing():
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    assert "names no non-uniform body-force" in text
    assert "no deck is paired with it" in text


# ---------------------------------------------------------------------------
# and both builds have to walk the same increments
# ---------------------------------------------------------------------------
def test_a_load_controlled_step_keeps_its_automatic_incrementation():
    """Fixing the increment was tried, and the measurement refused it.

    The two builds do walk different increments -- ten for the original and
    sixteen for the converted build on BodyForce-Growth-2Stages.for, because
    the converted routine returns the OTI tangent rather than the author's
    analytic DDSDDE and Newton converges at a different rate. *STATIC, DIRECT
    removes the solver's freedom to choose, so both would walk the same ones.

    It cannot be used. Measured on that same model, the ORIGINAL then stops:

        ***ERROR: FIXED TIME INCREMENT IS TOO LARGE
        1  7  1  0  16  16  0.150  0.150  0.02500
        THE ANALYSIS HAS NOT BEEN COMPLETED

    Its stiffness changes along the path and it needs the cutbacks it was
    denied -- at a quarter of the increment size, not only at the original's
    own. A fixed size small enough for both is a number nothing measured, so
    the histories are paired by time instead. See align_by_time.
    """
    segment = under_body_force((("BYNU", 1.0),), held=(1, 2, 3))
    text = generate_deck(replace(_manifest(), loading=(segment,)))
    assert "*STATIC, DIRECT" not in text
    assert "*STATIC" in text


def test_the_displacement_steps_keep_their_automatic_incrementation():
    """The eighty-six entries that verify walk identical increments already;
    changing their experiment would be a change with no finding behind it."""
    from umat_oti.abaqus.manifest import uniaxial
    text = generate_deck(replace(_manifest(), loading=(uniaxial(0.01, 4),)))
    assert "*STATIC, DIRECT" not in text
    assert "*STATIC" in text
