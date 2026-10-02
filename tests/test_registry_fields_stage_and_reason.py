"""Registry fields that contradicted the record they sit in (Vera, B6 note 3).

* ``compiled`` was copied from the batch row even where the transform was
  refused. The row's flag is about whatever Fortran the attempt emitted, and a
  refusal by the semantic checks can follow a build that compiles: the HETVAL
  Lemaitre source read ``transformed False, compiled True``. The registry's
  ``compiled`` is the stage after ``transformed``.
* A source whose own text says it is not a UMAT carried the transform's
  refusal text as its reason, as though the refusal had decided ``not_a_umat``
  (rhdodds__warp3d user_routines_umat.f, where the pass16 reason had been the
  file's 43-argument UMAT).

``bytes`` changing while ``sha256`` did not, the third observation, is the
B1 correction (tests/test_registry_fields_bytes_and_companions.py): the frozen
pass16 value was the decoded length, the rebuilt one is the file size.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"
WARP3D = "rhdodds__warp3d/src/user_routines_umat.f"


def _records():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]


def test_nothing_is_compiled_that_was_not_transformed():
    both = [r["source_id"] for r in _records()
            if r["transformed"] is not True and r["compiled"] is True]
    assert both == []


def test_a_file_that_is_not_a_umat_is_not_given_a_refusal_as_its_reason():
    for record in _records():
        if record["terminal_state"] != "not_a_umat" or record["transformed"]:
            continue
        if not record["attempted"]:
            continue
        assert record["reason"].startswith(
            "not a UMAT by the file's own entry point"), record["source_id"]
        assert record["classification_basis"], record["source_id"]
    warp3d = next(r for r in _records() if r["source_id"] == WARP3D)
    assert "43 arguments" in warp3d["classification_basis"]
    assert "the transform also refused it: Semantic check failed" in warp3d["reason"]
