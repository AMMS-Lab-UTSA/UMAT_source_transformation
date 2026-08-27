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


def test_every_shipped_contract_declares_its_material():
    """The round can only run what the repository already pins."""
    contracts = sorted((REPO_ROOT / "parameter_sensitivity" / "contracts").glob("*.json"))
    assert contracts, "no contracts found"
    undeclared = [c.stem for c in contracts if _declared(c.stem) is None]
    assert not undeclared, (
        f"these contracts declare no material vector, so the round would have "
        f"to invent one or skip them: {undeclared}")


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
