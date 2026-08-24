"""Finding a UMAT's local Newton solve must not require knowing the model.

An internal constitutive Jacobian is the derivative of a local residual with
respect to a local iteration variable. Extracting it starts with finding that
loop, and the discovery is purely syntactic: a scalar Newton update has the
shape ``X = X - A / B``, and matching that shape identifies the triple with no
symbol whitelist and no model names.

These tests pin both halves of the contract: it finds the solve where one
exists, and it says so plainly where one does not, rather than forcing a match.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.transform.internal_jacobian import describe_source, discover_local_solves

REPO_ROOT = Path(__file__).resolve().parents[1]
ICP = REPO_ROOT / "UMATs" / "UMATs" / "ICP"

#: Every ICP model with a scalar return-map solve. Discovered, not declared:
#: the scan finds these without being told any of them.
WITH_LOCAL_SOLVE = {
    "UMAT_NKH_1.02.for", "UMAT_PCL.for", "UMAT_PCLI.for", "UMAT_PCLI_R.for",
    "UMAT_PCLK.for", "UMAT_PCO.for", "UMAT_VPDCL.for", "UMAT_VPDCL_R.for",
    "UMAT_VPDCO.for",
}
WITHOUT = {"UMAT_ECL_TEMP.for", "UMAT_ECO.for", "UMAT_HIN.for"}


def test_a_minimal_newton_update_is_found():
    source = "\n".join([
        "      SUBROUTINE UMAT",
        "      DO",
        "        RES = F - G",
        "        DRES = -G",
        "        X = X - RES/DRES",
        "        IF(DABS(RES).LT.TOL) EXIT",
        "      END DO",
        "      END",
    ])
    solves = discover_local_solves(source)
    assert len(solves) == 1
    solve = solves[0]
    assert (solve.iterate, solve.residual, solve.jacobian) == ("X", "RES", "DRES")
    assert solve.sign == "-"
    assert solve.loop_start_line == 2 and solve.loop_end_line == 7
    assert solve.convergence_variable == "RES" and solve.convergence_tolerance == "TOL"


def test_a_plus_update_is_also_found():
    source = "      X = X + R/J\n"
    solve = discover_local_solves(source)[0]
    assert solve.sign == "+" and solve.jacobian == "J"


def test_an_assignment_to_a_different_variable_is_not_a_newton_update():
    """Y = X - A/B updates something else; it is not an iteration."""
    assert discover_local_solves("      Y = X - A/B\n") == []


def test_comment_lines_are_ignored():
    """Fixed-form comments start in column 1 and must not be scanned."""
    assert discover_local_solves("C     X = X - A/B\n") == []
    assert discover_local_solves("*     X = X - A/B\n") == []


def test_a_source_with_no_local_solve_reports_why():
    result = describe_source("      SUBROUTINE UMAT\n      END\n", name="flat.for")
    assert result["supported"] is False
    assert result["local_solves"] == []
    assert "no scalar Newton update" in result["reason"]
    # an honest negative, not a defect
    assert "none is claimed" in result["reason"]


@pytest.mark.skipif(not ICP.is_dir(), reason="ICP sources not present")
@pytest.mark.parametrize("name", sorted(WITH_LOCAL_SOLVE))
def test_every_return_mapping_model_yields_the_same_triple(name):
    """Nine independent sources, one syntactic rule, no model names."""
    result = describe_source((ICP / name).read_text(errors="replace"), name=name)
    assert result["supported"] is True, name
    solve = result["local_solves"][0]
    assert solve["iteration_variable"] == "GAM_PAR"
    assert solve["residual_variable"] == "FGAM"
    assert solve["hand_coded_jacobian_variable"] == "FJAC"
    assert solve["loop_start_line"] and solve["loop_end_line"]
    assert solve["loop_start_line"] < solve["update_line"] < solve["loop_end_line"]
    assert solve["convergence_variable"] == "FGAM"


@pytest.mark.skipif(not ICP.is_dir(), reason="ICP sources not present")
@pytest.mark.parametrize("name", sorted(WITHOUT))
def test_models_without_a_scalar_solve_are_reported_not_forced(name):
    result = describe_source((ICP / name).read_text(errors="replace"), name=name)
    assert result["supported"] is False, f"{name} should have no scalar Newton update"
    assert result["reason"]


@pytest.mark.skipif(not ICP.is_dir(), reason="ICP sources not present")
def test_the_discovered_jacobian_is_labelled_as_a_claim_not_a_reference():
    """The model's hand-coded Jacobian is what we check, never what we check against."""
    result = describe_source((ICP / "UMAT_PCL.for").read_text(errors="replace"))
    solve = result["local_solves"][0]
    assert "hand_coded_jacobian_variable" in solve
    assert "jacobian" not in {k for k in solve if k.endswith("_reference")}
