"""Host adapters must keep discovery's three rules off GitHub too.

Licence before content, a pinned version, and a distinctness check before
anything is cached -- replayed offline against recorded-shape API responses, so
no test touches the network. The two failures that matter: fetching something
whose licence is outside D-2's list, and caching a Zenodo archive on the
strength of a metadata field alone.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import discover_hosts as H  # noqa: E402
import discover_umat_sources as base  # noqa: E402
from discover_umat_sources import Survey, _hashes, survey_repository  # noqa: E402

MIT_TEXT = """MIT License

Copyright (c) 2024 Someone

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
"""
UMAT = ("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE)\n"
        "      DDSDDE(1,1)=1.0D0\n      RETURN\n      END\n")
SHA = "a" * 40


class Replay:
    """An opener that serves canned bodies and records every URL asked for."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def __call__(self, url, timeout):
        self.asked.append(url)
        for needle, (body, headers) in self.routes.items():
            if needle in url:
                return (body if isinstance(body, bytes) else json.dumps(body).encode(),
                        headers)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def gitlab_routes(key="mit", licence_text=MIT_TEXT):
    return {
        "?license=true": ({"default_branch": "main", "license": {"key": key}}, {}),
        "/repository/commits/main": ({"id": SHA}, {}),
        "/repository/tree": ([
            {"id": "b1", "path": "LICENSE", "type": "blob"},
            {"id": "b2", "path": "src/umat.f", "type": "blob"},
            {"id": "b3", "path": "run/job.inp", "type": "blob"}], {}),
        "/blobs/b1/raw": (licence_text.encode(), {}),
        "/blobs/b2/raw": (UMAT.encode(), {}),
        "/blobs/b3/raw": (b"*HEADING\n", {}),
    }


def test_gitlab_licence_is_read_from_the_file_at_the_pinned_commit():
    client = H.GitLabClient(opener=Replay(gitlab_routes()))
    spdx, evidence = client.license("gitlab.com", "ns/proj")
    assert spdx == "MIT"
    assert SHA[:12] in evidence and "LICENSE" in evidence
    assert client.resolve_commit("gitlab.com", "ns/proj", "main") == SHA


def test_gitlab_detector_and_file_that_disagree_are_refused():
    client = H.GitLabClient(opener=Replay(gitlab_routes(key="apache-2.0")))
    spdx, evidence = client.license("gitlab.com", "ns/proj")
    assert spdx is None and "disagree" in evidence


def test_gitlab_candidate_is_pinned_and_cached_only_after_the_licence_clears(tmp_path):
    replay = Replay(gitlab_routes())
    survey = Survey()
    with H.d2_gate():
        survey_repository(H.GitLabClient(opener=replay), "gitlab.com/ns/proj", {},
                          survey, max_files=10, cache_dir=tmp_path)
    (row,) = [r for r in survey.rows if r.outcome == "candidate"]
    assert row.commit == SHA and row.path == "src/umat.f"
    assert (tmp_path / "gitlab.com__ns__proj" / "src" / "umat.f").is_file()
    assert row.decks == "run/job.inp"


def test_a_licence_outside_d2_is_recorded_and_nothing_is_fetched(tmp_path):
    agpl = "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007\n"
    replay = Replay(gitlab_routes(key="agpl-3.0", licence_text=agpl))
    survey = Survey()
    with H.d2_gate():
        survey_repository(H.GitLabClient(opener=replay), "gitlab.com/ns/proj", {},
                          survey, max_files=10, cache_dir=tmp_path)
    assert [r.outcome for r in survey.rows] == ["licence_incompatible"]
    assert not any("/blobs/b2" in u or "/blobs/b3" in u for u in replay.asked)
    assert list(tmp_path.iterdir()) == []


def test_d2_gate_is_narrower_than_the_github_gate_and_is_restored():
    before = base.REDISTRIBUTABLE_SPDX
    assert "AGPL-3.0" in before and "AGPL-3.0" not in H.D2_SPDX
    with H.d2_gate():
        assert base.REDISTRIBUTABLE_SPDX is H.D2_SPDX
    assert base.REDISTRIBUTABLE_SPDX is before


def test_an_already_known_gitlab_file_is_not_a_new_one():
    content, code_only = _hashes(UMAT, "umat.f")
    survey = Survey()
    with H.d2_gate():
        survey_repository(H.GitLabClient(opener=Replay(gitlab_routes())),
                          "gitlab.com/ns/proj", {code_only: "corpus/x"}, survey,
                          max_files=10)
    assert [r.outcome for r in survey.rows] == ["already_known"]


