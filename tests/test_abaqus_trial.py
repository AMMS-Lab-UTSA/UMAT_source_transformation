import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.services.abaqus_trial import run_abaqus_trial


def test_workflow_deck_uses_cumulative_targets_and_material_values(tmp_path):
    from umat_oti.abaqus.trial_deck import generate_workflow_deck

    settings = tmp_path / "material.json"
    settings.write_text(json.dumps({"kinematics": "small_strain", "nstatev": 4,
                                    "props_values": [123000.0, 0.29],
                                    "check_path": {"increments": [[0.001, 0, 0, 0, 0, 0],
                                                                  [-0.0005, 0, 0, 0, 0, 0]]}}))
    deck, record = generate_workflow_deck(settings, source=tmp_path / "umat.f90", ntens=6)
    assert record["props"] == (123000.0, 0.29)
    assert record["nstatv"] == 4
    assert [segment["strain"][0] for segment in record["loading"]] == [0.001, 0.0005]
    assert all(segment["period"] == 1.0 for segment in record["loading"])
    assert deck.count("*STEP,") == 2
    assert deck.count("*INITIAL CONDITIONS, TYPE=TEMPERATURE") == 1
    assert "ALL, 293.15" in deck


@pytest.mark.parametrize("failure", [None, "jacobian", "sensitivities", "abaqus"])
def test_complete_workflow_sequences_and_gates_abaqus(tmp_path, monkeypatch, failure):
    from umat_oti.services import complete_workflow as workflow

    source = tmp_path / "umat.f90"
    source.write_text("subroutine umat(props)\nreal(8) props(2), young\nyoung=props(1)\nend\n")
    material = tmp_path / "material.json"
    material.write_text(json.dumps({"kinematics": "small_strain", "nstatev": 0,
                                    "props_values": [123000.0, 0.29],
                                    "check_path": {"dstran_per_increment": [0.001, 0, 0, 0, 0, 0],
                                                   "n_increments": 2}}))
    events = []
    monkeypatch.setattr(workflow, "_payload_with_resolved_closure",
                        lambda *args: (json.dumps({"source": str(source)}).encode(), {"entry_routine": "UMAT"}))

    def tangent(source, out, **kwargs):
        events.append("jacobian")
        out.mkdir()
        return SimpleNamespace(succeeded=failure != "jacobian", summary={"transform_success": failure != "jacobian"},
                               contract_path=out / "jacobian_contract.json")

    monkeypatch.setattr(workflow, "run_jacobian_transform", tangent)
    monkeypatch.setattr(workflow, "stage_model", lambda *args: source)

    def package(*args, **kwargs):
        events.append("sensitivities")
        assert kwargs["verify"] is True
        return {"exit_code": 1 if failure == "sensitivities" else 0}

    def trial(run, deck, **kwargs):
        events.append("abaqus")
        assert deck.is_file()
        assert "*USER MATERIAL" in deck.read_text()
        assert kwargs["run_prefix"] == ""
        return {"status": "failed" if failure == "abaqus" else "completed", "verified": False}

    monkeypatch.setattr(workflow, "package", package)
    monkeypatch.setattr("umat_oti.services.abaqus_trial.run_abaqus_trial", trial)
    output = tmp_path / "out"
    summary = workflow.run_complete_workflow(source, material, output,
                    abaqus_options=workflow.CompleteAbaqusOptions(modules="", run_prefix=""))
    expected_events = ["jacobian", "sensitivities", "abaqus"]
    if failure is not None:
        expected_events = expected_events[:expected_events.index(failure) + 1]
    assert events == expected_events
    assert summary["exit_code"] == (1 if failure else 0)
    assert summary.get("failed_stage") == failure
    assert summary["stages"]["abaqus"]["verified"] is False
    assert json.loads((output / "workflow_summary.json").read_text()) == summary


def test_all_cli_forwards_abaqus_options(tmp_path, monkeypatch, capsys):
    from umat_oti.cli import main

    def workflow(source, material, output, **kwargs):
        options = kwargs["abaqus_options"]
        assert options.command == "custom-abaqus"
        assert options.modules == ""
        assert options.run_prefix == ""
        assert not options.smoke
        return {"exit_code": 0}

    monkeypatch.setattr("umat_oti.services.complete_workflow.run_complete_workflow", workflow)
    assert main(["all", "umat.f90", "--material-config", "material.json", "--out", str(tmp_path),
                 "--abaqus", "--abaqus-command", "custom-abaqus", "--abaqus-modules", "",
                 "--abaqus-run-prefix", ""]) == 0
    assert json.loads(capsys.readouterr().out)["exit_code"] == 0


