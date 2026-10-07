"""``umat-oti check`` ends with the one-page verdict and the headline numbers,
and leaves the derivatives in a table with named columns (Nico, B11: the answer
was a 50 KB JSON on the screen and a CSV whose first value column is ``oti``).
"""
import csv
import json
import shutil
from pathlib import Path

import pytest

from umat_oti.app import check_command as check
from umat_oti.app import check_summary as summary

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
J2 = ROOT / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"
HEADER = ["array", "column", "increment", "component", "oti", "reference", "uncertainty",
          "window_spread", "noise_floor", "step", "relative_error", "verdict", "judged_by", "reason"]


def _row(array, column, increment, component, oti, ref, verdict="agrees"):
    return [array, column, increment, component, oti, ref, 0, 0, 0, 0.01,
            abs(oti - ref) / abs(ref) if ref else 0.0, verdict, "within_resolution", ""]


def _fake_results(tmp_path, *, state_growth=6.1, tangent_change=True, disagree=0):
    out = tmp_path / "res"
    folder = out / "sensitivities" / "verification"
    folder.mkdir(parents=True)
    rows = []
    for inc in (1, 2):
        for k, name in enumerate(("EMOD", "ENU"), start=1):
            for comp in range(1, 7):
                rows.append(_row("DSIGMA_DP", name, inc, comp, 0.001 * k * comp * inc, 0.001 * k * comp * inc))
        for comp in range(1, 7):
            for col in range(1, 7):
                value = (100.0 + (inc if tangent_change else 0)) * (comp == col)
                rows.append(_row("DDSDDE", str(col), inc, comp, value, value, verdict="agrees"))
    rows.append(_row("DSTATEV_DP", "EMOD", 2, 1, 0.5, 0.5))
    rows.append(_row("DSIGMA_DP", "EMOD", 2, 3, 0.0, 0.0, verdict="consistent_with_zero"))
    if disagree:
        rows.append(_row("DSIGMA_DP", "ENU", 2, 1, 9.0, 1.0, verdict="disagrees"))
    with open(folder / "verification_entries.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    (folder / "verification.json").write_text(json.dumps({
        "verdict": "verified" if not disagree else "disagrees", "passed": not disagree, "increments": 2,
        "state_growth": state_growth, "criterion": {"relative_tolerance": 2e-6},
        "arrays": {"DSIGMA_DP": {"worst_relative_error_agreeing": 3e-9},
                   "DSTATEV_DP": {"worst_relative_error_agreeing": 1e-9}},
        "comparisons": {"verified_entries": 40, "consistent_with_zero": 7,
                        "reference_unresolved": 0, "disagreeing": disagree}}))
    return out


def test_the_table_has_named_columns_a_row_per_component_and_the_check_beside_each_value(tmp_path):
    out = _fake_results(tmp_path)
    files = summary.results_table(out)
    text = files["text"].read_text()
    assert "d(stress) / d(constant), at the last increment (2)" in text
    header = next(line for line in text.splitlines() if "EMOD" in line and "ENU" in line)
    assert header.split() == ["EMOD", "ENU"]
    assert [l.split()[:2] for l in text.splitlines() if l.startswith("stress ")] == [
        ["stress", c] for c in ("11", "22", "33", "12", "13", "23")]
    assert "d(state variable) / d(constant)" in text and "EMOD 6 of 6" in text
    rows = list(csv.DictReader(open(files["csv"])))
    assert set(rows[0]) == {"quantity", "component", "constant", "derivative",
                            "finite_difference_reference", "relative_difference", "agreement", "increment"}
    assert not [r for r in rows if r["increment"] != "2"]
    assert {r["agreement"] for r in rows} == {"agrees", "zero (the check agrees it is zero)"}
    assert "oti" not in rows[0]


def test_the_facts_say_whether_the_loading_left_the_elastic_range(tmp_path):
    assert summary.facts(_fake_results(tmp_path / "a"))["nonlinear"][0] is True
    elastic = summary.facts(_fake_results(tmp_path / "b", state_growth=0.0, tangent_change=False))
    assert elastic["nonlinear"][0] is False and "--peak" in elastic["nonlinear"][1]
    stiffness_only = summary.facts(_fake_results(tmp_path / "c", state_growth=0.0))
    assert stiffness_only["nonlinear"][0] is True and "stiffness changed" in stiffness_only["nonlinear"][1]
    found = summary.facts(_fake_results(tmp_path / "d"))
    assert found["parameters"] == ["EMOD", "ENU"] and found["agree"] == 40 and found["worst"] == 3e-9


