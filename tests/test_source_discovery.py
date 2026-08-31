"""Discovery decides what may be used, and it must not decide anything else.

A source that survives this step has been shown to be a distinct,
permissively licensed Fortran file declaring a UMAT entry point. Two failure
modes matter more than the count it produces: reporting a source the
collection already has as a new one, which inflates a generality claim; and
fetching or caching something whose licence does not permit it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from umat_oti.corpus.acquire import REDISTRIBUTABLE_SPDX  # noqa: E402
from umat_oti.corpus.identity import content_identity  # noqa: E402
from discover_umat_sources import (  # noqa: E402
    _has_umat_entry, _hashes, known_identities,
)

# The pinned snapshot, by the convention the rest of the
# suite uses: an absolute path here records this machine's
# home directory in a tracked file.
SNAPSHOT_ROOT = Path(
    os.environ.get("UMAT_OTI_SNAPSHOT_ROOT")
    or REPO_ROOT.parent / "Residual_Assembler" / "sources")


def test_hashes_agree_with_the_identity_registry():
    """Discovery must hash a file exactly as the collection identifies it.

    A different normalisation is a silent duplicate: the same implementation
    gets a different digest and is reported as a new source.
    """
    source = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"
    identity = content_identity(source)
    content, code_only = _hashes(source.read_text(errors="replace"), str(source))
    assert content == identity.content_sha256
    assert code_only == identity.code_only_sha256


def test_a_fixed_form_suffix_changes_the_code_only_hash():
    """The fixed-form decision is part of the identity, not a detail."""
    text = "      SUBROUTINE UMAT(STRESS)\nC     a comment\n      END\n"
    _, fixed = _hashes(text, "umat.for")
    _, free = _hashes(text, "umat.f90")
    assert fixed != free, (
        "hashing a .for file as free-form gives a different digest for the "
        "same bytes, and the duplicate is missed")


@pytest.mark.skipif(not SNAPSHOT_ROOT.is_dir(), reason="snapshot root absent")
def test_sources_already_in_the_collection_are_recognised():
    """The regression this exists for: an empty known-set rediscovers everything."""
    known = known_identities(SNAPSHOT_ROOT)
    assert known, "no known implementations were loaded"

    checked = 0
    for name in ("UMATS/UMAT_ECO.for", "UMATS/UMAT_PCL.for", "UMATS/UMAT_PCLK.for"):
        source = SNAPSHOT_ROOT / "permissive/jgomezc1_ABAQUS-US" / name
        if not source.is_file():
            continue
        _, code_only = _hashes(source.read_text(errors="replace"), str(source))
        assert code_only in known, f"{name} is in the corpus but was not recognised"
        checked += 1
    assert checked, "no corpus source was available to check against"


def test_a_umat_entry_is_detected_however_it_is_spaced():
    assert _has_umat_entry("      SUBROUTINE UMAT(STRESS,STATEV)")
    assert _has_umat_entry("      subroutine  umat ( stress )")
    assert _has_umat_entry("      SUBROUTINE\n     & UMAT(STRESS)")
    assert not _has_umat_entry("      SUBROUTINE UEL(RHS,AMATRX)")
    assert not _has_umat_entry("C     this file mentions UMAT only in prose")


def test_the_licence_gate_excludes_what_this_project_may_not_redistribute():
    """GPL-2.0-only is not compatible with this repository's GPL-3.0."""
    assert "GPL-2.0" not in REDISTRIBUTABLE_SPDX
    assert "GPL-2.0-only" not in REDISTRIBUTABLE_SPDX
    assert "" not in REDISTRIBUTABLE_SPDX
    for allowed in ("MIT", "BSD-3-Clause", "Apache-2.0", "GPL-3.0"):
        assert allowed in REDISTRIBUTABLE_SPDX


def test_the_published_manifest_never_claims_a_candidate_is_verified():
    """Discovery reports eligibility, never evidence."""
    import json

    manifest = REPO_ROOT / "paper_results" / "discovery" / "discovered_sources.json"
    if not manifest.is_file():
        pytest.skip("discovery has not been run")
    summary = json.loads(manifest.read_text(encoding="utf-8"))
    caveat = summary.get("caveat", "")
    assert "transformed" in caveat and "verified" in caveat, (
        "the manifest must say plainly that a candidate is not evidence")
    assert summary.get("search_total_reported_by_github") is not None
    assert "search_pages_read" in summary, (
        "a count of what was found is a statement about the search that was "
        "run, and the manifest has to say how much of it was read")


