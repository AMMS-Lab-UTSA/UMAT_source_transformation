"""A local-Jacobian request either delivers its value to the variable it replaces, or is refused.

A ``constitutive_jacobians`` request that names ``replace_variable`` switches
off the hand-coded lines it lists and writes the extracted Jacobian into the
replaced variable's shadow, which the Newton update then reads. When that
shadow is not declared, or the extraction is not emitted, the update reads a
variable nothing assigns and the file still compiles. These tests transform the
bundled m5_cpflow UMAT (no compiler needed) and check that the replaced variable
is promoted without being listed, and that every request the transform cannot
honour is refused with the replaced variable named.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from umat_oti.services.transformation import run_transformation

REPO_ROOT = Path(__file__).resolve().parents[1]
M5_UMAT = REPO_ROOT / "parameter_sensitivity" / "models" / "m5_cpflow" / "umat.for"
#: A hand-coded Jacobian that depends on nothing seeded, so only the request
#: can make it differentiated.
WRONG_SOURCE = M5_UMAT.read_text(encoding="utf-8").replace("DF=ONE-DTIME*DGDOT", "DF=ONE")


def _line_of(lines: list[str], statement: str) -> int:
    hits = [number for number, line in enumerate(lines, start=1)
            if line.strip().replace(" ", "").upper() == statement]
    assert len(hits) == 1, (statement, hits)
    return hits[0]


def _transform(tmp_path: Path, **request_changes) -> tuple[dict, int]:
    source = tmp_path / "m5.for"
    source.write_text(WRONG_SOURCE, encoding="utf-8")
    lines = WRONG_SOURCE.splitlines()
    request = {
        "id": "newton_slope",
        "seed": "DEQPL",
        "output": "F",
        "loop": {"top": _line_of(lines, "DOKNEWT=1,60")},
        "extract_after": _line_of(lines, "F=DEQPL-DTIME*GDOT"),
        "replace_variable": "DF",
        "replace_lines": [_line_of(lines, "DF=ONE")],
        **request_changes,
    }
    contract = {
        "name": "m5_local_jacobian",
        "source": source.name,
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "promote": ["STRESS"],
        "replace": [],
        "ntens": 6,
        "order": 1,
        "constitutive_jacobians": [request],
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return run_transformation(path, tmp_path / "oti")


def _refused(summary: dict, code: int) -> str:
    assert code == 1, summary
    assert summary["transform_success"] is False, summary
    assert not (Path(summary["out_dir"]) / "m5_oti.for").exists()
    return "\n".join(summary["blockers"])


def test_the_replaced_variable_is_promoted_without_being_listed(tmp_path):
    summary, code = _transform(tmp_path)
    assert code == 0 and summary["transform_success"], summary
    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert "DF" in report["promoted_variables"]
    text = Path(summary["transformed_source"]).read_text(encoding="utf-8")
    assert re.search(r"TYPE\(ONUMM7N1\)\s*::\s*DF_OTI\s*$", text, re.MULTILINE)
    assert "DF_OTI = GETIM(F_OTI, 7)" in text
    assert "DEQPL_OTI=DEQPL_OTI-F_OTI/DF_OTI" in text


def test_a_request_with_more_than_one_seed_direction_is_refused_by_name(tmp_path):
    # Only a single-direction request has its Jacobian written into the
    # replaced variable; with two, DF's line would be switched off and nothing
    # would assign it.
    blockers = _refused(*_transform(tmp_path, seed_directions=2))
    assert "'newton_slope' replaces DF" in blockers
    assert "2 seed direction(s)" in blockers


def test_a_request_with_its_extraction_line_outside_the_source_is_refused_by_name(tmp_path):
    blockers = _refused(*_transform(tmp_path, extract_after=len(WRONG_SOURCE.splitlines()) + 5))
    assert "'newton_slope' replaces DF" in blockers
    assert "no extracted value would be written into it" in blockers


def test_a_replaced_variable_the_routine_does_not_have_is_refused_by_name(tmp_path):
    blockers = _refused(*_transform(tmp_path, replace_variable="DFDQ"))
    assert "'newton_slope' replaces DFDQ" in blockers
    assert "DFDQ does not occur in UMAT" in blockers


def test_a_replaced_variable_that_cannot_be_promoted_is_refused_by_name(tmp_path):
    # EXP is an intrinsic the source calls; an intrinsic's name is never given
    # a shadow, so no DF-like variable would receive the value.
    blockers = _refused(*_transform(tmp_path, replace_variable="EXP"))
    assert "'newton_slope' replaces EXP" in blockers
    assert "EXP cannot be promoted" in blockers

