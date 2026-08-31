"""Live acquisition of external UMAT sources, pinned to immutable commits.

The offline round replays snapshots. This is the half that produces them: query
a repository, resolve whatever moving ref it advertises to a 40-character commit
SHA, read its licence, enumerate its Fortran, and cache only what the licence
permits redistributing.

Three rules shape the design.

**Nothing moving survives.** A manifest that records ``main`` describes a
repository as it was on the day someone looked. Every accepted source is pinned
to a commit and the resolved SHA is what gets written.

**Nothing runs before it is cleared.** Downloading is separated from executing.
A source is fetched, hashed, licence-classified and dependency-checked before
any compiler sees it, and a source whose licence does not permit redistribution
is recorded as metadata and never cached.

**Failures are recorded, not smoothed.** Rate limiting, a missing licence and a
network error are three different outcomes and each is reported as itself.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

__all__ = [
    "GitHubClient",
    "AcquisitionError",
    "RateLimited",
    "RepositorySnapshot",
    "acquire_repository",
    "REDISTRIBUTABLE_SPDX",
]

API = "https://api.github.com"
FORTRAN_SUFFIXES = (".for", ".f", ".f90", ".f77")

#: Licences under which we are willing to cache a copy of someone's source.
REDISTRIBUTABLE_SPDX = frozenset({
    "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "Zlib",
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
    "LGPL-3.0", "LGPL-3.0-only", "AGPL-3.0", "AGPL-3.0-only",
})


#: Distinctive phrases that identify a licence when GitHub's detector does not.
#: Its detector matches canonical texts, so a LICENSE.md that puts the name in a
#: markdown heading comes back as NOASSERTION -- which is how two genuinely
#: BSD-3-Clause repositories were nearly recorded as unlicensed. A phrase match
#: is weaker evidence than the API's and is always recorded as such.
_LICENSE_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AGPL-3.0", ("gnu affero general public license",)),
    ("GPL-3.0", ("gnu general public license", "version 3")),
    ("LGPL-3.0", ("gnu lesser general public license",)),
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("BSD-3-Clause", ("redistribution and use in source and binary forms",
                      "neither the name")),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
)


def classify_license_text(text: str) -> Optional[str]:
    """SPDX identifier implied by a licence file's wording, or None."""
    lowered = " ".join(text.lower().split())
    for spdx, phrases in _LICENSE_PHRASES:
        if all(phrase in lowered for phrase in phrases):
            return spdx
    return None


class AcquisitionError(RuntimeError):
    """Acquisition failed for a reason worth recording verbatim."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class RateLimited(AcquisitionError):
    """The API refused because the quota is exhausted."""

    def __init__(self, reset_epoch: Optional[int]):
        self.reset_epoch = reset_epoch
        when = ("unknown" if not reset_epoch else
                datetime.fromtimestamp(reset_epoch, timezone.utc).isoformat())
        super().__init__(
            "github_rate_limited",
            f"the GitHub API quota is exhausted; it resets at {when}. "
            "Authenticate to raise the limit from 60 to 5000 requests an hour: "
            "set GH_TOKEN, or run 'gh auth login' so 'gh auth token' works.")


#: Places gh is installed that a login shell may not have on PATH. A
#: per-user install under ~/.local/bin is the default for the tarball and for
#: several package managers, and it is exactly the case that looks like an
#: absent tool: `command -v gh` finds nothing, this function falls back to
#: unauthenticated, and GitHub's code-search endpoint answers 401 rather than
#: rate-limiting -- so the failure reads as "search is unavailable" instead of
#: "you are not logged in".
_GH_FALLBACK_PATHS = (
    "~/.local/bin/gh",
    "/usr/local/bin/gh",
    "/opt/homebrew/bin/gh",
    "/snap/bin/gh",
)


def _gh_executable() -> Optional[str]:
    """The gh binary, whether or not the caller's PATH mentions it."""
    found = shutil.which("gh")
    if found:
        return found
    for candidate in _GH_FALLBACK_PATHS:
        expanded = Path(candidate).expanduser()
        if expanded.is_file() and os.access(expanded, os.X_OK):
            return str(expanded)
    return None


