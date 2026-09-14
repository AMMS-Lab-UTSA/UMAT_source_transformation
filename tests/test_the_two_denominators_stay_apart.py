"""391 acquired sources is one number. The UMATs that could be driven is another.

A single "verification rate" over a corpus is two different claims wearing one
number, and which of the two a reader takes it for decides whether the figure
means anything:

* **D1, the 391 acquired sources.** Everything the acquisition brought back,
  whatever it turned out to be -- a UEL, a second copy of another file, a
  template with an empty body, an Elmer solver module. This is the denominator
  for "what happened to the corpus we collected".

* **D2, the adequately specified genuine UMATs.** The subset that presents the
  Abaqus UMAT interface, is a distinct member of the corpus, has a
  constitutive model inside it, builds as its author published it, has
  everything it USEs published beside it, and has material constants published
  for it. This is the denominator for "what happened to the UMATs that could
  be driven at all".

The danger in having two is the temptation to move a source from D2's
denominator whenever it fails, which raises the rate without establishing
anything. So the rule this module enforces is one-directional and absolute:

    NOTHING INTERNAL MAY SHRINK D2.

A source this project's transformer refused, whose deck this project could not
generate, whose experiment this project could not make informative, stays in
D2 and counts against us. Only a fact about somebody else's published
repository -- with the evidence that established it recorded on the record --
may take a source out.
"""
import csv
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"
REPORT = REPO / "paper_results/corpus/CORPUS_VERIFICATION.md"
CSV_PATH = REPO / "paper_results/corpus/corpus_registry.csv"


def registry():
    if not REGISTRY.is_file():
        pytest.skip("the registry has not been built")
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def report():
    if not REPORT.is_file():
        pytest.skip("the report has not been built")
    return REPORT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------
def test_nothing_internal_takes_a_source_out_of_the_umat_denominator():
    """Every exclusion from D2 is a fact about somebody's published
    repository. If an internal limitation ever removes a source, the rate
    quoted against D2 goes up without anything having been established, which
    is the one failure this separation exists to prevent."""
    excluded = [r for r in registry()["records"]
                if r["adequately_specified"] is False]
    assert excluded, "nothing was excluded from D2 at all"
    offenders = [(r["source_id"], r["adequacy_kind"]) for r in excluded
                 if r["adequacy_kind"] != "external"]
    assert not offenders, offenders


def test_every_exclusion_names_the_evidence_that_established_it():
    """A source removed from a denominator with no reason recorded is a
    source removed from a denominator."""
    for record in registry()["records"]:
        if record["adequately_specified"] is False:
            assert record["adequacy_basis"], record["source_id"]
            assert len(record["adequacy_basis"]) > 20, record["source_id"]


def test_the_two_denominators_are_both_published_and_d2_is_inside_d1():
    summary = registry()["summary"]
    records = registry()["records"]
    d1 = summary["acquired"]
    d2 = summary["adequately_specified_genuine_umats"]
    assert d1 == len(records) == 391, d1
    assert 0 < d2 <= d1
    assert len([r for r in records if r["adequately_specified"] is True]) == d2
    both = summary["denominators"]
    assert both["acquired_sources"]["count"] == d1
    assert both["adequately_specified_genuine_umats"]["count"] == d2
    # Every record is in exactly one of the three buckets, so nothing can be
    # quietly dropped from both the numerator and the denominator.
    kinds = [r["adequately_specified"] for r in records]
    assert kinds.count(True) + kinds.count(False) + kinds.count(None) == d1


def test_a_verified_source_is_counted_against_both_denominators():
    """A source that verified is in D1 and, unless something external
    excludes it, in D2. The two verified counts are published separately so a
    reader can see that the numerator did not change when the denominator
    did."""
    summary = registry()["summary"]
    assert summary["fully_verified_and_adequately_specified"] <= \
        summary["fully_verified"]
    records = registry()["records"]
    verified = [r for r in records if r["terminal_state"] == "fully_verified"]
    assert len(verified) == summary["fully_verified"]


# ---------------------------------------------------------------------------
# a reason for every one of the 391 that is not verified
# ---------------------------------------------------------------------------
def test_everything_not_verified_carries_a_named_reason():
    """Unknown is never verified, and a source that is not verified has to say
    why in words a reader can check."""
    missing = [r["source_id"] for r in registry()["records"]
               if r["terminal_state"] != "fully_verified"
               and not r["not_verified_reason"]]
    assert not missing, missing[:10]
    assert registry()["summary"]["records_with_no_named_reason"] == []


def test_a_reason_is_never_only_that_the_transformer_refused_it():
    """"The transformer refused it" is an answer about the transformer. Where
    a transform refusal is what stopped a source, the reason still has to name
    what the FILE is, established by parsing it."""
    for record in registry()["records"]:
        reason = record["not_verified_reason"]
        if not reason:
            continue
        assert "terminal state" in reason, record["source_id"]
        if record["terminal_state"] == "transform_refused":
            assert record["refusal_class"], record["source_id"]
            assert record["classification_basis"] or record["output_search"], \
                record["source_id"]