def test_all_cli_material_configuration_is_optional(tmp_path, monkeypatch, capsys):
    from umat_oti.cli import main

    def workflow(source, material, output, **kwargs):
        assert material is None
        assert kwargs["material_discovery_root"] == tmp_path
        return {"exit_code": 0}

    monkeypatch.setattr("umat_oti.services.complete_workflow.run_complete_workflow", workflow)
    assert main(["all", "umat.f90", "--out", str(tmp_path),
                 "--material-discovery-root", str(tmp_path), "--abaqus"]) == 0
    assert json.loads(capsys.readouterr().out)["exit_code"] == 0


def test_experiment_generates_workflow_config(experiment):
    from umat_oti.abaqus.trial_deck import main

    output = experiment.parent / "auto"
    assert main(["--discover-workflow", "--settings", str(experiment),
                 "--source", str(experiment.parent / "umat.f90"), "--ntens", "6",
                 "--out", str(output)]) == 0
    material = json.loads((output / "material_workflow.json").read_text())
    assert material["props_values"] == [210000.0, 0.3]
    assert material["nstatev"] == 0
    assert material["check_path"]["increments"] == [[0, 0, 0, 0.001, 0, 0]] * 20


@pytest.mark.parametrize("changes", [{"kinematics": "finite"},
                                     {"initial_state_from_user_subroutine": True},
                                     {"initial_statev": [1.0]},
                                     {"orientation_axes": [1, 0, 0, 0, 1, 0]},
                                     {"isothermal_temperature": 500.0}])
def test_workflow_discovery_refuses_unsupported_settings(experiment, changes):
    from umat_oti.abaqus.trial_deck import main

    experiment.write_text(json.dumps({**json.loads(experiment.read_text()), **changes}))
    output = experiment.parent / "out"
    with pytest.raises(SystemExit) as error:
        main(["--discover-workflow", "--settings", str(experiment),
              "--source", str(experiment.parent / "umat.f90"), "--ntens", "6",
              "--out", str(output)])
    assert error.value.code == 2
    assert not (output / "material_workflow.json").exists()


