"""Thirteen sources wrote a growth tensor and switched it off in the constants.

``PureGravity.for`` builds its growth exactly the way its growing siblings do::

    Lambda1z0 = 1.0
    Lambda1z1 = 0.0
    DtltaG11  = (Lambda1z0 + Y*Lambda1z1 - 1.0)*(TIME(1)+DTIME)/TotalT
    G11       = 1.0 + DtltaG11
    STATEV(8) = G11

and computes no growth at all: with those two constants the increment is
identically zero for every Y and every time. The file is named PureGravity and
its deformation comes from the body force its own ``SUBROUTINE DLOAD``
computes. In the pass10 corpus run ten of those entries reached
``experiment_not_informative`` on "STATEV(8) moved 0.000%, STATEV(9) moved
0.000%". The gate was right. The family was wrong.

What makes the fix a fix and not a patch is that the filename decides nothing.
In the same repository:

* ``HelixUp/Th002/PureGravity.for`` -- same name, same variables, same
  statements -- writes ``Lambda1z0 = (3*Sqrt(1 + 16*Pi**2*X**4))/5.`` against
  the point's coordinate. It really grows, and it reached ``verified``.
* ``Flat/Th001/PureGrowth.for`` -- the growth filename -- carries
  PureGravity's constants and computes no growth either.

So a rule keyed on the name, in either direction, gets one of those two wrong.
Only the constants decide, and deciding on them is constant propagation.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.constant_folding import (LOAD_ROUTINES, fold,
                                              fold_expression, role_of,
                                              routines)
from umat_oti.abaqus.experiment import (classify, clock_reading,
                                        growth_developed,
                                        state_is_not_its_own,
                                        deformed_under_the_load,
                                        growth_state_slots,
                                        time_driven_state_slots)

pytestmark = pytest.mark.unit

CACHE = Path(__file__).resolve().parents[2] / "discovery_cache"
JEFF97 = (CACHE / "Jeff97__Programming-Plane-Strain-Plates-through-Growth-"
                  "Under-Body-Forces")

#: The growth switched off, reduced to the statements that do it. The DLOAD
#: applies a real force, which is what makes the answer "body force" rather
#: than "no experiment".
IDENTITY_GROWTH = """\
      SUBROUTINE DLOAD(F,KSTEP,KINC,TIME,NOEL,NPT,LAYER,KSPT,
     1 COORDS,JLTYP,SNAME)
        RhoR = 1000.0
        fZ = -10.0
        TotalT = 1.0
        TargetF = RhoR*fZ
        F = TargetF*TIME(1)/TotalT
      RETURN
      END
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
        Y = STATEV(2)
        Lambda1z0 = 1.0
        Lambda2z0 = 1.0
        Lambda1z1 = 0.0
        Lambda2z1 = 0.0
        TotalT = 1.0
        DtltaG11 = (Lambda1z0 + Y*Lambda1z1-1.0)
     &             *(TIME(1)+DTIME)/TotalT
        DtltaG22 = (Lambda2z0 + Y*Lambda2z1-1.0)*(TIME(1)+DTIME)/TotalT
        G11 = 1.0+DtltaG11
        G22 = 1.0+DtltaG22
        STATEV(8) = G11
        F = DFGRD1
      RETURN
      END
