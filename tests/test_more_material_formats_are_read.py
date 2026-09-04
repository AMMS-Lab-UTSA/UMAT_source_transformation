"""Constants an author did publish must not be reported as constants missing.

Seven corpus entries were sitting at ``needs_material_data`` -- "no published
material constants are paired with this source" -- while their own repository
shipped a deck with the numbers in it. Three separate defects put them there,
and each one is pinned by tests below:

1. The pairing rejected on state variables and blamed constants. UEL8_PCLK and
   UEL9_PCLK read ``PROPS(1..6)``; ``UNIUSER_CLA_KIN.inp`` declares
   ``CONSTANTS=6`` and gives six values. The rejection came from the *Depvar
   arm -- the deck declares 14 where inference reads 20 off the source -- and
   the recorded reason said the deck supplied too few constants, which was
   false. The state-variable count is now resolved as the larger of the two,
   the way :func:`build_validation_workspace` has always resolved it, and a
   refusal names the arm that actually refused.

2. ``*UEL PROPERTY`` was never read. Fifteen decks in jgomezc1/ABAQUS-US and
   HIT-FSW-314/abaqus publish their constant vector under that keyword and
   nothing else, and the parser had no path for it at all.

3. NPROPS was inferred per file. hamza-djeloud/plate_with_notch holds a UEL
   that reads ``PROPS(1..4)`` and a UMAT that reads ``PROPS(1..2)``; the
   file-wide maximum of 4 was checked against a deck whose ``*User Material,
   constants=2`` supplies exactly what the UMAT reads.

What breaks if any of this regresses: those entries go back to claiming their
authors published no constants. The opposite failure is worse and is pinned
too -- a deck that genuinely supplies too few constants is still refused, and a
repository that ships no deck still yields nothing.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from umat_oti.assist.deck_pairing import (
    check_pairing, expected_counts_for_routine, pair_source_with_deck,
)
from umat_oti.corpus.abaqus_deck import parse_deck
from umat_oti.assist.proposals import Verdict

CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
             or Path.home() / "softwarex_work" / "discovery_cache")


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _cached(relative: str) -> Path:
    path = CACHE / relative
    if not path.is_file():
        pytest.skip(f"{relative} is not in this discovery cache")
    return path


# --------------------------------------------------------------------------
# (2) *UEL PROPERTY is a published constant vector
# --------------------------------------------------------------------------

def test_a_uel_property_vector_is_read(tmp_path: Path):
    """A UEL's constants live under ``*UEL PROPERTY``, never ``*Material``.

    Regression guard: with no path for this keyword the parser returned an
    empty list for UNIUSER_COS_KIN.inp and every deck like it, and the pairing
    then reported that the repository published no constants.
    """
    deck = _write(tmp_path, "uel.inp", """\
*USER ELEMENT,NODES=8,TYPE=U1,PROPERTIES=8,COORDINATES=2,VARIABLES=307
 1,2,6
*ELEMENT,TYPE=U1, ELSET=TODOS
 1,1,2,3,4,5,6,7,8
*UEL PROPERTY,ELSET=TODOS
42.34E3,0.34,0.005,90000.0,21.77,15.542,383.3,6227.4
""")
    (block,) = parse_deck(deck)
    assert block.props == [42340.0, 0.34, 0.005, 90000.0,
                           21.77, 15.542, 383.3, 6227.4]
    assert block.declared_constants == 8, (
        "*USER ELEMENT PROPERTIES= is where a UEL deck declares its count")
    assert block.nstatv == 307, "*USER ELEMENT VARIABLES= is the SVARS length"
    assert block.consistent


def test_a_uel_property_vector_says_it_is_not_a_material_block(tmp_path: Path):
    """The two keywords mean different things, so a reader must be able to tell.

    ``*Material``/``*User Material`` names a material Abaqus hands to a UMAT;
    ``*UEL PROPERTY`` is an element property vector. Both are constants the
    author published, but provenance that called the second one a *Material
    block would be a false citation.
    """
    deck = _write(tmp_path, "both.inp", """\