def test_all_without_material_data_reports_discovery_failure(tmp_path, capsys):
    from umat_oti.cli import main

    source = tmp_path / "umat.f90"
    source.write_text("subroutine umat(props)\nreal(8) props(2), young\nyoung=props(1)\nend\n")
    output = tmp_path / "out"
    assert main(["all", str(source), "--out", str(output), "--abaqus"]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed_stage"] == "material_settings"
    assert summary["stages"]["material_settings"]["automatic"] is True
    assert summary["stages"]["abaqus"]["status"] == "not_run"
    assert (output / "abaqus_discovery.json").is_file()
    assert not (output / "material_workflow.json").exists()
    assert not (output / "jacobian").exists()


@pytest.mark.parametrize("smoke", [False, True])
def test_complete_stage_reuses_explicit_deck_or_smoke(candidate, monkeypatch, smoke):
    from umat_oti.services.complete_workflow import CompleteAbaqusOptions, _complete_abaqus_stage

    run, deck = candidate

    def trial(actual_run, actual_deck, **kwargs):
        assert actual_run is run
        assert actual_deck == (None if smoke else deck)
        assert kwargs["smoke"] is smoke
        return {"status": "built" if smoke else "completed", "verified": False}

    monkeypatch.setattr("umat_oti.services.abaqus_trial.run_abaqus_trial", trial)
    result = _complete_abaqus_stage(run, run.transformed_source, deck.parent / "absent-material.json",
                                    CompleteAbaqusOptions(input_deck=None if smoke else deck, smoke=smoke))
    assert result["status"] == ("built" if smoke else "completed")
    assert not (deck.parent / "abaqus_trial.inp").exists()


@pytest.fixture
def experiment(tmp_path):
    settings = tmp_path / "experiment.json"
    settings.write_text(json.dumps({
        "name": "synthetic", "element_type": "C3D8", "kinematics": "small strain",
        "props": [210000.0, 0.3], "material_provenance": "synthetic test",
        "nstatv": 0, "loading": [{"name": "shear", "strain": [0, 0, 0, 0.02, 0, 0],
                                  "increments": 20, "period": 2.0}]}))
    return settings


def test_generate_trial_deck_reuses_generator(experiment):
    from umat_oti.abaqus.trial_deck import generate_trial_deck
    from umat_oti.abaqus.deck import generate_deck
    from umat_oti.abaqus.manifest import LoadingSegment, VerificationManifest

    source = experiment.parent / "umat.f90"
    deck, record = generate_trial_deck(experiment, source=source, ntens=6)
    expected = VerificationManifest(name="synthetic", source=source, element_type="C3D8",
                                    props=[210000.0, 0.3], nprops=2, nstatv=0,
                                    material_provenance="synthetic test",
                                    loading=(LoadingSegment("shear", [0, 0, 0, 0.02, 0, 0], 20, 2.0),))
    assert deck == generate_deck(expected)
    assert record["loading"][0]["strain"][3] == 0.02


@pytest.mark.parametrize("sidecar", [False, True])
def test_auto_discovery_fills_unknowns_and_preserves_loading(experiment, monkeypatch, sidecar):
    from umat_oti.abaqus.trial_deck import generate_trial_deck
    from umat_oti.abaqus.manifest import LoadingSegment, VerificationManifest

    source = experiment.parent / "umat.f90"
    manifest = VerificationManifest(name="discovered", source=source, props=(120000.0, 0.28),
                                    nprops=2, nstatv=3, material_provenance="author deck",
                                    loading=(LoadingSegment("extension", (0.001, 0, 0, 0, 0, 0)),))
    planned = SimpleNamespace(found=True, manifest=manifest,
                              as_dict=lambda: {"found": True, "material": "author deck"})
    monkeypatch.setattr("umat_oti.abaqus.experiment.plan", lambda *args: planned)
    if sidecar:
        raw = json.loads(experiment.read_text())
        raw.update(props=None, nstatv=None, kinematics=None, material_provenance="")
        experiment.write_text(json.dumps(raw))
    report = experiment.parent / "discovery.json"
    deck, record = generate_trial_deck(experiment if sidecar else None, source=source, ntens=6,
                                       discovery_root=experiment.parent, discovery_report=report)
    assert record["props"] == [120000.0, 0.28]
    assert record["nstatv"] == 3
    assert record["loading"][0]["name"] == ("shear" if sidecar else "extension")
    assert "120000" in deck
    assert json.loads(report.read_text())["found"] is True


def test_auto_discovery_records_refusal_without_inventing_properties(tmp_path, monkeypatch):
    from umat_oti.abaqus.trial_deck import generate_trial_deck

    planned = SimpleNamespace(found=False, manifest=None,
                              experiment=SimpleNamespace(refusal="No matching material deck"),
                              as_dict=lambda: {"refusal": "No matching material deck"})
    monkeypatch.setattr("umat_oti.abaqus.experiment.plan", lambda *args: planned)
    report = tmp_path / "discovery.json"
    with pytest.raises(ValueError, match="No matching material deck"):
        generate_trial_deck(None, source=tmp_path / "umat.f90", ntens=6,
                            discovery_root=tmp_path, discovery_report=report)
    assert report.is_file()


@pytest.mark.parametrize("change", [{"nstatv": -1}, {"props": []}, {"ntens": 4},
                                    {"amplitdue": 0.1}, {"loading": []},
                                    {"material_provenance": ""}, {"kinematics": "guess"}])
def test_invalid_experiment_is_refused(experiment, change):
    from umat_oti.abaqus.trial_deck import generate_trial_deck

    raw = json.loads(experiment.read_text())
    experiment.write_text(json.dumps({**raw, **change}))
    with pytest.raises(ValueError):
        generate_trial_deck(experiment, source=experiment.parent / "umat.f90", ntens=6)


@pytest.fixture
def candidate(tmp_path):
    source = tmp_path / "candidate.f90"
    source.write_text("subroutine umat\nend subroutine\n")
    (tmp_path / "compile_order.txt").write_text("candidate.f90\n")
    deck = tmp_path / "model.inp"
    deck.write_text("*Heading\nSynthetic trial\n")
    run = SimpleNamespace(contract_path=tmp_path / "jacobian_contract.json",
                          transformed_source=source,
                          summary={"transform_success": False, "blockers": [],
                                   "semantic_checks": {"stress_path_consumes_the_seed": False}})
    return run, deck


def test_semantic_failure_requires_override(candidate):
    run, deck = candidate
    report = run_abaqus_trial(run, deck)
    assert report["status"] == "blocked"
    assert "--abaqus-allow-semantic-failures" in report["error"]
    assert "command" not in report


@pytest.mark.parametrize("returncode,library,status", [(0, True, "built"),
                                                       (0, False, "failed"),
                                                       (1, True, "failed")])
def test_build_smoke_needs_no_material_settings(candidate, monkeypatch, returncode, library, status):
    run, deck = candidate
    (deck.parent / "standardU.so").write_text("stale library")
    (deck.parent / "dependencies").mkdir()
    (deck.parent / "dependencies" / "constants.inc").write_text("integer :: count\n")

    def execute(command, *, cwd, **kwargs):
        assert "make" in command[-1]
        assert "library=" in command[-1]
        assert "input=" not in command[-1]
        assert cwd != deck.parent
        assert not (cwd / "standardU.so").exists()
        assert (cwd / "dependencies" / "constants.inc").is_file()
        if library:
            (cwd / "standardU.so").write_text("new synthetic library")
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr("umat_oti.services.abaqus_trial.subprocess.run", execute)
    report = run_abaqus_trial(run, smoke=True, allow_semantic_failures=True,
                             abaqus_modules="", run_prefix="")
    assert report["status"] == status
    assert report["mode"] == "build_smoke"
    assert report["input"] is None
    assert report["analysis_completed"] is False
    assert report["verified"] is False


@pytest.mark.parametrize("transform_code,status,expected", [(1, "built", 1),
                                                          (0, "built", 0),
                                                          (0, "failed", 1)])
def test_cli_smoke_bypasses_incomplete_sidecar(candidate, monkeypatch, capsys,
                                              transform_code, status, expected):
    from umat_oti.cli import main

    run, deck = candidate
    run.exit_code = transform_code
    run.transformed_source.with_suffix(".abaqus.json").write_text('{"props": null}')
    monkeypatch.setattr("umat_oti.cli.run_jacobian_transform", lambda *args, **kwargs: run)

    def trial(actual_run, input_deck, **kwargs):
        assert input_deck is None
        assert kwargs["smoke"] is True
        assert kwargs["allow_semantic_failures"] is True
        return {"status": status, "verified": False}

    monkeypatch.setattr("umat_oti.services.abaqus_trial.run_abaqus_trial", trial)
    assert main(["jacobian", str(run.transformed_source), "--ntens", "6", "--out", str(deck.parent),
                 "--abaqus-smoke", "--abaqus-allow-semantic-failures"]) == expected
    assert json.loads(capsys.readouterr().out)["abaqus_trial"]["status"] == status


@pytest.mark.parametrize("options", [["--abaqus"], ["--abaqus-input", "model.inp"],
                                    ["--abaqus-experiment", "experiment.json"]])
def test_cli_smoke_refuses_analysis_options(tmp_path, options):
    from umat_oti.cli import main

    with pytest.raises(SystemExit) as error:
        main(["jacobian", "unused.f90", "--ntens", "6", "--out", str(tmp_path),
              "--abaqus-smoke", *options])
    assert error.value.code == 2


@pytest.mark.parametrize("returncode,completed,status", [(0, True, "completed"),
                                                          (0, False, "failed"),
                                                          (1, True, "failed")])
def test_trial_executes_without_claiming_verification(candidate, monkeypatch, returncode, completed, status):
    run, deck = candidate

    def execute(command, *, cwd, **kwargs):
        import shlex

        invocation = shlex.split(command[-1].split("exec ", 1)[1])
        job = next(arg.split("=", 1)[1] for arg in invocation if arg.startswith("job="))
        assert f"input={deck}" in invocation
        assert Path(next(arg.split("=", 1)[1] for arg in invocation if arg.startswith("user="))).is_file()
        if completed:
            (cwd / f"{job}.dat").write_text("THE ANALYSIS HAS BEEN COMPLETED\n")
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr("umat_oti.services.abaqus_trial.subprocess.run", execute)
    report = run_abaqus_trial(run, deck, allow_semantic_failures=True,
                             abaqus_modules="", run_prefix="")
    assert report["status"] == status
    assert report["verified"] is False
    assert report["semantic_override"] is True
    assert run.summary["transform_success"] is False
    assert json.loads(Path(report["report"]).read_text()) == report


@pytest.mark.parametrize("problem", ["blocker", "missing_unit", "missing_candidate", "other_failure"])
def test_override_does_not_bypass_hard_failures(candidate, problem):
    run, deck = candidate
    if problem == "blocker":
        run.summary["blockers"] = ["unsupported source"]
    elif problem == "missing_unit":
        (deck.parent / "compile_order.txt").write_text("candidate.f90\nmissing.f90\n")
    elif problem == "missing_candidate":
        run.transformed_source = None
    else:
        run.summary["semantic_checks"] = {}
    report = run_abaqus_trial(run, deck, allow_semantic_failures=True)
    assert report["status"] == "blocked"
    assert "command" not in report


@pytest.mark.parametrize("transform_code,trial_status,expected", [
    (1, "completed", 1), (0, "failed", 1), (0, "completed", 0)])
def test_cli_trial_preserves_transform_failure(candidate, monkeypatch, capsys,
                                               transform_code, trial_status, expected):
    from umat_oti.cli import main

    run, deck = candidate
    run.exit_code = transform_code
    monkeypatch.setattr("umat_oti.cli.run_jacobian_transform", lambda *args, **kwargs: run)

    def trial(actual_run, input_deck, **kwargs):
        assert actual_run is run
        assert input_deck == deck
        assert kwargs["allow_semantic_failures"] is True
        return {"status": trial_status, "verified": False}

    monkeypatch.setattr("umat_oti.services.abaqus_trial.run_abaqus_trial", trial)
    code = main(["jacobian", str(run.transformed_source), "--ntens", "6", "--out", str(deck.parent),
                 "--abaqus-input", str(deck), "--abaqus-allow-semantic-failures"])
    assert code == expected
    assert json.loads(capsys.readouterr().out)["abaqus_trial"]["verified"] is False


def test_cli_override_requires_deck(tmp_path):
    from umat_oti.cli import main

    with pytest.raises(SystemExit) as error:
        main(["jacobian", "unused.f90", "--ntens", "6", "--out", str(tmp_path),
              "--abaqus-allow-semantic-failures"])
    assert error.value.code == 2


@pytest.mark.parametrize("explicit", [False, True])
def test_cli_generates_deck_by_default(candidate, experiment, monkeypatch, capsys, explicit):
    from umat_oti.cli import main

    run, deck = candidate
    run.exit_code = 1
    run.transformed_source.with_suffix(".abaqus.json").write_text(experiment.read_text())
    monkeypatch.setattr("umat_oti.cli.run_jacobian_transform", lambda *args, **kwargs: run)

    def trial(actual_run, input_deck, **kwargs):
        assert input_deck == deck.parent / "abaqus_trial.inp"
        assert "*ELEMENT, TYPE=C3D8" in input_deck.read_text()
        assert (deck.parent / "abaqus_experiment.json").is_file()
        assert kwargs["allow_semantic_failures"] is True
        return {"status": "completed", "verified": False}

    monkeypatch.setattr("umat_oti.services.abaqus_trial.run_abaqus_trial", trial)
    arguments = ["jacobian", str(run.transformed_source), "--ntens", "6", "--out", str(deck.parent),
                 "--abaqus", "--abaqus-allow-semantic-failures"]
    if explicit:
        arguments += ["--abaqus-experiment", str(experiment)]
    assert main(arguments) == 1
    assert json.loads(capsys.readouterr().out)["abaqus_trial"]["status"] == "completed"


def test_cli_existing_deck_overrides_experiment(candidate, monkeypatch):
    from umat_oti.cli import main

    run, deck = candidate
    run.exit_code = 0
    monkeypatch.setattr("umat_oti.cli.run_jacobian_transform", lambda *args, **kwargs: run)

    def trial(actual_run, input_deck, **kwargs):
        assert input_deck == deck
        return {"status": "completed", "verified": False}

    monkeypatch.setattr("umat_oti.services.abaqus_trial.run_abaqus_trial", trial)
    assert main(["jacobian", str(run.transformed_source), "--ntens", "6", "--out", str(deck.parent),
                 "--abaqus", "--abaqus-input", str(deck),
                 "--abaqus-experiment", "does-not-exist.json"]) == 0
    assert not (deck.parent / "abaqus_trial.inp").exists()


def test_cli_generation_requires_settings(tmp_path, capsys):
    from umat_oti.cli import main

    (tmp_path / "umat.f90").write_text("subroutine umat(stress, props)\nreal(8) stress(6),props(2)\nend\n")
    with pytest.raises(SystemExit) as error:
        main(["jacobian", str(tmp_path / "umat.f90"), "--ntens", "6", "--out", str(tmp_path), "--abaqus"])
    assert error.value.code == 2
    assert "Automatic Abaqus material discovery failed" in capsys.readouterr().err
    assert (tmp_path / "abaqus_discovery.json").is_file()


def test_real_planner_discovers_material_without_sidecar(tmp_path):
    from umat_oti.abaqus.deck import generate_deck
    from umat_oti.abaqus.manifest import VerificationManifest, uniaxial
    from umat_oti.abaqus.trial_deck import generate_trial_deck

    source = tmp_path / "umat.f90"
    source.write_text("""subroutine umat(stress, dstran, props)
implicit none
real(8) stress(6), dstran(6), props(2), young, poisson
young = props(1)
poisson = props(2)
stress = stress + young*dstran
end subroutine
""")
    material = VerificationManifest(name="elastic", source=source, props=(120000.0, 0.28),
                                    nprops=2, nstatv=3, material_provenance="synthetic fixture",
                                    loading=(uniaxial(0.001),))
    (tmp_path / "umat.inp").write_text(generate_deck(material))
    deck, record = generate_trial_deck(None, source=source, ntens=6, discovery_root=tmp_path)
    assert record["props"] == [120000.0, 0.28]
    assert record["nstatv"] == 3
    assert "umat.inp" in record["material_provenance"]
    assert "*USER MATERIAL" in deck


def test_real_subprocess_trial(candidate):
    import sys
    import shlex

    run, deck = candidate
    executable = deck.parent / "fake abaqus.py"
    executable.write_text("""import sys
from pathlib import Path
job = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('job='))
Path(job + '.dat').write_text('THE ANALYSIS HAS BEEN COMPLETED\\n')
print('synthetic Abaqus completed')
""")
    report = run_abaqus_trial(run, deck, allow_semantic_failures=True,
                             abaqus_command=shlex.join([sys.executable, str(executable)]),
                             abaqus_modules="", run_prefix="")
    assert report["status"] == "completed", report
    assert "synthetic Abaqus completed" in Path(report["stdout"]).read_text()


@pytest.mark.parametrize("generated_deck", [False, True])
def test_generated_candidate_can_be_tried_after_semantic_failure(tmp_path, monkeypatch, capsys,
                                                                experiment, generated_deck):
    import subprocess
    import sys

    from umat_oti.cli import main
    from umat_oti.transform import source_transform

    source = tmp_path / "umat.f90"
    source.write_text("""subroutine umat(stress,dstran,ddsdde,ntens)
implicit none
integer :: ntens, idx
real(8) :: stress(ntens),dstran(ntens),ddsdde(ntens,ntens)
do idx=1,ntens
stress(idx)=stress(idx)+2.0d0*dstran(idx)
end do
ddsdde=0.0d0
end subroutine umat
""")
    deck = tmp_path / "model.inp"
    deck.write_text("*Heading\nSynthetic trial\n")
    original_checks = source_transform._semantic_checks
    original_execute = subprocess.run

    def fail_check(**kwargs):
        checks, warnings = original_checks(**kwargs)
        checks["stress_path_consumes_the_seed"] = False
        warnings.append("Semantic check failed: stress_path_consumes_the_seed.")
        return checks, warnings

    def execute(command, *, cwd=None, **kwargs):
        import shlex

        if command[0] == sys.executable:
            return original_execute(command, cwd=cwd, **kwargs)
        invocation = shlex.split(command[-1].split("exec ", 1)[1])
        job = next(arg.split("=", 1)[1] for arg in invocation if arg.startswith("job="))
        combined = Path(next(arg.split("=", 1)[1] for arg in invocation if arg.startswith("user=")))
        assert "MODULE" in combined.read_text().upper()
        (cwd / f"{job}.dat").write_text("THE ANALYSIS HAS BEEN COMPLETED\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(source_transform, "_semantic_checks", fail_check)
    monkeypatch.setattr("umat_oti.services.abaqus_trial.subprocess.run", execute)
    output = tmp_path / "out"
    deck_options = (["--abaqus", "--abaqus-experiment", str(experiment)] if generated_deck
                    else ["--abaqus-input", str(deck)])
    code = main(["jacobian", str(source), "--ntens", "6", "--out", str(output),
                 *deck_options, "--abaqus-allow-semantic-failures",
                 "--abaqus-run-prefix", "", "--abaqus-modules", ""])
    result = json.loads(capsys.readouterr().out)
    assert code == 1
    assert result["transform_success"] is False
    assert result["abaqus_trial"]["status"] == "completed"
    assert result["abaqus_trial"]["verified"] is False
    assert json.loads((output / "transform_report.json").read_text())["success"] is False
    if generated_deck:
        assert Path(result["abaqus_trial"]["input"]) == output / "abaqus_trial.inp"
        assert (output / "abaqus_experiment.json").is_file()