"""A local-Jacobian request is recorded as the contract wrote it.

The transformation service normalizes the expanded configuration, in which a
compact contract's local-Jacobian requests are stored under the transformer's
key, ``extra_jacobian_contracts``, in their expanded shape. Read naively, that
made every ``constitutive_jacobians`` contract look like the legacy alias (and
warn), recorded the request's target as the residual instead of the variable
the derivative is written into, and the manifest counted only the NTENS strain
directions of a build that also carries the local seed. These tests transform
the bundled m5_cpflow UMAT through the service (no compiler needed) and read
the summary and ``derivative_manifest.json``.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

from umat_oti.services.transformation import run_transformation

REPO_ROOT = Path(__file__).resolve().parents[1]
M5_UMAT = REPO_ROOT / "parameter_sensitivity" / "models" / "m5_cpflow" / "umat.for"
NTENS = 6


def _line_of(lines: list[str], statement: str) -> int:
    hits = [number for number, line in enumerate(lines, start=1)
            if line.strip().replace(" ", "").upper() == statement]
    assert len(hits) == 1, (statement, hits)
    return hits[0]


def _transform(tmp_path: Path, key: str) -> tuple[dict, list[str]]:
    """Transform m5 with its Newton slope requested under ``key``; return the
    summary and the messages of the DeprecationWarnings raised."""
    text = M5_UMAT.read_text(encoding="utf-8")
    (tmp_path / "m5.for").write_text(text, encoding="utf-8")
    lines = text.splitlines()
    contract = {
        "name": "m5_local_jacobian",
        "source": "m5.for",
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "promote": ["STRESS"],
        "replace": [],
        "ntens": NTENS,
        "order": 1,
        key: [{
            "id": "newton_slope",
            "seed": "DEQPL",
            "output": "F",
            "loop": {"top": _line_of(lines, "DOKNEWT=1,60")},
            "extract_after": _line_of(lines, "F=DEQPL-DTIME*GDOT"),
            "replace_variable": "DF",
            "replace_lines": [_line_of(lines, "DF=ONE-DTIME*DGDOT")],
        }],
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        summary, code = run_transformation(path, tmp_path / "oti")
    assert code == 0 and summary["transform_success"], summary
    return summary, [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]


def _local_request(records: list[dict]) -> dict:
    [request] = [r for r in records if r["kind"] == "local_jacobian"]
    return request


def test_the_current_key_does_not_warn_and_is_recorded_as_written(tmp_path):
    summary, deprecations = _transform(tmp_path, "constitutive_jacobians")
    assert not [m for m in deprecations if "legacy alias" in m], deprecations
    assert _local_request(summary["derivative_requests"])["source_contract"] == "constitutive_jacobians"


def test_the_legacy_key_still_warns_and_is_recorded_as_written(tmp_path):
    summary, deprecations = _transform(tmp_path, "extra_jacobian_contracts")
    assert [m for m in deprecations if "'extra_jacobian_contracts' is a legacy alias" in m]
    assert _local_request(summary["derivative_requests"])["source_contract"] == "extra_jacobian_contracts"


def test_the_target_is_the_variable_the_derivative_is_written_into(tmp_path):
    """Target is where the derivative lands, response is what is differentiated:
    DDSDDE and STRESS for the tangent, DF and F for the Newton slope."""
    summary, _ = _transform(tmp_path, "constitutive_jacobians")
    manifest = json.loads(Path(summary["manifest"]).read_text(encoding="utf-8"))
    for records in (summary["derivative_requests"], manifest["derivatives"]):
        request = _local_request(records)
        assert (request["target"], request["seed"], request["response"]) == ("DF", ["DEQPL"], "F")
        tangent = next(r for r in records if r["kind"] == "material_tangent")
        assert (tangent["target"], tangent["response"]) == ("DDSDDE", "STRESS")


def test_the_manifest_counts_the_directions_the_build_used(tmp_path):
    summary, _ = _transform(tmp_path, "constitutive_jacobians")
    manifest = json.loads(Path(summary["manifest"]).read_text(encoding="utf-8"))
    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    # Six strain directions and the local seed, as the module was built.
    assert report["oti_module_name"] == f"otim{NTENS + 1}n1"
    assert (Path(summary["out_dir"]) / f"otim{NTENS + 1}n1.f90").is_file()
    assert manifest["direction_order"]["direction_count"] == NTENS + 1
