"""The paired Abaqus round must not manufacture the things it is checking.

Two failure modes this guards. A deck built with placeholder constants
compares two builds of a subroutine on a material the source never described,
and a deck that never leaves the elastic branch compares the one part of a
law that every build gets right. Either produces a green result that means
much less than it appears to.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from umat_oti.validation.job_builder import _props_lines  # noqa: E402
from run_abaqus_paired_round import _declared, _load_case_for, run_one  # noqa: E402


def test_a_declared_material_vector_reaches_the_deck():
    line = _props_lines(4, "XNU=PROPS(2)", [210000.0, 0.3, 250.0, 2000.0])
    assert "210000.0" in line and "250.0" in line and "2000.0" in line


def test_without_a_declared_vector_the_placeholder_is_used():
    line = _props_lines(4, "XNU=PROPS(2)")
    assert line.strip() == "1.0, 0.3, 1.0, 1.0,"


def test_a_short_declared_vector_is_padded_not_silently_truncated():
    line = _props_lines(4, "", [7.0, 8.0])
    values = [v.strip() for v in line.strip().rstrip(",").split(",")]
    assert values[:2] == ["7.0", "8.0"] and len(values) == 4


def test_every_benchmark_model_declares_its_material():
    """The round can only run what the repository already pins.

    Scoped to the benchmark set the sweep declares, not to whatever files
    happen to be in the contracts directory: contracts are generated, and a
    run of the tools can leave one there for a model outside that set. Such a
    contract is handled correctly -- reported as having no declared material
    rather than given one -- which is what
    ``test_a_source_with_no_declared_material_is_recorded_not_invented``
    pins. What matters here is that nothing in the shipped set is missing one.
    """
    import run_abaqus_paired_round as rnd  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from run_parameter_sensitivity_sweep import REQUIRED  # noqa: PLC0415

    assert REQUIRED, "the benchmark set is empty"
    undeclared = [m for m in REQUIRED if rnd._declared(m) is None]
    assert not undeclared, (
        f"these benchmark models declare no material vector, so the round "
        f"would have to invent one or skip them: {undeclared}")


def test_the_deck_and_the_check_ask_the_same_question(tmp_path: Path):
    """The load case must come from the signal that grades the result.

    Picking it any other way lets the two disagree, and they did: six models
    were driven with a 1e-4 elastic step while the activation check waited for
    a plastic state the deck was never going to produce, and every one of them
    was reported as failing.
    """
    from umat_oti.fortran.scanner import analyze_fortran_source

    models = sorted((REPO_ROOT / "parameter_sensitivity" / "models").iterdir())
    checked = 0
    for directory in models:
        source = directory / "umat.for"
        if not source.is_file():
            continue
        expected_by_scanner = bool(
            (analyze_fortran_source(source).get("plasticity_indicators") or {})
            .get("is_plasticity_candidate"))
        mode, expected_by_round = _load_case_for(source)
        assert expected_by_round == expected_by_scanner, (
            f"{directory.name}: the round expects plasticity="
            f"{expected_by_round} but the scanner that grades it says "
            f"{expected_by_scanner}")
        assert ("plastic" in mode) == expected_by_scanner
        checked += 1
    assert checked >= 15, f"only {checked} models were checked"


def test_a_law_with_no_yield_surface_is_not_driven_past_one(tmp_path: Path):
    elastic = tmp_path / "umat.for"
    elastic.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS)\n"
        "      DDSDDE(1,1)=1.0\n"
        "      END\n", encoding="utf-8")
    mode, expected = _load_case_for(elastic)
    assert expected is False and "plastic" not in mode


def test_a_source_with_no_declared_material_is_recorded_not_invented(tmp_path: Path):
    row = run_one("a_model_that_does_not_exist", tmp_path, "/usr/bin/abaqus")
    assert row["status"] == "no_declared_material"
    assert "invent" in row["blocker"]
    assert row["max_rel_difference"] == "", (
        "a source that was never run must carry no difference, not a zero")


def test_a_tangent_only_disagreement_is_named_not_called_a_pass():
    """Two builds can agree on the material and still return different tangents.

    A source whose own DDSDDE is an elastic predictor disagrees with the
    transformed build by construction, because replacing that predictor with
    the consistent tangent is what the transform is for. A paired run holds
    only those two tangents and cannot say which is right, so it must neither
    call that a pass nor file it with the genuine failures.
    """
    from run_abaqus_paired_round import _only_the_tangent_differs

    agree_except_tangent = {"stress_pass": True, "statev_pass": True,
                            "convergence_pass": True, "activation_pass": True,
                            "ddsdde_pass": False}
    assert _only_the_tangent_differs(agree_except_tangent)

    also_stress = dict(agree_except_tangent, stress_pass=False)
    assert not _only_the_tangent_differs(also_stress), (
        "a stress disagreement is a real failure and must not be filed as a "
        "tangent-comparability question")

    everything_agrees = dict(agree_except_tangent, ddsdde_pass=True)
    assert not _only_the_tangent_differs(everything_agrees)


def test_generated_free_form_lines_fit_the_compiler_abaqus_uses():
    """gfortran takes any line length; the compiler Abaqus uses does not.

    Stitching a source's fixed-form continuations into single free-form
    statements produced a line of 14858 characters. gfortran is given
    -ffree-line-length-none and compiled it; ifort truncates at 7200 and the
    Abaqus job failed with no useful diagnostic. Wrapping must move line
    breaks only -- never a character of the statement.
    """
    import re

    from umat_oti.transform.helper_lifting import (
        FREE_FORM_LINE_WIDTH, wrap_free_form,
    )

    long_expression = "      DET = " + " + ".join(
        f"A{i}{j}*B{j}{i}" for i in range(1, 10) for j in range(1, 10))
    source = f"{long_expression}\n      X = 1.0\n"
    assert len(long_expression) > FREE_FORM_LINE_WIDTH

    wrapped = wrap_free_form(source)
    lines = wrapped.splitlines()
    assert max(len(line) for line in lines) <= FREE_FORM_LINE_WIDTH + 12
    assert all(line.rstrip().endswith("&")
               for line in lines[:-2] if line.strip() and "DET" in line or line.strip().startswith("A"))

    def flatten(text: str) -> str:
        return re.sub(r"\s+", "", text.replace("&\n", "").replace("&", ""))

    assert flatten(wrapped) == flatten(source), (
        "wrapping changed the statement, not just where it breaks")


def test_a_string_literal_is_never_split():
    """A break inside a literal would change what the program prints."""
    from umat_oti.transform.helper_lifting import wrap_free_form

    literal = "'" + "x" * 300 + "'"
    wrapped = wrap_free_form(f"      WRITE(*,*) {literal}\n", width=40)
    assert any(literal in line for line in wrapped.splitlines()), (
        "the literal was broken across a continuation")


def test_a_comment_is_left_alone():
    from umat_oti.transform.helper_lifting import wrap_free_form

    comment = "    ! " + "y" * 400
    wrapped = wrap_free_form(comment + "\n")
    assert wrapped.strip() == comment.strip()


def test_a_source_that_never_updates_its_tangent_on_yield_is_recognised():
    """The discriminator has to be read off the source, not assumed."""
    from run_abaqus_paired_round import tangent_is_an_elastic_predictor

    models = REPO_ROOT / "parameter_sensitivity" / "models"
    predictor, evidence = tangent_is_an_elastic_predictor(models / "m5_cpflow" / "umat.for")
    assert predictor and "0 of them inside a yield branch" in evidence

    consistent, evidence = tangent_is_an_elastic_predictor(models / "m3_j2" / "umat.for")
    assert not consistent and "inside a yield branch" in evidence


def test_a_stress_disagreement_is_only_excused_with_that_evidence():
    """The direction that could launder a real error into a caveat."""
    from run_abaqus_paired_round import _only_the_tangent_differs

    models = REPO_ROOT / "parameter_sensitivity" / "models"
    row = {"stress_pass": False, "statev_pass": True, "convergence_pass": True,
           "activation_pass": True, "ddsdde_pass": False}

    assert not _only_the_tangent_differs(row, None), (
        "without the source there is no evidence, so a stress disagreement "
        "must stay a failure")
    assert not _only_the_tangent_differs(row, models / "m3_j2" / "umat.for"), (
        "m3_j2 computes a consistent tangent, so a stress disagreement there "
        "is a real one")
    assert _only_the_tangent_differs(row, models / "m5_cpflow" / "umat.for")


def test_a_state_or_convergence_disagreement_is_never_excused():
    from run_abaqus_paired_round import _only_the_tangent_differs

    predictor_source = (REPO_ROOT / "parameter_sensitivity" / "models"
                        / "m5_cpflow" / "umat.for")
    for broken in ("statev_pass", "convergence_pass", "activation_pass"):
        row = {"stress_pass": True, "statev_pass": True, "convergence_pass": True,
               "activation_pass": True, "ddsdde_pass": False, broken: False}
        assert not _only_the_tangent_differs(row, predictor_source), (
            f"{broken} False must not be filed as a tangent-comparability question")


def test_an_undeclared_integer_is_not_promoted():
    """Fortran types an undeclared name by its first letter.

    The Oxford-lineage crystal plasticity source computes IJ2 = I + J - 2 and
    asks MOD(IJ2,2). Promoting IJ2 to the differentiated type turned an
    integer parity test into an unsupported intrinsic on a derived type and
    blocked the whole source.
    """
    from umat_oti.core.roles import implicit_integer_letters

    assert implicit_integer_letters("      X = 1\n") == frozenset("IJKLMN"), (
        "with no IMPLICIT statement, Fortran's own default applies")
    assert implicit_integer_letters(
        "      IMPLICIT REAL*8 (A-H,O-Z)\n") == frozenset("IJKLMN"), (
        "the usual UMAT declaration leaves the integer range where it was")
    assert implicit_integer_letters("      IMPLICIT REAL*8 (A-Z)\n") == frozenset(), (
        "a source that types every letter real has no implicit integers, and "
        "refusing to promote its reals would be a regression")
    assert implicit_integer_letters("      IMPLICIT NONE\n") == frozenset()


def test_a_call_is_not_read_as_an_unshaped_array():
    """NAME(...) is indexing only when NAME is an array.

    FLOAT(NSLPTL) is an intrinsic and F(X,PROP) is a function the source
    defines; both were reported as promoted arrays with no confirmed shape,
    blocking a source with nothing wrong with it.
    """
    from umat_oti.transform.source_transform import (
        _INTRINSIC_CALLS, _defined_function_names,
    )

    assert "FLOAT" in _INTRINSIC_CALLS and "MOD" in _INTRINSIC_CALLS

    source = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      X = F(1.0)\n"
        "      END\n"
        "      REAL*8 FUNCTION F(A)\n"
        "      F = A\n"
        "      END\n")
    assert "F" in _defined_function_names(source)
    assert "STRESS" not in _defined_function_names(source), (
        "an array must not be mistaken for a function")


def test_the_deck_is_sized_by_the_declared_state_not_an_inferred_one(tmp_path: Path):
    """Builds a deck and reads *Depvar out of it.

    An earlier version of this test only asserted that the parameter existed
    in a signature, which stays green if the value is accepted and ignored.
    The Huang/Kysar crystal-plasticity lineage sizes its state as
    10*NSLPTL + 5, which no static reading of the text can see: inference
    returned 1 where the source pins 172, and the untransformed UMAT wrote
    past the end of a 37-slot array.
    """
    import re

    from umat_oti.validation.job_builder import _write_input_deck

    source = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,NTENS,NSTATV,PROPS)\n"
              "      STATEV(1)=0.0\n"
              "      END\n")
    # _write_input_deck is handed the total the workspace already sized,
    # instrumentation included, and must write exactly that.
    for requested in (172 + 6 * 6, 7 + 6 * 6):
        deck = _write_input_deck(tmp_path / f"d{requested}.inp", 6,
                                 "single element tension", requested, 4, source)
        written = int(re.search(r"\*Depvar\s*\n\s*(\d+)", deck.read_text())[1])
        assert written == requested, f"*Depvar is {written}, asked for {requested}"

    # And the workspace must never shrink below what inference found, or a
    # contract that under-declares reintroduces the out-of-bounds write.
    from umat_oti.validation.job_builder import (  # noqa: PLC0415
        infer_validation_dimensions_from_source,
    )
    inferred_nstatv, _ = infer_validation_dimensions_from_source(
        source, statev_name="STATEV", ntens=6)
    assert max(0, inferred_nstatv) == inferred_nstatv


def test_the_declared_material_reaches_the_deck_untruncated(tmp_path: Path):
    """The whole vector, not as many as inference guessed the source wanted.

    UMAT_PCO declares eight constants; the deck carried five, so the source
    read PROPS(8) past the end of the array and divided by it. Both builds got
    the same truncated deck, so the comparison was still like for like -- but
    the row claimed the contract's material had been used when it had not.
    """
    import re

    from umat_oti.validation.job_builder import _write_input_deck

    props = [220000.0, 0.3, 0.005, 900000.0, 56.0, 0.0, 343.5, 0.25]
    deck = _write_input_deck(tmp_path / "props.inp", 6, "single element tension",
                             1, len(props), "      SUBROUTINE UMAT()\n      END\n",
                             props)
    text = deck.read_text()
    assert re.search(r"\*User Material, constants=8", text)
    for value in props:
        assert repr(value) in text, f"{value} never reached the deck"



def test_a_commented_out_statement_is_never_stitched_into_code():
    """The most dangerous rewrite found: a comment turned into a statement.

    This source carries "C      IF (STATEV(1).EQ.0.) THEN" as a note about a
    condition its author deliberately removed. Stitching continuations dropped
    the marker, the line then read as a promoted branch, and the transform
    emitted it live. It failed to compile, which is luck: a commented-out
    statement that happened to compile would have put a condition back into
    the model with nothing to show for it.

    Asserted against the stitchers themselves rather than against
    ``_is_commented``, which would stay green with every guard deleted.
    """
    from umat_oti.transform.source_transform import (
        _is_commented, _logical_assignment_line, _logical_branch_line,
        _logical_helper_call_line,
    )

    lines = [
        "      X = 1.0",
        "C      IF (STATEV(1).EQ.0.) THEN Modified by author",
        "C      DSTRESS(1) = TRVAL",
        "     &   + 1.0",
        "C      CALL KMLT(DSTRESS,",
        "     &   TRVAL)",
    ]
    for index, line in enumerate(lines, start=1):
        if not _is_commented(line):
            continue
        # Every stitcher must decline a comment. These mirror the three call
        # sites in the transform loop; a comment reaching any of them comes
        # back as executable text with its marker gone.
        for stitch in (_logical_branch_line, _logical_assignment_line,
                       _logical_helper_call_line):
            stitched, _ = stitch(lines, index, "fixed")
            if stitched:
                assert stitched.lstrip()[:1] in "Cc*!", (
                    f"{stitch.__name__} turned a comment into code: "
                    f"{stitched.strip()[:60]!r}")


def test_an_intrinsic_is_never_classified_as_a_variable_to_promote():
    """FLOAT(NSLPTL) became FLOAT_OTI(NSLPTL), declared nowhere."""
    from umat_oti.core.roles import INTRINSIC_CALL_NAMES, defined_function_names

    for name in ("FLOAT", "SQRT", "SIGN", "MOD", "MAX", "DBLE"):
        assert name in INTRINSIC_CALL_NAMES

    source = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      X = GSLP0(1.0)\n"
        "      END\n"
        "      REAL*8 FUNCTION GSLP0(A)\n"
        "      GSLP0 = A\n"
        "      END\n")
    assert "GSLP0" in defined_function_names(source)
    assert "UMAT" not in defined_function_names(source), (
        "a subroutine is not a function subprogram")


def test_the_seed_check_follows_the_variable_that_was_actually_seeded():
    """Regression: a finite-strain source seeds DFGRD1, not DSTRAN.

    Looking only for DSTRAN_OTI consumers found none in a finite-strain
    transform, which turned "nothing consumes the seed" -- the condition these
    checks exist to catch -- into the verdict for a source that had been
    seeding correctly all along, and broke lucarini_neohookean, which had
    passed in Abaqus the run before.
    """
    from umat_oti.transform.source_transform import _seed_consuming_stress_lines

    finite_lines = [
        (10, "      PK2_OTI(I) = PK2_OTI(I) + C_OTI(I,J)*DFGRD1_OTI(J)"),
        (11, "      X_OTI = Y_OTI + 1.0D0"),
    ]
    assert _seed_consuming_stress_lines(finite_lines, {"DSTRAN"}) == [], (
        "this is the state that used to be reported, and it is why the "
        "check has to be told which variable carries the seed")
    assert _seed_consuming_stress_lines(finite_lines, {"DSTRAN", "DFGRD1"}) == [10]

    small_strain = [(20, "      STRESS_OTI(I)=STRESS_OTI(I)+D_OTI(I,J)*DSTRAN_OTI(J)")]
    assert _seed_consuming_stress_lines(small_strain, {"DSTRAN"}) == [20]

    # And the condition it exists to catch still fires.
    assert _seed_consuming_stress_lines(
        [(30, "      X_OTI = Y_OTI * 2.0D0")], {"DSTRAN", "DFGRD1"}) == []
    assert _seed_consuming_stress_lines(small_strain, set()) == []