*USER ELEMENT,NODES=4,TYPE=U1,PROPERTIES=2,COORDINATES=2,VARIABLES=8
 1,2
*UEL PROPERTY,ELSET=TODOS
1000.0, 0.3
*Material, name=STEEL
*User Material, constants=3
210000.0, 0.3, 250.0
*Depvar
5
""")
    uel, material = parse_deck(deck)
    assert uel.kind == "uel property" and material.kind == "material"
    assert uel.props == [1000.0, 0.3]
    assert material.props == [210000.0, 0.3, 250.0]
    assert "*UEL PROPERTY" in uel.as_dict()["provenance"]
    assert "elset=TODOS" in uel.as_dict()["provenance"]
    assert "*Material" in material.as_dict()["provenance"]


def test_a_uel_property_count_that_disagrees_is_reported_not_repaired(tmp_path: Path):
    """Same rule as ``CONSTANTS=``: a contradiction is reported, never trimmed.

    Padding the vector out to the declared length, or silently trusting the
    shorter one, would put numbers into the evidence that the author did not
    write.
    """
    deck = _write(tmp_path, "short.inp", """\
*USER ELEMENT,NODES=4,TYPE=U1,PROPERTIES=6,COORDINATES=2,VARIABLES=8
 1,2
*UEL PROPERTY,ELSET=TODOS
1000.0, 0.3
""")
    (block,) = parse_deck(deck)
    assert block.props == [1000.0, 0.3]
    assert not block.consistent
    assert "PROPERTIES=6" in " ".join(block.problems)


def test_a_uel_property_block_does_not_capture_a_later_material(tmp_path: Path):
    """``*Depvar`` and ``*User Material`` belong to a ``*Material`` block only.

    A UEL property block that swallowed the next ``*Depvar`` would report a
    state-variable count for the wrong entity.
    """
    deck = _write(tmp_path, "order.inp", """\
*USER ELEMENT,NODES=4,TYPE=U1,PROPERTIES=2,COORDINATES=2,VARIABLES=8
 1,2
