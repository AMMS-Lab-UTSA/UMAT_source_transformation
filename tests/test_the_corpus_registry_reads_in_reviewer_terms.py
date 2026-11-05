"""The committed corpus registry reads in the current vocabulary, and its readers still work.

1.2.1 rewrote the agent role names in paper_results/corpus and
paper_results/discovery to "reviewer" (council_*, vera_accepted_* and similar
columns; values such as "Vera" and "Scout (B3)"), and component names for
the two builders' producer ids. This loads the rewritten registry the way its
readers do, and checks that no record still needs the legacy-name reader.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

import pytest

from umat_oti.corpus_features.legacy_names import upgrade

REPO = Path(__file__).resolve().parents[1]
REGISTRY_JSON = REPO / "paper_results" / "corpus" / "corpus_registry.json"
REGISTRY_CSV = REPO / "paper_results" / "corpus" / "corpus_registry.csv"
FOLDERS = (REPO / "paper_results" / "corpus", REPO / "paper_results" / "discovery")
AGENT = re.compile(r"(?i)(?<![A-Za-z0-9])(vera|scout|noether|council|curie|quill|hopper|nico|"
                   r"atlas|lovelace|iris|vfn333)(?![a-z])|\bgauss/B\d|\bAda\b")

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_the_registry_loads_with_reviewer_columns_in_both_forms():
    records = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))["records"]
    rows = list(csv.DictReader(REGISTRY_CSV.open(encoding="utf-8")))
    assert len(records) == len(rows) == 419
    for fields in (records[0].keys(), rows[0].keys()):
        assert {"reviewer_deck_ref", "reviewer_fingerprint", "reviewer_sets",
                "review_accepted_template", "review_accepted_instance", "reviewer_refusal"} <= set(fields)
    assert [r["key"] for r in records] == [r["key"] for r in rows]


def test_no_record_still_needs_the_legacy_reader():
    records = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))["records"]
    assert upgrade(records) == records


def test_the_case_tool_finds_a_registry_row():
    spec = importlib.util.spec_from_file_location("corpus_cases_registry", REPO / "tools" / "corpus_cases.py")
    cases = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cases)
    key = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))["records"][0]["key"]
    assert cases.registry_row(key)["key"] == key


def test_no_agent_name_is_left_in_the_corpus_data():
    hits = []
    for folder in FOLDERS:
        for path in folder.rglob("*"):
            if path.suffix.lower() not in {".json", ".csv", ".md", ".jsonl", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            hits += [f"{path.relative_to(REPO)}: {m.group(0)}" for m in AGENT.finditer(text)]
    assert not hits, hits[:10]
