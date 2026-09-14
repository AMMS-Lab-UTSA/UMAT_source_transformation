"""Objectivity is a statement about two runs, and nobody was making the second.

``experiment.DECLARED_ONLY`` says the finite-strain family needs "a superposed
rigid rotation must leave the material response unchanged, which needs a second
run whose path is the first one rotated", and returns it as a ``Finding`` with
``met=None`` -- honest for one run, and a permanent block for a verdict. Left
alone it put ``NeoHookean_umat.for`` at ``informativeness_not_established`` on a
question this harness had never asked rather than one it could not answer, and
54 finite-strain entries with it.

So the second run is made. The material is driven along exactly the same strain
history and only the frame moves, so Abaqus hands the routine ``F = Q(I+E)``
and a ``DROT`` carrying Q. Two different facts come out of it, and they are
kept apart: whether the CONVERTED build still matches the original there, which
is about the transform and is what a dropped DROT breaks; and whether the
ORIGINAL's own response is the unrotated response rotated, which is a property
of the author's model and is never charged to the conversion.
"""
import math

import pytest

from umat_oti.abaqus import deck
from umat_oti.abaqus.manifest import (OBJECTIVITY_ROTATION,
                                      OBJECTIVITY_ROTATION_PLANE,
                                      LoadingSegment, VerificationManifest,
                                      rotated, uniaxial)


def _matrix(flat):
    return [list(flat[0:3]), list(flat[3:6]), list(flat[6:9])]


@pytest.mark.parametrize("flat", [OBJECTIVITY_ROTATION,
                                  OBJECTIVITY_ROTATION_PLANE])
def test_the_superposed_rotation_is_a_rotation(flat):
    """Q Q^T = I and det Q = +1. A near-rotation is a deformation, and
    superposing one would change the strain the material is asked about."""
    q = _matrix(flat)
    for i in range(3):
        for j in range(3):
            dot = sum(q[i][k] * q[j][k] for k in range(3))
            assert abs(dot - (1.0 if i == j else 0.0)) < 1e-12
    determinant = (
        q[0][0] * (q[1][1] * q[2][2] - q[1][2] * q[2][1])
        - q[0][1] * (q[1][0] * q[2][2] - q[1][2] * q[2][0])
        + q[0][2] * (q[1][0] * q[2][1] - q[1][1] * q[2][0]))
    assert abs(determinant - 1.0) < 1e-12


def test_the_three_dimensional_rotation_mixes_every_component():
    """A rotation about a coordinate axis, or by ninety degrees, permutes
    components rather than mixing them -- and a build that dropped DROT could
    reproduce the answer by accident. Every entry of Q is away from zero."""
    assert min(abs(value) for value in OBJECTIVITY_ROTATION) > 0.2


def test_the_plane_rotation_stays_in_the_plane():
    """An out-of-plane rotation takes a 2D element out of its own plane, which
    is a different analysis rather than the same one from another frame."""
    q = _matrix(OBJECTIVITY_ROTATION_PLANE)
    assert q[2] == [0.0, 0.0, 1.0]
    assert q[0][2] == 0.0 and q[1][2] == 0.0


def test_a_corner_is_driven_to_the_rotated_position():
    """u' = Q(X + u) - X, written on the position because a rotation acts on
    where the material is and not on how far it moved."""
    strain = (0.02, 0.0, 0.0, 0.0, 0.0, 0.0)
    node = (1.0, 1.0, 1.0)
    plain = deck._displacement(node, strain)
    turned = deck._displacement(node, strain, OBJECTIVITY_ROTATION)

    q = _matrix(OBJECTIVITY_ROTATION)
    placed = [node[i] + plain[i] for i in range(3)]
    for row in range(3):
        wanted = sum(q[row][k] * placed[k] for k in range(3)) - node[row]
        assert turned[row] == pytest.approx(wanted, rel=0, abs=1e-15)


def test_the_rotation_does_not_change_how_far_the_corner_is_from_the_origin():
    """The whole point: the deformation is the same one, seen differently."""
    strain = (0.05, -0.01, 0.0, 0.03, 0.0, 0.0)
    for node in ((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.5, 1.0, 1.0)):
        plain = deck._displacement(node, strain)
        turned = deck._displacement(node, strain, OBJECTIVITY_ROTATION)
        before = math.dist((0, 0, 0), [node[i] + plain[i] for i in range(3)])
        after = math.dist((0, 0, 0), [node[i] + turned[i] for i in range(3)])
        assert after == pytest.approx(before, rel=1e-14)


