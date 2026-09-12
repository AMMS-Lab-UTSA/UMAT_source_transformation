"""A unit cube is not a neutral place to put a UMAT that reads COORDS.

Two repositories, two different ways the same assumption failed.

``Jeff97__growth-of-circular-plate/Wrinkle/*.for`` caches ``COORDS(1)`` and
``COORDS(2)`` in ``STATEV(3)`` and ``STATEV(4)`` and then computes::

    G12=(G11-G22)*STATEV(3)*STATEV(4)/
   &      (STATEV(3)*STATEV(3)-STATEV(4)*STATEV(4))

The divisor is ``x^2 - y^2``, which is zero on the diagonals -- and four of
the eight integration points of a unit cube at the origin sit exactly on
``x = y``. All six of those sources came back as "the model produced no
numbers at any amplitude from 8e-07 to 1, searched downward from 0.0001 and
then upward to the ceiling". The amplitude was never the variable.

``Jeff97__.../PureGrowth.for`` builds ``G11 = 1 + (Pi/2 + Y*(-Pi) - 1)*t`` and
``CalAe`` divides by ``det G = G11``. Over the author's plate, whose nodes span
``y in [0, 0.01]``, G11 stays near 1.55. On a unit cube the upper integration
points sit at ``y = 0.789``, where ``G11 = 1 - 1.908 t`` passes through zero at
``t = 0.524``.

Note the second one is not caught by the divisor scan: ``det G`` is built
inside a called subroutine out of a variable the caller assembled. It is caught
by the first rule, which is the stronger one -- stand where the author stood.
"""
import pytest

from umat_oti.abaqus.coordinate_domain import (author_elements,
                                               compile_denominator,
                                               coordinate_aliases,
                                               declared_lengths,
                                               denominator_texts,
                                               geometry_agreement, place,
                                               statements)

pytestmark = pytest.mark.unit

PLATE_SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
      IF (STATEV(3) .EQ. 0) THEN
              STATEV(3)=COORDS(1)
      END IF
      IF (STATEV(4) .EQ. 0) THEN
              STATEV(4)=COORDS(2)
      END IF
      h = 0.005
      L = 1.0
      G12=(G11-G22)*STATEV(3)*STATEV(4)/
     &      (STATEV(3)*STATEV(3)-STATEV(4)*STATEV(4))
      RETURN
      END
"""

#: Two elements of an author's mesh: one straddling the diagonal, one far from
#: it. Written the way a deck writes them, connectivity and all.
PLATE_DECK = """\
*Heading
*Node
 1, -1.0, 0.0, 0.0
 2, -0.9, 0.0, 0.0
 3, -0.9, -0.1, 0.0
 4, -1.0, -0.1, 0.0
 5, -1.0, 0.0, 0.001
 6, -0.9, 0.0, 0.001
 7, -0.9, -0.1, 0.001
 8, -1.0, -0.1, 0.001
 9, 0.1, 0.1, 0.0
10, 0.2, 0.1, 0.0
11, 0.2, 0.2, 0.0
12, 0.1, 0.2, 0.0
13, 0.1, 0.1, 0.001
14, 0.2, 0.1, 0.001
15, 0.2, 0.2, 0.001
16, 0.1, 0.2, 0.001
*Element, type=C3D8H
1, 1, 2, 3, 4, 5, 6, 7, 8
2, 9, 10, 11, 12, 13, 14, 15, 16
*Solid Section, elset=Shell, material=NeoHookean
"""


def test_a_continuation_line_carries_the_half_of_the_statement_that_matters():
    """The circular-plate divisor is entirely on the continuation line. A scan
    that stops at the newline sees a division by nothing and finds no divisor
    at all; joining the statement finds ``x^2 - y^2``."""
    joined = statements(PLATE_SOURCE)
    assert any("STATEV(3)*STATEV(3)-STATEV(4)*STATEV(4)" in
               "".join(line.split()) for line in joined)


def test_the_coordinates_a_routine_caches_are_traced_through_state():
    """These routines read COORDS once and then read the cached value back out
    of STATEV for the rest of the analysis, so the alias has to be followed
    through the state array or the divisor looks like arithmetic on numbers."""
    aliases = coordinate_aliases(PLATE_SOURCE)
    assert aliases["STATEV(3)"] == 0
    assert aliases["STATEV(4)"] == 1


def test_a_divisor_built_from_coordinates_is_found_and_evaluated():
    """Found as text, then compiled, then evaluated. ``x^2 - y^2`` is zero at
    (0.5, 0.5) -- a unit cube's integration point -- and 0.96 at the far
    element's centre."""
    aliases = coordinate_aliases(PLATE_SOURCE)
    texts = denominator_texts(PLATE_SOURCE, aliases)
    assert texts == ("(STATEV(3)*STATEV(3)-STATEV(4)*STATEV(4))",)
    evaluate = compile_denominator(texts[0], aliases)
    assert evaluate is not None
    assert abs(evaluate((0.5, 0.5, 0.0))) < 1e-12
    assert abs(evaluate((-0.95, -0.05, 0.0)) - (0.9025 - 0.0025)) < 1e-9