"""

#: The same file with the author's growing coefficients. One constant differs.
REAL_GROWTH = IDENTITY_GROWTH.replace(
    "        Lambda1z0 = 1.0\n", "        Lambda1z0 = Pi/2.\n").replace(
    "        Lambda1z1 = 0.0\n", "        Lambda1z1 = Pi\n").replace(
    "        Y = STATEV(2)\n", "        Y = STATEV(2)\n        Pi = 3.14159\n")


def jeff97(relative: str) -> Path:
    path = JEFF97 / relative
    if not path.exists():
        pytest.skip(f"corpus source not cached: {relative}")
    return path


# ---------------------------------------------------------------------------
# the arithmetic the rule needs
# ---------------------------------------------------------------------------
def test_a_known_zero_annihilates_an_unknown_factor():
    """``Y*Lambda1z1`` is zero for every Y once Lambda1z1 folds to zero, and
    without that rule nothing here is decidable: Y is a coordinate read back
    out of STATEV and is unknown by construction."""
    assert fold_expression("(1.0 + Y*0.0 - 1.0)*(TIME(1)+DTIME)/1.0") == 0.0
    # And it does not over-reach: a non-zero coefficient leaves it unknown.
    assert fold_expression("(1.0 + Y*3.14 - 1.0)*(TIME(1)+DTIME)/1.0") is None


def test_the_fold_says_constant_or_undecided_and_never_says_varies():
    """The one-directional property the whole reclassification rests on. An
    expression this cannot evaluate comes back None, and a None keeps a source
    in the growth family."""
    assert fold_expression("2.0 + 3.0*4.0") == 14.0
    assert fold_expression("Sqrt(16.0)/2.0") == 2.0
    for undecidable in ("PROPS(1)*2.0", "f(x) + 1", "1.0/UNKNOWN",
                        "(/ 1,5,9 /)", "TIME(1)", "1.0 +"):
        assert fold_expression(undecidable) is None, undecidable


def test_fortran_binds_a_power_tighter_than_a_unary_sign():
    """``-X**2`` is ``-(X**2)``. Getting that backwards changes the sign of a
    growth coefficient, which is the difference between growing and shrinking."""
    assert fold_expression("-2.0**2") == -4.0
    assert fold_expression("(-2.0)**2") == 4.0


def test_a_dummy_argument_is_never_a_constant():
    """Its value comes from the caller. A routine that assigns to its own
    argument and a routine that reads one are both outside what this can
    decide."""
    text = ("      SUBROUTINE HELPER(A,B)\n"
            "        A = 2.0\n"
            "        C = A*3.0\n"
            "      RETURN\n      END\n")
    folding = fold(text)
    assert not folding.is_constant("A")
    assert not folding.is_constant("C")


def test_a_conditional_assignment_pins_nothing():
    """It may not execute, and a loop may execute it many times. Either way
    the name has no single value from there on."""
    text = ("      SUBROUTINE UMAT(STRESS)\n"
            "        X = 1.0\n"
            "        IF (KSTEP .EQ. 2) THEN\n"
            "          X = 5.0\n"
            "        END IF\n"
            "        Y = X*2.0\n"
            "      RETURN\n      END\n")
    folding = fold(text)
    assert not folding.is_constant("X")
    assert not folding.is_constant("Y")


def test_an_expression_sees_only_what_the_statements_above_it_fixed():
    """A single forward pass and not a fixed point. A fixed point would fold
    ``TotalT`` into a statement written before ``TotalT = 1.0``, which is not
    what the program does."""
    text = ("      SUBROUTINE UMAT(STRESS)\n"
            "        EARLY = SCALE*2.0\n"
            "        SCALE = 3.0\n"
            "        LATE = SCALE*2.0\n"
            "      RETURN\n      END\n")
    folding = fold(text)
    assert not folding.is_constant("EARLY")
    assert folding.value("LATE") == 6.0


def test_a_name_is_a_name_only_inside_one_routine():
    """``PureGravity.for`` computes the scalar body force F from the clock in
    its DLOAD and assigns the deformation gradient to a different F in its
    UMAT. Read as one namespace the load ramp made the material look like a
    growth law, and no filter downstream could undo it."""
    folding = fold(IDENTITY_GROWTH)
    assert set(folding.assigned_in["F"]) == {"DLOAD", "UMAT"}
    assert folding.roles["DLOAD"] == "load"
    assert folding.roles["UMAT"] == "material"


def test_a_load_definition_is_a_load_definition_whatever_its_arity():
    """Abaqus documents DLOAD with eleven arguments and the interface table
    this reuses records twelve. Demoting a real DLOAD over that disagreement
    put its ``F = TargetF*TIME(1)/TotalT`` ramp back among the growth
    candidates, so the count is not what decides a load routine's role."""
    assert role_of("DLOAD", 11) == "load"
    assert role_of("DLOAD", 12) == "load"
    assert "VUAMP" in LOAD_ROUTINES
    # A private helper that borrows a material interface's NAME is still
    # caught by the count, because there a wrong answer adds growth.
    assert role_of("UMAT", 9) == "utility"
    assert role_of("UMAT", 37) == "material"