def test_no_rotation_leaves_every_deck_exactly_as_it_was():
    """Every entry that is not finite strain must generate the deck it did."""
    strain = (0.01, 0.0, 0.0, 0.02, 0.0, 0.0)
    node = (0.7, -0.3, 1.1)
    assert deck._displacement(node, strain, ()) == deck._displacement(node, strain)


def test_rotated_prepends_a_lead_in_and_changes_nothing_else():
    """The author's own segments are carried through untouched; a lead-in that
    turns the element from the identity to Q at zero strain goes in front."""
    loading = (uniaxial(0.01, 10), LoadingSegment("shear", (0, 0, 0, 0.02, 0, 0),
                                                  increments=7, period=2.0))
    turned = rotated(loading)
    assert len(turned) == len(loading) + 1
    assert turned[0].name == "rigid_rotation_lead_in"
    assert turned[0].rotation_lead_in is True
    assert not any(turned[0].strain)
    assert [s.rotation for s in turned] == [OBJECTIVITY_ROTATION] * 3
    assert [s.rotation_lead_in for s in turned[1:]] == [False, False]
    for before, after in zip(loading, turned[1:]):
        assert after.strain == before.strain
        assert after.increments == before.increments
        assert after.period == before.period
        assert after.name == before.name


def test_the_plane_flag_selects_the_in_plane_rotation():
    turned = rotated((uniaxial(0.01, 4),), plane=True)
    assert all(s.rotation == OBJECTIVITY_ROTATION_PLANE for s in turned)


def test_rotation_is_the_last_field_so_nothing_positional_lands_in_it():
    """It was inserted after ``strain`` first, and every positional
    construction in the package then bound ``increments`` to it -- which the
    deck generator read as a rotation matrix and raised on. The field order is
    part of the interface here, so it is asserted."""
    import dataclasses
    names = [f.name for f in dataclasses.fields(LoadingSegment)]
    assert names[-2:] == ["rotation", "rotation_lead_in"]
    assert names[1] == "strain" and names[2] == "increments"


def test_the_generated_deck_drives_the_rotated_positions():
    """End to end: the boundary block of a rotated manifest is not the
    boundary block of the same manifest unrotated, and both are complete."""
    base = VerificationManifest(name="m", source="m.f", element_type="C3D8",
                                nprops=1, props=(1.0,), nstatv=1,
                                kinematics="finite",
                                loading=(uniaxial(0.02, 4),))
    turned = VerificationManifest(name="m", source="m.f", element_type="C3D8",
                                  nprops=1, props=(1.0,), nstatv=1,
                                  kinematics="finite",
                                  loading=rotated(base.loading))
    plain_text, turned_text = deck.generate_deck(base), deck.generate_deck(turned)
    assert plain_text != turned_text
    for text in (plain_text, turned_text):
        assert "*BOUNDARY" in text
        assert "NLGEOM=YES" in text.upper()

    def _rows(text):
        rows, keep = [], False
        for line in text.splitlines():
            if line.upper().startswith("*BOUNDARY"):
                keep = True
                continue
            if line.startswith("*"):
                keep = False
                continue
            if keep and line.strip():
                rows.append(line)
        return rows

    # eight corners times three degrees of freedom, driven in both -- and the
    # rotated deck drives them twice, once in the lead-in that turns the
    # element and once in the author's own segment.
    assert len(_rows(plain_text)) == 24
    assert len(_rows(turned_text)) == 48
    assert turned_text.count("*STEP") == plain_text.count("*STEP") + 1


# ---------------------------------------------------------------------------
# the author's own objectivity, which is a different question
# ---------------------------------------------------------------------------
def _verifier():
    import importlib.util
    import pathlib
    import sys
    where = pathlib.Path(__file__).resolve().parents[1] / "tools" / "verify_store_in_abaqus.py"
    spec = importlib.util.spec_from_file_location("_vs_objectivity", where)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_vs_objectivity"] = module
    spec.loader.exec_module(module)
    return module


