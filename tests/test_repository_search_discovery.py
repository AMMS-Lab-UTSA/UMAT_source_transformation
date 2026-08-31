"""Finding a repository by its name when its UMAT is buried in the content index.

GitHub's code search caps any one query at a thousand results however many
hits it reports, so a repository whose UMAT sits below a thousand
better-matching files cannot be reached by adding pages. The same repository
is often findable by name, description or topic -- a different index entirely.

Nothing about the gate changes: how a repository was found says nothing about
whether it may be used, so licence, commit pinning and UMAT-entry detection
all still apply.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from discover_umat_sources import (  # noqa: E402
    DEFAULT_QUERY, search_repositories_by_topic,
)


class _FakeClient:
    """Answers the two pages a test needs and records what was asked."""

    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def _get(self, url):
        self.urls.append(url)
        index = len(self.urls) - 1
        return self.pages[index] if index < len(self.pages) else {"items": []}


def test_names_are_collected_in_order():
    client = _FakeClient([{ "total_count": 2,
                            "items": [{"full_name": "a/one"}, {"full_name": "b/two"}]}])
    names, total, read = search_repositories_by_topic(
        client, query="abaqus umat", pages=1, per_page=100)
    assert names == ["a/one", "b/two"]
    assert total == 2
    assert read == 1


def test_it_stops_on_a_short_page_rather_than_asking_again():
    """A page shorter than per_page is the last one."""
    client = _FakeClient([{"total_count": 1, "items": [{"full_name": "a/one"}]}])
    names, _total, read = search_repositories_by_topic(
        client, query="q", pages=5, per_page=100)
    assert names == ["a/one"]
    assert read == 1
    assert len(client.urls) == 1


def test_an_empty_page_ends_the_walk():
    client = _FakeClient([{"total_count": 0, "items": []}])
    names, _total, read = search_repositories_by_topic(client, query="q", pages=3)
    assert names == []
    assert read == 0


def test_a_repeated_name_across_pages_is_listed_once():
    client = _FakeClient([
        {"total_count": 2, "items": [{"full_name": "a/one"}] * 100},
        {"total_count": 2, "items": [{"full_name": "a/one"}, {"full_name": "b/two"}]},
    ])
    names, _total, _read = search_repositories_by_topic(
        client, query="q", pages=2, per_page=100, pause=0.0)
    assert names == ["a/one", "b/two"]


def test_it_queries_the_repository_index_not_the_code_index():
    """The whole point: a different index, reaching different work."""
    client = _FakeClient([{"total_count": 0, "items": []}])
    search_repositories_by_topic(client, query="topic:abaqus", pages=1)
    assert "search/repositories" in client.urls[0]
    assert "search/code" not in client.urls[0]


def test_the_query_is_url_encoded():
    client = _FakeClient([{"total_count": 0, "items": []}])
    search_repositories_by_topic(client, query="abaqus umat", pages=1)
    assert "abaqus%20umat" in client.urls[0] or "abaqus+umat" in client.urls[0]


def test_a_rate_limit_ends_the_walk_without_losing_what_was_read():
    from discover_umat_sources import RateLimited

    class Limited(_FakeClient):
        def _get(self, url):
            self.urls.append(url)
            if len(self.urls) == 1:
                return {"total_count": 9, "items": [{"full_name": "a/one"}] * 100}
            raise RateLimited(None)

    client = Limited([])
    names, total, read = search_repositories_by_topic(
        client, query="q", pages=4, per_page=100, pause=0.0)
    assert names == ["a/one"]
    assert read == 1
    assert total == 9, "what the first page reported is still worth recording"


def test_the_code_search_default_is_unchanged():
    assert DEFAULT_QUERY == '"SUBROUTINE UMAT" language:Fortran'


class TestMainCombinesTheTwoSearches:
    """The manifest has to say which questions were asked and what each returned."""

    @pytest.fixture
    def stubbed(self, monkeypatch, tmp_path):
        import discover_umat_sources as d

        monkeypatch.setattr(d.GitHubClient, "discover",
                            classmethod(lambda cls, **kw: cls(token="x", auth_source="stub")))
        monkeypatch.setattr(d, "known_identities", lambda root: {"deadbeef": "known"})
        monkeypatch.setattr(d, "survey_repository",
                            lambda *a, **k: None)
        calls = {"code": [], "repo": []}

        def code(client, *, pages, per_page=100, query=d.DEFAULT_QUERY, pause=2.0):
            calls["code"].append(query)
            return (["c/one"], 2576, 1, {})

        def repo(client, *, query, pages, per_page=100, pause=2.0):
            calls["repo"].append(query)
            return (["r/two"], 40, 1)

        monkeypatch.setattr(d, "search_repositories", code)
        monkeypatch.setattr(d, "search_repositories_by_topic", repo)
        return d, calls, tmp_path

    def _run(self, d, tmp_path, *extra):
        return d.main(["--out-dir", str(tmp_path / "out"),
                       "--snapshot-root", str(tmp_path / "snap"), *extra])

    def _manifest(self, tmp_path):
        import json
        return json.loads((tmp_path / "out" / "discovered_sources.json").read_text())

    def test_no_query_at_all_still_asks_the_default_code_question(self, stubbed):
        d, calls, tmp_path = stubbed
        self._run(d, tmp_path)
        assert calls["code"] == [d.DEFAULT_QUERY]
        assert calls["repo"] == []

    def test_a_repository_question_alone_does_not_add_the_default_code_one(self, stubbed):
        d, calls, tmp_path = stubbed
        self._run(d, tmp_path, "--repo-query", "topic:umat")
        assert calls["code"] == [], (
            "asking a repository question should not survey the default code "
            "search as well and report its hits in the same totals")
        assert calls["repo"] == ["topic:umat"]

    def test_both_kinds_run_when_both_are_given(self, stubbed):
        d, calls, tmp_path = stubbed
        self._run(d, tmp_path, "--query", "X", "--repo-query", "topic:umat")
        assert calls["code"] == ["X"]
        assert calls["repo"] == ["topic:umat"]

    def test_the_two_totals_are_recorded_apart(self, stubbed):
        """One counts files, the other repositories; their sum is not a quantity."""
        d, _calls, tmp_path = stubbed
        self._run(d, tmp_path, "--query", "X", "--repo-query", "topic:umat")
        manifest = self._manifest(tmp_path)
        assert manifest["search_total_reported_by_github"] == 2576
        assert manifest["repositories_reported_by_repository_search"] == 40

    def test_the_manifest_names_every_question_asked(self, stubbed):
        d, _calls, tmp_path = stubbed
        self._run(d, tmp_path, "--query", "A", "--query", "B",
                  "--repo-query", "topic:umat")
        manifest = self._manifest(tmp_path)
        assert manifest["queries"] == ["A", "B"]
        assert manifest["repository_queries"] == ["topic:umat"]
