"""Council evidence locators without ``#`` in the path (Scout, Vera D-27).

``#`` separates a locator's path from its selector, so a set folder named
``<key>#A`` can never be named by a locator. ``tools/council_locators.py``
copies the folders to ``<key>_A`` and rewrites the cells; no fingerprint-
covered code changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import council_locators as cl  # noqa: E402
from umat_oti.corpus_features import manifest as m  # noqa: E402

KEY = "4698392c1e21de908d263766"


def test_the_set_folder_name_loses_its_hash_and_nothing_else():
    assert cl.safe_name(f"{KEY}#A") == f"{KEY}_A"
    assert cl.safe_name(f"{KEY}#B.log") == f"{KEY}_B.log"
    assert cl.safe_name("corpus_features.jsonl") == "corpus_features.jsonl"
    assert cl.safe_name("full.%s#A.log" % KEY) == "full.%s#A.log" % KEY


def test_the_rewritten_locator_has_only_the_fragment_separator():
    old = (f"campaign:pass23_council/growth/primal/{KEY}#A/corpus_features.jsonl"
           f"#key={KEY}#A&feature=ddsdde")
    new = cl.rewrite_locator(old)
    assert new == (f"campaign:pass23_council/growth/primal/{KEY}_A/corpus_features.jsonl"
                   f"#key={KEY}&set=A&feature=ddsdde")
    assert new.count("#") == 1
    assert cl.rewrite_locator(new) == new            # idempotent
    assert cl.rewrite_locator("repo:a/b.json#x=1") == "repo:a/b.json#x=1"


def test_the_old_locator_does_not_resolve_and_the_new_one_does(tmp_path):
    run = tmp_path / "pass/growth/primal"
    (run / f"{KEY}#A").mkdir(parents=True)
    (run / f"{KEY}#A" / "corpus_features.jsonl").write_text("{}\n")
    roots = {"campaign": str(tmp_path)}
    old = f"campaign:pass/growth/primal/{KEY}#A/corpus_features.jsonl#key={KEY}#A"
    assert m.resolve_locator(old, roots)[0] is None
    cells = tmp_path / "cells.jsonl"
    cells.write_text(json.dumps({"evidence": old, "evidence_all": [old]}) + "\n")
    out = tmp_path / "out.jsonl"
    assert cl.main([str(cells), str(out), str(run)]) == 0
    cell = json.loads(out.read_text())
    target, why = m.resolve_locator(cell["evidence"], roots)
    assert why == "" and target == (run / f"{KEY}_A" / "corpus_features.jsonl").resolve()
    assert m.resolve_locator(cell["evidence_all"][0], roots)[0] == target
    # the originals are untouched and the copies carry the same digests
    assert (run / f"{KEY}#A" / "corpus_features.jsonl").is_file()
    copies = json.loads(out.with_suffix(".copies.json").read_text())["files"]
    assert copies and all(c["sha256"] == c["sha256_copy"] for c in copies)
