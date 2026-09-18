"""The two developer screens of the IMQCAM presentation, driven through AppTest.

Slide 16/40, "Constitutive Jacobian": load the UMAT, set NTENS, differentiate
STRESS with respect to DSTRAN and write into DDSDDE; the tangent block is found
for you; one click. Slide 17/41, "Parameter Sensitivities": take that UMAT,
list the parameters with their PROPS index and value, tick the stress and state
derivatives, Build.

These run in the ordinary offline suite (gfortran, no browser, no Abaqus). The
same flows in a real browser are in ``test_imqcam_developer_screens_browser.py``
(``pytest -m gui``). Each test compares the screen's product with the command
line's product for the same inputs, and the transformed tangent and the built
provider with an independent reference: centred finite differences of the
ORIGINAL source.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from streamlit.testing.v1 import AppTest

from umat_oti.provider import collaborator
from umat_oti.services import jacobian_request as jr
from umat_oti.validation.parameter_sensitivity_provider import J2_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
J2_SOURCE = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"
FCC_SOURCE = REPO_ROOT / "parameter_sensitivity" / "models" / "m6_fcc" / "umat.for"
ELASTIC_SOURCE = REPO_ROOT / "UMATs" / "UMATs" / "ICP" / "elasticity" / "elastic.f"
ELASTIC_CONTRACT = REPO_ROOT / "examples" / "elastic_minimal.json"

#: The parameter tables the presentation shows: slide 41 (J2) and slide 17 (FCC).
J2_TABLE = [("E", 1, 200000.0), ("nu", 2, 0.3), ("SIGY0", 3, 250.0), ("H", 4, 2000.0)]
FCC_TABLE = [("C11", 1, 168000.0), ("C12", 2, 121000.0), ("C44", 3, 75000.0), ("g0", 4, 13.0),
             ("gsat", 5, 55.0), ("h0", 6, 800.0), ("a", 7, 2.0), ("q", 8, 1.4),
             ("gd0", 9, 0.001), ("m", 10, 0.05)]

JACOBIAN = "from umat_oti.app.presentation_screens import render_jacobian_screen\nrender_jacobian_screen()"
PROVIDER = "from umat_oti.app.presentation_screens import render_provider_screen\nrender_provider_screen()"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("UMAT_OTI_GUI_WORKSPACE", str(tmp_path / "gui"))
    return tmp_path


def _jacobian_run(source: Path, ntens: int) -> dict:
    app = AppTest.from_string(JACOBIAN, default_timeout=180).run()
    app.text_input(key="pj_path").set_value(str(source)).run()
    assert not app.exception and not app.error
    app.number_input(key="pj_ntens").set_value(ntens).run()
    # The three derivative fields default to the presentation's choices.
    assert [box.value for box in app.selectbox] == ["DSTRAN", "STRESS", "DDSDDE"]
    shown = {box.label: box.value for box in app.text_input}
    app.button(key="pj_transform").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    assert [s.value for s in app.success] == ["Transform succeeded"]
    run = app.session_state["pj_run"]
    run["shown"] = shown
    run["downloads"] = [button.label for button in app.get("download_button")]
    return run


#: What the screen says about the lines that assign DDSDDE, and the block the
#: transform report says it replaced. The J2 routine's elastic stiffness at
#: 38-48 is the predictor the stress update reads, so it stays; the FCC routine
#: assigns DDSDDE only there (line 132, the slide's "132-132").
BLOCKS = {
    "m3_j2": ("86-108 replaced; 38-48 kept (read by the stress update); extraction after line 111", "86-108"),
    "elastic": ("83-87 replaced; extraction after line 87", "83-87"),
    "m6_fcc": ("131-133 kept (read by the stress update); extraction after line 189", "(none found)"),
}


@pytest.mark.integration
@pytest.mark.parametrize("source,ntens,model", [
    (J2_SOURCE, 6, "m3_j2"), (ELASTIC_SOURCE, 4, "elastic"), (FCC_SOURCE, 6, "m6_fcc"),
], ids=["m3_j2", "elastic", "m6_fcc"])
def test_four_fields_and_one_click_give_what_the_command_line_gives(workspace, source, ntens, model):
    run = _jacobian_run(source, ntens)
    assert run["exit_code"] == 0
    # "The Jacobian block is found for you": shown before the click, and the
    # transform report agrees about the block it replaced.
    shown, replaced = BLOCKS[model]
    assert run["shown"]["line(s) that assign the tangent"] == shown
    assert run["tangent_block"] == shown
    assert jr.format_lines(run["tangent_lines"]) == replaced
    assert "STRESS" in run["shown"]["variables carried through the derivative"]
    assert any(label.startswith("Transformed UMAT") for label in run["downloads"])
    assert any(label.startswith("Transform report") for label in run["downloads"])

    # The same four fields through the command line.
    cli_out = workspace / "cli"
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli", "jacobian", str(source), "--ntens", str(ntens),
         "--out", str(cli_out)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    gui_file, cli_file = Path(run["transformed"]), cli_out / Path(run["transformed"]).name
    assert gui_file.read_bytes() == cli_file.read_bytes()
    assert Path(run["drop_in"]).read_bytes() == (cli_out / Path(run["drop_in"]).name).read_bytes()
    assert json.loads(completed.stdout)["transform_success"] is True
    # And through umat-oti-config with the contract the screen wrote.
    config_out = workspace / "config"
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli_json", "--config", run["contract"],
         "--out", str(config_out)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert (config_out / gui_file.name).read_bytes() == gui_file.read_bytes()


@pytest.mark.integration
def test_a_routine_that_is_not_a_umat_is_refused_with_the_services_reasons(workspace):
    source = workspace / "not_a_umat.for"
    source.write_text("      SUBROUTINE FOO(X)\n      X=1.0\n      RETURN\n      END\n")
    app = AppTest.from_string(JACOBIAN, default_timeout=180).run()
    app.text_input(key="pj_path").set_value(str(source)).run()
    app.button(key="pj_transform").click().run()
    assert not app.exception
    run = app.session_state["pj_run"]
    assert run["exit_code"] != 0 and not run["succeeded"]
    assert any(e.value.startswith(f"Transform did not succeed (exit code {run['exit_code']}")
               for e in app.error)
    assert not app.success and not app.get("download_button")
    # The command line refuses the same four fields with the same exit code.
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli", "jacobian", str(source), "--ntens", "6",
         "--out", str(workspace / "cli")], capture_output=True, text=True)
    assert completed.returncode == run["exit_code"]


@pytest.mark.integration
def test_the_inferred_block_reproduces_the_curated_elastic_example(workspace):
    """The four fields give byte-for-byte the output of the hand-written contract."""
    run = _jacobian_run(ELASTIC_SOURCE, 4)
    curated = workspace / "curated"
    completed = subprocess.run(
        [sys.executable, "-m", "umat_oti.cli_json", "--config", str(ELASTIC_CONTRACT),
         "--out", str(curated)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert Path(run["transformed"]).read_bytes() == (curated / "elastic_oti.f").read_bytes()


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.parametrize("source,ntens,nstatv,props,path", [
    (J2_SOURCE, 6, 1, [200000.0, 0.3, 250.0, 2000.0], J2_PATH),
    (ELASTIC_SOURCE, 4, 0, [210000.0, 0.3],
     np.array([[4e-4, -1e-4, 0.0, 2e-4], [3e-4, 5e-5, -1e-4, -1e-4]])),
], ids=["m3_j2", "elastic"])
def test_the_downloaded_umat_returns_the_tangent_of_the_original(workspace, source, ntens,
                                                                 nstatv, props, path):
    """DDSDDE from the drop-in against centred FD of the ORIGINAL routine.

    The J2 path crosses elastic, plastic and unloading increments (the
    provider verifier's path, checked there to stay on one branch under these
    perturbations). Tangents are compared at every increment, scaled by the
    increment's largest reference entry, at three strain steps.
    """
    from tangent_reference import compare_with_original

    run = _jacobian_run(source, ntens)
    measured = compare_with_original(Path(run["drop_in"]), source, workspace / "fd",
                                     props=props, path=path, ntens=ntens, nstatv=nstatv)
    assert measured["primal_max_abs"] <= 1e-10 * measured["stress_scale"]
    assert max(measured["tangent_scaled_errors"]) < 2e-6, measured["tangent_scaled_errors"]


@pytest.mark.slow
@pytest.mark.fortran
def test_the_fcc_tangent_is_the_limit_of_the_finite_differences(workspace):
    """Slide 16's own example: the 12-slip-system crystal, at slide 17's values.

    The path is the provider check path scaled by 0.3, which drives slip on
    this rate-dependent, explicitly sub-stepped update without leaving the
    range it integrates (the unscaled path gives non-finite values in the
    ORIGINAL). Here the centred difference's truncation error, proportional
    to h**2, dominates at the larger steps, so no fixed step agrees to 2e-6.
    What is required instead is the behaviour of a derivative the differences
    converge to: each tenfold reduction of the step reduces the scaled error
    by at least 50 (h**2 gives 100), and the finest step agrees to 1e-8.
    """
    from tangent_reference import compare_with_original

    run = _jacobian_run(FCC_SOURCE, 6)
    props = [value for _, _, value in FCC_TABLE]
    measured = compare_with_original(Path(run["drop_in"]), FCC_SOURCE, workspace / "fd",
                                     props=props, path=J2_PATH * 0.3, ntens=6, nstatv=12)
    errors = measured["tangent_scaled_errors"]
    assert measured["primal_max_abs"] <= 1e-10 * measured["stress_scale"]
    assert errors[0] / errors[1] > 50 and errors[1] / errors[2] > 50, errors
    assert errors[2] < 1e-8, errors


def _provider_app(source: Path, table, nstatv: int, *, j2: bool) -> AppTest:
    app = AppTest.from_string(PROVIDER, default_timeout=900).run()
    app.text_input(key="pp_path").set_value(str(source)).run()
    assert not app.exception and not app.error
    # A new source starts from an empty table (the user lists the parameters).
    assert app.session_state["pp_rows"] == []
    app.number_input(key="pp_nstatv").set_value(nstatv).run()
    app.session_state["pp_rows"] = [{"parameter": n, "PROPS index": i, "value": v} for n, i, v in table]
    app.session_state["pp_table_version"] += 1
    app.run()
    assert app.checkbox(key="pp_stress").value and app.checkbox(key="pp_state").value
    if j2:
        app.checkbox(key="pp_j2").check().run()
    assert not app.button(key="pp_build").disabled, [w.value for w in app.warning]
    app.button(key="pp_build").click().run()
    assert not app.exception, app.exception
    return app


@pytest.mark.slow
@pytest.mark.fortran
def test_the_build_screen_hands_over_the_four_files_for_j2(workspace):
    app = _provider_app(J2_SOURCE, J2_TABLE, 1, j2=True)
    summary = app.session_state["pp_result"]
    assert summary["exit_code"] == 0 and summary["build"]["exit_code"] == 0
    assert [s.value for s in app.success] == ["Build succeeded and verified"]
    verification = summary["verification"]
    assert verification["exit_code"] == 0 and verification["passed"]
    result = verification["result"]
    assert result["props"] == [value for _, _, value in J2_TABLE]
    assert result["branches"][:4] == ["elastic", "elastic", "plastic", "plastic"]
    assert summary["tie"]["identical_outputs"] and summary["tie"]["generated_sources_identical"]
    shared = {name: Path(entry["path"]) for name, entry in summary["shared"].items()}
    assert set(shared) == set(collaborator.SHARED_FILES)
    mapping = json.loads(shared["Mapping.json"].read_text())
    assert mapping == json.loads(Path(summary["canonical"]["contract"]).read_text())
    assert mapping["object"]["sha256_full"] == _sha(shared["OTI_UMAT.obj"])
    assert mapping["regular_object"]["sha256_full"] == _sha(shared["REAL_UMAT.obj"])
    assert [p["name"] for p in mapping["parameters"]] == ["E", "nu", "SIGY0", "H"]
    report = shared["transform_report.txt"].read_text()
    assert "exit code 0" in report and "bit-identical" in report
    labels = [button.label for button in app.get("download_button")]
    for name in collaborator.SHARED_FILES:
        assert any(label.startswith(name) for label in labels), labels

    # The command line on the same contract gives the same verdict and numbers.
    contract = Path(summary["contract"])
    cli = subprocess.run([sys.executable, "-m", "umat_oti.validation.parameter_sensitivity_provider",
                          str(contract), "--out", str(workspace / "cli_verify")],
                         capture_output=True, text=True)
    assert cli.returncode == verification["exit_code"] == 0
    cli_result = json.loads((workspace / "cli_verify" / "verification.json").read_text())
    for key in ("parameter_steps", "tangent_steps", "fd_plateau", "primal_stress_max_abs"):
        assert cli_result[key] == result[key], key


@pytest.mark.slow
@pytest.mark.fortran
def test_the_build_screen_builds_the_ten_parameter_fcc_and_reports_the_verifier(workspace):
    """Slide 17's ten crystal-plasticity parameters.

    The build succeeds. The provider verifier's fixed check path (the J2 path
    of docs/PROVIDER.md) drives this explicit, sub-stepped crystal update to
    non-finite values, so the verifier refuses; the screen must say exactly what
    the verifier said, with its exit code, and must not call the object verified.
    """
    app = _provider_app(FCC_SOURCE, FCC_TABLE, 12, j2=False)
    summary = app.session_state["pp_result"]
    assert summary["build"]["exit_code"] == 0
    mapping = json.loads(Path(summary["shared"]["Mapping.json"]["path"]).read_text())
    assert [(p["name"], p["props_index"]) for p in mapping["parameters"]] == \
        [(name, index) for name, index, _ in FCC_TABLE]
    assert mapping["dimensions"] == {"ntens": 6, "nprops": 10, "nstatev": 12, "nparam": 10}
    cli = subprocess.run([sys.executable, "-m", "umat_oti.validation.parameter_sensitivity_provider",
                          summary["contract"], "--out", str(workspace / "cli_verify"), "--elastic"],
                         capture_output=True, text=True)
    assert summary["verification"]["exit_code"] == cli.returncode
    assert summary["exit_code"] == (0 if cli.returncode == 0 else 1)
    if cli.returncode:
        assert "Build succeeded; verification did not pass" in [w.value for w in app.warning]
        assert "Verification failed" in " ".join(e.value for e in app.error)


@pytest.mark.unit
@pytest.mark.parametrize("rows,message", [
    ([], "at least one"),
    ([{"parameter": "E", "PROPS index": 1, "value": None}], "needs a name"),
    ([{"parameter": "E", "PROPS index": 1.5, "value": 1.0}], "positive integer"),
    ([{"parameter": "E", "PROPS index": 1, "value": 1.0},
      {"parameter": "E", "PROPS index": 2, "value": 1.0}], "names must be unique"),
    ([{"parameter": "E", "PROPS index": 1, "value": 1.0},
      {"parameter": "F", "PROPS index": 1, "value": 1.0}], "indices must be unique"),
])
def test_the_parameter_table_refuses_what_it_cannot_mean(rows, message):
    with pytest.raises(ValueError, match=message):
        collaborator.parse_parameters(rows)


@pytest.mark.unit
def test_the_derivative_ticks_map_onto_what_the_provider_returns():
    parameters = collaborator.parse_parameters(
        [{"parameter": n, "PROPS index": i, "value": v} for n, i, v in J2_TABLE])
    contract = collaborator.provider_contract("umat.for", name="m3_j2", nstatev=1,
                                              parameters=parameters)
    assert contract["history"] == {"path_dependent": True}
    assert contract["validation"]["props_values"] == [200000.0, 0.3, 250.0, 2000.0]
    assert contract["output"] == {"object": "umat_m3_j2_oti.obj", "contract": "umat_m3_j2_oti.json"}
    with pytest.raises(ValueError, match="cannot be switched off"):
        collaborator.provider_contract("umat.for", name="m", nstatev=1, parameters=parameters,
                                       stress=False)
    with pytest.raises(ValueError, match="NSTATV > 0"):
        collaborator.provider_contract("umat.for", name="m", nstatev=1, parameters=parameters,
                                       state=False)
    stateless = collaborator.provider_contract("umat.for", name="m", nstatev=0,
                                               parameters=parameters, state=False)
    assert stateless["history"] == {"path_dependent": False}
    with pytest.raises(ValueError, match=r"slot\(s\) \[2\]"):
        collaborator.provider_contract(
            "umat.for", name="m", nstatev=0,
            parameters=collaborator.parse_parameters(
                [{"parameter": "E", "PROPS index": 1, "value": 1.0},
                 {"parameter": "H", "PROPS index": 3, "value": 1.0}]))
