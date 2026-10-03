"""A fixture frozen from what the current verifier writes meets the contract.

Since 4d91f0c the verifier records which gate decided the primal
(``evidence.primal_decided_by``). The fixture exporter carries the verifier's
evidence into ``finite_history.evidence`` verbatim, and the shared fixture
schema closes that object (additionalProperties: false) without listing the
key -- so every fixture frozen at the current generation failed the contract
its own producer ships, and the Residual Assembler refused it.

The evidence keys and the primal_decided_by values are read from the
verifier's source, not restated here, so a key the verifier gains later fails
this test instead of the consumer.
"""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from export_residual_fixture import freeze  # noqa: E402
from umat_oti.contract.schema import SchemaViolation, validate  # noqa: E402

VERIFIER = REPO / "tools" / "verify_store_in_abaqus.py"
CORPUS = REPO / "tests" / "fixtures" / "corpus"


def _is_evidence(node: ast.AST) -> bool:
    """``record["evidence"]``"""
    return (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and node.slice.value == "evidence")


def _verifier_evidence() -> tuple[set, set]:
    """The evidence keys the verifier writes, and every primal_decided_by value."""
    tree = ast.parse(VERIFIER.read_text(encoding="utf-8"))
    keys: set = set()
    decided: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if _is_evidence(target) and isinstance(node.value, ast.Dict):
                    keys |= {key.value for key in node.value.keys if isinstance(key, ast.Constant)}
                if (isinstance(target, ast.Subscript) and _is_evidence(target.value)
                        and isinstance(target.slice, ast.Constant)):
                    keys.add(target.slice.value)
                if isinstance(target, ast.Name) and target.id == "decided_by":
                    # the branches of the conditional, not the keys it reads
                    decided |= {branch.value for item in ast.walk(node.value) if isinstance(item, ast.IfExp)
                                for branch in (item.body, item.orelse)
                                if isinstance(branch, ast.Constant) and isinstance(branch.value, str)}
    return keys, decided


KEYS, DECIDED = _verifier_evidence()


@pytest.fixture(scope="module")
def control():
    return json.loads((CORPUS / "results" / "store_verification.jsonl").read_text().strip())


def test_the_verifier_is_read_rather_than_restated():
    assert "primal_decided_by" in KEYS and "primal_agreed" in KEYS
    assert "routine_level+jacobian_matched" in DECIDED and len(DECIDED) >= 4


@pytest.mark.parametrize("decided_by", sorted(_verifier_evidence()[1]))
def test_a_fixture_carrying_the_verifiers_evidence_validates(control, decided_by):
    row = copy.deepcopy(control)
    evidence = {key: True for key in KEYS}
    evidence["primal_decided_by"] = decided_by
    row["evidence"] = evidence
    validate(freeze(row, CORPUS / "work"), "residual_fixture", where=decided_by)


def test_a_primal_decision_the_verifier_never_writes_is_refused(control):
    row = copy.deepcopy(control)
    row["evidence"] = {**{key: True for key in KEYS}, "primal_decided_by": "fe_comparison"}
    with pytest.raises(SchemaViolation, match="primal_decided_by|fe_comparison"):
        validate(freeze(row, CORPUS / "work"), "residual_fixture")
