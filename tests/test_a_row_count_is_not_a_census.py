"""The results file holds 254 rows. The store holds 240 entries. 41 sources
verified, not 44.

Both gaps have the same cause and it is not an error in either artefact: the
verification results file is append-only, and the pass resumed onto the file an
earlier pass had been writing. So it carries rows from before the transform
store was rebuilt, describing generated Fortran that no longer exists.

    254 rows
    = 240 at fingerprint 668e7e64c1371b47, one per store entry
    + 14 at fingerprint ff94800b1884bcc0, the store as it stood before

    243 distinct sources
    = 240 in the store now
    +   3 whose only row is superseded, and which the re-transform refused,
          so they are not in the store at this fingerprint at all

    44 rows at stage `verified`
    = 41 store entries that verified
    +  3 rows for sources that verified under BOTH stores

Neither the row key nor the source digest can collapse the duplicates, in
opposite directions. The key is derived from the store entry, so the same
source under two fingerprints has two keys and all 254 are distinct. The digest
is of the ACQUIRED file, and several acquired files are byte-identical to
another acquired file that also transformed, so 240 rows carry only 232
distinct digests.

The identity is the PATH INSIDE THE ACQUISITION CACHE. The digest corroborates
that a row is about the file the registry read, and the fingerprint says
whether it is about the transformed file the store holds now.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"


def summary() -> dict:
    if not REGISTRY.is_file():
        pytest.skip("the registry has not been built")
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["summary"]


def reconciliation() -> dict:
    found = summary().get("verification_file_reconciliation") or {}
    if not found:
        pytest.skip("the registry was built without verification results")
    return found


def test_the_rows_in_the_file_add_up_to_the_sources_the_registry_counts():
    """A registry that cannot explain its own denominator is not evidence, so
    the arithmetic is published and it has to close."""
    r = reconciliation()
    assert (r["rows_at_the_current_store_fingerprint"]
            + r["rows_at_a_superseded_store_fingerprint"]) == r["rows_in_the_file"]
    assert r["sources_counted_by_this_registry"] == \
        r["rows_at_the_current_store_fingerprint"]
    assert (len(r["superseded_rows_whose_source_was_rerun"])
            + len(r["superseded_rows_whose_source_is_no_longer_in_the_store"])
            ) == r["rows_at_a_superseded_store_fingerprint"]
    assert (r["sources_counted_by_this_registry"]
            + len(r["superseded_rows_whose_source_is_no_longer_in_the_store"])
            ) == r["distinct_sources_in_the_file"]


def test_a_row_count_is_not_the_verified_count():
    """A count of ROWS carrying the word and a count of VERIFIED SOURCES are
    different numbers, and only the second is a verification rate.

    pass10 showed it through duplication (an append-only file counted three
    sources twice). pass12 shows it a second way: 57 rows carry the word
    'verified' and 13 of them hold a gate reading false in their own evidence.
    What is asserted is the arithmetic, which holds whichever cause is present.
    """
    r = reconciliation()
    double = r["verified_rows_that_double_count_a_source"]
    demoted = r["rows_demoted_because_their_own_evidence_contradicts_the_word"]
    assert (r["store_entries_that_verified"] + len(double) + len(demoted)
            == r["rows_whose_file_stage_says_verified"])
    assert summary()["fully_verified"] == r["store_entries_that_verified"]
    assert "there_is_one_verified_number" in r

def test_neither_the_row_key_nor_the_digest_could_have_been_the_identity():
    """The key over-counts and the digest under-counts, so the path inside the
    cache is what the registry is keyed on."""
    r = reconciliation()
    assert r["distinct_keys_in_the_file"] == r["rows_in_the_file"], (
        "if the key ever collapses two rows, this reasoning needs rechecking")
    assert r["distinct_source_digests_at_the_current_fingerprint"] < \
        r["rows_at_the_current_store_fingerprint"], (
            "if every store entry has a distinct source digest, the "
            "under-counting half of this test has gone")


def test_a_superseded_row_never_becomes_a_verdict():
    """Unknown is never verified. A source whose only verification row was
    produced against a store that has since been rebuilt gets no stage from
    it, and its record says what the row was and why it does not count.

    pass11 carries no such row -- it was written fresh rather than resumed
    onto an earlier pass's file, and all 237 of its rows are at the current
    fingerprint. So the rule is checked where it applies AND the absence is
    checked against the reconciliation, rather than the test quietly passing
    on an empty list or failing because the input got cleaner."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    stale = [r for r in registry["records"] if r["superseded_verification"]]
    if not stale:
        assert reconciliation()["rows_at_a_superseded_store_fingerprint"] == 0
        return
    for record in stale:
        assert record["terminal_state"] != "fully_verified", record["source_id"]
        assert record["verification_fingerprint"] == "", record["source_id"]
        assert "has since been rebuilt" in record["superseded_verification"]
        assert record["superseded_verification"] in \
            record["not_verified_reason"], record["source_id"]
    assert sorted(r["source_id"] for r in stale) == \
        summary()["verification_rows_at_a_stale_fingerprint"]


def test_a_verification_row_that_names_a_different_file_is_not_evidence():
    """Every row this registry took a verdict from carries the sha256 of the
    acquired file it ran, and it agrees with the sha256 this registry computed
    from the cache. A row whose digest disagreed would be about a different
    file however well the paths lined up."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    checked = [r for r in registry["records"] if r["verification_sha256"]]
    assert len(checked) >= 200, len(checked)
    disagreeing = [r["source_id"] for r in checked
                   if r["verification_sha256_agrees"] is not True]
    assert not disagreeing, disagreeing[:10]


def test_the_report_shows_the_reader_the_same_arithmetic():
    report = REPO / "paper_results/corpus/CORPUS_VERIFICATION.md"
    if not report.is_file():
        pytest.skip("the report has not been built")
    text = report.read_text(encoding="utf-8")
    r = reconciliation()
    assert "Why the results file holds more rows than the store holds entries" \
        in text
    assert str(r["rows_in_the_file"]) in text
    assert str(r["store_entries_that_verified"]) in text
    assert "is not a census" in text
    for name in r["superseded_rows_whose_source_is_no_longer_in_the_store"]:
        assert name in text, name
