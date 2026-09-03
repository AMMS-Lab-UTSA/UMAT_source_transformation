"""The generated deck and the verification-only probe.

The deck is one parameterised single-element template driven entirely by a
manifest, so that a UMAT with no input deck of its own can still be run. Single
element and displacement-controlled on purpose: the strain history is then known
before the job runs, which is what a finite-difference check needs -- a
perturbation has to be applied to a known increment of strain.

The probe exists because Abaqus stores ODB field output in single precision.
Measured: a stress whose exact value is 2826.923076923077 comes back from
odbAccess as 2826.923095703125, bit-exactly float32 of it. That is fine for
comparing two primal histories and useless for a centred difference, where the
leading digits cancel and what is left is the answer.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.abaqus.deck import _displacement, generate_deck, total_increments  # noqa: E402
from umat_oti.abaqus.manifest import (  # noqa: E402
    VerificationManifest, reverse, simple_shear, uniaxial,
)
from umat_oti.abaqus.probe import instrument, parse_probe, probe_call  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "elastic_smoke_umat.for"


def _manifest(**kwargs) -> VerificationManifest:
    base = dict(name="m", source=FIXTURE, nprops=2, props=(210000.0, 0.3),
                material_provenance="test fixture", nstatv=1,
                loading=(uniaxial(0.01, 10),))
    base.update(kwargs)
    return VerificationManifest(**base)


class TestTheDeckDescribesTheModelItWasGiven:
    def test_the_material_vector_is_written_in_full(self):
        deck = generate_deck(_manifest(props=tuple(float(i) for i in range(20)),
                                       nprops=20))
        assert "*USER MATERIAL, CONSTANTS=20" in deck
        # Eight to a line is Abaqus's limit; all twenty have to survive it.
        body = deck.split("*USER MATERIAL, CONSTANTS=20\n", 1)[1]
        numbers = []
        for line in body.splitlines():
            if line.startswith("*"):
                break
            numbers += [token.strip() for token in line.split(",") if token.strip()]
        assert len(numbers) == 20

    def test_unsymm_is_requested_when_the_model_needs_it(self):
        assert ", UNSYMM" in generate_deck(_manifest(unsymmetric=True))
        assert ", UNSYMM" not in generate_deck(_manifest())

    def test_state_variables_are_declared(self):
        assert "*DEPVAR\n150," in generate_deck(_manifest(nstatv=150))

    def test_finite_strain_asks_for_nlgeom(self):
        assert "NLGEOM=YES" in generate_deck(_manifest(kinematics="finite"))
        assert "NLGEOM=NO" in generate_deck(_manifest())

    def test_an_orientation_is_attached_to_the_section(self):
        deck = generate_deck(_manifest(orientation=(30.0, 45.0, 60.0),
                                       orientation_provenance="deck"))
        assert "*ORIENTATION, NAME=CRYSTAL" in deck
        assert "ORIENTATION=CRYSTAL" in deck

    def test_the_provenance_of_the_material_is_recorded_in_the_deck(self):
        deck = generate_deck(_manifest(material_provenance="job-1.inp line 47"))
        assert "job-1.inp line 47" in deck

    def test_every_segment_becomes_a_step(self):
        deck = generate_deck(_manifest(
            loading=(uniaxial(0.01, 5), simple_shear(0.02, 7))))
        assert deck.count("*STEP") == 2
        assert total_increments((uniaxial(0.01, 5), simple_shear(0.02, 7))) == 12

    def test_initial_state_is_written_when_it_is_not_all_zero(self):
        assert "*INITIAL CONDITIONS, TYPE=SOLUTION" in generate_deck(
            _manifest(nstatv=3, initial_statev=(1.0, 1.0, 0.0),
                      initial_statev_provenance="the source's own SDVINI"))
        assert "*INITIAL CONDITIONS" not in generate_deck(
            _manifest(nstatv=3, initial_statev=(0.0, 0.0, 0.0)))


class TestTheStrainTheDeckActuallyApplies:
    def test_a_unit_extension_moves_the_far_face(self):
        assert _displacement((1.0, 0.0, 0.0), (0.01, 0, 0, 0, 0, 0)) == (0.01, 0.0, 0.0)

    def test_engineering_shear_is_halved_onto_both_off_diagonals(self):
        # Getting this factor wrong would perturb a different component than
        # the finite-difference column being compared against.
        ux, uy, _ = _displacement((0.0, 1.0, 0.0), (0, 0, 0, 0.02, 0, 0))
        assert ux == 0.01 and uy == 0.0
        ux, uy, _ = _displacement((1.0, 0.0, 0.0), (0, 0, 0, 0.02, 0, 0))
        assert ux == 0.0 and uy == 0.01

    def test_the_origin_never_moves(self):
        assert _displacement((0.0, 0.0, 0.0), (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)) == \
            (0.0, 0.0, 0.0)


class TestAManifestKnowsWhatItIsMissing:
    def test_no_material_is_named(self):
        assert "no material constants" in VerificationManifest(
            name="x", source=FIXTURE).missing_requirements()

    def test_constants_without_provenance_are_not_usable(self):
        missing = VerificationManifest(
            name="x", source=FIXTURE, props=(1.0,),
            loading=(uniaxial(),)).missing_requirements()
        assert any("provenance" in item for item in missing)

    def test_a_complete_manifest_is_missing_nothing(self):
        assert _manifest().missing_requirements() == ()

    def test_a_reversal_turns_the_path_around(self):
        back = reverse(uniaxial(0.01, 5))
        assert back.strain[0] < 0 and "reversal" in back.description


class TestTheProbeIsSeparateInertAndPlaced:
    def test_the_continuation_marker_sits_in_column_six(self):
        # Fixed form counts columns; column 7 is a syntax error.
        second = probe_call("t").splitlines()[1]
        assert second[5] == "1" and second[:5].strip() == ""

    def test_the_result_call_sits_before_the_return_of_the_entry_routine(self):
        text, ok = instrument(FIXTURE.read_text(), "orig")
        assert ok
        lines = text.splitlines()
        call = next(i for i, l in enumerate(lines)
                    if "CALL OTIS_PROBE(" in l)
        assert lines[call + 2].strip().upper() == "RETURN"

    def test_the_entry_call_comes_first_and_before_any_assignment(self):
        """STRESS and STATEV still hold the state the increment starts from.

        Recording them any later would record a starting point the UMAT had
        already begun to overwrite, and an offline replay of the increment
        would then start somewhere the solver never was.
        """
        text, ok = instrument(FIXTURE.read_text(), "orig")
        assert ok
        lines = text.splitlines()
        entry = next(i for i, l in enumerate(lines) if "CALL OTIS_PROBE_IN(" in l)
        result = next(i for i, l in enumerate(lines) if "CALL OTIS_PROBE(" in l)
        assert entry < result
        # nothing that runs precedes it inside the routine
        opener = next(i for i, l in enumerate(lines)
                      if re.search(r"SUBROUTINE\s+UMAT\b", l, re.IGNORECASE))
        for line in lines[opener + 1:entry]:
            if re.match(r"^[cC*!]", line) or not line.strip():
                continue
            assert "=" not in line.split("!")[0] or line.strip().upper().startswith(
                ("CHARACTER", "INTEGER", "REAL", "DOUBLE", "PARAMETER", "DIMENSION",
                 "IMPLICIT", "COMMON", "DATA")), line

    def test_a_continuation_line_is_never_split_by_the_entry_call(self):
        """Column 6 carries the tail of the statement above it."""
        text, ok = instrument(FIXTURE.read_text(), "orig")
        assert ok
        lines = text.splitlines()
        entry = next(i for i, l in enumerate(lines) if "CALL OTIS_PROBE_IN(" in l)
        following = lines[entry + 4]      # the call spans four lines
        assert not (len(following) > 5 and following[5] not in " \t")

    def test_it_touches_no_state_variable(self):
        """It reads STATEV to record it and never writes one.

        An implied-do "(STATEV(I),I=1,NSTATV)" contains an equals sign and
        assigns nothing, so the property has to be tested as a statement whose
        left-hand side is STATEV -- which is what would corrupt the model.
        """
        import re

        text, _ = instrument(FIXTURE.read_text(), "orig")
        body = text.split("SUBROUTINE OTIS_PROBE", 1)[1]
        writes = [line for line in body.splitlines()
                  if re.match(r"^\s{6,}STATEV\s*(\([^)]*\))?\s*=(?!=)", line,
                              re.IGNORECASE)]
        assert writes == [], writes

    def test_it_assigns_nothing_the_umat_reads(self):
        """Every assignment in the probe targets one of its own locals."""
        import re

        text, _ = instrument(FIXTURE.read_text(), "orig")
        body = text.split("SUBROUTINE OTIS_PROBE", 1)[1]
        own = {"FNAME", "IOS", "I", "J"}
        for line in body.splitlines():
            match = re.match(r"^\s{6,}([A-Z_]\w*)\s*(\([^)]*\))?\s*=(?!=)", line,
                             re.IGNORECASE)
            if match:
                assert match.group(1).upper() in own, line

    def test_a_source_with_no_umat_is_left_alone(self):
        text, ok = instrument("      SUBROUTINE OTHER(X)\n      RETURN\n      END\n",
                              "t")
        assert not ok and "OTIS_PROBE" not in text

    def test_the_record_round_trips(self, tmp_path):
        path = tmp_path / "p.txt"
        path.write_text(
            "RECORD orig        1        1        1        3   "
            " 0.10000000000000000E+001\n"
            "STRESS        2\n"
            "  0.28269230769230771E+004  0.12115384615384616E+004\n"
            "STATEV        1\n"
            "  0.10000000000000000E-001\n"
            "DDSDDE        4\n"
            "  0.1E+001  0.2E+001  0.3E+001  0.4E+001\n", encoding="utf-8")
        records = parse_probe(path)
        assert len(records) == 1
        assert records[0]["increment"] == 3
        assert records[0]["STRESS"][0] == 2826.9230769230771
        assert records[0]["DDSDDE"] == [1.0, 2.0, 3.0, 4.0]

    def test_a_missing_file_is_no_records_not_a_crash(self, tmp_path):
        assert parse_probe(tmp_path / "absent.txt") == []


def _driven(deck: str) -> list:
    """The prescribed-displacement lines: node, dof, same dof, value.

    Matching on the repeated degree of freedom is what separates them from an
    element connectivity line, which is also a row of comma-separated integers.
    """
    return [line for line in deck.splitlines()
            if re.match(r"^\d+, ([123]), \1, ", line)]


def test_a_tetrahedron_gets_tetrahedron_nodes():
    """Four nodes in three dimensions, not the first four corners of a cube.

    C3D8R would be the obvious one-integration-point element, but Abaqus
    refuses a reduced-integration element under a user material unless an
    hourglass stiffness is supplied, and that number is not ours to invent.
    The constant-strain tetrahedron has one integration point and no hourglass
    modes, so it needs nothing added.
    """
    from umat_oti.abaqus.deck import generate_deck
    from umat_oti.abaqus.manifest import VerificationManifest, uniaxial

    deck = generate_deck(VerificationManifest(
        name="t", source=Path("t.for"), element_type="C3D4",
        props=(1.0,), loading=(uniaxial(0.01, 2),)))
    lines = deck.splitlines()
    assert "*ELEMENT, TYPE=C3D4, ELSET=ONE" in lines
    assert lines[lines.index("*ELEMENT, TYPE=C3D4, ELSET=ONE") + 1] == "1, 1, 2, 3, 4"
    # every node driven in all three directions: four nodes times three
    assert len(_driven(deck)) == 12


def test_a_plane_element_is_driven_in_two_directions_only():
    from umat_oti.abaqus.deck import generate_deck
    from umat_oti.abaqus.manifest import VerificationManifest, uniaxial

    deck = generate_deck(VerificationManifest(
        name="t", source=Path("t.for"), element_type="CPE4",
        props=(1.0,), loading=(uniaxial(0.01, 2),)))
    driven = _driven(deck)
    assert len(driven) == 8                      # four nodes, two directions
    assert not any(line.split(", ")[1] == "3" for line in driven)


def _call(increment, stress, point=1, step=1, element=1):
    return {"element": element, "point": point, "step": step,
            "increment": increment, "STRESS": list(stress)}


def test_only_the_converged_call_of_each_increment_is_kept():
    """A UMAT is called once per iteration; only the last one was accepted."""
    from umat_oti.abaqus.probe import converged_only

    kept = converged_only([
        _call(1, [10.0]), _call(1, [11.0]), _call(1, [11.5]),   # three iterations
        _call(2, [20.0]), _call(2, [21.0]),                     # two
    ])
    assert [record["increment"] for record in kept] == [1, 2]
    assert [record["STRESS"] for record in kept] == [[11.5], [21.0]]


def test_iteration_counts_may_differ_without_being_a_disagreement():
    """The whole point: how many passes a solve took is not a material fact."""
    from umat_oti.abaqus.compare import compare_primal
    from umat_oti.abaqus.probe import converged_only

    left = converged_only([_call(1, [10.0]), _call(1, [12.0])])
    right = converged_only([_call(1, [3.0]), _call(1, [9.0]), _call(1, [12.0])])
    assert compare_primal(left, right).agrees


def test_points_and_steps_are_kept_apart():
    from umat_oti.abaqus.probe import converged_only

    kept = converged_only([_call(1, [1.0], point=1), _call(1, [2.0], point=2),
                           _call(1, [3.0], point=1, step=2)])
    assert len(kept) == 3


class TestADeclaredStartingPoint:
    """An unloaded material point, driven along the input the source reads.

    Which input carries the increment is read from the transformed file rather
    than assumed. Guessing it wrong is silent and total: a hyperelastic source
    that computes its stress from the deformation gradient, handed an identity
    gradient and a nonzero DSTRAN, returns zero stress at every increment.
    Both builds then return zero, and a comparison that accepted that would
    report perfect agreement about a model neither had exercised. The corpus's
    NeoHookean source did exactly this until the drive was read.
    """

    def test_a_source_with_no_transform_to_read_is_driven_by_the_strain(self):
        from umat_oti.abaqus.replay import declared_start

        state = declared_start((1.0, 2.0), ntens=6, strain=1e-4)
        assert state["DSTRAN"][0] == 1e-4
        assert state["driven_through"] == "strain increment"
        assert state["DFGRD1"] == [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]

    def test_a_gradient_driven_source_advances_the_gradient(self, tmp_path):
        """DFGRD1 must move, or the source sees no deformation at all."""
        from umat_oti.abaqus.replay import declared_start

        emitted = tmp_path / "u_oti.for"
        emitted.write_text(
            "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)\n"
            "      DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1\n"
            "      RETURN\n      END\n", encoding="utf-8")
        state = declared_start((1.0,), ntens=6, strain=1e-4,
                               transformed_source=emitted)
        assert state["driven_through"] == "deformation gradient"
        assert state["DFGRD1"][0] != 1.0

    def test_the_state_is_zero_because_the_point_is_unloaded(self):
        from umat_oti.abaqus.replay import declared_start

        state = declared_start((1.0,), ntens=6, nstatv=4)
        assert state["STRESS0"] == [0.0] * 6
        assert state["STATEV0"] == [0.0] * 4
        assert state["STRAN"] == [0.0] * 6

    def test_a_published_initial_state_is_used_when_given(self):
        """A growth model's author may publish an initial stretch of 1.0.

        Running it from zeros is a different model, so a caller that has read
        one from a deck can supply it and it is not overwritten.
        """
        from umat_oti.abaqus.replay import declared_start

        state = declared_start((1.0,), nstatv=3, initial_statev=(1.0, 1.0, 1.0))
        assert state["STATEV0"] == [1.0, 1.0, 1.0]

    def test_the_probe_coordinates_are_neither_the_origin_nor_all_ones(self):
        """Models here divide by COORDS(1)**2 - COORDS(2)**2, which both zero."""
        from umat_oti.abaqus.replay import declared_start

        coords = declared_start((1.0,))["COORDS"][:3]
        assert coords != [0.0, 0.0, 0.0] and coords != [1.0, 1.0, 1.0]
        assert coords[0] ** 2 != coords[1] ** 2

    def test_the_state_round_trips_through_write_state(self, tmp_path):
        """It has to be the shape write_state accepts, or the driver reads junk."""
        from umat_oti.abaqus.replay import STATE_FILE, declared_start, write_state

        state = declared_start((1.0, 2.0, 3.0), ntens=6, nstatv=2)
        write_state(state, tmp_path / STATE_FILE)
        first = (tmp_path / STATE_FILE).read_text().splitlines()[0].split()
        assert first == ["6", "2", "3", "3", "3"]


class TestAProbeRecordThatCouldNotBeWritten:
    """A Fortran field that does not fit its format writes asterisks.

    Found on the first real batch: one source's probe wrote
    `SHAPE 6 ******** 2 3 3`, having printed `NSTATV 0` in its first record,
    while the paired deck declares `*DEPVAR 9`. NSTATV is an argument Abaqus
    passes in, so something wrote over it during the run.

    Which array overran is NOT established, and an earlier version of this
    docstring claimed it was an undersized state array. For that source the
    deck's *DEPVAR, the highest literal STATEV subscript and the constant
    count all agree, so that explanation does not hold; a computed subscript
    or a local array would look the same from here.

    What is established is that such a record's numbers are not measurements.
    The parser crashed on it with `invalid literal for int()`, which turned a
    finding about the run into a crash in the harness.
    """

    def test_an_overflowed_shape_field_is_reported_not_crashed_on(self, tmp_path):
        from umat_oti.abaqus.probe import CORRUPT, parse_probe

        path = tmp_path / "p.txt"
        path.write_text(
            "ENTRY t        1        1        1        1   0.0E+000\n"
            "SHAPE        6 ********        2        3        3\n"
            "STATEV0 ********\n", encoding="utf-8")
        records = parse_probe(path)
        assert len(records) == 1
        assert CORRUPT in records[0]
        assert "overwrote its own argument list" in records[0][CORRUPT] or \
            "damaged its own interface" in records[0][CORRUPT]

    def test_nothing_past_the_corrupt_field_is_parsed(self, tmp_path):
        """Once NSTATV is unreadable there is no way to know how many values
        follow, so anything read past it would be guesswork dressed as data."""
        from umat_oti.abaqus.probe import CORRUPT, parse_probe

        path = tmp_path / "p.txt"
        path.write_text(
            "ENTRY t        1        1        1        1   0.0E+000\n"
            "SHAPE        6 ********        2        3        3\n"
            "STRESS0        6\n"
            "   1.0E+000   2.0E+000   3.0E+000   4.0E+000\n", encoding="utf-8")
        record = parse_probe(path)[0]
        assert CORRUPT in record
        assert "STRESS0" not in record

    def test_an_overflowed_record_header_is_reported(self, tmp_path):
        from umat_oti.abaqus.probe import CORRUPT, parse_probe

        path = tmp_path / "p.txt"
        path.write_text("ENTRY t ******** 1 1 1   0.0E+000\n", encoding="utf-8")
        assert CORRUPT in parse_probe(path)[0]

    def test_an_unreadable_number_in_a_block_is_reported(self, tmp_path):
        from umat_oti.abaqus.probe import CORRUPT, parse_probe

        path = tmp_path / "p.txt"
        path.write_text(
            "ENTRY t        1        1        1        1   0.0E+000\n"
            "STRESS0        2\n   1.0E+000   ****\n", encoding="utf-8")
        assert CORRUPT in parse_probe(path)[0]

    def test_a_clean_file_carries_no_corruption_marker(self, tmp_path):
        """The guard must not label a healthy record."""
        from umat_oti.abaqus.probe import CORRUPT, parse_probe

        path = tmp_path / "p.txt"
        path.write_text(
            "ENTRY t        1        1        1        1   0.0E+000\n"
            "SHAPE        6        4        2        3        3\n"
            "STRESS0        2\n   1.0E+000   2.0E+000\n", encoding="utf-8")
        record = parse_probe(path)[0]
        assert CORRUPT not in record
        assert record["STRESS0"] == [1.0, 2.0]
        assert record["NSTATV"] == 4


class TestTheProbeNamesWhatTheRoutineHas:
    """Three ways the probe made a source stop compiling, each measured.

    All three had the same shape: the job never started, so the entry was
    recorded as a failure of somebody's model for a defect in this harness.
    With them fixed, 194 of the corpus's 199 originals instrument and compile;
    the remaining 5 have no call site and are reported as that.
    """

    def test_the_newer_abaqus_interface_uses_jstep_not_kstep(self):
        """Abaqus replaced the scalar KSTEP with the array JSTEP(4).

        A source written against it rejected the probe with "This name does not
        have a type" on KSTEP.
        """
        from umat_oti.abaqus.probe import instrument

        source = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NOEL,NPT,\n"
                  "     &    LAYER,KSPT,JSTEP,KINC)\n"
                  "      IMPLICIT NONE\n"
                  "      INTEGER JSTEP(4)\n"
                  "      STRESS(1) = 1.0\n"
                  "      RETURN\n      END\n")
        text, ok = instrument(source, "t")
        assert ok
        call = next(l for l in text.splitlines() if "OTIS_PROBE_IN(" in l)
        assert "JSTEP(1)" in call and ",KSTEP," not in call

    def test_a_routine_with_kstep_still_uses_kstep(self):
        from umat_oti.abaqus.probe import instrument

        source = ("      SUBROUTINE UMAT(STRESS,NOEL,NPT,KSTEP,KINC)\n"
                  "      STRESS(1) = 1.0\n"
                  "      RETURN\n      END\n")
        text, _ = instrument(source, "t")
        call = next(l for l in text.splitlines() if "OTIS_PROBE_IN(" in l)
        assert ",KSTEP," in call

    def test_a_routine_with_neither_records_a_literal(self):
        """The step number labels a record; it is not a measurement, so the
        probe should still compile rather than refuse the source."""
        from umat_oti.abaqus.probe import step_expression

        assert step_expression({"STRESS", "NOEL"}) == "1"

    def test_an_indented_free_style_comment_is_a_comment(self):
        """`! variables passed in` at column 9 read as a statement, was called
        executable, and the probe went in above the type declarations that
        followed it -- so every argument it named had no type yet."""
        from umat_oti.abaqus.probe import _is_comment

        assert _is_comment("        ! variables passed in")
        assert _is_comment("C     a fixed-form comment")
        assert _is_comment("   \t ")
        # a trailing comment does not make the line one
        assert not _is_comment("      X = 1.0 ! set it")

    def test_the_probe_goes_after_the_declarations_it_names(self):
        from umat_oti.abaqus.probe import instrument

        source = ("      SUBROUTINE UMAT(STRESS,NOEL,NPT,KSTEP,KINC)\n"
                  "        use NumKind\n"
                  "        implicit none\n"
                  "        ! variables passed in\n"
                  "        integer(ikind) :: noel, npt, kstep, kinc\n"
                  "        real(rkind) :: stress(6)\n"
                  "        stress(1) = 1.0\n"
                  "      RETURN\n      END\n")
        text, ok = instrument(source, "t")
        assert ok
        lines = text.splitlines()
        call = next(i for i, l in enumerate(lines) if "OTIS_PROBE_IN(" in l)
        declaration = next(i for i, l in enumerate(lines)
                           if "real(rkind)" in l)
        assert call > declaration, "the probe precedes the types it names"


def test_a_zero_length_block_does_not_end_the_record(tmp_path):
    """A model with no state variables writes `STATEV 0` and a blank line.

    Fortran still performs the WRITE, so the empty implied-do emits an empty
    record. Reading that blank as the end of the probe record dropped the
    DDSDDE that follows it -- and with it the tangent check for every
    stateless model. Six of the eight entries that had already agreed on
    their primal histories in Abaqus were blocked by exactly this.
    """
    from umat_oti.abaqus.probe import parse_probe

    path = tmp_path / "p.txt"
    path.write_text(
        "RECORD t        1        1        1        1   0.0E+000\n"
        "STRESS        2\n"
        "   1.0E+000   2.0E+000\n"
        "STATEV        0\n"
        "\n"
        "DDSDDE        4\n"
        "   10.0E+000   20.0E+000   30.0E+000   40.0E+000\n", encoding="utf-8")
    record = parse_probe(path)[0]
    assert record["STATEV"] == []
    assert record["DDSDDE"] == [10.0, 20.0, 30.0, 40.0]


def test_a_blank_line_does_not_merge_two_records(tmp_path):
    """The record still ends at the next ENTRY or RECORD."""
    from umat_oti.abaqus.probe import parse_probe

    path = tmp_path / "p.txt"
    path.write_text(
        "RECORD t        1        1        1        1   0.0E+000\n"
        "STATEV        0\n"
        "\n"
        "RECORD t        1        1        1        2   1.0E+000\n"
        "STRESS        1\n"
        "   5.0E+000\n", encoding="utf-8")
    records = parse_probe(path)
    assert len(records) == 2
    assert "STRESS" not in records[0]
    assert records[1]["STRESS"] == [5.0]
    assert records[1]["increment"] == 2