def _turn(stress, flat):
    """Q sigma Q^T, in the Voigt order the probe writes."""
    q = _matrix(flat)
    index = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))
    sigma = [[0.0] * 3 for _ in range(3)]
    for slot, (row, column) in enumerate(index):
        sigma[row][column] = sigma[column][row] = stress[slot]
    turned = [[sum(q[i][a] * sigma[a][b] * q[j][b]
                   for a in range(3) for b in range(3)) for j in range(3)]
              for i in range(3)]
    return [turned[row][column] for row, column in index]


def test_a_response_that_rotates_with_the_frame_is_objective():
    """Which basis the recorded stress is in was settled by MEASUREMENT.

    With the rotated path finally correct, NeoHookean_umat.for gave, over 1680
    components:

        |Q sigma Q^T - sigma'|   4.405e-13
        |sigma       - sigma'|   7.023e-01

    so the history carries stress in the global basis and an objective response
    rotates with it. Both are still computed, because the day the other one is
    the small one is the day that stopped being true.
    """
    vs = _verifier()
    stress = [120.0, -35.0, 8.0, 17.0, -4.0, 2.5]
    answer = vs._objective_response(
        [{"STRESS": stress}], [{"STRESS": _turn(stress, OBJECTIVITY_ROTATION)}],
        OBJECTIVITY_ROTATION)
    assert answer["objective"] is True
    assert answer["objectivity_worst_relative"] < 1e-14
    assert answer["compared_components"] == 6
    assert answer["objectivity_worst_corotational"] > 0.1


def test_a_response_that_never_turned_is_not_objective():
    """The positive control: components that came back unchanged in the global
    basis are what a routine that ignored DROT returns."""
    vs = _verifier()
    stress = [120.0, -35.0, 8.0, 17.0, -4.0, 2.5]
    answer = vs._objective_response([{"STRESS": stress}], [{"STRESS": stress}],
                                    OBJECTIVITY_ROTATION)
    assert answer["objective"] is False
    assert answer["objectivity_worst_relative"] > 0.1
    assert "is NOT" in answer["objectivity_reason"]
    assert answer["objectivity_worst_corotational"] < 1e-14


def test_no_six_component_increment_is_not_a_verdict_either_way():
    """A 2D element hands fewer components and the missing ones cannot be
    filled in here without assuming which they are. That is 'not measured'."""
    vs = _verifier()
    answer = vs._objective_response([{"STRESS": [1.0, 2.0, 3.0]}],
                                    [{"STRESS": [1.0, 2.0, 3.0]}],
                                    OBJECTIVITY_ROTATION)
    assert answer["objective"] is None
    assert "could not be formed" in answer["objectivity_reason"]


def test_a_zero_stress_increment_is_skipped_rather_than_counted_as_agreeing():
    """Dividing by a zero field would make every build objective for free."""
    vs = _verifier()
    answer = vs._objective_response([{"STRESS": [0.0] * 6}],
                                    [{"STRESS": [0.0] * 6}],
                                    OBJECTIVITY_ROTATION)
    assert answer["objective"] is None


def test_the_transform_question_and_the_author_question_stay_apart():
    """``agreed`` is about the conversion; ``objective`` is about the model. A
    routine that ignores DROT is faithfully converted by a conversion that
    ignores it identically, and reporting that as a conversion failure would
    charge this project with somebody else's modelling decision."""
    vs = _verifier()
    import inspect
    text = inspect.getsource(vs.run_objectivity)
    assert '"agreed"' in text and "_objective_response" in text
    # the two never feed one another
    assert "objective\"] and" not in text and "agreed = " not in text


# ---------------------------------------------------------------------------
# the path has to BE a rotation at every increment, not only at the end
# ---------------------------------------------------------------------------
def test_a_partly_applied_rotation_is_a_rotation_and_not_a_chord():
    """This is the defect the first build of this had.

    Abaqus ramps a prescribed displacement LINEARLY over its step. Half of a
    rotation's displacement is the chord, not half the rotation, so a corner
    driven that way cuts across the arc and the element is squashed. Measured
    on a real pair of runs before the fix: the stress trace of the "rotated"
    run differed from the unrotated run's by a factor of 24, and a rotation
    preserves the trace -- the two runs were not the same deformation at all,
    and the objectivity verdict read from them was meaningless.
    """
    for fraction in (0.0, 0.125, 0.25, 0.5, 0.75, 1.0):
        q = deck._rotation_at(fraction, OBJECTIVITY_ROTATION)
        for i in range(3):
            for j in range(3):
                dot = sum(q[3 * i + k] * q[3 * j + k] for k in range(3))
                assert abs(dot - (1.0 if i == j else 0.0)) < 1e-14


