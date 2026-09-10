"""The interface and the pipeline must not have two opinions.

A screenshot stops being evidence the moment the panel showing it decides
anything the batch did not. So the interface reads this service, the service
reads the artefacts the batch wrote, and nothing between them computes a
verdict, a tolerance or a count of its own.

These tests pin the shape, because a front end pinned to a schema can refuse to
render something it does not understand -- and pin the two rules that make the
shape worth having: every question a reader is entitled to ask is answerable
from one record, and a terminal state names whose move it is.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.terminal_states import (EXTERNAL,  # noqa: E402
                                             FULLY_VERIFIED, INTERNAL,
                                             from_stage, kind_of)
from umat_oti.app.corpus_view import (MODES, SCHEMA,  # noqa: E402
                                      componentwise_errors, deck_text,
                                      entry_view, histories, job_log,
                                      load_run, progress, run_command)

VERIFIED_ROW = {
    "key": "aaaa1111", "source": "owner__repo/umat.for", "repository": "owner/repo",
    "stage": "verified", "reason": "agreed at all 3 states",
    "element_type": "CPE4", "ntens": 4, "kinematics": "finite",
    "props_count": 3, "nstatv": 2, "unsymmetric": False,
    "material_block": "STEEL", "deck": "owner__repo/decks/job.inp",
    "material_provenance": "job.inp *MATERIAL STEEL: 3 constants",
    "formulation": {"element": "CPE4", "family": "plane strain",
                    "agreement": "the source and the deck agree"},
    "discovery": {"outcome": "activated", "chosen_amplitude": 0.004},
    "original": {"completed": True, "increments": 30},
    "transformed": {"completed": True, "increments": 30},
    "primal": {"agrees": True, "worst_stress_relative": 0.0, "increments": 30},
    "tangent": {"verified": True, "states": [
        {"increment": 5, "verified": True,
         "comparison": {"best_relative": 1e-12,
                        "sweep": [{"step": 1e-3, "relative": 1e-12,
                                   "absolute": 1.0, "frobenius": 2.0},
                                  {"step": 1e-4, "relative": 3e-12,
                                   "absolute": 2.0, "frobenius": 4.0}]}}]},
    "seconds": 42.0,
}

NO_MATERIAL_ROW = {
    "key": "bbbb2222", "source": "owner__repo/other.for", "repository": "owner/repo",
    "stage": "needs_material_data",
    "reason": "no deck is paired with this source",
}


def write_run(tmp_path: Path, rows) -> Path:
    results = tmp_path / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "store_verification.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return results


def test_the_shape_is_declared_and_stable(tmp_path: Path):
    view = load_run(write_run(tmp_path, [VERIFIED_ROW]))
    assert view.schema == SCHEMA
    record = view.as_dict()
    assert set(record) >= {"schema", "entries", "by_terminal_state", "by_kind",
                           "attempted", "finished"}
    entry = record["entries"][0]
    assert set(entry) >= {"source_id", "terminal_state", "kind", "manifest",
                          "formulation", "discovery", "jobs", "primal",
                          "tangent", "requirements", "artifacts"}


def test_a_terminal_state_says_whose_move_it_is(tmp_path: Path):
    view = load_run(write_run(tmp_path, [VERIFIED_ROW, NO_MATERIAL_ROW]))
    states = {e.source_id: (e.terminal_state, e.kind) for e in view.entries}
    assert states["owner__repo/umat.for"] == (FULLY_VERIFIED, "verified")
    assert states["owner__repo/other.for"] == ("missing_material_data", "external")
    assert view.by_kind == {"verified": 1, "external": 1, "internal": 0}


def test_every_internal_state_is_named_as_ours():
    for stage in ("primal_disagreed", "tangent_not_verified",
                  "original_job_failed", "derivative_truncated",
                  "support_build_failed", "manifest_refused"):
        verdict = from_stage(stage)
        assert verdict.kind == "internal", stage
        assert not verdict.finished, stage


def test_every_external_state_is_named_as_finished():
    for state in EXTERNAL:
        assert kind_of(state) == "external"
    for stage in ("not_a_umat", "needs_material_data",
                  "incomplete_or_corrupt_source",
                  "external_dependency_unavailable"):
        assert from_stage(stage).finished, stage


def test_the_internal_and_external_vocabularies_do_not_overlap():
    assert not set(EXTERNAL) & set(INTERNAL)
    assert FULLY_VERIFIED not in set(EXTERNAL) | set(INTERNAL)


def test_a_missing_requirement_says_what_is_missing(tmp_path: Path):
    view = load_run(write_run(tmp_path, [NO_MATERIAL_ROW]))
    requirements = {r.name: r for r in view.entries[0].requirements}
    assert not requirements["published material constants"].satisfied
    assert "no deck" in requirements["published material constants"].detail


def test_progress_can_be_read_while_a_run_is_still_going(tmp_path: Path):
    """No summary file yet, and the record already answers how far it got."""
    results = write_run(tmp_path, [VERIFIED_ROW])
    found = progress(results)
    assert found["attempted"] == 1
    assert found["finished"] is False
    assert found["latest"] == ["owner__repo/umat.for"]


def test_the_command_a_button_would_run_can_be_shown_first(tmp_path: Path):
    discovery = run_command("discovery", tmp_path / "r", tmp_path / "w")
    regression = run_command("regression", tmp_path / "r", tmp_path / "w",
                             baseline=tmp_path / "baseline.json")
    assert "verify_store_in_abaqus.py" in " ".join(discovery)
    assert "--mode" not in discovery, "discovery is the default mode"
    assert "--mode" in regression and "regression" in regression
    assert "--no-discovery" in regression, (
        "a regression re-runs frozen decks; it does not search again")
    assert "--baseline" in regression


def test_an_unknown_mode_is_refused_rather_than_defaulted(tmp_path: Path):
    import pytest
    with pytest.raises(ValueError):
        run_command("whatever", tmp_path, tmp_path)
    assert set(MODES) == {"discovery", "regression"}


def test_the_histories_come_back_as_series_a_plot_can_use(tmp_path: Path):
    work = tmp_path / "work" / "aaaa1111"
    (work / "original").mkdir(parents=True)
    (work / "original" / "original_history.json").write_text(json.dumps([
        {"increment": 1, "time": 0.0, "STRESS": [1.0] * 6, "STATEV": [0.0],
         "entry": {"STRAN": [0.0] * 6, "DSTRAN": [0.001] * 6}},
        {"increment": 2, "time": 0.1, "STRESS": [2.0] * 6, "STATEV": [0.1],
         "entry": {"STRAN": [0.001] * 6, "DSTRAN": [0.001] * 6}}]))
    series = histories(tmp_path / "work", "aaaa1111")
    assert set(series) == {"original"}
    assert series["original"]["increment"] == [1, 2]
    assert series["original"]["strain"][1] == [0.002] * 6
    assert series["original"]["stress"][0] == [1.0] * 6


def test_an_abaqus_failure_is_readable_from_its_own_files(tmp_path: Path):
    work = tmp_path / "work" / "aaaa1111" / "original"
    work.mkdir(parents=True)
    (work / "original.msg").write_text("***ERROR: too many attempts\n")
    (work / "original.sta").write_text("THE ANALYSIS HAS NOT COMPLETED\n")
    found = job_log(tmp_path / "work", "aaaa1111", "original")
    assert "too many attempts" in found["files"][".msg"]
    assert "NOT COMPLETED" in found["files"][".sta"]
    assert set(found["files"]) == {".msg", ".sta"}, (
        "which file a diagnostic came from is part of reading it")


def test_the_generated_deck_can_be_located_and_read(tmp_path: Path):
    work = tmp_path / "work" / "aaaa1111" / "original"
    work.mkdir(parents=True)
    (work / "original.inp").write_text("*HEADING\nsingle-element deck\n")
    assert "single-element deck" in deck_text(tmp_path / "work", "aaaa1111")
    view = entry_view(VERIFIED_ROW, tmp_path / "work")
    assert view.artifacts["original"]["deck"].endswith("original.inp")


def test_the_step_sweep_is_a_table_a_reader_can_sort():
    view = entry_view(VERIFIED_ROW)
    rows = componentwise_errors(view)
    assert [row["step"] for row in rows] == [1e-3, 1e-4]
    assert rows[0]["relative"] == 1e-12


def test_nothing_here_reads_a_corpus_source():
    """The corpus is not redistributable. The interface shows paths, digests
    and provenance; the text stays outside the tree."""
    module = (Path(__file__).resolve().parents[1]
              / "src/umat_oti/app/corpus_view.py").read_text()
    assert "cache_root" not in module
    assert "discovery_cache" not in module


# ---------------------------------------------------------------------------
# and the page that renders it draws only what the service returned
# ---------------------------------------------------------------------------
class Recorder:
    """A stand-in for Streamlit that records what would be drawn.

    Enough of the API for the corpus page, and no browser. What it is for is
    the rule the page exists under: it may render the evidence and may not
    decide anything, so a test can read back everything the page put on screen
    and check it against the record the batch wrote.
    """

    def __init__(self, choices=None):
        self.written: list = []
        self.choices = choices or {}
        self.columns_made = 0

    def _record(self, kind, *values):
        self.written.append((kind, values))

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self._record(name, *args)
            return None
        return call

    def columns(self, count):
        self.columns_made = count
        return [Recorder() for _ in range(count)]

    def selectbox(self, label, options, **kwargs):
        self._record("selectbox", label, list(options))
        return self.choices.get(label, list(options)[0] if options else None)

    def text_input(self, label, value="", **kwargs):
        self._record("text_input", label)
        return self.choices.get(label, value)

    def button(self, label, **kwargs):
        self._record("button", label)
        return False

    def expander(self, label, **kwargs):
        self._record("expander", label)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def texts(self) -> str:
        return " ".join(str(value) for _kind, values in self.written
                        for value in values)


def test_the_page_shows_the_verdict_the_batch_recorded(tmp_path: Path):
    from umat_oti.app.corpus_tab import render

    results = write_run(tmp_path, [VERIFIED_ROW, NO_MATERIAL_ROW])
    work = tmp_path / "work"
    (work / "aaaa1111" / "original").mkdir(parents=True)
    (work / "aaaa1111" / "original" / "original.inp").write_text("*HEADING\nprobe\n")
    recorder = Recorder()
    render(results, work, st=recorder)
    shown = recorder.texts()
    assert "owner__repo/umat.for" in shown
    assert "fully_verified" in shown
    assert "missing_material_data" in shown
    # the command a button would run, shown before the button
    assert "verify_store_in_abaqus.py" in shown
    # and the two modes are offered by name, each with what it does
    assert "discovery" in shown and "regression" in shown


def test_the_page_never_starts_a_run_the_user_did_not_press(tmp_path: Path):
    from umat_oti.app.corpus_tab import render

    results = write_run(tmp_path, [VERIFIED_ROW])
    recorder = Recorder()
    render(results, tmp_path / "work", st=recorder)
    started = [kind for kind, _ in recorder.written if kind == "button"]
    assert started, "the page offers a button"
    assert not (results / "discovery.log").exists()


def test_the_page_shows_a_missing_requirement_rather_than_a_blank(tmp_path: Path):
    from umat_oti.app.corpus_tab import render

    results = write_run(tmp_path, [NO_MATERIAL_ROW])
    recorder = Recorder(choices={"entry": "owner__repo/other.for"})
    render(results, tmp_path / "work", st=recorder)
    shown = recorder.texts()
    assert "published material constants" in shown
    assert "no deck" in shown


def test_every_terminal_state_has_a_gloss_on_the_page():
    from umat_oti.abaqus.terminal_states import ALL
    from umat_oti.app.corpus_tab import GLOSS

    assert set(ALL) <= set(GLOSS), sorted(set(ALL) - set(GLOSS))