def test_every_record_says_where_its_file_was_searched_for_a_stress_update():
    """A refusal that does not say where it searched is a claim, not a
    finding. Every acquired source the cache holds carries the search: how
    many logical lines were read, under which source form, and what was looked
    for."""
    for record in registry()["records"]:
        if not record["sha256"]:
            continue                        # not in the cache; says so
        assert record["output_search"], record["source_id"]
        assert "logical lines" in record["output_search"]
        assert record["output_calls"] is not None


# ---------------------------------------------------------------------------
# the report a person reads
# ---------------------------------------------------------------------------
def test_no_percentage_appears_without_its_denominator():
    """A percentage without its denominator stated is not acceptable output,
    so every one in the report is followed by the population it is a
    percentage of."""
    text = report()
    for match in re.finditer(r"\d+(?:\.\d+)?%", text):
        tail = text[match.end():match.end() + 8]
        assert tail.startswith(" of "), (
            f"{match.group(0)} at offset {match.start()} does not name a "
            f"denominator: ...{text[match.start() - 60:match.end() + 40]}...")


def test_the_report_names_both_denominators_and_keeps_them_apart():
    text = report()
    assert "acquired sources" in text
    assert "adequately specified genuine UMATs" in text
    assert "D1" in text and "D2" in text
    assert "NOTHING INTERNAL" in text.upper()


def test_every_terminal_state_in_the_report_is_marked_external_or_internal():
    """For every terminal state the report has to say whose move it is. A
    table of state names with no owner is the thing this project exists not to
    print."""
    from umat_oti.abaqus.terminal_states import kind_of
    text = report()
    table = text.split("## Every terminal state, and whose move it is")[1]
    table = table.split("\n##")[0]
    rows = [line for line in table.splitlines()
            if line.startswith("| `")]
    assert rows, "the terminal-state table is empty"
    for line in rows:
        state = line.split("`")[1]
        expected = {"verified": "VERIFIED", "external": "EXTERNAL",
                    "internal": "INTERNAL"}[kind_of(state)]
        assert expected in line, (state, line)


def test_the_report_names_the_file_every_number_came_from():
    text = report()
    summary = registry()["summary"]
    assert "Where every number below comes from" in text
    for key in ("transform_report", "verification_results"):
        value = (summary.get("inputs") or {}).get(key)
        if value:
            assert value in text, key


# ---------------------------------------------------------------------------
# no machine paths, ever
# ---------------------------------------------------------------------------
MACHINE_SHAPED = re.compile(
    r"/home/[a-z][-a-z0-9_]*/|/Users/[A-Za-z][-A-Za-z0-9_]*/"
    r"|/tmp/(?:claude|tmp|pytest-of-|pyright-|scratch)[-a-zA-Z0-9_.]*/")


@pytest.mark.parametrize("path", [REGISTRY, REPORT, CSV_PATH])
def test_no_published_artefact_names_a_machine(path: Path):
    """`tools/audit_repository_standards.py` fails a build on a path under
    somebody's home or scratch directory, and this registry has failed on
    exactly that before: an absolute home path reached a published column
    because the string it arrived in was a compiler diagnostic, which names
    the temporary directory the syntax pass ran in."""
    if not path.is_file():
        pytest.skip(f"{path.name} has not been built")
    text = path.read_text(encoding="utf-8", errors="replace")
    found = MACHINE_SHAPED.search(text)
    assert not found, (path.name,
                       text[max(0, found.start() - 80):found.end() + 80])


def test_the_builder_refuses_to_write_a_machine_path_rather_than_scrubbing_it():
    """Scrubbing silently would be worse than failing: the registry would
    still be published and nobody could tell a line had been edited. So the
    build stops and names the offending text."""
    from build_corpus_registry import refuse_machine_paths

    clean = "paper_results/corpus/corpus_registry.json is fine"
    assert refuse_machine_paths(clean, "fixture") == clean

    for offender in (
            "ifort: error in /home/someone/work/scratch/umat.f",   # machine-path-fixture: the home-directory shape the audit fails a build on
            "catastrophic error: /tmp/claude-1000/xyz/aba_param.inc",  # machine-path-fixture: the scratch shape a compiler diagnostic arrives in
            "/Users/someone/Desktop/umat.for",                     # machine-path-fixture: the macOS home shape
    ):
        with pytest.raises(ValueError) as raised:
            refuse_machine_paths(offender, "a fixture record")
        assert "machine path" in str(raised.value)
        assert "a fixture record" in str(raised.value)


def test_the_csv_carries_the_same_391_rows_as_the_json():
    if not CSV_PATH.is_file():
        pytest.skip("the registry CSV has not been built")
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 391
    assert {r["source_id"] for r in rows} == \
        {r["source_id"] for r in registry()["records"]}


def test_a_source_is_identified_by_its_path_and_never_by_its_basename():
    """Eighteen acquired sources share one basename. A registry keyed on the
    basename would hold one row where the corpus holds eighteen files."""
    records = registry()["records"]
    basenames = [r["source_id"].rsplit("/", 1)[-1] for r in records]
    worst = max(set(basenames), key=basenames.count)
    assert basenames.count(worst) >= 10, (worst, basenames.count(worst))
    assert len({r["source_id"] for r in records}) == len(records)
    for record in records:
        assert "/" in record["source_id"], record["source_id"]
        assert record["cache_path"] == record["source_id"]
