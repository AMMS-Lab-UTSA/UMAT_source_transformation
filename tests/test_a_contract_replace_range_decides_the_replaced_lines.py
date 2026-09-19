"""A contract's ``replace`` range decides which old-tangent lines are replaced.

The range names the hand-coded tangent block the OTI extraction takes over.
The detected tangent region it overlaps is replaced, and a DDSDDE-writing block
after the stress update that it does NOT name is left out of the replacement.
Leaving such a block live would return the old tangent over the new one, so the
transform then refuses, naming each uncovered assignment, rather than choosing
for the contract.

The published viscoplastic damage UMAT ``UMAT_VPDCL.for`` has two tangent
blocks after its stress update: ``CALL KCLEAR(DDSDDE,...)`` at line 244 and
the hand-coded consistent tangent at lines 248-270. Its elastic stiffness at
lines 117-125 is also written into DDSDDE, before the stress update, and is
read by it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from umat_oti.services.transformation import run_transformation

REPO_ROOT = Path(__file__).resolve().parents[1]
VPDCL = REPO_ROOT / "UMATs" / "UMATs" / "ICP" / "UMAT_VPDCL.for"
ELASTIC_CONTRACT = REPO_ROOT / "examples" / "elastic_minimal.json"

#: The hand-coded consistent tangent's DDSDDE assignments, lines 259-268.
HAND_CODED_TANGENT = (
    "DDSDDE(K2, K1)=(ONE-D)*EFFLAM",
    "DDSDDE(K1, K1)=(ONE-D)*(EFFG2+EFFLAM)",
    "DDSDDE(K1, K1)=(ONE-D)*EFFG",
    "DDSDDE(K2, K1)=DDSDDE(K2, K1)+(ONE-D)*EFFHRD",
)


def _transform(tmp_path: Path, name: str, replace) -> tuple[dict, int]:
    contract = {
        "name": name, "source": str(VPDCL),
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "promote": ["STRESS"], "ntens": 4, "order": 1, "replace": replace,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return run_transformation(path, tmp_path / name)


def _skipped(text: str) -> list[str]:
    return [line.split("OTIS-SKIP:", 1)[1].strip()
            for line in text.splitlines() if "OTIS-SKIP:" in line]


def _replaced(summary: dict) -> list[tuple[int, int]]:
    report = json.loads(Path(summary["report_path"]).read_text())
    return [(region["start_line"], region["end_line"])
            for region in report["old_tangent_regions_replaced"]]


def test_the_named_block_is_the_one_replaced(tmp_path):
    summary, code = _transform(tmp_path, "named", ["248-270"])
    assert code == 0 and summary["transform_success"], summary

    assert _replaced(summary) == [(248, 270)]
    text = Path(summary["transformed_source"]).read_text()
    skipped = _skipped(text)
    for assignment in HAND_CODED_TANGENT:
        assert any(line.startswith(assignment) for line in skipped), assignment
    # Lines outside the range that the stress update reads stay live.
    live = [line.strip() for line in text.splitlines()
            if "DDSDDE(K" in line and "OTIS-SKIP" not in line]
    assert any(line.startswith("DDSDDE(K2, K1)=ELAM") for line in live), live
    assert not any(line.startswith("DDSDDE(K2, K1)=ELAM") for line in skipped)


def test_a_range_that_names_another_block_leaves_the_tangent_unreplaced_and_refuses(tmp_path):
    """Line 244, which only clears DDSDDE, is a detected tangent block too.
    Named alone, it is the only one replaced: the block at 248-270 is not taken
    over behind the contract's back, and the transform says so."""
    summary, code = _transform(tmp_path, "elsewhere", ["244-244"])

    assert code == 1
    assert summary["transform_success"] is False
    assert summary["status_category"] == "transform_blocked"
    uncovered = [str(blocker) for blocker in summary["blockers"]]
    assert len(uncovered) == len(HAND_CODED_TANGENT), uncovered
    for assignment in HAND_CODED_TANGENT:
        assert any("not covered by an old tangent replacement region" in blocker
                   and assignment in blocker for blocker in uncovered), assignment


def test_the_file_qualified_form_is_the_same_range(tmp_path):
    """``{"file": ..., "lines": [...]}`` names the same lines as the bare form."""
    bare, bare_code = _transform(tmp_path, "bare", ["248-270"])
    qualified, qualified_code = _transform(
        tmp_path, "qualified", [{"file": VPDCL.name, "lines": ["248-270"]}])
    assert bare_code == qualified_code == 0
    assert _replaced(qualified) == _replaced(bare) == [(248, 270)]
    assert (Path(qualified["transformed_source"]).read_text()
            == Path(bare["transformed_source"]).read_text())


def test_the_shipped_elastic_contract_replaces_exactly_its_range(tmp_path):
    """``examples/elastic_minimal.json`` carries ``replace: ["83-87"]``."""
    contract = json.loads(ELASTIC_CONTRACT.read_text(encoding="utf-8"))
    assert contract["replace"] == ["83-87"]
    summary, code = run_transformation(ELASTIC_CONTRACT, tmp_path / "elastic")
    assert code == 0, summary

    assert _replaced(summary) == [(83, 87)]
    source = (ELASTIC_CONTRACT.parent / contract["source"]).resolve()
    original = source.read_text(encoding="utf-8").splitlines()
    assignment = re.compile(r"^\s+DDSDDE\s*\(.*\)\s*=", re.IGNORECASE)
    ddsdde_lines = [number for number, line in enumerate(original, start=1)
                    if assignment.match(line)]
    assert ddsdde_lines == [84, 87]
    skipped = _skipped(Path(summary["transformed_source"]).read_text())
    assert [original[number - 1].strip() for number in ddsdde_lines] == skipped
