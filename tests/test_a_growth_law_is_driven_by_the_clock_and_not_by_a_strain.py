"""A moving state variable is not a growth, and a finite number is not a stress.

The run this file exists because of: ``BodyForce-Growth-2Stages.for`` driven by
a prescribed-strain deck whose step period had been shortened to make the
history finite. It completed. Every increment was finite. Every generic
activation indicator fired -- STATEV(9) ran from 0.003125 to 0.40625, a
hundred-and-thirty-fold change, monotone. It was recorded as verified.

Two things were wrong with it and neither is visible to an activation
detector.

STATEV(9) in that source is ``(TIME(2)+DTIME)``: the elapsed time, written into
the state array. It moves in every run of any length by construction, including
a run that shortened the clock until the growth stopped happening. The quantity
the growth law computes is STATEV(8) = G11, and under that experiment it did
not move at all.

And the peak stress was 1.575e13 against a material block carrying ONE
constant, 1e8 -- a ratio of 157,500. The same model sat at about 4e13 at the
smallest amplitude the search ever probed, so no amplitude would have rescued
that deck. The deck was wrong, and what made it wrong was the place the
element stood and the clock it was run on.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.experiment import (Family, MEANINGFUL_ACTIVATION,
                                        PLAUSIBLE_STRESS_MULTIPLE, assess,
                                        applies_a_body_force, build, classify,
                                        clock_read, growth_developed,
                                        growth_state_slots,
                                        stress_stays_on_the_material_scale,
                                        time_driven_state_slots)
from umat_oti.abaqus.manifest import VerificationManifest
from umat_oti.abaqus.time_scale import required_total_time

pytestmark = pytest.mark.unit

TWO_STAGES = """\
      SUBROUTINE DLOAD(F,KSTEP,KINC,TIME,NOEL,NPT,LAYER,KSPT,
     1 COORDS,JLTYP,SNAME)
      TargetF0 = RhoR*fZ
      TargetF = TargetF0/DetF
      F = TargetF*(TIME(1))/TotalT
      RETURN
      END
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
        TotalT=1.0
        G11St1 = (Lambda1z0St1 + Y*Lambda1z1St1)
        G11St2 = (Lambda1z0St2 + Y*Lambda1z1St2)
        IF ( (TIME(2)+DTIME) .LE. 1.0) THEN
          G11=1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
        ELSE IF ( (TIME(2)+DTIME) .LE. 2.0) THEN
          G11=2.0*G11St1-G11St2
     &        +(G11St2-G11St1)*(TIME(2)+DTIME)/TotalT
        ELSE IF ( (TIME(2)+DTIME) .LE. 3.0) THEN
          G11=G11St2
        END IF
        STATEV(8) = G11
        STATEV(9) = (TIME(2)+DTIME)
      RETURN
      END
"""

PURE_GROWTH = """\
      SUBROUTINE DLOAD(F,KSTEP,KINC,TIME)
      TargetF = RhoR*fZ
! TODO: for testing
      F = 0.0
      RETURN
      END
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
        TotalT=1.0
        DtltaG11 = (Lambda1z0 + Y*Lambda1z1-1.0)
     &              *(TIME(1)+DTIME)/TotalT
        G11 = 1.0+DtltaG11
        STATEV(8) = G11
      RETURN
      END