*UEL PROPERTY,ELSET=TODOS
1000.0, 0.3
*Depvar
99
""")
    (block,) = parse_deck(deck)
    assert block.kind == "uel property"
    assert block.nstatv == 8, "VARIABLES=8, not the stray *Depvar"


def test_the_real_jgomezc1_uel_decks_publish_their_constants():
    """The concrete decks that motivated this: read them, do not guess them."""
    deck = _cached("jgomezc1__ABAQUS-US/INPUT_FILES/UNIUSER_COS_KIN.inp")
    (block,) = [b for b in parse_deck(deck) if b.kind == "uel property"]
    assert block.props == [42340.0, 0.34, 0.005, 90000.0,
                           21.77, 15.542, 383.3, 6227.4]
    assert block.declared_constants == 8 and block.consistent


# --------------------------------------------------------------------------
# (1) the state-variable arm resolves, it does not reject
# --------------------------------------------------------------------------

def _umat_repo(tmp_path: Path, *, constants: int, depvar: int) -> tuple[Path, Path]:
    source = tmp_path / "umat.for"
    source.write_text("      SUBROUTINE UMAT(STRESS,STATEV,PROPS)\n      END\n",
                      encoding="utf-8")
    deck = tmp_path / "job.inp"
    values = ", ".join(str(float(i + 1)) for i in range(constants))
    deck.write_text(
        f"*Material, name=M\n*User Material, constants={constants}\n"
        f"{values}\n*Depvar\n{depvar}\n", encoding="utf-8")
    return source, deck


def test_a_deck_declaring_fewer_state_variables_still_supplies_its_constants(
        tmp_path: Path):
    """*Depvar is resolved as a maximum, the way the job builder resolves it.

    UNIUSER_CLA_KIN.inp declares ``*Depvar 14``; inference reads 20 off
    UEL8_PCLK's own STATEV layout. The harness allocates ``max`` of the two --
    :func:`build_validation_workspace` has done that since the out-of-bounds
    write it was written to prevent -- so nothing is at risk, and rejecting the
    pairing threw away six constants the author had published.
    """
    source, deck = _umat_repo(tmp_path, constants=6, depvar=14)
    ok, detail = check_pairing(source, deck, expected_nprops=6,
                               expected_nstatv=20)
    assert ok
    assert "6 constants" in detail
    assert "20" in detail, "the resolved state-variable count has to be visible"


def test_a_refusal_names_the_arm_that_refused(tmp_path: Path):
    """The recorded reason was false, which is worse than being unhelpful.

    Every failure used to be written up as a constants shortfall, so a row
    rejected on state variables was filed as "no published material constants",
    and a reader chasing it went looking for numbers that were there all along.
    """
    source, deck = _umat_repo(tmp_path, constants=4, depvar=10)
    ok, detail = check_pairing(source, deck, expected_nprops=9,
                               expected_nstatv=1)
    assert not ok
    assert "constants" in detail and "4" in detail and "9" in detail

    proposal = pair_source_with_deck(source, [deck], expected_nprops=9,
                                     expected_nstatv=1, model=None)
    assert proposal.verdict is Verdict.CONTRADICTED
    assert "constants" in proposal.evidence


def test_too_few_constants_is_still_refused(tmp_path: Path):
    """The loosening is one-sided. Constants are never invented.

    If this ever passes, the pairing is handing a driver a vector shorter than
    the subroutine indexes, and the numbers past the end come from nobody.
    """
    source, deck = _umat_repo(tmp_path, constants=2, depvar=10)
    ok, _ = check_pairing(source, deck, expected_nprops=6, expected_nstatv=1)
    assert not ok


def test_a_repository_with_no_deck_still_yields_nothing(tmp_path: Path):
    """needs_material_data is a correct final answer where nothing was published.

    The point of this work is to stop mislabelling published constants, not to
    find excuses to supply numbers.
    """
    source = tmp_path / "umat.for"
    source.write_text("      SUBROUTINE UMAT(STRESS,STATEV,PROPS)\n      END\n",
                      encoding="utf-8")
    proposal = pair_source_with_deck(source, [], expected_nprops=2,
                                     expected_nstatv=1, model=None)
    assert proposal.verdict is Verdict.CONTRADICTED


# --------------------------------------------------------------------------
# (3) NPROPS belongs to a subprogram, not to a file
# --------------------------------------------------------------------------

_TWO_ROUTINES = """\
      SUBROUTINE UEL(RHS,AMATRX,SVARS,ENERGY,NDOFEL,NRHS,NSVARS,PROPS)
      DIMENSION PROPS(*)
      EMOD = PROPS(1)
      ENU  = PROPS(2)
      THCK = PROPS(3)
      PARK = PROPS(4)
      END
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,PROPS,NPROPS)
      DIMENSION PROPS(NPROPS)
      E  = PROPS(1)
      XN = PROPS(2)
      END
"""


def test_nprops_is_what_the_transformed_routine_reads(tmp_path: Path):
    """A file's maximum is not any routine's count.

    plate_with_notch.for holds a UEL reading PROPS(1..4) beside a UMAT reading
    PROPS(1..2). Judging the UMAT by the file gave 4, and the deck's own
    ``*User Material, constants=2`` -- fully numeric, 1e-11 and 0.3 -- was
    rejected as too short.
    """
    source = _write(tmp_path, "both.for", _TWO_ROUTINES)
    assert expected_counts_for_routine(source, "UMAT")[0] == 2
    assert expected_counts_for_routine(source, "UEL")[0] == 4


def test_a_helper_the_routine_calls_counts_toward_its_nprops(tmp_path: Path):
    """Per-subprogram must not mean "this subprogram's own lines only".

    A UMAT that passes PROPS down to a helper reads every index the helper
    reads. Counting the entry point alone would under-declare NPROPS and pair
    a deck too short for the routine -- the exact failure this work forbids.
    """
    source = _write(tmp_path, "helper.for", """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,PROPS,NPROPS)
      DIMENSION PROPS(NPROPS)
      E = PROPS(1)
      CALL KMODEL(PROPS)
      END
      SUBROUTINE KMODEL(PROPS)
      DIMENSION PROPS(*)
      Q = PROPS(7)
      END