# ---------------------------------------------------------------------------
# what it decides about the corpus
# ---------------------------------------------------------------------------
def test_growth_switched_off_in_the_constants_is_not_a_growth_law():
    reading = clock_reading(IDENTITY_GROWTH)
    assert reading.slots == {}
    assert "STATEV(8)" in reading.constant
    assert "1 for all time" in reading.constant["STATEV(8)"]
    assert growth_state_slots(IDENTITY_GROWTH) == {}
    assert classify(IDENTITY_GROWTH, element="C3D8H").name == "body force"


def test_one_changed_coefficient_is_the_whole_difference():
    """The same file, the same statements, one constant different."""
    assert classify(IDENTITY_GROWTH, element="C3D8H").name == "body force"
    assert classify(REAL_GROWTH, element="C3D8H").name == "growth"
    assert sorted(growth_state_slots(REAL_GROWTH)) == [8]


def test_a_clock_ramp_in_a_load_definition_is_not_a_material_growing():
    """``F = TargetF*TIME(1)/TotalT`` inside DLOAD is gravity being switched on
    over the step. That is what the body-force family is for."""
    reading = clock_reading(IDENTITY_GROWTH)
    assert "F" in reading.load_only
    assert "F" not in reading.driven
    family = classify(IDENTITY_GROWTH, element="C3D8H")
    assert family.name == "body force"
    assert any("load definition" in note for note in family.notes)


def test_the_reclassification_says_why_in_the_record():
    """A body-force verification whose source writes a growth tensor has to
    say so, or the next reader asks the same question again."""
    family = classify(IDENTITY_GROWTH, element="C3D8H")
    said = " ".join(family.notes)
    assert "literal constants fix" in said
    assert "STATEV(8)" in said


def test_the_clock_renamed_into_a_local_is_not_a_quantity_computed_from_it():
    """``time_n = TIME(2)`` is the clock, spelled differently. Forty-three
    corpus sources were in the growth family on statements of exactly that
    form, which bought each of them a time-only experiment with no strain in
    it -- for crystal plasticity, for NEML, for viscoelastic curing."""
    text = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)\n"
            "        time_n = TIME(2)\n"
            "        time_np1 = TIME(2) + DTIME\n"
            "        CALL NEML(time_n, time_np1, STRESS)\n"
            "      RETURN\n      END\n")
    reading = clock_reading(text)
    assert sorted(reading.clock_only) == ["TIME_N", "TIME_NP1"]
    assert reading.driven == {}
    assert classify(text, element="C3D8").name != "growth"


def test_a_chain_through_a_renamed_clock_is_still_a_growth_quantity():
    """The filter removes the rename, not what is computed from it."""
    text = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)\n"
            "        t = TIME(1)\n"
            "        theta = 1.0 + (tmax - 1.0)*t/TotalT\n"
            "        STATEV(1) = theta\n"
            "      RETURN\n      END\n")
    reading = clock_reading(text)
    assert "T" in reading.clock_only
    assert sorted(reading.slots) == [1]
    assert classify(text, element="C3D8").name == "growth"


