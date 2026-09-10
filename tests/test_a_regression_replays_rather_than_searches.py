"""A regression that searches again is not a regression.

The amplitude was chosen by running the ORIGINAL until the material did
something. The segments were built around it, the hold was added because a
rate probe found time dependence, the step ladder and the tolerances came with
them. All of that was decided ONCE, when the material first verified.

Replay it and a later run's difference is a difference in the CODE. Search
again and the two runs measured different experiments, so a difference between
them says nothing about the commit in between -- which is the only thing a
regression exists to say.

The frozen experiment is used only while the source's bytes are the ones it
was chosen for. A source that has changed is a different file, and an
experiment chosen for the old text describes nothing about the new.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from umat_oti.abaqus.manifest import (VerificationManifest,  # noqa: E402
                                      hold, reverse, simple_shear, uniaxial)
from verify_store_in_abaqus import frozen_manifests, thaw  # noqa: E402


def a_manifest() -> VerificationManifest:
    pull = uniaxial(0.0125, 10)
    return VerificationManifest(
        name="STEEL", source=Path("owner__repo/umat.for"),
        element_type="CPE4", kinematics="finite",
        props=(210000.0, 0.3, 250.0), nprops=3, nstatv=2,
        material_provenance="job.inp *MATERIAL STEEL: 3 constants",
        loading=(pull, simple_shear(0.0125, 10), reverse(pull),
                 hold(pull, period=10.0, increments=5)),
        fd_steps=(1e-3, 1e-4, 1e-5), primal_tolerance=1e-10)


def freeze(tmp_path: Path, manifest, *, digest="abc123", states=None) -> Path:
    folder = tmp_path / "owner-repo--umat--deadbeef"
    folder.mkdir(parents=True)
    (folder / "contract.json").write_text(json.dumps({
        "source_id": "owner__repo/umat.for",
        "source_sha256": digest,
        "frozen_manifest": manifest.as_dict(),
        "frozen_states": states or [{"increment": 5, "record_index": 4}],
    }), encoding="utf-8")
    return tmp_path


def test_a_frozen_manifest_survives_the_round_trip(tmp_path: Path):
    original = a_manifest()
    collection = freeze(tmp_path, original)
    kept = frozen_manifests(collection)["owner__repo/umat.for"]
    back = thaw(kept["manifest"])
    assert back.element_type == original.element_type
    assert back.ntens == original.ntens
    assert back.props == original.props
    assert back.fd_steps == original.fd_steps
    assert back.primal_tolerance == original.primal_tolerance
    assert [s.name for s in back.loading] == [s.name for s in original.loading]
    assert back.loading[0].strain == original.loading[0].strain, (
        "the amplitude the search chose is the amplitude replayed")


def test_the_hold_a_rate_probe_added_is_frozen_with_the_rest(tmp_path: Path):
    """It is the only part of the path that exercises a time-dependent
    branch, so a replay without it tests something else."""
    kept = frozen_manifests(freeze(tmp_path, a_manifest()))
    back = thaw(kept["owner__repo/umat.for"]["manifest"])
    held = [segment for segment in back.loading if segment.name.endswith("_hold")]
    assert held and held[0].period == 10.0
    assert held[0].strain == back.loading[0].strain


def test_the_states_the_tangent_was_measured_at_are_frozen(tmp_path: Path):
    kept = frozen_manifests(freeze(tmp_path, a_manifest()))
    assert kept["owner__repo/umat.for"]["states"] == [
        {"increment": 5, "record_index": 4}]


def test_a_collection_with_no_frozen_manifest_offers_nothing(tmp_path: Path):
    folder = tmp_path / "owner-repo--umat--deadbeef"
    folder.mkdir(parents=True)
    (folder / "contract.json").write_text(json.dumps(
        {"source_id": "owner__repo/umat.for"}), encoding="utf-8")
    assert frozen_manifests(tmp_path) == {}


def test_a_missing_collection_is_not_an_error(tmp_path: Path):
    assert frozen_manifests(tmp_path / "nothing") == {}
    assert frozen_manifests(None) == {}


def test_the_digest_is_carried_so_a_changed_source_can_be_noticed(tmp_path: Path):
    kept = frozen_manifests(freeze(tmp_path, a_manifest(), digest="abc123"))
    assert kept["owner__repo/umat.for"]["source_sha256"] == "abc123"


def test_the_regression_command_asks_for_no_discovery():
    """The two halves of the same rule: replay the frozen experiment, and do
    not go looking for a new one."""
    from umat_oti.app.corpus_view import run_command

    command = run_command("regression", Path("r"), Path("w"))
    assert "--no-discovery" in command
    assert "--mode" in command and command[command.index("--mode") + 1] == "regression"


# ---------------------------------------------------------------------------
# and a verdict settled under a rule that has since changed is not settled
# ---------------------------------------------------------------------------
def test_a_resumed_run_skips_what_is_settled():
    from verify_store_in_abaqus import should_skip

    assert should_skip("k", {"k": "verified"}, resume=True)
    assert should_skip("k", {"k": "not_a_umat"}, resume=True)
    assert not should_skip("k", {"k": "harness_error"}, resume=True), (
        "a crash is a statement about the run, not about the model")
    assert not should_skip("k", {"k": "verified"}, resume=False)


def test_a_named_stage_is_done_again_even_when_it_was_settled():
    """The use for it is a fix to the harness: an entry recorded under a
    coverage rule that has since been corrected has a settled outcome that is
    settled about the old rule."""
    from verify_store_in_abaqus import should_skip

    assert not should_skip("k", {"k": "tangent_not_verified"}, resume=True,
                           retry=("tangent_not_verified",))
    assert should_skip("k", {"k": "verified"}, resume=True,
                       retry=("tangent_not_verified",))


def test_external_verdicts_are_not_in_the_internal_retry_set():
    """Re-running them changes nothing while the file stays as it is, and
    including them would spend Abaqus time on answers nobody disputes."""
    from umat_oti.abaqus.terminal_states import EXTERNAL, FROM_STAGE, INTERNAL

    internal_stages = {stage for stage, state in FROM_STAGE.items()
                       if state in set(INTERNAL)}
    external_stages = {stage for stage, state in FROM_STAGE.items()
                       if state in set(EXTERNAL)}
    assert not internal_stages & external_stages
    assert "tangent_not_verified" in internal_stages
    assert "primal_disagreed" in internal_stages
    assert "not_a_umat" not in internal_stages
    assert "needs_material_data" not in internal_stages
    assert "verified" not in internal_stages
