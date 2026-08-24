"""Every front end must reach the same execution path.

Four separate transform entry points is how CLI, batch, UI, corpus and evidence
generation drift into separate readings of the same contract. These tests pin
the convergence: one pure service, reached the same way from everywhere, and an
explicit list of what has not been migrated yet -- so an unfinished front end is
visible rather than merely absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.pipeline.manifest import sha256_file
from umat_oti.services.transformation import TransformationOptions, run_transformation

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "examples" / "code_imp_actual_higher_order.json"

#: Front ends and the symbol each must reach the service through.
DELEGATED_FRONT_ENDS = {
    "src/umat_oti/cli.py": "run_transformation",
    "src/umat_oti/cli_batch.py": "run_transformation",
    "src/umat_oti/app/engine.py": "run_transformation",
    "src/umat_oti/app/streamlit_app.py": "run_transformation",
    "src/umat_oti/reports/run_softwarex_evidence.py": "run_transformation",
    "src/umat_oti/pipeline/stages.py": "run_transformation",
}

#: Not yet migrated. Listed rather than omitted: an unfinished front end that
#: nobody can see is indistinguishable from a finished one.
UNMIGRATED_FRONT_ENDS = {
    "src/umat_oti/corpus/cli.py": (
        "calls transform_umat_to_oti_from_config directly. The corpus runner "
        "operates on discovered sources that have no contract yet, so routing it "
        "through the service needs contract synthesis first."
    ),
}


def test_every_migrated_front_end_calls_the_service():
    missing = []
    for path, symbol in DELEGATED_FRONT_ENDS.items():
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if symbol not in text:
            missing.append(path)
    assert not missing, f"front ends not reaching the service: {missing}"


def test_no_front_end_still_uses_the_deprecated_wrapper():
    offenders = []
    for path in DELEGATED_FRONT_ENDS:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if "run_config_transform" in text:
            offenders.append(path)
    assert not offenders, (
        f"these still call the deprecated CLI wrapper rather than the service: {offenders}")


def test_unmigrated_front_ends_are_declared_and_still_unmigrated():
    """If one gets migrated, this test fails and the list must be updated."""
    for path, reason in UNMIGRATED_FRONT_ENDS.items():
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert "transform_umat_to_oti_from_config" in text, (
            f"{path} appears migrated; remove it from UNMIGRATED_FRONT_ENDS "
            f"and add it to DELEGATED_FRONT_ENDS. Recorded reason was: {reason}")


def test_the_core_never_reaches_through_a_cli():
    """Validation and pipeline are core; they must not import a front end."""
    offenders = []
    for package in ("pipeline", "validation", "services"):
        for module in (REPO_ROOT / "src" / "umat_oti" / package).glob("*.py"):
            for line in module.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not (stripped.startswith("from ") or stripped.startswith("import ")):
                    continue
                if "umat_oti.cli" in stripped:
                    offenders.append(f"{package}/{module.name}: {stripped}")
    assert not offenders, "core module imports a CLI: " + "; ".join(offenders)


@pytest.mark.slow
def test_the_wrapper_and_the_service_produce_identical_artifacts(tmp_path):
    """The deprecated wrapper must be a delegation, not a second implementation."""
    from umat_oti import cli_json

    direct, direct_code = run_transformation(
        CONTRACT, tmp_path / "direct", TransformationOptions())
    with pytest.warns(DeprecationWarning):
        wrapped, wrapped_code = cli_json.run_config_transform(CONTRACT, tmp_path / "wrapped")

    assert direct_code == wrapped_code
    assert direct["derivative_requests"] == wrapped["derivative_requests"], (
        "the two paths normalized the same contract differently")
    assert direct["status_category"] == wrapped["status_category"]

    a, b = Path(direct["transformed_source"]), Path(wrapped["transformed_source"])
    assert a.exists() and b.exists()
    assert sha256_file(a) == sha256_file(b), (
        "the same contract produced different transformed source through two paths")


@pytest.mark.slow
def test_the_pipeline_normalizes_identically_to_the_service(tmp_path):
    from umat_oti.pipeline.stages import canonical_engine

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract["_base_dir"] = str(CONTRACT.parent)
    manifest = canonical_engine(REPO_ROOT).run(
        contract=contract, work_dir=tmp_path / "pipe", run_id="equiv",
        options={"config_path": str(CONTRACT)},
        only=["derivative_request_normalization"])
    piped = manifest.stages["derivative_request_normalization"].outputs["requests"]

    summary, _ = run_transformation(CONTRACT, tmp_path / "svc", TransformationOptions())
    assert piped == summary["derivative_requests"], (
        "the pipeline and the service disagree about the same contract")