"""


def _records(growth_slot_8, peak_stress):
    """A run recorded the way the probe records one, at two increments."""
    def record(g11, time, stress):
        return {"kind": "result", "time": time,
                "STATEV": [0.0] * 7 + [g11, time],
                "STRESS": [stress] * 6}
    return [record(1.0, 0.003125, peak_stress * 1e-6),
            record(growth_slot_8, 0.40625, peak_stress)]


def test_the_clock_written_into_state_is_not_a_growth_quantity():
    """``STATEV(9) = (TIME(2)+DTIME)`` is the elapsed time. It is driven by the
    clock, so it is in the clock-driven set, and it is not a growth quantity,
    so it is not in the growth set. The withdrawn verdict rested on it."""
    assert sorted(time_driven_state_slots(TWO_STAGES)) == [8, 9]
    assert sorted(growth_state_slots(TWO_STAGES)) == [8]


def test_a_growth_quantity_reached_through_three_assignments_is_still_found():
    """``PureGrowth.for`` goes TIME -> DtltaG11 -> G11 -> STATEV(8), across a
    continuation line. One pass of the assignment scan found none of it."""
    assert sorted(growth_state_slots(PURE_GROWTH)) == [8]


def test_the_growth_criterion_rejects_the_run_that_was_recorded_as_verified():
    """Measured on the withdrawn run: STATEV(9) moved 12900% and STATEV(8),
    which is G11, did not move at all. The criterion watches G11 and says so."""
    finding = growth_developed(_records(1.0, 1.0e6),
                               growth_state_slots(TWO_STAGES))
    assert finding.met is False
    assert "STATEV(8)" in finding.reason
    assert "initial state" in finding.reason


def test_the_growth_criterion_accepts_a_growth_that_actually_developed():
    """A growth stretch that reaches 1.55 -- which is what the author's own
    plate reaches at the end of its own step -- moves 55% of its starting
    value, well past the 1% this family asks for."""
    finding = growth_developed(_records(1.55, 1.0e6),
                               growth_state_slots(TWO_STAGES))
    assert finding.met is True
    assert finding.magnitude == pytest.approx(0.55, rel=1e-6)


def test_a_response_far_above_the_material_s_own_constants_is_not_a_response():
    """1.575e13 against a largest material constant of 1e8. An elastic
    constant is the stress the material carries at unit strain, so this is a
    strain of a hundred thousand or arithmetic that has left the model."""
    manifest = VerificationManifest(name="g", source=Path("g.for"),
                                    props=(1.0e8,), nstatv=9)
    finding = stress_stays_on_the_material_scale(_records(1.55, 1.575e13),
                                                 manifest.props)
    assert finding.met is False
    assert finding.magnitude == pytest.approx(157500.0, rel=1e-6)
    assert str(int(PLAUSIBLE_STRESS_MULTIPLE)) in finding.reason


def test_plausibility_is_checked_for_every_family_and_not_only_for_growth():
    """It is the check that would have caught the withdrawn run, and nothing
    about it is specific to growth: a stress a hundred thousand times the
    material's own constants is not evidence about any family."""
    manifest = VerificationManifest(name="g", source=Path("g.for"),
                                    props=(1.0e8,), nstatv=9)
    for family in ("growth", "cohesive", "strain driven", "plane stress"):
        findings = assess(Family(family, "strain"), _records(1.55, 1.575e13),
                          manifest, TWO_STAGES)
        assert findings[0].name == "stress on the material scale"
        assert findings[0].met is False


def test_a_growth_run_needs_both_criteria_and_the_withdrawn_one_failed_both():
    """Finite, complete, monotone, and active by every generic indicator --
    and the growth tensor did not move and the stress was 1e5 times what the
    material can carry."""
    manifest = VerificationManifest(name="g", source=Path("g.for"),
                                    props=(1.0e8,), nstatv=9)
    findings = assess(Family("growth", "time"), _records(1.0, 1.575e13),
                      manifest, TWO_STAGES)
    met = {finding.name: finding.met for finding in findings}
    assert met["stress on the material scale"] is False
    assert met["growth developed"] is False


def test_which_clock_a_law_reads_decides_how_many_steps_it_may_have():
    """TIME(1) restarts at zero when a step ends. ``PureGrowth.for`` ramps in
    it, so a staged experiment would reset its growth tensor to the identity
    at every boundary; ``BodyForce-Growth-2Stages.for`` branches on TIME(2) at
    1, 2 and 3 and so REQUIRES three steps to reach its own third branch."""
    assert clock_read(PURE_GROWTH) == "step"
    assert clock_read(TWO_STAGES) == "both"
    assert required_total_time(TWO_STAGES, (1.0e8,)).periods == (1.0, 1.0, 1.0)


def test_the_same_dload_routine_in_two_files_is_two_different_experiments():
    """``PureGrowth.for`` and ``BodyForce-Growth-2Stages.for`` carry the same
    DLOAD and the first ends it with ``! TODO: for testing`` and ``F = 0.0``.
    Reading only ``SUBROUTINE DLOAD`` would give them both a body force, and
    one of them has none."""
    applied, why = applies_a_body_force(PURE_GROWTH)
    assert applied is False
    assert "F = 0.0" in why
    assert applies_a_body_force(TWO_STAGES)[0] is True


