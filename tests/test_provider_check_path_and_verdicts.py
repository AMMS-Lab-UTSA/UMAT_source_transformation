"""The provider check: the contract's own path, and one verdict per entry.

The verifier used to replay one fixed seven-increment J2 path for every
material and pass a column only if the error at each of three fixed steps,
scaled by the column's largest entry with a 1e-12 floor, stayed under 2e-6.
The crystal-plasticity model m6_fcc cannot integrate that path (its original
routine returns non-finite values on it) and its small parameters were stepped
by amounts larger than themselves.

Now the path comes from the contract (``validation.check_path``; the J2 path
when absent), and every entry is judged against centred differences of the
ORIGINAL over the project's step ladder: agrees, consistent with zero,
reference unresolved (never counted as agreement), or disagrees.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from umat_oti.provider import collaborator
from umat_oti.validation import parameter_sensitivity_provider as verifier

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "parameter_sensitivity" / "models"
FCC_SLIDE_17 = [("C11", 1, 168000.0), ("C12", 2, 121000.0), ("C44", 3, 75000.0), ("g0", 4, 13.0),
                ("gsat", 5, 55.0), ("h0", 6, 800.0), ("a", 7, 2.0), ("q", 8, 1.4),
                ("gd0", 9, 0.001), ("m", 10, 0.05)]


# --------------------------------------------------------------------------
# The path
# --------------------------------------------------------------------------

@pytest.mark.unit
def test_without_a_check_path_the_j2_path_is_used():
    path, source = verifier.check_path({"validation": {"props_values": [1.0]}}, 6)
    np.testing.assert_array_equal(path, verifier.J2_PATH)
    assert source.startswith("provider default")


@pytest.mark.unit
def test_a_repeated_increment_and_explicit_increments_are_both_read():
    repeated, source = verifier.check_path({"validation": {"check_path": {
        "dstran_per_increment": [1e-4, 0, 0, 0, 0, 0], "n_increments": 3, "source": "declared"}}}, 6)
    assert repeated.shape == (3, 6) and source == "declared"
    explicit, _ = verifier.check_path({"validation": {"check_path": {
        "increments": [[1e-4, 0, 0, 0, 0, 0], [0, 1e-4, 0, 0, 0, 0]]}}}, 6)
    assert explicit.shape == (2, 6) and explicit[1, 1] == 1e-4


@pytest.mark.unit
@pytest.mark.parametrize("spec,message", [
    ([1, 2], "object"),
    ({"increments": [[1e-4, 0, 0]]}, "rows of 6"),
    ({"increments": [[float("nan")] * 6]}, "finite"),
    ({"increments": [[0.0] * 6]}, "does not deform"),
    ({"dstran_per_increment": [1e-4] * 6, "n_increments": 0}, "positive integer"),
    ({"other": 1}, "needs increments"),
])
def test_an_unusable_check_path_is_refused(spec, message):
    with pytest.raises(verifier.CheckPathError, match=message):
        verifier.check_path({"validation": {"check_path": spec}}, 6)


@pytest.mark.unit
def test_the_named_paths_are_what_they_say():
    assert collaborator.check_path_spec("provider") is None
    uniaxial = collaborator.check_path_spec("uniaxial")
    declared = json.loads((ROOT / "parameter_sensitivity" / "loading_paths.json").read_text())["default"]
    assert uniaxial["dstran_per_increment"] == declared["dstran_per_increment"]
    assert uniaxial["n_increments"] == declared["n_increments"]
    shear = collaborator.check_path_spec("tension_shear")
    assert shear["dstran_per_increment"] == [1e-4, 0.0, 0.0, 1e-4, 0.0, 0.0]
    with pytest.raises(ValueError, match="unknown check path"):
        collaborator.check_path_spec("other")


# --------------------------------------------------------------------------
# One entry
# --------------------------------------------------------------------------

STEPS = verifier.STEP_LADDER


def _series(limit: float, curvature: float, noise: float, seed: int = 0) -> tuple:
    """A centred difference: h^2 truncation onto ``limit``, then round-off ~ 1/h."""
    rng = np.random.default_rng(seed)
    return tuple(limit + curvature * h * h + noise / h * rng.uniform(-1, 1) for h in STEPS)


@pytest.mark.unit
def test_a_converged_reference_agrees_with_the_right_value_and_not_a_wrong_one():
    series = _series(1.0, 1.0, 1e-16)
    noise = tuple(0.0 for _ in STEPS)
    right = verifier._adjudicate(1.0, series, STEPS, noise, 2e-6)
    wrong = verifier._adjudicate(1.0 + 1e-4, series, STEPS, noise, 2e-6)
    assert right["verdict"] == "agrees" and right["relative_error"] < 1e-8
    assert wrong["verdict"] == "disagrees"


@pytest.mark.unit
def test_a_reference_that_cannot_pin_the_entry_down_is_unresolved_not_agreement():
    series = _series(1e-9, 0.0, 1e-17, seed=3)   # scatter ~1e-10 near the small steps
    noise = tuple(1e-12 / h for h in STEPS)       # a response whose rounding swamps the entry
    row = verifier._adjudicate(1.0001e-9, series, STEPS, noise, 2e-6)
    assert row["verdict"] == "reference_unresolved", row


@pytest.mark.unit
def test_zero_is_zero_only_to_within_the_reference():
    series = tuple(1e-18 * (-1) ** index for index in range(len(STEPS)))
    noise = tuple(1e-16 for _ in STEPS)
    assert verifier._adjudicate(0.0, series, STEPS, noise, 2e-6)["verdict"] == "consistent_with_zero"
    assert verifier._adjudicate(1e-3, series, STEPS, noise, 2e-6)["verdict"] == "disagrees"


@pytest.mark.unit
def test_a_column_of_zeros_is_unresolved_and_says_why():
    rows = [{"verdict": "consistent_with_zero"}] * 4
    verdict, reason = verifier._column_verdict(rows)
    assert verdict == "unresolved" and "zero to within the reference" in reason
    verdict, _ = verifier._column_verdict(rows + [{"verdict": "agrees"}])
    assert verdict == "agrees"
    verdict, _ = verifier._column_verdict(rows + [{"verdict": "agrees"}, {"verdict": "disagrees"}])
    assert verdict == "disagrees"


# --------------------------------------------------------------------------
# Whole models
# --------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.parametrize("scale,where", [(1.0 + 1e-5, "all"), (None, "one")])
def test_a_wrong_derivative_is_caught(tmp_path, monkeypatch, scale, where):
    """The criterion fails a provider that returns a wrong DSIGMA_DP."""
    original = verifier.ProviderLibrary.evaluate

    def corrupted(self, props, path, *, carry=True):
        stress, state, tangent, dsigma, dstate = original(self, props, path, carry=carry)
        dsigma = dsigma.copy()
        if where == "all":
            dsigma *= scale
        else:
            dsigma[3, 0, 2] *= 1.001   # one entry, SIGY0 column, a plastic increment
        return stress, state, tangent, dsigma, dstate

    monkeypatch.setattr(verifier.ProviderLibrary, "evaluate", corrupted)
    with pytest.raises(AssertionError, match="disagree"):
        verifier.verify_provider(MODELS / "m3_j2" / "contract_v2.json", tmp_path / "out")


def _fcc_contract(tmp_path: Path, path_key: str) -> Path:
    parameters = collaborator.parse_parameters(
        [{"parameter": name, "PROPS index": index, "value": value} for name, index, value in FCC_SLIDE_17])
    contract = collaborator.provider_contract("umat.for", name="m6_fcc", nstatev=12,
                                              parameters=parameters, check_path=path_key)
    return collaborator.stage_model(MODELS / "m6_fcc" / "umat.for", tmp_path / "m6_fcc", contract)


@pytest.mark.slow
@pytest.mark.fortran
def test_the_ten_parameter_fcc_verifies_on_a_path_that_yields(tmp_path):
    """Slide 17's values, tension with shear: every column of every array agrees."""
    report = verifier.verify_provider(_fcc_contract(tmp_path, "tension_shear"), tmp_path / "out",
                                      require_j2_branches=False)
    assert report["passed"] and report["verdict"] == "verified"
    assert report["primal_stress_max_abs"] < 1e-10 and report["primal_state_max_abs"] < 1e-12
    # The slip resistances grow from zero: the path yields.
    assert report["state_growth"] > 0.1 * 13.0
    by = {(column["array"], column["column"]): column for column in report["columns"]}
    for name, _, _ in FCC_SLIDE_17:
        for array in ("DSIGMA_DP", "DSTATEV_DP", "DSIGMA_DP (MARCH)"):
            assert by[(array, name)]["verdict"] == "agrees", by[(array, name)]
    assert report["comparisons"]["disagreeing"] == 0
    assert report["comparisons"]["verified_entries"] > 4000
    assert all(summary["worst_relative_error_agreeing"] < verifier.RELATIVE_TOLERANCE
               for summary in report["arrays"].values())


@pytest.mark.slow
@pytest.mark.fortran
def test_on_uniaxial_strain_the_shear_modulus_column_is_reported_unresolved(tmp_path):
    """The sweep's declared uniaxial path puts no shear stress on the cube axes.

    dsigma/dC44 is then zero along the whole path; the column is reported
    unresolved with that reason, and every other column agrees.
    """
    report = verifier.verify_provider(_fcc_contract(tmp_path, "uniaxial"), tmp_path / "out",
                                      require_j2_branches=False)
    assert report["passed"] and report["verdict"] == "verified_with_unresolved_columns"
    unresolved = {(column["array"], column["column"]) for column in report["unresolved_columns"]}
    assert unresolved == {("DSIGMA_DP", "C44"), ("DSTATEV_DP", "C44"), ("DSIGMA_DP (MARCH)", "C44")}
    assert all("zero to within the reference" in column["reason"]
               for column in report["unresolved_columns"])
    assert report["state_growth"] > 0.05 * 13.0