# --------------------------------------------------------------------------- #
# What the discovered sources exposed in the pipeline itself.
# --------------------------------------------------------------------------- #
def test_a_variable_is_never_assigned_two_roles(tmp_path: Path):
    """Regression: sixteen of seventy-one sources aborted with no report.

    The contract builder forces the response variable into "promote", and the
    deformation gradient too when the kinematics are finite -- precisely
    because the classifier may not have put them there, which means they are
    still sitting in whichever list it did choose. Emitting both assignments
    makes a contract the loader rejects with "assigns variable DFGRD1 to
    multiple roles", and the transform aborts before it can report anything.
    Every source that hit it was finite-strain.
    """
    from umat_oti.app.engine import _build_contract

    source = tmp_path / "umat.for"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,DFGRD0,DFGRD1)\n"
        "      DIMENSION STRESS(6),DFGRD1(3,3)\n"
        "      DETF = DFGRD1(1,1)\n"
        "      STRESS(1) = DETF\n"
        "      DDSDDE(1,1) = 1.0\n"
        "      END\n", encoding="utf-8")

    config, _finite = _build_contract(
        "probe", "auto", "STRESS", "DDSDDE", 6, 1, source)
    variables = config["variables"]
    roles = {name: set(variables[name]) for name in
             ("seed", "promote", "constant", "real")}
    overlaps = {
        f"{a} and {b}": sorted(roles[a] & roles[b])
        for a in roles for b in roles if a < b and (roles[a] & roles[b])
    }
    assert not overlaps, f"a variable holds two roles: {overlaps}"


def test_the_forced_names_win_their_role(tmp_path: Path):
    """Precedence, not merely deduplication.

    Dropping the duplicate from "promote" instead of from the lower-priority
    list would resolve the contradiction and quietly stop differentiating the
    response.
    """
    from umat_oti.app.engine import _build_contract

    source = tmp_path / "umat.for"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,DFGRD0,DFGRD1)\n"
        "      DIMENSION STRESS(6),DFGRD1(3,3)\n"
        "      DETF = DFGRD1(1,1)\n"
        "      STRESS(1) = DETF\n"
        "      DDSDDE(1,1) = 1.0\n"
        "      END\n", encoding="utf-8")
    config, finite = _build_contract(
        "probe", "auto", "STRESS", "DDSDDE", 6, 1, source)
    variables = config["variables"]
    assert "STRESS" in variables["promote"], "the response must carry a derivative"
    if finite:
        assert "DFGRD1" in variables["promote"], (
            "a finite-strain source differentiates the deformation gradient")
        assert "DFGRD1" not in variables["real"]
    assert variables["seed"] == ["DSTRAN"]
    assert "DSTRAN" not in variables["promote"]


# --------------------------------------------------------------------------- #
# Widening the search: what it must reach, and what it must still refuse.
# --------------------------------------------------------------------------- #

from discover_umat_sources import (  # noqa: E402
    CODE_QUERIES, REPOSITORY_QUERIES, Survey, _declares_vumat_only,
    _decks_near, _licence_class, _may_be_source, cache_identities,
    search_repositories, survey_repository,
)

_UMAT = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,\n"
         "     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME)\n"
         "      INCLUDE 'ABA_PARAM.INC'\n"
         "      DIMENSION STRESS(NTENS),DDSDDE(NTENS,NTENS)\n"
         "      RETURN\n      END\n")
_VUMAT = ("      SUBROUTINE VUMAT(NBLOCK,NDIR,NSHR,NSTATEV)\n"
          "      RETURN\n      END\n")
_NOT_A_UMAT = "      SUBROUTINE HELPER(A,B)\n      RETURN\n      END\n"


