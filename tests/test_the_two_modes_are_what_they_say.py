"""Two modes, and the difference between them is the only thing either is for.

``discovery`` goes looking for the experiment. It does not know what amplitude
makes a material do something, or whether the material is rate dependent, or
which states along the path a difference can be taken at, so it runs the
ORIGINAL until it finds out -- several extra Abaqus jobs per entry -- and then
verifies against what it found.

``regression`` replays. The amplitude was chosen once, the segments were built
around it, the hold was added because a rate probe found time dependence, the
step ladder and the tolerances came with them, and all of that was frozen into
the material's contract when it first verified. Replaying it means a later
run's difference is a difference in the CODE. Searching again means the two
runs measured different experiments, and a difference between them then says
nothing about the commit in between -- which is the only thing a regression
exists to say.

So the tests here are about the seam. That both modes exist and are offered by
name; that each one's command carries the flags its meaning requires and not
the other's; that a regression's exit code is a gate and an inventory's is not;
and that the interface shows the command before it runs it, because a user is
entitled to see what a button will do.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.app.corpus_view import (MODES, RunHandle,  # noqa: E402
                                      run_command, start_run)


def test_there_are_exactly_two_modes_and_each_says_what_it_does():
    """A button with an unexplained name is how a user starts the wrong one."""
    assert set(MODES) == {"discovery", "regression"}
    assert "search" in MODES["discovery"]
    assert "re-run the frozen" in MODES["regression"]
    for mode, description in MODES.items():
        assert len(description) > 60, mode


def test_discovery_searches_for_the_experiment(tmp_path: Path):
    """It must NOT carry --no-discovery: without the search, a material that
    answers a fixed probe elastically is verified on its elastic branch only,
    which is the part every build gets right."""
    command = run_command("discovery", tmp_path / "r", tmp_path / "w")
    assert "--no-discovery" not in command
    assert "--mode" not in command, (
        "the tool's default mode is inventory, which always exits 0 -- a "
        "discovery run is a survey, and reading its exit code as a verdict is "
        "the mistake the mode split exists to prevent")
    assert command[1].endswith("verify_store_in_abaqus.py")
    assert "--work-dir" in command and "--results-dir" in command


def test_regression_replays_and_does_not_search(tmp_path: Path):
    """The two halves of the same rule."""
    command = run_command("regression", tmp_path / "r", tmp_path / "w")
    assert "--mode" in command
    assert command[command.index("--mode") + 1] == "regression"
    assert "--no-discovery" in command


def test_a_regression_can_be_given_the_baseline_it_is_a_regression_against(
        tmp_path: Path):
    """Without one it can only fail on entries that ran and failed, and cannot
    tell that an entry stopped being attempted -- which is exactly the failure
    a regression exists to catch, and it leaves no failing row to notice."""
    baseline = tmp_path / "baseline.json"
    command = run_command("regression", tmp_path / "r", tmp_path / "w",
                          baseline=baseline)
    assert "--baseline" in command
    assert command[command.index("--baseline") + 1] == str(baseline)
    assert "--baseline" not in run_command("discovery", tmp_path / "r",
                                           tmp_path / "w", baseline=baseline), (
        "a discovery run has nothing to be a regression against")


def test_the_flags_that_separate_the_modes_are_the_only_difference(
        tmp_path: Path):
    """Same tool, same store, same work directory. If the two commands
    differed anywhere else, a regression would not be re-running the thing
    discovery ran."""
    discovery = run_command("discovery", tmp_path / "r", tmp_path / "w")
    regression = run_command("regression", tmp_path / "r", tmp_path / "w")
    assert set(discovery) < set(regression)
    assert set(regression) - set(discovery) == {
        "--mode", "regression", "--no-discovery"}


def test_a_filter_is_carried_by_both_so_the_same_subset_can_be_re_run(
        tmp_path: Path):
    for mode in MODES:
        command = run_command(mode, tmp_path / "r", tmp_path / "w",
                              only="BristolComposites", limit=3, jobs=4)
        assert command[command.index("--only") + 1] == "BristolComposites"
        assert command[command.index("--limit") + 1] == "3"
        assert command[command.index("--jobs") + 1] == "4"


def test_an_unknown_mode_is_refused_rather_than_defaulted(tmp_path: Path):
    """Defaulting an unrecognised mode to either one runs the wrong batch and
    reports it under the name of the right one."""
    with pytest.raises(ValueError) as raised:
        run_command("replay", tmp_path, tmp_path)
    assert "discovery" in str(raised.value) and "regression" in str(raised.value)


def test_the_command_can_be_shown_before_the_button_that_runs_it(tmp_path: Path):
    """A user is entitled to see what a button will do, and a test can then
    check the command without running Abaqus."""
    from umat_oti.app.corpus_tab import render

    results = tmp_path / "results"
    results.mkdir()
    (results / "store_verification.jsonl").write_text("", encoding="utf-8")

    drawn: list = []

    class Recorder:
        def __getattr__(self, name):
            def call(*args, **kwargs):
                drawn.extend(str(a) for a in args)
                return None
            return call

        def columns(self, count):
            return [Recorder() for _ in range(count)]

        def selectbox(self, label, options, **kwargs):
            drawn.append(str(list(options)))
            return list(options)[0]

        def text_input(self, label, value="", **kwargs):
            return value

        def button(self, label, **kwargs):
            drawn.append(f"button:{label}")
            return False

    render(results, tmp_path / "work", st=Recorder())
    shown = " ".join(drawn)
    assert "verify_store_in_abaqus.py" in shown
    assert "discovery" in shown and "regression" in shown
    assert any(item.startswith("button:") for item in drawn)
    assert not list(tmp_path.glob("*.log")), "showing is not running"


def test_starting_a_run_hands_back_where_to_watch_it(tmp_path: Path):
    """An Abaqus corpus round is hours; an interface that blocks on one is an
    interface nobody can use to watch it. The handle carries the command, the
    pid and the directories progress is read from."""
    handle = start_run("discovery", tmp_path / "r", tmp_path / "w",
                       only="nothing-matches-this")
    assert isinstance(handle, RunHandle)
    record = handle.as_dict()
    assert record["mode"] == "discovery"
    assert record["command"][1].endswith("verify_store_in_abaqus.py")
    assert (tmp_path / "r").is_dir() and (tmp_path / "w").is_dir()
    if handle.started:                             # the tool is importable here
        assert isinstance(handle.pid, int)
        assert (tmp_path / "r" / "discovery.log").exists()
    else:
        assert handle.reason, "a run that did not start says why"


# ---------------------------------------------------------------------------
# and what the modes mean inside the tool the buttons run
# ---------------------------------------------------------------------------
def test_regression_is_a_gate_and_discoverys_mode_is_not():
    """``inventory`` answers "where does everything stand?", and every stage in
    it -- including a failure -- is an answer. ``regression`` is a claim about
    a commit, so it exits non-zero when a required entry fails, is blocked, or
    stopped being attempted."""
    from verify_store_in_abaqus import exit_verdict

    verified = [{"source": "a.for", "stage": "verified"}]
    failed = [{"source": "a.for", "stage": "tangent_not_verified"}]
    assert exit_verdict("inventory", failed, set()).code == 0
    assert exit_verdict("regression", failed, {"a.for"}).code != 0
    assert exit_verdict("regression", verified, {"a.for"}).code == 0


def test_an_entry_that_stopped_being_attempted_fails_the_regression():
    """It leaves no failing row to notice, which is why the required set is
    what a regression is judged against rather than the rows it produced."""
    from verify_store_in_abaqus import exit_verdict

    outcome = exit_verdict("regression", [{"source": "a.for", "stage": "verified"}],
                           {"a.for", "b.for"})
    assert outcome.code != 0
    assert any("b.for" in line and "not attempted" in line
               for line in outcome.lines)


def test_a_regression_that_ran_nothing_is_a_failure_not_a_clean_sheet():
    from verify_store_in_abaqus import exit_verdict

    outcome = exit_verdict("regression", [], {"a.for"})
    assert outcome.code != 0
    assert any("proves nothing" in line for line in outcome.lines)


def test_the_frozen_experiment_a_regression_replays_is_the_whole_experiment(
        tmp_path: Path):
    """Amplitude, segments, the hold a rate probe added, the step ladder and
    the tolerances -- all of it, or the replay is of something else.

    The hold matters most: it is the only part of the path that exercises a
    time-dependent branch, and no amplitude would have found the need for it,
    because raising the strain does not make time pass.
    """
    from umat_oti.abaqus.manifest import (VerificationManifest, hold, reverse,
                                          simple_shear, uniaxial)
    from verify_store_in_abaqus import frozen_manifests, thaw

    pull = uniaxial(0.0125, 10)
    manifest = VerificationManifest(
        name="STEEL", source=Path("owner__repo/umat.for"), element_type="CPE4",
        kinematics="finite", props=(210000.0, 0.3, 250.0), nprops=3, nstatv=2,
        material_provenance="job.inp *MATERIAL STEEL: 3 constants",
        loading=(pull, simple_shear(0.0125, 10), reverse(pull),
                 hold(pull, period=10.0, increments=5)),
        fd_steps=(1e-3, 1e-4, 1e-5), primal_tolerance=1e-10)
    folder = tmp_path / "owner-repo--umat--deadbeef"
    folder.mkdir(parents=True)
    (folder / "contract.json").write_text(json.dumps({
        "source_id": "owner__repo/umat.for", "source_sha256": "abc123",
        "frozen_manifest": manifest.as_dict(),
        "frozen_states": [{"increment": 5, "record_index": 4}]}),
        encoding="utf-8")

    kept = frozen_manifests(tmp_path)["owner__repo/umat.for"]
    back = thaw(kept["manifest"])
    assert back.loading[0].strain == pull.strain
    assert [s.name for s in back.loading] == [s.name for s in manifest.loading]
    held = [s for s in back.loading if s.name.endswith("_hold")]
    assert held and held[0].period == 10.0
    assert back.fd_steps == manifest.fd_steps
    assert back.primal_tolerance == 1e-10
    assert kept["states"] == [{"increment": 5, "record_index": 4}]
    assert kept["source_sha256"] == "abc123", (
        "an experiment chosen for the old bytes describes nothing about new "
        "ones, so the digest travels with it")


def test_a_frozen_fixture_is_replayed_rather_than_re_derived():
    """The regression fixtures this repository freezes carry the window they
    were taken from and the evidence that it was a complete finite run, so a
    replay compares against the same numbers rather than against whatever a
    fresh search would now choose.

    Measured on the bundled J2 control: the frozen window starts at record 3,
    which is the first record the pipeline verified a tangent at, and carries
    6 increments.
    """
    fixtures = sorted((REPO / "tests" / "fixtures" / "verified").glob("*.json"))
    assert fixtures, "the control is frozen in the tree, not re-derived"
    for path in fixtures:
        payload = json.loads(path.read_text(encoding="utf-8"))
        frozen = payload["finite_history"]
        assert frozen["complete_finite_verification_run"] is True, path.name
        assert isinstance(frozen["window_starts_at_record"], int), path.name
        assert frozen["increments_carried"] == len(payload["original"])
        assert payload["deck"], "the experiment that produced these numbers"