# ---------------------------------------------------------------------------
# against the corpus itself
# ---------------------------------------------------------------------------
def test_the_filename_decides_nothing_and_the_constants_decide_everything():
    """The four sources that make any name-keyed rule wrong. Two are called
    PureGravity and disagree with each other; two are called PureGrowth and
    disagree with each other."""
    cases = {
        "Examples-In-Section-3/ArcDown/Th001/PureGravity.for": "body force",
        "Examples-In-Section-3/HelixUp/Th002/PureGravity.for": "growth",
        "Examples-In-Section-3/Flat/Th001/PureGrowth.for": "finite strain",
        "Examples-In-Section-3/ArcDown/Th001/PureGrowth.for": "growth",
    }
    for relative, expected in cases.items():
        path = jeff97(relative)
        found = classify(path.read_text(errors="replace"),
                         element="C3D8H", path=path)
        assert found.name == expected, f"{relative}: {found.name}"


def test_the_helix_variants_that_verified_keep_their_family():
    """``HelixUp/Th002`` and ``HelixUp/Th005`` reached verified in pass10 on a
    growth experiment. A reclassification that moved them would be worse than
    the bug it fixes."""
    for thickness in ("Th001", "Th002", "Th005", "Th01"):
        path = jeff97(f"Examples-In-Section-3/HelixUp/{thickness}/"
                      "PureGravity.for")
        text = path.read_text(errors="replace")
        assert classify(text, element="C3D8H", path=path).name == "growth"
        assert sorted(growth_state_slots(text)) == [8, 9]


def test_the_coordinate_dependence_is_what_keeps_helix_undecidable():
    """``Lambda1z0 = (3*Sqrt(1 + 16*Pi**2*X**4))/5.`` reads the point's
    coordinate. The fold cannot evaluate it and does not try to, which is the
    one-directional property doing its job on a real file."""
    path = jeff97("Examples-In-Section-3/HelixUp/Th002/PureGravity.for")
    folding = fold(path.read_text(errors="replace"), path=path)
    assert not folding.is_constant("Lambda1z0")
    assert not folding.is_constant("DtltaG11")
    assert not folding.is_constant("STATEV(8)")
    # while the component the author really did switch off is decided
    assert folding.value("DtltaG22") == 0.0


def test_every_jeff97_source_lands_where_its_constants_put_it():
    """Over the whole repository: ten become body force, four become finite
    strain, fifty stay growth. The ten and the four are exactly the entries
    that reached experiment_not_informative in pass10 on a growth that never
    happened."""
    if not JEFF97.exists():
        pytest.skip("corpus repository not cached")
    families: dict[str, int] = {}
    for path in sorted(JEFF97.rglob("*.for")):
        found = classify(path.read_text(errors="replace"),
                         element="C3D8H", path=path)
        families[found.name] = families.get(found.name, 0) + 1
    assert families == {"body force": 10, "finite strain": 4, "growth": 50}


def test_the_statev_slots_reached_by_the_clock_stay_wider_than_the_growth_set():
    """Two readings, kept apart: what the clock REACHES and what it DECIDES.
    Collapsing them loses the ability to say which of the two a slot failed."""
    text = jeff97("Examples-In-Section-3/ArcDown/Th001/PureGravity.for"
                  ).read_text(errors="replace")
    assert sorted(time_driven_state_slots(text)) == [8, 9]
    assert growth_state_slots(text) == {}


# ---------------------------------------------------------------------------
# the criterion that is still weak, stated rather than hidden
# ---------------------------------------------------------------------------
def test_a_body_force_finding_reports_the_size_it_reached():
    """"Moved at all" is a threshold at the resolution of the instrument, not
    at a size that means anything mechanically. The ten reclassified entries
    reach 5.5e-07 to 1.4e-05 strain and 1.3e-06 to 3.1e-05 of their own
    largest material constant, so the finding carries the ratio and the
    weakness is visible in the record instead of hidden behind a boolean."""
    records = [{"kind": "result", "STRAN": [5.497e-7, 0, 0],
                "STRESS": [12.78, 0, 0]}]
    found = deformed_under_the_load(records, props=(1e7, 0.4999))
    assert found.met is True
    assert "1.278e-06" in found.reason
    assert "largest material constant of 1e+07" in found.reason
    # and the failure it exists to catch still fails
    silent = deformed_under_the_load([{"kind": "result", "STRAN": [0.0] * 6}],
                                     props=(1e7,))
    assert silent.met is False


