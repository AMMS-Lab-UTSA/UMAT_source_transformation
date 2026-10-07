#!/usr/bin/env python3
"""Host adapters for UMAT discovery beyond GitHub: GitLab and Zenodo.

``discover_umat_sources.py`` is GitHub-only. The rules it enforces do not
depend on GitHub, so this module carries them to two other hosts instead of
restating them:

**Licence first.** The licence is decided before any source is read or
written. It must be one of ``D2_SPDX`` (decision D-2: MIT, BSD-2/3, Apache-2.0,
GPL-3.0 or later, LGPL-3.0). That list is narrower than the GitHub tool's
``REDISTRIBUTABLE_SPDX`` -- AGPL, ISC and Zlib are outside it here -- and a
licence outside it is recorded as ``licence_incompatible`` with the licence
text link, not fetched. A licence FILE must back it: GitLab's own detector is
corroborated by reading the LICENSE blob at the pinned commit, and a Zenodo
record's metadata licence is corroborated by a LICENSE file inside the
archive. Metadata alone is ``licence_metadata_only``: reported, never cached.

**Nothing moving survives.** A GitLab project is pinned to the 40-character
commit its default branch resolved to; a Zenodo record to its record id (the
version-specific DOI) and the md5 of each archive, verified after download.

**Nothing is cached before the licence is cleared**, and not before the file is
shown to be distinct: the content-hash dedup is the existing tool's
(``_hashes``, ``known_identities``, ``cache_identities``).

**Failures are recorded as themselves.**

GitLab is driven through the same five-method client interface as
``GitHubClient`` so that ``survey_repository`` is reused unchanged: the first
path segment of the "owner" is the host name (``gitlab.com``), so the project
``ns/group/proj`` is surveyed as ``gitlab.com/ns/group/proj``. Zenodo is not a
git host and has its own survey function.

    python tools/discover_hosts.py --host gitlab --out-dir <dir>
    python tools/discover_hosts.py --host zenodo --out-dir <dir> --cache-dir <dir>
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from umat_oti.corpus.acquire import (  # noqa: E402
    AcquisitionError, RateLimited, classify_license_text,
)
import discover_umat_sources as base  # noqa: E402
from discover_umat_sources import (  # noqa: E402
    COLUMNS, Discovery, Survey, _decks_near, _declares_vumat_only, _hashes,
    _has_umat_entry, _licence_class, _may_be_source, cache_identities,
    known_identities, survey_repository,
)

#: Decision D-2, verbatim. Narrower than ``REDISTRIBUTABLE_SPDX`` on purpose.
D2_SPDX = frozenset({
    "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0",
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
    "LGPL-3.0", "LGPL-3.0-only", "LGPL-3.0-or-later",
})

#: GitLab's licensee keys -> SPDX. A key not here is "unrecognised", which is
#: refused, never guessed.
GITLAB_LICENCE_KEYS = {
    "mit": "MIT", "apache-2.0": "Apache-2.0",
    "bsd-2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
    "gpl-3.0": "GPL-3.0", "gpl-3.0+": "GPL-3.0-or-later",
    "lgpl-3.0": "LGPL-3.0", "lgpl-3.0+": "LGPL-3.0-or-later",
    "agpl-3.0": "AGPL-3.0", "gpl-2.0": "GPL-2.0", "gpl-2.0+": "GPL-2.0-or-later",
    "lgpl-2.1": "LGPL-2.1", "mpl-2.0": "MPL-2.0", "unlicense": "Unlicense",
    "cc-by-4.0": "CC-BY-4.0", "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "eupl-1.2": "EUPL-1.2", "isc": "ISC", "zlib": "Zlib",
}

#: Zenodo's licence ids -> SPDX. Zenodo's "bsd-license" does not say which
#: clause count, so it maps to nothing here and is settled by the LICENSE file.
ZENODO_LICENCE_IDS = {
    "mit-license": "MIT", "mit": "MIT", "apache2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0", "bsd-3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "gpl-3.0": "GPL-3.0", "gpl-3.0-only": "GPL-3.0-only",
    "gpl-3.0-or-later": "GPL-3.0-or-later", "lgpl-3.0": "LGPL-3.0",
    "lgpl-3.0-only": "LGPL-3.0", "lgpl-3.0-or-later": "LGPL-3.0-or-later",
    "agpl-3.0": "AGPL-3.0", "gpl-2.0": "GPL-2.0", "gpl-2.0-or-later": "GPL-2.0-or-later",
    "lgpl-2.1": "LGPL-2.1", "mpl-2.0": "MPL-2.0", "isc": "ISC",
    "cc-by-4.0": "CC-BY-4.0", "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0", "cc-zero": "CC0-1.0", "eupl-1.2": "EUPL-1.2",
    "bsd-license": "BSD-unspecified",
}

_LICENCE_FILE = re.compile(
    r"(^|/)(licen[cs]e|copying|unlicense)(\.[a-z]+)?$", re.IGNORECASE)
_ARCHIVE = re.compile(r"\.(zip|tar|tar\.gz|tgz|tar\.bz2)$", re.IGNORECASE)

#: A hit worth a tree walk. GitLab project search matches substrings of any
#: name ("sumativa", "pumatycoon"), so without this nearly every result costs a
#: tree request for nothing.
GITLAB_RELEVANT = re.compile(
    r"(^|[^a-z])(umat|vumat|abaqus|abq)([^a-z]|$)|user[ -_]?material|"
    r"ddsdde|constitutive|plasticity|hyperelastic|viscoelastic",
    re.IGNORECASE)

GITLAB_QUERIES = (
    "umat", "abaqus umat", "abaqus user material", "abaqus subroutine",
    "user material subroutine", "constitutive model abaqus", "abaqus",
    "vumat", "crystal plasticity umat", "phase field abaqus",
    "hyperelastic umat", "viscoelastic umat", "abaqus fortran", "ddsdde",
)

ZENODO_QUERIES = (
    "umat", '"abaqus" "umat"', '"user material" abaqus', "abaqus subroutine",
    '"SUBROUTINE UMAT"', "DDSDDE", "abaqus fortran", "umat crystal plasticity",
    "umat damage", "umat phase-field", "umat viscoelastic", "umat hyperelastic",
    "umat concrete", '"abaqus" constitutive model implementation',
    "abaqus user-defined material", "umat.for",
    "UMAT subroutine", "Abaqus Standard user material", "material subroutine abaqus",
    "user-defined material model Abaqus Fortran", "elastoplastic UMAT",
    "crystal plasticity abaqus", "viscoplasticity UMAT", "cohesive zone UMAT",
    "concrete damage UMAT", "composite damage UMAT abaqus", "UMAT growth remodelling",
    "thermomechanical UMAT abaqus", "gradient damage abaqus UMAT",
    "phase field fracture abaqus UMAT", "hyperelastic Abaqus subroutine",
    "soil constitutive model Abaqus UMAT", "shape memory alloy UMAT",
    "polymer constitutive model UMAT", "fatigue damage UMAT",
)

#: Records of this project's own releases; they are the thing being validated.
OWN_MARKERS = ("umat_source_transformation", "residual_assembler", "umat-oti")


def _open(url: str, timeout: int) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "umat-oti-discovery"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


class _Http:
    """GET with the failure classes the survey records as themselves.

    ``opener`` is injectable so tests replay recorded responses offline.
    """

    host_label = "host"

    def __init__(self, *, timeout: int = 60,
                 opener: Callable[[str, int], tuple[bytes, dict[str, str]]] = _open):
        self.timeout = timeout
        self._opener = opener
        self.requests_made = 0

    def _get(self, url: str) -> tuple[bytes, dict[str, str]]:
        try:
            body, headers = self._opener(url, self.timeout)
            self.requests_made += 1
            return body, headers
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                reset = exc.headers.get("RateLimit-Reset") or exc.headers.get(
                    "X-RateLimit-Reset")
                raise RateLimited(int(reset) if reset and reset.isdigit() else None) from exc
            if exc.code == 404:
                raise AcquisitionError("not_found", f"{url} returned 404") from exc
            raise AcquisitionError(
                "http_error", f"{url} returned {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise AcquisitionError("network_error", f"{url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AcquisitionError("timeout", f"{url} timed out") from exc

    def _json(self, url: str) -> Any:
        body, _ = self._get(url)
        return json.loads(body.decode("utf-8"))


class GitLabClient(_Http):
    """The ``GitHubClient`` interface over the GitLab v4 REST API.

    Anonymous: GitLab exposes public projects, trees and raw blobs without a
    token (500 requests a minute per IP, reported in ``RateLimit-*`` headers).
    ``owner`` is the host name and ``repo`` the project path, so a nested group
    ``a/b/c`` is ``repo="b/c"`` with ``owner="a"`` after the host is split off
    by the caller; ``_path`` rebuilds it.
    """

    API = "https://gitlab.com/api/v4"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._pinned: dict[str, str] = {}
        self._meta: dict[str, dict] = {}

    @staticmethod
    def _path(owner: str, repo: str) -> str:
        # survey_repository names a project "<host>/<ns>/<proj>" and splits at
        # the first "/", so owner is the host and repo the whole project path.
        return urllib.parse.quote(repo, safe="")

    def search_projects(self, query: str, *, pages: int = 3,
                        pause: float = 0.3) -> list[dict]:
        found: list[dict] = []
        for page in range(1, pages + 1):
            url = (f"{self.API}/projects?simple=true&per_page=100&page={page}"
                   f"&search={urllib.parse.quote(query)}")
            hits = self._json(url)
            found.extend(hits)
            if len(hits) < 100:
                break
            time.sleep(pause)
        return found

    def group_projects(self, group: str, *, cap: int = 150) -> list[dict]:
        """Public projects of a group and its subgroups ([] for a user namespace).

        Project search matches names and descriptions only, so a lab's UMAT
        repository called ``continuum-plasticity`` is invisible to every query
        that names UMAT or Abaqus. The group of a project that did match is the
        cheapest way to find its siblings.
        """
        out: list[dict] = []
        for page in range(1, 4):
            url = (f"{self.API}/groups/{urllib.parse.quote(group, safe='')}/projects"
                   f"?include_subgroups=true&simple=true&per_page=100&page={page}")
            try:
                hits = self._json(url)
            except AcquisitionError as exc:
                if exc.code == "not_found":
                    return []
                raise
            out.extend(hits)
            if len(hits) < 100 or len(out) >= cap:
                break
        return out[:cap]

    def _project(self, owner: str, repo: str) -> dict:
        key = f"{owner}/{repo}"
        if key not in self._meta:
            self._meta[key] = self._json(
                f"{self.API}/projects/{self._path(owner, repo)}?license=true")
        return self._meta[key]

    def default_branch(self, owner: str, repo: str) -> str:
        branch = self._project(owner, repo).get("default_branch")
        if not branch:
            raise AcquisitionError("no_default_branch",
                                   f"{owner}/{repo} reports no default branch (empty project)")
        return branch

    def resolve_commit(self, owner: str, repo: str, ref: str) -> str:
        key = f"{owner}/{repo}"
        if ref == self._project(owner, repo).get("default_branch") and key in self._pinned:
            return self._pinned[key]
        sha = self._json(f"{self.API}/projects/{self._path(owner, repo)}"
                         f"/repository/commits/{urllib.parse.quote(ref, safe='')}").get("id", "")
        if len(sha) != 40:
            raise AcquisitionError("unresolved_ref",
                                   f"{owner}/{repo}@{ref} did not resolve to a 40-char commit")
        return sha

    def tree(self, owner: str, repo: str, sha: str, *, subpath: str = "",
             recursive: bool = True) -> list[dict]:
        entries: list[dict] = []
        page = 1
        while True:
            url = (f"{self.API}/projects/{self._path(owner, repo)}/repository/tree"
                   f"?ref={sha}&per_page=100&page={page}"
                   f"{'&recursive=true' if recursive else ''}")
            body, headers = self._get(url)
            entries.extend(json.loads(body.decode("utf-8")))
            nxt = headers.get("x-next-page", "")
            if not nxt:
                break
            page = int(nxt)
            if page > 200:
                raise AcquisitionError("tree_truncated",
                                       f"{owner}/{repo}@{sha[:12]} has more than 20000 entries")
        # GitHub's vocabulary: type "blob", and "sha" is the blob id.
        return [{"path": e["path"], "type": "blob" if e["type"] == "blob" else "tree",
                 "sha": e["id"]} for e in entries]

    def blob(self, owner: str, repo: str, sha: str) -> bytes:
        body, _ = self._get(
            f"{self.API}/projects/{self._path(owner, repo)}/repository/blobs/{sha}/raw")
        return body

    def license(self, owner: str, repo: str) -> tuple[Optional[str], str]:
        """SPDX id and the evidence. Pins the commit the licence is read at."""
        meta = self._project(owner, repo)
        branch = meta.get("default_branch")
        if not branch:
            return None, "empty project: no commit, so no LICENSE file"
        commit = self.resolve_commit(owner, repo, branch)
        self._pinned[f"{owner}/{repo}"] = commit
        root = self.tree(owner, repo, commit, recursive=False)
        files = [e for e in root if e["type"] == "blob" and _LICENCE_FILE.search(e["path"])]
        key = ((meta.get("license") or {}).get("key") or "").lower()
        detected = GITLAB_LICENCE_KEYS.get(key)
        for entry in files:
            text = self.blob(owner, repo, entry["sha"]).decode("utf-8", errors="replace")
            matched = classify_license_text(text)
            if matched and (detected is None or matched.split("-")[0] == detected.split("-")[0]):
                return matched, (f"{entry['path']}@{commit[:12]} read and classified "
                                 f"as {matched}; GitLab detector says {key or 'nothing'}")
            if matched and detected and matched != detected:
                return None, (f"{entry['path']}@{commit[:12]} reads as {matched} but GitLab "
                              f"says {detected}: disagreement, refused")
        if not files:
            return None, (f"no LICENSE/COPYING file at the root of {commit[:12]}; "
                          f"GitLab detector says {key or 'nothing'}")
        return None, (f"{files[0]['path']}@{commit[:12]} present but not identified "
                      f"(GitLab detector says {key or 'nothing'})")


class d2_gate:
    """Run ``survey_repository`` under D-2's licence list, not GitHub's.

    ``survey_repository`` reads the module-level ``REDISTRIBUTABLE_SPDX`` of
    ``discover_umat_sources`` (which also admits AGPL, ISC and Zlib). Rather
    than fork a 200-line function, the gate is swapped for the duration of the
    call and restored on exit, including on an exception.
    """

    def __enter__(self):
        self._saved = base.REDISTRIBUTABLE_SPDX
        base.REDISTRIBUTABLE_SPDX = D2_SPDX
        return self

    def __exit__(self, *exc):
        base.REDISTRIBUTABLE_SPDX = self._saved
        return False


def search_gitlab(client: GitLabClient, queries=GITLAB_QUERIES, *, pages: int = 3,
                  pause: float = 0.3, expand_groups: bool = True) -> tuple[list[str], list[dict]]:
    """Distinct relevant project paths, and what each query contributed."""
    names: dict[str, str] = {}
    provenance = []
    for query in queries:
        hits = client.search_projects(query, pages=pages, pause=pause)
        new = 0
        for hit in hits:
            path = hit["path_with_namespace"]
            text = f"{path} {hit.get('description') or ''}"
            if hit.get("forked_from_project") or not GITLAB_RELEVANT.search(text):
                continue
            if path not in names:
                names[path] = query
                new += 1
        provenance.append({"query": query, "hits": len(hits), "new_relevant": new})
    if expand_groups:
        groups = sorted({n.split("/")[0] for n in names})
        for group in groups:
            new = 0
            for hit in client.group_projects(group):
                path = hit["path_with_namespace"]
                if hit.get("forked_from_project") or path in names:
                    continue
                names[path] = f"group:{group}"
                new += 1
            provenance.append({"query": f"group:{group}", "hits": new, "new_relevant": new})
    return sorted(names), provenance


# --------------------------------------------------------------------------
# Zenodo
# --------------------------------------------------------------------------

class ZenodoClient(_Http):
    """Anonymous Zenodo REST client: ``/api/records`` (25 per page, 30/min)."""

    API = "https://zenodo.org/api"

    def search(self, query: str, *, pages: int = 6, pause: float = 2.3) -> list[dict]:
        out: list[dict] = []
        for page in range(1, pages + 1):
            url = (f"{self.API}/records?size=25&page={page}"
                   f"&q={urllib.parse.quote(query)}")
            hits = self._json(url)["hits"]["hits"]
            out.extend(hits)
            if len(hits) < 25:
                break
            time.sleep(pause)
        return out

    def download(self, url: str, md5: str) -> bytes:
        body, _ = self._get(url)
        if md5 and hashlib.md5(body).hexdigest() != md5:
            raise AcquisitionError("checksum_mismatch",
                                   f"{url} did not match the record's md5 {md5}")
        return body


def zenodo_licence(record: dict) -> tuple[str, str, str]:
    """(SPDX or '', raw Zenodo id, evidence) from the record metadata."""
    raw = ((record.get("metadata") or {}).get("license") or {}).get("id") or ""
    spdx = ZENODO_LICENCE_IDS.get(raw.lower(), "")
    return spdx, raw, (f"Zenodo record metadata license.id={raw!r}" if raw
                       else "Zenodo record declares no licence")


def _archive_members(name: str, data: bytes) -> dict[str, bytes]:
    """Every regular file in a zip or tar archive, in memory, never on disk."""
    members: dict[str, bytes] = {}
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if not info.is_dir() and info.file_size <= 8_000_000:
                    members[info.filename] = archive.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for info in archive:
                if info.isfile() and info.size <= 8_000_000:
                    handle = archive.extractfile(info)
                    if handle is not None:
                        members[info.name] = handle.read()
    return members


def survey_zenodo_record(client: ZenodoClient, record: dict, known: dict[str, str],
                         survey: Survey, *, cache_dir: Optional[Path] = None,
                         max_bytes: int = 300_000_000, found_by: str = "") -> None:
    rid = str(record.get("id"))
    label = f"zenodo.org/records/{rid}"
    row = Discovery(repository=label, found_by=found_by)
    if any(m in " ".join(f.get("key", "") for f in record.get("files", [])).lower()
           or m in str((record.get("metadata") or {}).get("title", "")).lower()
           for m in OWN_MARKERS):
        row.outcome = "own_repository"
        row.reason = "a release of the project being validated, not external evidence"
        survey.add(row)
        return
    spdx, raw, evidence = zenodo_licence(record)
    row.license_spdx = spdx or raw
    row.license_evidence = evidence
    row.license_class = _licence_class(spdx) if spdx in D2_SPDX else ""
    if not raw:
        row.outcome, row.reason = "licence_absent", (
            "the record declares no licence; nothing fetched")
        survey.add(row); return
    if spdx not in D2_SPDX:
        row.outcome = "licence_incompatible"
        row.reason = (f"{raw} ({spdx or 'unmapped'}) is outside D-2's list; recorded, "
                      f"not fetched; licence: {(record.get('metadata') or {}).get('license')}")
        survey.add(row); return

    archives = [f for f in record.get("files", []) if _ARCHIVE.search(f.get("key", ""))]
    loose = [f for f in record.get("files", [])
             if f.get("key", "").lower().endswith(base._FORTRAN_SUFFIXES)]
    if not archives and not loose:
        row.outcome, row.reason = "no_fortran", "no archive and no Fortran file in the record"
        survey.add(row); return

    for entry in archives + loose:
        key = entry["key"]
        md5 = (entry.get("checksum") or "").removeprefix("md5:")
        pin = f"record {rid} ({record.get('doi', '')}); {key} md5:{md5}"
        base_row = {**row.row(), "commit": pin}
        if int(entry.get("size") or 0) > max_bytes:
            survey.add(Discovery(**{**base_row, "path": key, "outcome": "not_examined",
                                    "reason": f"{entry.get('size')} bytes exceeds the {max_bytes} cap"}))
            continue
        try:
            data = client.download(entry["links"]["self"], md5)
        except RateLimited:
            raise
        except AcquisitionError as exc:
            survey.add(Discovery(**{**base_row, "path": key, "outcome": "unreadable",
                                    "reason": f"download failed: {exc}"}))
            continue
        try:
            members = (_archive_members(key, data) if _ARCHIVE.search(key) else {key: data})
        except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
            survey.add(Discovery(**{**base_row, "path": key, "outcome": "unreadable",
                                    "reason": f"archive could not be opened: {exc}"}))
            continue
        # The licence FILE, inside the pinned archive, must agree with the metadata.
        licence_files = {p: classify_license_text(b.decode("utf-8", errors="replace"))
                         for p, b in members.items() if _LICENCE_FILE.search(p)}
        file_spdx = next((v for v in licence_files.values() if v), None)
        if not file_spdx or file_spdx.split("-")[0] != spdx.split("-")[0]:
            survey.add(Discovery(**{
                **base_row, "path": key, "outcome": "licence_metadata_only",
                "reason": (f"metadata says {spdx} but the archive's licence file(s) "
                           f"{sorted(licence_files) or 'are absent'} give {file_spdx}; D-2 "
                           "needs a licence FILE; nothing cached")}))
            continue
        base_row["license_evidence"] = (f"{evidence}; archive {sorted(licence_files)[0]} "
                                        f"read as {file_spdx}")
        tree_entries = [{"path": p, "type": "blob"} for p in members]
        for path, blob in sorted(members.items()):
            if not (path.lower().endswith(base._FORTRAN_SUFFIXES) or _may_be_source(path)):
                continue
            if _LICENCE_FILE.search(path) or _is_deck(path):
                continue
            text = blob.decode("utf-8", errors="replace")
            cand = Discovery(**{**base_row, "path": f"{key}!/{path}", "bytes": len(blob)})
            if not _has_umat_entry(text):
                if path.lower().endswith(base._FORTRAN_SUFFIXES):
                    cand.outcome = "no_umat_entry"
                    cand.reason = ("declares a VUMAT and no UMAT" if _declares_vumat_only(text)
                                   else "Fortran, but it declares no SUBROUTINE UMAT")
                    survey.add(cand)
                continue
            cand.content_sha256, cand.code_only_sha256 = _hashes(text, path)
            already = known.get(cand.code_only_sha256) or known.get(cand.content_sha256)
            if already:
                cand.outcome = "already_known"
                cand.reason = f"the same implementation as {already}"
            elif cand.code_only_sha256 in {r.code_only_sha256 for r in survey.rows
                                           if r.outcome == "candidate"}:
                cand.outcome = "duplicate_within_search"
                cand.reason = "the same implementation as an earlier hit"
            else:
                cand.outcome = "candidate"
                cand.license_class = _licence_class(spdx)
                cand.reason = (f"distinct, licensed {spdx} (licence file in the archive), "
                               "declares a UMAT entry point; not yet transformed or verified")
                cand.decks = ";".join(_decks_near(tree_entries, path)[:base._DECKS_PER_SOURCE])
                if cache_dir is not None:
                    target = Path(cache_dir) / f"zenodo.org__{rid}" / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob)
                    cand.cached_as = str(target.relative_to(Path(cache_dir)))
            survey.add(cand)


def _is_deck(path: str) -> bool:
    return path.lower().endswith((".inp", ".odb", ".sim"))


def zenodo_prefilter(record: dict) -> bool:
    """Worth looking at: names Abaqus or a UMAT and carries code or an archive."""
    meta = record.get("metadata") or {}
    text = f"{meta.get('title', '')} {meta.get('description') or ''}".lower()
    names = [f.get("key", "") for f in record.get("files", [])]
    if not ("abaqus" in text or "umat" in text or any("umat" in n.lower() for n in names)):
        return False
    return any(_ARCHIVE.search(n) or n.lower().endswith(base._FORTRAN_SUFFIXES)
               for n in names)


def search_zenodo(client: ZenodoClient, queries=None) -> tuple[dict[str, dict], list[dict]]:
    """Relevant records by id, and what each query contributed or why it failed."""
    records: dict[str, dict] = {}
    provenance: list[dict] = []
    for query in (ZENODO_QUERIES if queries is None else queries):
        try:
            hits = client.search(query)
        except RateLimited:
            raise
        except AcquisitionError as exc:
            # A query the host rejects is a recorded outcome, not a crash:
            # Zenodo answered 500 to a query containing "/".
            provenance.append({"query": query, "error": str(exc)})
            continue
        new = 0
        for hit in hits:
            if str(hit["id"]) not in records and zenodo_prefilter(hit):
                records[str(hit["id"])] = {**hit, "_q": query}
                new += 1
        provenance.append({"query": query, "hits": len(hits), "new_relevant": new})
    return records, provenance


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("gitlab", "zenodo"), required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--known-cache", type=Path, action="append", default=[])
    parser.add_argument("--snapshot-root", type=Path, default=base.REPO_ROOT.parent / "Residual_Assembler" / "sources")
    parser.add_argument("--max-files-per-repository", type=int, default=80)
    args = parser.parse_args(argv)

    known = known_identities(args.snapshot_root)
    roots = list(args.known_cache) + ([args.cache_dir] if args.cache_dir else [])
    known.update({k: v for k, v in cache_identities(*roots).items() if k not in known})
    if not known:
        print("refusing to run with an empty known-set")
        return 2

    survey = Survey()
    stopped = ""
    if args.host == "gitlab":
        client = GitLabClient()
        names, provenance = search_gitlab(client)
        print(f"{len(names)} relevant projects")
        for name in names:
            try:
                with d2_gate():
                    survey_repository(client, f"gitlab.com/{name}", known, survey,
                                      max_files=args.max_files_per_repository,
                                      cache_dir=args.cache_dir, found_by="gitlab search")
            except RateLimited as exc:
                stopped = str(exc); break
    else:
        client = ZenodoClient()
        records, provenance = search_zenodo(client)
        print(f"{len(records)} relevant records")
        for rid, record in records.items():
            try:
                survey_zenodo_record(client, record, known, survey,
                                     cache_dir=args.cache_dir, found_by=record["_q"])
            except RateLimited as exc:
                stopped = str(exc); break

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / f"{args.host}_sources.csv").open("w", newline="", encoding="utf-8") as h:
        writer = csv.DictWriter(h, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(r.row() for r in survey.rows)
    outcomes: dict[str, int] = {}
    for r in survey.rows:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
    summary = {"host": args.host, "queries": provenance, "outcomes": outcomes,
               "stopped_early": stopped, "licence_gate": sorted(D2_SPDX),
               "new_candidates": [r.row() for r in survey.rows if r.outcome == "candidate"]}
    (args.out_dir / f"{args.host}_sources.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"outcomes": outcomes, "stopped_early": stopped}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