def test_the_element_chosen_is_the_one_the_routine_is_defined_at():
    """Element 2 of the fixture straddles ``x = y``; element 1 sits at
    ``x ~ -0.95, y ~ -0.05`` where the divisor is 0.9. The placement takes
    element 1 and says by how much."""
    placement = place(PLATE_SOURCE, PLATE_DECK, ("C3D8H",))
    assert placement.found is True
    assert placement.element.number == 1
    assert placement.margin > 0.5
    assert "divides by" in placement.reason


def test_a_routine_that_never_reads_coords_still_stands_on_the_author_s_mesh():
    """Where it sits cannot change what it computes, so nothing is refused --
    but the geometry is still the author's rather than a cube this harness
    invented, because that costs nothing and removes a difference."""
    placement = place("      SUBROUTINE UMAT(STRESS)\n      RETURN\n      END\n",
                      PLATE_DECK, ("C3D8H",))
    assert placement.found is True
    assert placement.coordinate_dependent is False
    assert "never reads COORDS" in placement.reason


def test_the_author_s_element_is_reduced_to_its_corner_nodes():
    """A C3D20 has twenty nodes and twelve of them are midside. What a
    material-point comparison needs is the corners, and the first-order
    sibling this harness runs takes exactly the first eight."""
    elements = author_elements(PLATE_DECK, ("C3D8H",))
    assert [element.number for element in elements] == [1, 2]
    assert elements[0].node_count == 8
    assert elements[0].nodes[0] == (1, -1.0, 0.0, 0.0)


def test_a_source_states_which_mesh_it_belongs_on_by_hard_coding_its_size():
    """``h = 0.005`` and ``L = 1.0``, and the author's Th001 plate spans 1.0 by
    0.01 -- which is 2h. Its Th01 sibling says ``h = 0.05`` for a plate ten
    times as thick, and the two decks are otherwise indistinguishable."""
    lengths = declared_lengths(PLATE_SOURCE)
    assert lengths["H"] == 0.005
    assert lengths["L"] == 1.0

    def mesh(span_x: float, span_y: float) -> str:
        return (f"*Node\n1, 0., 0., 0.\n2, {span_x}, 0., 0.\n"
                f"3, {span_x}, {span_y}, 0.\n4, 0., {span_y}, 0.\n")

    thin, thick = mesh(1.0, 0.01), mesh(1.0, 0.1)
    assert geometry_agreement(PLATE_SOURCE, thin)[0] == 2
    assert geometry_agreement(PLATE_SOURCE, thick)[0] == 1
    assert "2*H" in geometry_agreement(PLATE_SOURCE, thin)[1]


def test_a_length_written_as_a_quotient_is_still_a_length():
    """``Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for`` writes
    ``h = 0.1/20.0`` and ``L = 1.0/10.0``. Reading only bare literals said that
    source declared no geometry, and it declares a plate a tenth as long as
    every other one in its repository."""
    lengths = declared_lengths(
        "      h = 0.1/20.0 ! m (total thickness = 2h)\n"
        "      L = 1.0/10.0 ! length of the beam\n"
        "      X = COORDS(1)\n")
    assert lengths["H"] == pytest.approx(0.005)
    assert lengths["L"] == pytest.approx(0.1)