# ---------------------------------------------------------------- Zenodo

def make_zip(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def zenodo_record(licence, data, name="proj-v1.zip", md5=None):
    return {"id": 99, "doi": "10.5281/zenodo.99",
            "metadata": {"title": "An Abaqus UMAT", "license": {"id": licence}},
            "files": [{"key": name, "size": len(data),
                       "checksum": "md5:" + (md5 or hashlib.md5(data).hexdigest()),
                       "links": {"self": "https://zenodo.org/files/proj"}}]}


def zenodo_client(data):
    return H.ZenodoClient(opener=Replay({"/files/proj": (data, {})}))


def test_zenodo_candidate_needs_a_licence_file_in_the_archive_and_is_pinned(tmp_path):
    data = make_zip({"p/LICENSE": MIT_TEXT, "p/umat.for": UMAT, "p/a.inp": "*HEADING"})
    survey = Survey()
    H.survey_zenodo_record(zenodo_client(data), zenodo_record("mit-license", data), {},
                           survey, cache_dir=tmp_path)
    (row,) = [r for r in survey.rows if r.outcome == "candidate"]
    assert "md5:" in row.commit and "record 99" in row.commit
    assert row.path == "proj-v1.zip!/p/umat.for" and row.decks == "p/a.inp"
    assert (tmp_path / "zenodo.org__99" / "p" / "umat.for").is_file()


def test_zenodo_metadata_licence_alone_is_not_enough_to_cache(tmp_path):
    data = make_zip({"p/umat.for": UMAT})
    survey = Survey()
    H.survey_zenodo_record(zenodo_client(data), zenodo_record("mit-license", data), {},
                           survey, cache_dir=tmp_path)
    assert [r.outcome for r in survey.rows] == ["licence_metadata_only"]
    assert list(tmp_path.iterdir()) == []


def test_zenodo_cc_by_is_recorded_and_the_archive_is_never_downloaded():
    data = make_zip({"p/umat.for": UMAT})
    client = zenodo_client(data)
    survey = Survey()
    H.survey_zenodo_record(client, zenodo_record("cc-by-4.0", data), {}, survey)
    assert [r.outcome for r in survey.rows] == ["licence_incompatible"]
    assert client._opener.asked == []


def test_zenodo_checksum_mismatch_is_unreadable_not_trusted(tmp_path):
    data = make_zip({"p/LICENSE": MIT_TEXT, "p/umat.for": UMAT})
    survey = Survey()
    H.survey_zenodo_record(zenodo_client(data),
                           zenodo_record("mit-license", data, md5="0" * 32), {},
                           survey, cache_dir=tmp_path)
    assert [r.outcome for r in survey.rows] == ["unreadable"]
    assert list(tmp_path.iterdir()) == []


def test_zenodo_duplicate_of_a_known_source_is_reported_as_known(tmp_path):
    data = make_zip({"p/LICENSE": MIT_TEXT, "p/umat.for": UMAT})
    _, code_only = _hashes(UMAT, "umat.for")
    survey = Survey()
    H.survey_zenodo_record(zenodo_client(data), zenodo_record("mit-license", data),
                           {code_only: "corpus/x"}, survey, cache_dir=tmp_path)
    assert [r.outcome for r in survey.rows] == ["already_known"]
    assert list(tmp_path.iterdir()) == []


def test_zenodo_prefilter_wants_abaqus_text_and_code():
    data = b"x"
    assert H.zenodo_prefilter(zenodo_record("mit-license", data))
    other = zenodo_record("mit-license", data)
    other["metadata"]["title"] = "A web app"
    assert not H.zenodo_prefilter(other)


def test_a_query_the_host_rejects_is_recorded_not_fatal():
    """Zenodo returned 500 for one query; the others must still run."""
    calls = []

    class Flaky(H.ZenodoClient):
        def search(self, query, **kw):
            calls.append(query)
            if "bad" in query:
                raise H.AcquisitionError("http_error", "500")
            return []

    records, provenance = H.search_zenodo(Flaky(), ("bad/query", "good"))
    assert calls == ["bad/query", "good"] and records == {}
    assert "error" in provenance[0] and provenance[1]["query"] == "good"