def test_the_partial_rotation_starts_at_the_identity_and_ends_at_q():
    start = deck._rotation_at(0.0, OBJECTIVITY_ROTATION)
    end = deck._rotation_at(1.0, OBJECTIVITY_ROTATION)
    identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    assert max(abs(a - b) for a, b in zip(start, identity)) < 1e-15
    assert max(abs(a - b) for a, b in zip(end, OBJECTIVITY_ROTATION)) < 1e-14


@pytest.mark.parametrize("node", [(1.0, 0.0, 0.0), (1.0, 1.0, 0.0),
                                  (0.0, 1.0, 1.0), (1.0, 1.0, 1.0)])
def test_the_driven_corner_keeps_its_distance_at_every_fraction(node):
    """The invariant that catches a chord: |Q(f)(I+fE)X| = |(I+fE)X|, because
    a rotation preserves length. A linearly ramped displacement fails this
    everywhere except the two ends."""
    segment = rotated((uniaxial(0.02, 4),))[0]
    for step in range(5):
        fraction = step / 4
        partial = tuple(value * fraction for value in segment.strain)
        turned = deck._displacement(node, partial,
                                    deck._rotation_at(fraction, segment.rotation))
        plain = deck._displacement(node, partial)
        far = math.dist((0, 0, 0), [node[i] + turned[i] for i in range(3)])
        near = math.dist((0, 0, 0), [node[i] + plain[i] for i in range(3)])
        assert far == pytest.approx(near, abs=1e-15)


def test_the_chord_this_replaces_would_fail_that_invariant():
    """A positive control, so the test above is known to have power: driving
    the final rotated displacement linearly does NOT preserve the distance.

    The corner is (1,0,0), off the axis. (1,1,1) is ON the axis of this
    rotation and does not move at all under it, so a chord test there passes
    for free -- which the first version of this control did, and it was
    measuring nothing.
    """
    segment = rotated((uniaxial(0.02, 4),))[0]
    node = (1.0, 0.0, 0.0)
    final = deck._displacement(node, segment.strain, segment.rotation)
    half = [node[i] + 0.5 * final[i] for i in range(3)]
    partial = tuple(value * 0.5 for value in segment.strain)
    wanted = math.dist((0, 0, 0), [node[i] + deck._displacement(node, partial)[i]
                                   for i in range(3)])
    assert abs(math.dist((0, 0, 0), half) - wanted) > 1e-3


def test_every_driven_degree_of_freedom_gets_its_own_amplitude_table():
    """One table per degree of freedom is what lets each follow its own path;
    a single BOUNDARY block cannot carry more than one amplitude."""
    from umat_oti.abaqus.manifest import VerificationManifest
    written = deck.generate_deck(VerificationManifest(
        name="m", source="m.f", element_type="C3D8", nprops=1, props=(1.0,),
        nstatv=1, kinematics="finite", loading=rotated((uniaxial(0.02, 4),))))
    assert written.count("*AMPLITUDE") == 24          # 8 corners x 3 dof
    # one table-driven block per degree of freedom for the lead-in, and one
    # plain block for the author's own segment, where Q is fixed and a linear
    # ramp is already exact
    assert written.count("*BOUNDARY") == 25
    # and they are model data, which must precede the first step
    assert written.index("*AMPLITUDE") < written.index("*STEP")
    # sampled at the increment boundaries, endpoints included
    block = written[written.index("*AMPLITUDE"):]
    block = block[:block.index("*AMPLITUDE", 1)]
    assert len(block.strip().splitlines()) == 10      # header plus 9 samples


def test_an_unrotated_manifest_still_writes_one_plain_boundary_block():
    from umat_oti.abaqus.manifest import VerificationManifest
    written = deck.generate_deck(VerificationManifest(
        name="m", source="m.f", element_type="C3D8", nprops=1, props=(1.0,),
        nstatv=1, kinematics="finite", loading=(uniaxial(0.02, 4),)))
    assert "*AMPLITUDE" not in written
    assert written.count("*BOUNDARY") == 1