def _discover_token() -> tuple[Optional[str], str]:
    """A token from the environment, or from the gh CLI, or none."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value, f"environment variable {name}"
    executable = _gh_executable()
    if executable:
        try:
            proc = subprocess.run([executable, "auth", "token"],
                                  capture_output=True, text=True, timeout=15)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip(), f"gh auth token ({executable})"
        except (OSError, subprocess.SubprocessError):
            pass
        return None, (f"{executable} is installed but not logged in "
                      "(run: gh auth login)")
    return None, ("unauthenticated (60 requests an hour); no gh on PATH or in "
                  + ", ".join(_GH_FALLBACK_PATHS))


@dataclass
class GitHubClient:
    """Minimal REST client that reports why it failed."""

    token: Optional[str] = None
    auth_source: str = "unauthenticated"
    timeout: int = 30
    requests_made: int = 0
    rate_limit_remaining: Optional[int] = None

    @classmethod
    def discover(cls, *, timeout: int = 30) -> "GitHubClient":
        token, source = _discover_token()
        return cls(token=token, auth_source=source, timeout=timeout)

    def _get(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "umat-oti-corpus",
            **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.requests_made += 1
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None:
                    self.rate_limit_remaining = int(remaining)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                reset = exc.headers.get("X-RateLimit-Reset")
                if exc.headers.get("X-RateLimit-Remaining") == "0":
                    raise RateLimited(int(reset) if reset else None) from exc
            if exc.code == 404:
                raise AcquisitionError("not_found", f"{url} returned 404") from exc
            raise AcquisitionError(
                "http_error", f"{url} returned {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise AcquisitionError("network_error", f"{url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AcquisitionError(
                "timeout", f"{url} did not respond within {self.timeout}s") from exc

    def default_branch(self, owner: str, repo: str) -> str:
        """Ask the repository, rather than guessing between main and master.

        Guessing costs a request and a confusing error: jgomezc1/ABAQUS-US still
        uses master, and asking for main returns 422 Unprocessable Entity, which
        reads like a malformed request rather than a wrong branch name.
        """
        payload = self._get(f"{API}/repos/{owner}/{repo}")
        branch = payload.get("default_branch")
        if not branch:
            raise AcquisitionError(
                "no_default_branch",
                f"{owner}/{repo} does not report a default branch")
        return branch

    def resolve_commit(self, owner: str, repo: str, ref: str) -> str:
        """Turn any ref -- branch, tag, short SHA -- into a 40-character commit."""
        payload = self._get(f"{API}/repos/{owner}/{repo}/commits/{ref}")
        sha = payload.get("sha", "")
        if len(sha) != 40:
            raise AcquisitionError(
                "unresolved_ref",
                f"{owner}/{repo}@{ref} did not resolve to a full commit SHA")
        return sha

    def license(self, owner: str, repo: str) -> tuple[Optional[str], str]:
        """(SPDX id, where it was read from). ``None`` when none is declared."""
        try:
            payload = self._get(f"{API}/repos/{owner}/{repo}/license")
        except AcquisitionError as exc:
            if exc.code == "not_found":
                return None, "no LICENSE file detected by the GitHub API"
            raise
        spdx = ((payload.get("license") or {}).get("spdx_id") or "").strip()
        path = payload.get("path", "LICENSE")
        if spdx and spdx != "NOASSERTION":
            return spdx, f"{path} (SPDX {spdx} via the GitHub licence API)"
        # Fall back to reading the file. GitHub's detector wants canonical text,
        # so a LICENSE.md with the name in a heading defeats it even though the
        # licence is unambiguous to a reader.
        content = payload.get("content")
        if content and payload.get("encoding") == "base64":
            try:
                text = base64.b64decode(content).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                text = ""
            matched = classify_license_text(text)
            if matched:
                return matched, (f"{path} (SPDX {matched} inferred from the "
                                 "licence text; GitHub's API reported no "
                                 "identifier for this file)")
        return None, (f"{path} present but neither GitHub nor a text match "
                      "identified a licence" if path else
                      "no LICENSE file detected by the GitHub API")

    def tree(self, owner: str, repo: str, sha: str) -> list[dict]:
        payload = self._get(
            f"{API}/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
        if payload.get("truncated"):
            raise AcquisitionError(
                "tree_truncated",
                f"the tree listing for {owner}/{repo}@{sha[:12]} was truncated by "
                "the API; a full clone would be needed to enumerate it")
        return payload.get("tree", [])

    def blob(self, owner: str, repo: str, sha: str) -> bytes:
        payload = self._get(f"{API}/repos/{owner}/{repo}/git/blobs/{sha}")
        if payload.get("encoding") != "base64":
            raise AcquisitionError(
                "unexpected_encoding",
                f"blob {sha[:12]} came back as {payload.get('encoding')!r}")
        return base64.b64decode(payload["content"])


@dataclass
class RepositorySnapshot:
    owner: str
    repo: str
    requested_ref: str
    commit_sha: Optional[str] = None
    license_spdx: Optional[str] = None
    license_source: str = ""
    redistribution_permitted: bool = False
    retrieved_at: str = ""
    fortran_files: list[dict] = field(default_factory=list)
    umat_entries: list[str] = field(default_factory=list)
    cached_paths: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"

    def as_dict(self) -> dict:
        return {
            "id": f"{self.owner}_{self.repo}",
            "url": self.url,
            "requested_ref": self.requested_ref,
            "commit_sha": self.commit_sha,
            "license_spdx": self.license_spdx,
            "license_source": self.license_source,
            "redistribution_permitted": self.redistribution_permitted,
            "retrieved_at": self.retrieved_at,
            "fortran_file_count": len(self.fortran_files),
            "umat_entry_files": sorted(self.umat_entries),
            "cached_paths": sorted(self.cached_paths),
            "failures": self.failures,
        }


def acquire_repository(client: GitHubClient, owner: str, repo: str, *,
                       ref: str = "HEAD", cache_root: Optional[Path] = None,
                       max_files: int = 400) -> RepositorySnapshot:
    """Resolve, classify, enumerate and (if permitted) cache one repository.

    Caching is gated on the licence, and nothing acquired here is executed:
    that happens later, from the cache, through the offline funnel.
    """
    snapshot = RepositorySnapshot(owner=owner, repo=repo, requested_ref=ref,
                                  retrieved_at=datetime.now(timezone.utc).isoformat())
    try:
        if ref in ("HEAD", "", None):
            ref = client.default_branch(owner, repo)
            snapshot.requested_ref = ref
        snapshot.commit_sha = client.resolve_commit(owner, repo, ref)
    except AcquisitionError as exc:
        snapshot.failures.append({"stage": "resolve_commit", "code": exc.code,
                                  "detail": exc.detail})
        return snapshot

    try:
        spdx, source = client.license(owner, repo)
    except AcquisitionError as exc:
        snapshot.failures.append({"stage": "license", "code": exc.code,
                                  "detail": exc.detail})
        return snapshot
    snapshot.license_spdx = spdx
    snapshot.license_source = source
    snapshot.redistribution_permitted = bool(spdx and spdx in REDISTRIBUTABLE_SPDX)

    try:
        entries = client.tree(owner, repo, snapshot.commit_sha)
    except AcquisitionError as exc:
        snapshot.failures.append({"stage": "enumerate", "code": exc.code,
                                  "detail": exc.detail})
        return snapshot

    fortran = [e for e in entries
               if e.get("type") == "blob"
               and e.get("path", "").lower().endswith(FORTRAN_SUFFIXES)]
    snapshot.fortran_files = [
        {"path": e["path"], "blob_sha": e["sha"], "size": e.get("size")}
        for e in fortran[:max_files]]
    if len(fortran) > max_files:
        snapshot.failures.append({
            "stage": "enumerate", "code": "file_cap",
            "detail": f"{len(fortran)} Fortran files found; only the first "
                      f"{max_files} were considered"})

    if not snapshot.redistribution_permitted:
        snapshot.failures.append({
            "stage": "cache", "code": "license_forbids_redistribution",
            "detail": (f"licence {spdx or 'NOASSERTION'} does not permit "
                       "redistribution, so nothing was cached; the repository is "
                       "recorded as metadata only")})
        return snapshot

    if cache_root is None:
        return snapshot
    destination = Path(cache_root) / f"{owner}_{repo}" / snapshot.commit_sha[:12]
    for entry in snapshot.fortran_files:
        try:
            content = client.blob(owner, repo, entry["blob_sha"])
        except AcquisitionError as exc:
            snapshot.failures.append({"stage": "download", "path": entry["path"],
                                      "code": exc.code, "detail": exc.detail})
            continue
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        snapshot.cached_paths.append(entry["path"])
        if b"SUBROUTINE UMAT" in content.upper().replace(b"\t", b" "):
            snapshot.umat_entries.append(entry["path"])
    return snapshot