class _FakeClient:
    """Answers the four questions survey_repository asks, and nothing else."""

    def __init__(self, *, spdx, evidence="LICENSE", tree=(), blobs=None,
                 search=None):
        self._spdx = spdx
        self._evidence = evidence
        self._tree = list(tree)
        self._blobs = dict(blobs or {})
        self._search = search or {}
        self.blobs_read: list[str] = []

    def license(self, owner, repo):
        return self._spdx, self._evidence

    def default_branch(self, owner, repo):
        return "main"

    def resolve_commit(self, owner, repo, branch):
        return "0" * 40

    def tree(self, owner, repo, commit):
        return self._tree

    def blob(self, owner, repo, sha):
        self.blobs_read.append(sha)
        return self._blobs[sha].encode("utf-8")

    def _get(self, url):
        for needle, payload in self._search.items():
            if needle in url:
                return payload
        return {"total_count": 0, "items": []}


def _entry(path, sha, size=100):
    return {"path": path, "sha": sha, "size": size, "type": "blob"}


def test_a_cached_source_is_not_admitted_a_second_time(tmp_path: Path):
    """The regression: discovery re-admitted everything it had already cached.

    ``known_identities`` reads the generality matrix, which lists what the
    corpus round processed. It has never listed what a previous discovery run
    cached, so before this every source in the cache was a fresh discovery on
    the next run -- the same files, fetched again and counted again as having
    widened the corpus.
    """
    cache = tmp_path / "discovery_cache"
    (cache / "owner__repo").mkdir(parents=True)
    (cache / "owner__repo" / "umat.for").write_text(_UMAT)

    known = cache_identities(cache)
    assert known, "a cache holding a UMAT produced no digests"

    client = _FakeClient(spdx="MIT", tree=[_entry("src/umat.for", "sha1")],
                         blobs={"sha1": _UMAT})
    survey = Survey()
    survey_repository(client, "owner/repo", known, survey, max_files=5)
    outcomes = [row.outcome for row in survey.rows]
    assert outcomes == ["already_known"], (
        f"a source already in the cache was admitted again: {outcomes}")
    assert "discovery_cache/owner__repo/umat.for" in survey.rows[0].reason


def test_the_cache_name_never_records_an_absolute_path(tmp_path: Path):
    """The reason string reaches published evidence; a home path must not."""
    cache = tmp_path / "discovery_cache"
    (cache / "owner__repo").mkdir(parents=True)
    (cache / "owner__repo" / "umat.for").write_text(_UMAT)
    for name in cache_identities(cache).values():
        assert not name.startswith("/"), name
        assert "home" not in name.split("/")[0]


def test_the_published_cache_would_not_be_rediscovered():
    """Against the real cache, when the machine running this has one."""
    root = os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
    if not root or not Path(root).is_dir():
        pytest.skip("no discovery cache on this machine")
    import csv as _csv

    manifest = REPO_ROOT / "paper_results" / "discovery" / "discovered_sources.csv"
    if not manifest.is_file():
        pytest.skip("discovery has not been run")
    known = cache_identities(Path(root))
    with manifest.open(newline="", encoding="utf-8") as handle:
        cached = [r for r in _csv.DictReader(handle)
                  if r["outcome"] == "candidate" and r.get("cached_as")]
    if not cached:
        pytest.skip("the published manifest cached nothing")
    missed = [r["cached_as"] for r in cached
              if r["content_sha256"] not in known
              and r["code_only_sha256"] not in known]
    assert not missed, (
        f"{len(missed)} of {len(cached)} already-cached sources would be "
        f"admitted again as new discoveries: {missed[:5]}")


def test_the_search_asks_more_than_one_question():
    """One code-search query cannot see past GitHub's 1000-result cap.

    Reading more pages of the same query does not reach further; asking a
    differently-shaped question does.
    """
    assert len(CODE_QUERIES) > 1
    names = [name for name, _ in CODE_QUERIES]
    assert len(set(names)) == len(names), "two formulations share a name"
    formulations = [q for _, q in CODE_QUERIES]
    assert len(set(formulations)) == len(formulations), "a query is duplicated"
    assert any("ABA_PARAM" in q.upper() for q in formulations)
    assert any("DDSDDE" in q.upper() for q in formulations)
    assert any("language:Fortran" not in q for q in formulations), (
        "GitHub does not classify a UMAT shipped as .inc or .txt as Fortran, "
        "so at least one formulation must not carry the language filter")