# ---------------------------------------------------------------------------
# the eighteenth entry: a different finding of the same shape
# ---------------------------------------------------------------------------
GHOST_UMAT = """\
      SUBROUTINE UEL(RHS,AMATRX,SVARS,ENERGY,NDOFEL,NRHS,NSVARS,
     1 PROPS,NPROPS,COORDS,MCRD,NNODE,U,DU,V,A,JTYPE,TIME,DTIME,
     2 KSTEP,KINC,JELEM,PARAMS,NDLOAD,JDLTYP,ADLMAG,PREDEF,NPREDF,
     3 LFLAGS,MLVARX,DDLMAG,MDLOAD,PNEWDT,JPROPS,NJPROP,PERIOD)
       COMMON/KUSER/USRVAR(4434,18,4)
       USRVAR(JELEM,1,1) = SVARS(1)
      RETURN
      END
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
       COMMON/KUSER/USRVAR(4434,18,4)
       EMOD=PROPS(1)
       ENU=PROPS(2)
       NELEMAN=NOEL-8868
       DO I=1,NSTATV
        STATEV(I)=USRVAR(NELEMAN,I,NPT)
       END DO
      RETURN
      END
"""


def test_a_routine_that_copies_its_state_in_does_not_own_it():
    """``plate_with_notch.for``'s UMAT is a visualisation ghost: a user element
    carries the mechanics and this puts the element's results where the ODB can
    see them. Driven alone there is no UEL to fill COMMON/KUSER/, so no state
    variable can move -- which is a fact about the experiment's reach, not
    about the material, and no amplitude, clock or load changes it."""
    said = state_is_not_its_own(GHOST_UMAT)
    assert "copied out of a COMMON block" in said
    assert "USRVAR" in said
    assert any("COMMON block" in note
               for note in classify(GHOST_UMAT, element="CPS4").notes)


def test_a_routine_that_computes_its_state_owns_it():
    """The check has to stay off every source that writes its own state, or it
    is a sentence printed on 1933 records that means nothing."""
    assert state_is_not_its_own(IDENTITY_GROWTH) == ""
    assert state_is_not_its_own(REAL_GROWTH) == ""


def test_the_ghost_umats_in_the_corpus_are_the_two_that_are_ghosts():
    """Two sources in the corpus do this and both are the same construction: a
    user element plus a ghost continuum element to carry its output."""
    for relative in ("hamza-djeloud__thesis_project/plate_with_notch.for",
                     "irfancn__Abaqus-UEL-elastic/uel_elastic.for"):
        path = CACHE / relative
        if not path.exists():
            pytest.skip(f"corpus source not cached: {relative}")
        assert state_is_not_its_own(path.read_text(errors="replace"),
                                    path=path)


# ---------------------------------------------------------------------------
# a small growth and a short run are two different failures
# ---------------------------------------------------------------------------
def _grown(to, at_time):
    return [{"kind": "result", "time": 0.0, "STATEV": [0.0] * 7 + [1.0, 1.0]},
            {"kind": "result", "time": at_time,
             "STATEV": [0.0] * 7 + [to, 1.0]}]


def test_a_growth_that_ran_its_whole_clock_is_not_a_run_that_stopped_early():
    """``BodyForce-Growth-2Stages.for`` builds its growth on the author's own
    ``Epsilon = RhoR*fZ*L/C0``, and C0 is the single constant the deck
    publishes. At the 25 MPa deck that caps |G11-1| at 0.2997% anywhere in the
    element, so no experiment of any length reaches 1%; at the 1 MPa deck the
    same source reaches 75% and passes. Two pass10 entries failed at 0.383% and
    0.195% having run the whole of their clock, and a message that says only
    "the material near its initial state" invites lengthening a complete run."""
    complete = growth_developed(_grown(1.00383, 2.2), {8: "G11"},
                                total_time=2.2)
    assert complete.met is False
    assert "not a short run" in complete.reason
    assert "this model's growth is small" in complete.reason

    truncated = growth_developed(_grown(1.00383, 2.2), {8: "G11"},
                                 total_time=10.0)
    assert truncated.met is False
    assert "cut off rather than small" in truncated.reason