def test_a_result_prints_the_verdict_then_the_numbers_and_never_green(tmp_path):
    out = _fake_results(tmp_path)
    text = summary.render({"exit_code": 0, "stages": {"sensitivities": {"verification": {
        "result": {"verdict": "verified"}}}}}, out)
    assert text.index("AMBER") < text.index("Constants checked (2): EMOD, ENU")
    assert "GREEN" not in text and "2 increments of loading" in text
    assert "40 entries agree" in text and "0 disagree" in text and "worst relative difference 3e-09" in text
    assert "Loading reached the nonlinear range: yes" in text
    assert str(out / "results_table.txt") in text and str(out / "workflow_summary.json") in text


def test_a_failed_derivative_check_is_not_green_and_says_where_it_stopped(tmp_path):
    out = _fake_results(tmp_path, disagree=1)
    text = summary.render({"exit_code": 1}, out, state="tangent_not_verified",
                          reason="Sensitivity build or verification failed", stage="sensitivities")
    assert "GREEN" not in text and "AMBER" in text
    assert "The run stopped while checking the derivatives." in text and "1 disagree" in text


def test_a_refusal_after_the_pipeline_started_is_a_card_with_no_internal_usage(tmp_path):
    text = summary.render({"exit_code": 1}, tmp_path, state="missing_material_data",
                          reason="Automatic material configuration failed: " + check.clean_reason(
                              "usage: trial_deck.py [-h]\n [--settings S]\ntrial_deck.py: error: "
                              "x publishes no deck with a *USER MATERIAL block"),
                          stage="material_settings")
    assert "BLUE" in text and "Whose move: you." in text and "GREEN" not in text
    assert "usage:" not in text.lower() and "trial_deck" not in text
    assert "The run stopped while reading the material." in text


def test_the_pipelines_internal_usage_block_is_cut_out_of_any_reason():
    raw = ("Automatic material configuration failed: usage: trial_deck.py [-h]\n"
           "                     [--settings SETTINGS | --material-config MATERIAL_CONFIG]\n"
           "trial_deck.py: error: Automatic Abaqus material discovery failed: nodeck publishes no deck")
    assert check.clean_reason(raw) == ("Automatic material configuration failed: Automatic Abaqus "
                                       "material discovery failed: nodeck publishes no deck")
    assert check.clean_reason("no usage here") == "no usage here"


def test_finish_writes_the_summary_to_a_file_and_returns_the_pipelines_code(tmp_path, capsys):
    out = _fake_results(tmp_path)
    assert check.finish({"exit_code": 0}, out) == 0
    printed = capsys.readouterr().out
    assert (out / "check_summary.txt").read_text().strip() == printed.strip()
    assert check.finish({"exit_code": 1, "failed_stage": "dependencies", "error": "Helper lifting "
                         "requires source definitions for ['SHEARMOD']"}, out) == 1
    assert "SHEARMOD" in capsys.readouterr().out


@pytest.mark.slow
@pytest.mark.fortran
def test_a_whole_run_ends_with_a_verdict_a_table_and_no_json_on_the_screen(tmp_path, monkeypatch, capsys):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    folder = tmp_path / "w"
    folder.mkdir()
    shutil.copy(J2, folder / "j2_props.f")
    monkeypatch.chdir(folder)
    assert check.main([str(folder / "j2_props.f"), "--props", "E=210000 xnu=0.3 SIGY0=250 H=2000",
                       "--peak", "0.02"]) == 0
    out = capsys.readouterr().out
    assert "AMBER: DERIVATIVES CHECKED, ABAQUS NOT RUN" in out and "GREEN" not in out and '"stages"' not in out
    assert "Loading reached the nonlinear range: yes" in out
    table = (folder / "j2_props_check" / "results_table.txt").read_text()
    assert "SIGY0" in table and "stress 11" in table
    assert (folder / "j2_props_check" / "results_table.csv").is_file()
    assert (folder / "j2_props_check" / "check_summary.txt").is_file()