""")
    assert expected_counts_for_routine(source, "UMAT")[0] == 7


def test_a_file_with_one_routine_is_left_alone(tmp_path: Path):
    """No ambiguity to resolve means nothing to change.

    Every pairing that already worked was computed file-wide, and a file
    holding a single subprogram has to keep giving the same answer or this
    change would move pairings it was never meant to touch.
    """
    source = _write(tmp_path, "one.for", """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,PROPS,NPROPS)
      DIMENSION PROPS(NPROPS)
      A = PROPS(5)
      END
""")
    assert expected_counts_for_routine(source, "UMAT")[0] == 5


def test_pairing_uses_the_transformed_routines_count(tmp_path: Path):
    """End to end: the deck that fits the UMAT is accepted for the UMAT."""
    source = _write(tmp_path, "both.for", _TWO_ROUTINES)
    deck = _write(tmp_path, "job.inp", """\
*Material, name=UMATELEM
*Depvar
     16,
*User Material, constants=2
 1e-11, 0.3
""")
    proposal = pair_source_with_deck(source, [deck], expected_nprops=4,
                                     expected_nstatv=1, model=None)
    assert proposal.verdict is Verdict.CONFIRMED
    assert proposal.confirmed_value() == str(deck)


# --------------------------------------------------------------------------
# the seven entries, on their real files
# --------------------------------------------------------------------------

@pytest.mark.parametrize("source_id, nprops", [
    ("hamza-djeloud__thesis_project/plate_with_notch.for", 2),
    ("jgomezc1__ABAQUS-US/UELS/UEL8_PCLK.for", 6),
    ("jgomezc1__ABAQUS-US/UELS/UEL9_PCLK.for", 6),
    ("jgomezc1__ABAQUS-US/UELS/UEL8_PCOR_KIN.for", 8),
    ("jgomezc1__ABAQUS-US/UELS/UEL9_PCOR_KIN.for", 8),
])
def test_the_recovered_entries_pair_with_a_published_deck(source_id, nprops):
    """The rows this work was for, checked against the upstream files.

    If these stop pairing, the corpus is once again reporting that these
    authors published no constants while their own repository ships them.

    Which of several fitting decks is the author's intended one is not settled
    here and never was -- the pairing is arithmetic, and the row stays flagged
    as unreviewed. What is settled is that a deck fits and that its constants
    are in the file verbatim.
    """
    source = _cached(source_id)
    repository = CACHE / Path(source_id).parts[0]
    decks = sorted(repository.rglob("*.inp"))
    inferred, nstatv, _why = expected_counts_for_routine(source, "UMAT")
    assert inferred == nprops, "the UMAT's own PROPS reach"
    proposal = pair_source_with_deck(source, decks, expected_nprops=nprops,
                                     expected_nstatv=nstatv, model=None)
    assert proposal.verdict is Verdict.CONFIRMED, proposal.evidence

    deck = Path(proposal.confirmed_value())
    fitting = [b for b in parse_deck(deck) if len(b.props) == nprops]
    assert fitting, f"{deck.name} must publish a {nprops}-value vector"
    block = fitting[0]
    assert block.consistent, (
        "a vector shorter or longer than the deck declares is a contradiction "
        "to report, never a vector to pair")
    assert block.declared_constants in (None, nprops)


def test_a_source_whose_repository_publishes_nothing_stays_unpaired():
    """needs_material_data is the right answer for most of the 41 rows.

    Twelve of them come from repositories that ship no .inp file at all. If
    this ever starts pairing them, something is inventing a deck.
    """
    source = _cached(
        "glu46__3D_anisotropic_viscoelastic_model/OrthoWoodCreep_General.for")
    repository = CACHE / Path(
        "glu46__3D_anisotropic_viscoelastic_model").parts[0]
    assert not sorted(repository.rglob("*.inp"))
    nprops, nstatv, _why = expected_counts_for_routine(source, "UMAT")
    proposal = pair_source_with_deck(source, [], expected_nprops=nprops,
                                     expected_nstatv=nstatv, model=None)
    assert proposal.verdict is Verdict.CONTRADICTED


# --------------------------------------------------------------------------
# the invariant that makes all three safe: a relaxation may add, never move
# --------------------------------------------------------------------------

def test_a_relaxation_never_moves_a_pairing_that_already_worked(tmp_path: Path):
    """The strict rule runs over every deck before a looser one is reached.

    Measured, not assumed: run as one loosened rule instead of a ladder, these
    three changes moved 44 sources that already paired onto different decks and
    changed the material vector recorded for each of them. A source's constants
    and the provenance line under them must not move because an unrelated rule
    was widened.

    Here the strict rule pairs ``strict.inp`` -- an exact six constants with a
    long enough *Depvar. ``loose.inp`` sorts first and would win under the
    relaxed rule, publishing its six constants under *UEL PROPERTY. It must
    not.
    """
    source = _write(tmp_path, "umat.for",
                    "      SUBROUTINE UMAT(STRESS,STATEV,PROPS)\n      END\n")
    loose = _write(tmp_path, "a_loose.inp", """\