def test_no_formulation_asks_for_a_vumat():
    """VUMAT is a different interface and is out of scope."""
    for _, query in CODE_QUERIES + REPOSITORY_QUERIES:
        assert "VUMAT" not in query.upper()


def test_a_vumat_only_file_is_refused_and_said_to_be_out_of_scope():
    assert _declares_vumat_only(_VUMAT)
    assert not _declares_vumat_only(_UMAT)
    assert not _declares_vumat_only(_NOT_A_UMAT)

    client = _FakeClient(spdx="MIT", tree=[_entry("vumat.for", "v1")],
                         blobs={"v1": _VUMAT})
    survey = Survey()
    survey_repository(client, "o/r", {"x": "y"}, survey, max_files=5)
    assert survey.rows[0].outcome == "no_umat_entry"
    assert "out of scope" in survey.rows[0].reason


def test_a_file_the_search_matched_is_read_whatever_its_extension():
    """Abaqus does not require a Fortran extension, and authors do not use one.

    A UMAT shipped as ``.inc`` or ``.txt`` was listed in the tree and never
    opened, because the tree walk filtered on a Fortran suffix -- discarding
    the very evidence, a search hit on that path, that found the file.
    """
    tree = [_entry("umat_material.inc", "inc1"),
            _entry("notes.txt", "txt1")]
    client = _FakeClient(spdx="MIT", tree=tree,
                         blobs={"inc1": _UMAT, "txt1": _NOT_A_UMAT})
    survey = Survey()
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      matched={"umat_material.inc"})
    admitted = [r for r in survey.rows if r.outcome == "candidate"]
    assert [r.path for r in admitted] == ["umat_material.inc"], (
        f"the matched .inc was not admitted: "
        f"{[(r.path, r.outcome) for r in survey.rows]}")
    assert "txt1" not in client.blobs_read, (
        "an unmatched non-Fortran file was fetched anyway")


def test_an_enormous_matched_file_is_not_fetched():
    """The suffix rule was also a size guard; replacing it needs another one."""
    client = _FakeClient(spdx="MIT",
                         tree=[_entry("data.csv", "big", size=50_000_000)],
                         blobs={"big": _UMAT})
    survey = Survey()
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      matched={"data.csv"})
    assert client.blobs_read == []
    assert survey.rows[0].outcome == "no_fortran"


def test_a_repository_with_no_licence_is_refused_before_anything_is_read():
    client = _FakeClient(spdx=None, evidence="",
                         tree=[_entry("umat.for", "s")], blobs={"s": _UMAT})
    survey = Survey()
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5)
    assert [r.outcome for r in survey.rows] == ["licence_absent"]
    assert "refused, not assumed" in survey.rows[0].reason
    assert client.blobs_read == [], "a file was fetched from an unlicensed repository"


def test_an_incompatible_licence_is_refused_before_anything_is_read():
    client = _FakeClient(spdx="GPL-2.0",
                         tree=[_entry("umat.for", "s")], blobs={"s": _UMAT})
    survey = Survey()
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5)
    assert [r.outcome for r in survey.rows] == ["licence_incompatible"]
    assert client.blobs_read == []


def test_a_refused_repository_is_never_cached(tmp_path: Path):
    """Not even its decks: caching is downstream of the licence, always."""
    tree = [_entry("umat.for", "s"), _entry("job.inp", "d")]
    client = _FakeClient(spdx=None, evidence="", tree=tree,
                         blobs={"s": _UMAT, "d": "*HEADING\n"})
    survey = Survey()
    cache = tmp_path / "cache"
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      cache_dir=cache)
    assert not cache.exists() or list(cache.rglob("*")) == []
    assert client.blobs_read == []


def test_the_licence_class_is_recorded_without_narrowing_the_gate():
    """The obligation is written down; REDISTRIBUTABLE_SPDX is not touched."""
    assert _licence_class("MIT") == "permissive"
    assert _licence_class("Apache-2.0") == "permissive"
    assert _licence_class("GPL-3.0") == "copyleft"
    assert _licence_class("AGPL-3.0") == "copyleft"
    assert _licence_class(None) == ""
    # The gate itself still admits what this GPL-3.0-only project may
    # redistribute: classifying is not gating.
    assert "GPL-3.0" in REDISTRIBUTABLE_SPDX


