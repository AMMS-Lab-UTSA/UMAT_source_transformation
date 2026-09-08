"""The ``umat/`` collection is evidence, and these are its integrity rules.

Every directory here claims a material passed Abaqus verification: both
builds executed, their histories agreed, and the OTI tangent agreed with a
finite difference of the ORIGINAL implementation at several states. These
tests do not re-run Abaqus. They check that what is committed actually
supports that claim and cannot quietly stop supporting it -- that the
registry and the directories agree, that no record is missing the evidence it
cites, that nothing here says "verified" without the numbers behind it, and
that no third-party source has been committed against the redistribution
policy.

The rerun itself is a separate, Abaqus-marked test and a separate command.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

COLLECTION = REPO / "umat"
REGISTRY = COLLECTION / "registry.json"
BASELINE = COLLECTION / "baseline.json"

pytestmark = pytest.mark.skipif(
    not REGISTRY.is_file(),
    reason="nothing has been promoted into umat/ yet")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry():
    return _load(REGISTRY)


@pytest.fixture(scope="module")
def materials(registry):
    return registry["materials"]


def _directories():
    return sorted(p for p in COLLECTION.iterdir()
                  if p.is_dir() and p.name != "materialized")


# ---- the registry and the directories describe the same collection -------
def test_every_registry_entry_has_a_directory(materials):
    present = {p.name for p in _directories()}
    missing = sorted(m["id"] for m in materials if m["id"] not in present)
    assert not missing, f"registry names materials with no directory: {missing}"


def test_every_directory_is_in_the_registry(materials):
    listed = {m["id"] for m in materials}
    stray = sorted(p.name for p in _directories() if p.name not in listed)
    assert not stray, f"directories with no registry entry: {stray}"


def test_the_registry_count_is_the_count(registry, materials):
    assert registry["count"] == len(materials)


def test_material_ids_are_unique(materials):
    ids = [m["id"] for m in materials]
    assert len(ids) == len(set(ids))


def test_source_ids_are_unique(materials):
    """One source, one verification record. Two records for one file would
    let a later run's verdict sit beside an earlier one with nothing saying
    which is current."""
    sources = [m["source_id"] for m in materials]
    assert len(sources) == len(set(sources))


# ---- each record carries what it cites -----------------------------------
@pytest.mark.parametrize("name", ["contract.json", "results.json",
                                  "source.json", "README.md"])
def test_every_material_carries_its_records(name):
    missing = [p.name for p in _directories() if not (p / name).is_file()]
    assert not missing, f"missing {name}: {missing}"


def test_every_material_carries_the_deck_it_was_run_on():
    missing = [p.name for p in _directories()
               if not (p / "verification" / "generated.inp").is_file()]
    assert not missing, f"no generated.inp: {missing}"


def test_every_material_carries_both_probe_histories():
    """Both, or the history comparison cannot be checked by a reader."""
    for folder in _directories():
        for name in ("original_history.json", "converted_history.json"):
            assert (folder / "verification" / name).is_file(), \
                f"{folder.name} is missing verification/{name}"


# ---- the claim is supported by numbers -----------------------------------
def test_every_result_records_the_stage_that_put_it_here():
    for folder in _directories():
        results = _load(folder / "results.json")
        assert results["stage"] == "verified", folder.name


def test_both_abaqus_executions_completed():
    """Both, not one. A converted build that did not run cannot have agreed
    with anything."""
    for folder in _directories():
        results = _load(folder / "results.json")
        for side in ("abaqus_original", "abaqus_converted"):
            execution = results[side] or {}
            assert execution.get("completed") is True, f"{folder.name}: {side}"
            assert execution.get("converged_records"), f"{folder.name}: {side}"


def test_the_two_executions_produced_the_same_number_of_records():
    for folder in _directories():
        results = _load(folder / "results.json")
        a = (results["abaqus_original"] or {}).get("converged_records")
        b = (results["abaqus_converted"] or {}).get("converged_records")
        assert a == b, f"{folder.name}: {a} against {b}"


def test_the_history_comparison_agreed_and_resolved_something():
    """Agreement over nothing is not agreement: a comparison that dismissed
    every component as unresolvable establishes nothing."""
    for folder in _directories():
        history = _load(folder / "results.json")["history_agreement"]
        assert history["agrees"] is True, folder.name
        assert history["resolved_components"] > 0, folder.name


def test_the_tangent_agreed_at_every_state_that_was_checked():
    for folder in _directories():
        tangent = _load(folder / "results.json")["tangent_agreement"]
        assert tangent["states_checked"] >= 1, folder.name
        assert tangent["states_agreeing"] == tangent["states_checked"], folder.name


def test_the_tangent_swept_more_than_one_step_size():
    """One step cannot separate truncation error from cancellation."""
    for folder in _directories():
        tangent = _load(folder / "results.json")["tangent_agreement"]
        assert len(tangent["fd_steps"] or ()) >= 2, folder.name


def test_every_checked_state_reports_a_measured_error():
    """A state recorded as agreeing must carry the number it agreed to. A
    verdict with no measurement behind it is the thing this collection is
    supposed to make impossible."""
    for folder in _directories():
        for state in _load(folder / "results.json")["tangent_agreement"]["per_state"]:
            assert state["verified"] is True, f"{folder.name} inc {state['increment']}"
            best = (state.get("comparison") or {}).get("best_relative")
            assert isinstance(best, (int, float)), \
                f"{folder.name} inc {state['increment']} has no measured error"


def test_the_registry_agrees_with_each_material_s_own_result(materials):
    """The summary a reader sees first must be the summary the evidence
    supports."""
    for entry in materials:
        results = _load(COLLECTION / entry["id"] / "results.json")
        tangent = results["tangent_agreement"]
        assert entry["states_checked"] == tangent["states_checked"], entry["id"]
        assert entry["states_agreeing"] == tangent["states_agreeing"], entry["id"]


# ---- the contract describes a run that could happen ----------------------
def test_every_contract_names_a_supported_element_with_a_matching_shape():
    from umat_oti.abaqus.elements import geometry_for

    for folder in _directories():
        point = _load(folder / "contract.json")["material_point"]
        geometry = geometry_for(point["element_type"])
        assert geometry.ntens == point["ntens"], folder.name


def test_every_contract_states_where_its_material_came_from():
    """A constant with no stated origin reads as established when nothing
    established it."""
    for folder in _directories():
        material = _load(folder / "contract.json")["material"]
        assert material["provenance"], folder.name
        assert material["deck"], folder.name
        assert material["props_count"] is not None, folder.name


def test_every_contract_refuses_to_call_the_probe_the_authors_history():
    for folder in _directories():
        loading = _load(folder / "contract.json")["loading"]
        assert "probe" in loading["kind"].lower(), folder.name
        assert "not" in loading["not_the_authors_history"].lower(), folder.name


def test_every_contract_records_the_transform_that_produced_it():
    """Without it, a result cannot be tied to the code that earned it."""
    for folder in _directories():
        assert _load(folder / "contract.json")["transform_fingerprint"], folder.name


# ---- redistribution --------------------------------------------------------
def test_no_third_party_source_is_committed_here():
    """A public repository without an explicit licence grant is not
    permission to redistribute it. Identity and a digest are committed; the
    bytes are fetched."""
    fortran = {".f", ".for", ".f90", ".f95", ".inc"}
    committed = [p for p in COLLECTION.rglob("*")
                 if p.is_file() and p.suffix.lower() in fortran
                 and "materialized" not in p.parts]
    assert not committed, f"Fortran sources committed under umat/: {committed}"


def test_every_material_records_the_digest_of_what_was_verified():
    """The digest is what lets a later run refuse a file that has changed
    upstream, rather than attaching an old verdict to new bytes."""
    for folder in _directories():
        source = _load(folder / "source.json")
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"] or ""), folder.name


def test_a_source_not_redistributed_says_how_to_get_it():
    for folder in _directories():
        source = _load(folder / "source.json")
        if not source["redistributed_here"]:
            assert "materialize_umat_sources" in source["why"], folder.name


def test_the_materialized_directory_is_ignored():
    ignore = (COLLECTION / ".gitignore").read_text(encoding="utf-8")
    assert "materialized/" in ignore


# ---- the baseline is a gate, not a diary ---------------------------------
def test_the_baseline_requires_exactly_what_was_promoted(materials):
    baseline = _load(BASELINE)
    required = {e["source"] for e in baseline["entries"]}
    assert required == {m["source_id"] for m in materials}


def test_every_baseline_entry_requires_verification():
    for entry in _load(BASELINE)["entries"]:
        assert entry["stage"] == "verified"


def test_the_baseline_says_it_is_not_written_by_a_regression_run():
    """A gate that rewrites its own baseline cannot fail."""
    baseline = _load(BASELINE)
    assert "never by a regression run" in baseline["what_this_is"]


def test_the_baseline_drives_the_regression_command():
    """The required set the strict mode reads is this file, so a material
    that stops verifying fails the command rather than being dropped."""
    from verify_store_in_abaqus import required_entries

    class _Args:
        require = ""
        baseline = BASELINE

    required = required_entries(_Args(), [])
    assert required == {m["source_id"] for m in _load(REGISTRY)["materials"]}


# ---- the collection says what it does not establish ----------------------
def test_the_collection_readme_states_the_limits():
    text = (COLLECTION / "README.md").read_text(encoding="utf-8")
    for claim in ("Compiling is not verification",
                  "reproduction of the author",
                  "meaning** of the material constants is not certified",
                  "Missing Abaqus is not a pass"):
        assert claim in text, claim


def test_every_material_readme_states_what_was_not_established():
    for folder in _directories():
        text = (folder / "README.md").read_text(encoding="utf-8")
        assert "What was NOT established" in text, folder.name
        assert "verification probe" in text, folder.name