def test_the_threshold_itself_does_not_move():
    """The distinction is in what the failure SAYS, not in what it takes to
    pass. A growth of 0.383% is still not a growth of 1%."""
    assert growth_developed(_grown(1.00383, 2.2), {8: "G11"},
                            total_time=2.2).met is False
    assert growth_developed(_grown(1.02, 2.2), {8: "G11"},
                            total_time=2.2).met is True


# ---------------------------------------------------------------------------
# the Fortran the fold has to survive without ever claiming too much
# ---------------------------------------------------------------------------
def _routine(body: str) -> str:
    return ("      SUBROUTINE UMAT(S)\n" + body + "      RETURN\n      END\n")


@pytest.mark.parametrize("label,body,expected", [
    ("a labelled DO poisons its body, and CONTINUE closes it",
     "        X = 1.0\n        DO 100 I=1,3\n          X = 2.0\n"
     "  100   CONTINUE\n        Y = X\n", {"X": None, "Y": None}),
    ("a loop variable is never a constant",
     "        DO I=1,3\n          A = I\n        END DO\n",
     {"I": None, "A": None}),
    ("ELSE IF does not unbalance the nesting",
     "        IF (A .GT. 1) THEN\n          Q = 1.0\n"
     "        ELSE IF (A .GT. 0) THEN\n          Q = 2.0\n"
     "        ELSE\n          Q = 3.0\n        END IF\n        Z = 4.0\n",
     {"Q": None, "Z": 4.0}),
    ("a repeated agreeing assignment still pins",
     "        T = 1.0\n        T = 1.0\n        W = T*5.0\n",
     {"T": 1.0, "W": 5.0}),
    ("a disagreeing reassignment pins nothing",
     "        T = 1.0\n        T = 2.0\n        W = T*5.0\n",
     {"T": None, "W": None}),
    ("an accumulation pins nothing",
     "        T = 1.0\n        T = T + 1.0\n", {"T": None}),
    ("an array constructor does not crash the parser",
     "        Seq=(/ 1,5,9,2,3,6 /)\n        G = 2.0\n",
     {"SEQ": None, "G": 2.0}),
])
def test_the_fold_reads_real_fortran_without_overclaiming(label, body,
                                                          expected):
    folding = fold(_routine(body))
    assert {name: folding.value(name) for name in expected} == expected, label


def test_a_parameter_declaration_is_a_constant_by_the_language_s_own_rules():
    """It cannot be assigned, so it is the one place a value can be read
    without a dataflow argument."""
    folding = fold(_routine("      PARAMETER (ONE=1.0,TWO=2.0)\n"
                            "        X = ONE + TWO*3.0\n"))
    assert folding.value("X") == 7.0


def test_both_fortran_exponent_spellings_and_a_literal_divide_by_zero():
    assert fold_expression("1.5d0*2.0") == 3.0
    assert fold_expression("1.5E-3*2.0") == 0.003
    assert fold_expression("1.0/0.0") is None
    # annihilation reaches inside an intrinsic's argument
    assert fold_expression("Sqrt(4.0 + Y*0.0)") == 2.0


def test_no_entry_this_reclassifies_contains_a_goto():
    """A backward jump can re-enter a region read as straight-line, so the
    module records GOTOs rather than assuming them away. Over the 1933 corpus
    proposals, none of the sources whose family this changes has one -- so for
    them the straight-line reading is not a reading but an exactness."""
    for relative in ("Examples-In-Section-3/ArcDown/Th001/PureGravity.for",
                     "Examples-In-Section-3/Flat/Th001/PureGrowth.for"):
        path = jeff97(relative)
        assert fold(path.read_text(errors="replace"), path=path).jumps == ()