def test_a_deck_beside_the_source_is_recorded_against_it():
    """ExampleInputFiles/ is where these repositories write a material vector."""
    entries = [_entry("src/umat.for", "s"),
               _entry("src/job.inp", "d0"),
               _entry("ExampleInputFiles/plate.inp", "d1"),
               _entry("unrelated/other/far.inp", "d2")]
    near = _decks_near(entries, "src/umat.for")
    assert near[0] == "src/job.inp", near
    assert "ExampleInputFiles/plate.inp" in near
    assert "unrelated/other/far.inp" not in near, (
        "a deck nowhere near the source was recorded as belonging to it")


def test_the_deck_pairing_reaches_the_row_and_the_cache(tmp_path: Path):
    tree = [_entry("umat.for", "s"), _entry("ExampleInputFiles/one.inp", "d1")]
    client = _FakeClient(spdx="MIT", tree=tree,
                         blobs={"s": _UMAT, "d1": "*HEADING\n"})
    survey = Survey()
    cache = tmp_path / "cache"
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      cache_dir=cache)
    row = survey.rows[0]
    assert row.outcome == "candidate"
    assert "ExampleInputFiles/one.inp" in row.decks
    assert (cache / "o__r" / "ExampleInputFiles" / "one.inp").is_file()
    assert not Path(row.cached_as).is_absolute()


def test_repository_search_reaches_names_code_search_did_not():
    """Code search indexes only the default branch and drops large repositories.

    Repository search answers a question it cannot: which projects say they
    are about UMATs.
    """
    client = _FakeClient(spdx="MIT", search={
        "search/code": {"total_count": 1, "items": [
            {"path": "umat.f", "repository": {"full_name": "a/code-only"}}]},
        "search/repositories": {"total_count": 1, "items": [
            {"full_name": "b/repo-only"}]},
    })
    names, total, pages, matched, provenance, found_by = search_repositories(
        client, pages=1, code_queries=(("c", "q1"),),
        repository_queries=(("r", "q2"),), repository_pages=1, pause=0.0)
    assert "a/code-only" in names and "b/repo-only" in names, names
    assert found_by["b/repo-only"] == "r"
    assert matched["a/code-only"] == {"umat.f"}
    kinds = {entry["kind"] for entry in provenance}
    assert kinds == {"code", "repository"}


def test_every_formulation_is_reported_even_when_it_finds_nothing():
    """A query that found nothing must be visible as such, not as an absence."""
    client = _FakeClient(spdx="MIT", search={})
    _, _, _, _, provenance, _ = search_repositories(
        client, pages=1, code_queries=(("a", "q1"), ("b", "q2")), pause=0.0)
    assert [entry["name"] for entry in provenance] == ["a", "b"]
    assert all(entry["repositories"] == 0 for entry in provenance)


def test_a_repository_named_twice_is_surveyed_once():
    client = _FakeClient(spdx="MIT", search={
        "search/code": {"total_count": 1, "items": [
            {"path": "umat.f", "repository": {"full_name": "a/one"}}]},
    })
    names, _, _, _, _, found_by = search_repositories(
        client, pages=1, code_queries=(("first", "q1"), ("second", "q2")),
        pause=0.0)
    assert names == ["a/one"]
    assert found_by["a/one"] == "first", "provenance must name the first finder"


def test_the_triage_reads_every_suffix_discovery_admits():
    """The two lists drifted, and the gap was a source nothing ever triaged.

    Discovery cached ``.f03`` and ``.fpp``; the triage globbed a hand-written
    set that did not include them, so those files appeared in no count at all
    -- not as transformed, not as blocked, not as skipped.
    """
    import run_discovery_triage  # noqa: F401
    from discover_umat_sources import _FORTRAN_SUFFIXES as admitted

    source = (REPO_ROOT / "tools" / "run_discovery_triage.py").read_text(
        encoding="utf-8")
    assert "set(_FORTRAN_SUFFIXES)" in source, (
        "the triage must import the suffix list discovery admits rather than "
        "repeating it")
    assert ".f03" in admitted and ".f77" in admitted