*USER ELEMENT,NODES=4,TYPE=U1,PROPERTIES=6,COORDINATES=2,VARIABLES=2
 1,2
*UEL PROPERTY,ELSET=TODOS
1.0, 2.0, 3.0, 4.0, 5.0, 6.0
""")
    strict = _write(tmp_path, "b_strict.inp", """\
*Material, name=M
*User Material, constants=6
9.0, 9.0, 9.0, 9.0, 9.0, 9.0
*Depvar
40
""")
    proposal = pair_source_with_deck(source, [loose, strict],
                                     expected_nprops=6, expected_nstatv=30,
                                     model=None)
    assert proposal.confirmed_value() == str(strict)
    assert proposal.metadata["pairing_level"] == 0


def test_a_relaxation_is_reached_when_the_strict_rule_pairs_nothing(tmp_path: Path):
    """And the evidence says which relaxation recovered the row.

    A row that only a fallback could pair has to say so, or a reviewer cannot
    tell a pairing the old rule would have made from one that rests on reading
    a new keyword.
    """
    source = _write(tmp_path, "umat.for",
                    "      SUBROUTINE UMAT(STRESS,STATEV,PROPS)\n      END\n")
    only = _write(tmp_path, "only.inp", """\
*USER ELEMENT,NODES=4,TYPE=U1,PROPERTIES=6,COORDINATES=2,VARIABLES=2
 1,2
*UEL PROPERTY,ELSET=TODOS
1.0, 2.0, 3.0, 4.0, 5.0, 6.0
""")
    proposal = pair_source_with_deck(source, [only], expected_nprops=6,
                                     expected_nstatv=30, model=None)
    assert proposal.confirmed_value() == str(only)
    assert proposal.metadata["pairing_level"] > 0
    assert "*UEL PROPERTY" in proposal.evidence


def test_the_proposal_carries_the_vector_it_was_confirmed_on(tmp_path: Path):
    """A filename is no longer enough to find the material again.

    plate_with_notch.inp publishes a two-value *Material beside *UEL PROPERTY
    vectors of three and four values. Which one the pairing accepted depends on
    the NPROPS it used, so re-deriving it from the deck path with a file-wide
    NPROPS picks the four-value element property vector -- real constants, cited
    as a *Material block the author never wrote.
    """
    source = _write(tmp_path, "both.for", _TWO_ROUTINES)
    deck = _cached("hamza-djeloud__thesis_project/plate_with_notch.inp")
    proposal = pair_source_with_deck(source, [deck], expected_nprops=4,
                                     expected_nstatv=1, model=None)
    record = proposal.metadata["material"]
    assert record["props"] == [1e-11, 0.3]
    assert record["kind"] == "material"
    assert "*Material name=UMATELEM" in record["provenance"]