def test_the_experiment_a_growth_law_gets_runs_the_author_s_whole_clock():
    """Three steps of unit period, because the law branches at total times 1,
    2 and 3 -- not one step shortened until the history came back finite."""
    manifest = VerificationManifest(name="g", source=Path("g.for"),
                                    element_type="C3D8H", props=(1.0e8,),
                                    nstatv=9, kinematics="finite")
    experiment = build(TWO_STAGES, manifest,
                       body_force=(("BXNU", 0.0), ("BYNU", 1.0)), held=(1, 2),
                       body_force_provenance="the author's deck")
    assert experiment.found is True
    assert experiment.family.name == "growth"
    assert [segment.period for segment in experiment.manifest.loading] == [
        1.0, 1.0, 1.0]
    assert all(segment.body_force for segment in experiment.manifest.loading)
    assert experiment.criterion == MEANINGFUL_ACTIVATION["growth"]


def test_a_step_clock_law_is_run_as_one_step_however_long_its_history():
    """A law that reads TIME(1) cannot be walked across several steps, and
    splitting it would reset the growth at every boundary."""
    manifest = VerificationManifest(name="p", source=Path("p.for"),
                                    element_type="C3D8H", props=(1.0e7,),
                                    nstatv=9, kinematics="finite")
    experiment = build(PURE_GROWTH, manifest)
    assert [segment.period for segment in experiment.manifest.loading] == [1.0]
    assert experiment.manifest.loading[0].driven_by == "time"


def test_a_clock_driven_law_with_no_declared_duration_is_refused():
    """Choosing a duration for a growth chooses how much of the growth
    happens, which is the constitutive problem and not the numerics."""
    text = ("      SUBROUTINE UMAT(STRESS,STATEV)\n"
            "      G11 = 1.0 + RATE*(TIME(2)+DTIME)\n"
            "      STATEV(1) = G11\n      RETURN\n      END\n")
    manifest = VerificationManifest(name="u", source=Path("u.for"),
                                    element_type="C3D8", props=(1.0,))
    experiment = build(text, manifest)
    assert experiment.found is False
    assert "how much of the growth happens" in experiment.refusal


def test_every_family_states_what_activating_it_means():
    """The criteria are the deliverable. Each is quoted into the run request
    that asks for the job, so a reader can tell what the run was for."""
    families = {"growth", "body force", "cohesive", "rate dependent",
                "damage", "oriented", "finite strain", "plane stress",
                "strain driven"}
    assert families <= set(MEANINGFUL_ACTIVATION)
    assert "GROWTH TENSOR" in MEANINGFUL_ACTIVATION["growth"]
    for name in families:
        assert len(MEANINGFUL_ACTIVATION[name]) > 80


def test_a_freely_growing_element_is_traction_free_so_a_face_may_be_held():
    """A growth that meets no resistance produces no stress, and an agreement
    about a zero is not a verification. The restrained variant holds the face
    at minimum x in the directions the author's own deck holds their plate's
    end -- ``Plate-1.LeftEnd, 1, 1`` and ``2, 2`` -- and leaves the opposite
    face free, so the element can still change volume and a material at
    nu = 0.4999 is never asked to change it against its own bulk modulus."""
    from umat_oti.abaqus.deck import generate_deck

    manifest = VerificationManifest(
        name="p", source=Path("p.for"), element_type="C3D8H",
        props=(1.0e7,), nstatv=9, kinematics="finite",
        plane_strain_directions=(3,))
    free = build(PURE_GROWTH, manifest)
    restrained = build(PURE_GROWTH, manifest, held=(1, 2), clamp_a_face=True)
    assert free.manifest.loading[0].clamped_face == ()
    assert restrained.manifest.loading[0].clamped_face == (1, 2)

    held = generate_deck(restrained.manifest).split("*BOUNDARY, OP=NEW")[1]
    held = held.split("*OUTPUT")[0]
    # The four nodes of the x = 0 face, in 1 and 2. The reference hexahedron
    # numbers them 1, 4, 5 and 8.
    for node in (1, 4, 5, 8):
        assert f"{node}, 1, 1, 0.0" in held
        assert f"{node}, 2, 2, 0.0" in held
    # ... and the opposite face keeps its x freedom, or the growth is blocked.
    assert "2, 1, 1, 0.0" not in held
    assert "the growth is resisted" in restrained.reason