def test_a_umat_the_triage_cannot_read_is_counted_not_dropped(tmp_path: Path):
    """A UMAT shipped as .inc is a hole in the triage; a README is not."""
    from run_discovery_triage import _looks_like_a_umat

    umat_inc = tmp_path / "material.inc"
    umat_inc.write_text(_UMAT)
    readme = tmp_path / "README.md"
    readme.write_text("this project contains a UMAT\n")
    assert _looks_like_a_umat(umat_inc)
    assert not _looks_like_a_umat(readme)


def test_decks_are_cached_only_for_a_repository_that_gave_a_source(tmp_path: Path):
    """A deck is evidence about the source it drives, not evidence on its own.

    Caching every ``.inp`` from every repository whose licence cleared is how
    the cache came to hold 670 decks against 71 sources, most of them input
    files for models the collection does not have.
    """
    tree = [_entry("uel.for", "s"), _entry("ExampleInputFiles/one.inp", "d")]
    client = _FakeClient(spdx="MIT", tree=tree,
                         blobs={"s": _NOT_A_UMAT, "d": "*HEADING\n"})
    survey = Survey()
    cache = tmp_path / "cache"
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      cache_dir=cache)
    assert survey.rows[0].outcome == "no_umat_entry"
    assert not (cache / "o__r" / "ExampleInputFiles" / "one.inp").exists(), (
        "a deck was cached from a repository that contributed no source")


def test_a_deck_beside_the_source_outranks_the_deck_cache_budget(tmp_path: Path):
    """The nearby deck is taken first, not the one that sorts first."""
    tree = [_entry("src/umat.for", "s"),
            _entry("aaa_unrelated/a.inp", "d0"),
            _entry("src/job.inp", "d1")]
    client = _FakeClient(spdx="MIT", tree=tree,
                         blobs={"s": _UMAT, "d0": "*A\n", "d1": "*B\n"})
    survey = Survey()
    cache = tmp_path / "cache"
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      cache_dir=cache, max_decks=1)
    assert (cache / "o__r" / "src" / "job.inp").is_file(), (
        "the deck beside the source lost its place to one that sorts earlier")
    assert not (cache / "o__r" / "aaa_unrelated" / "a.inp").exists()


def test_documentation_that_quotes_a_umat_is_not_a_umat():
    """The defect the first widened run produced, with its own filenames.

    Reading any path the search matched, whatever its extension, admitted six
    README and docs files as candidate sources. A markdown page that quotes a
    UMAT signature in a fenced code block contains a genuine
    ``SUBROUTINE UMAT(``, so no content check can reject it -- the file it
    sits in is what disqualifies it.
    """
    for path in ("README.md",
                 "docs/examples/ex01_stvenantkirchhoff.md",
                 "developers_guide.md",
                 "Notes_AbaqusSubroutine.md",
                 "docs/_sources/material/umat.rst.txt",
                 "astest/umat001a.22"):
        assert not _may_be_source(path), f"{path} was treated as source"


def test_the_shapes_the_relaxation_exists_to_reach_still_pass():
    for path in ("umat_material.inc", "UMAT", "src/umat", "umat.txt",
                 "material.dat", "umat.for", "subroutines/umat.f90"):
        assert _may_be_source(path), f"{path} was refused"


def test_a_matched_readme_is_never_fetched():
    """The guard has to bite before the blob is read, not after."""
    tree = [_entry("README.md", "r1"), _entry("umat.for", "s1")]
    client = _FakeClient(spdx="MIT", tree=tree,
                         blobs={"r1": "# docs\n```\n" + _UMAT + "```\n",
                                "s1": _UMAT})
    survey = Survey()
    survey_repository(client, "o/r", {"z": "z"}, survey, max_files=5,
                      matched={"README.md", "umat.for"})
    assert "r1" not in client.blobs_read, "a README was fetched"
    admitted = [r.path for r in survey.rows if r.outcome == "candidate"]
    assert admitted == ["umat.for"], admitted
