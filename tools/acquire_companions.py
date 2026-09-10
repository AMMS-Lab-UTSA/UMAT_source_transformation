#!/usr/bin/env python3
"""Fetch what the corpus's UMATs need beside them, and record where it came from.

The first acquisition took the Fortran that looked like a UMAT and the ``.inp``
decks near it. That is not everything a UMAT needs. ``adtzlr__ttb`` opens with
``include 'ttb/ttb_library.f'``; ``KnutAM__MaterialModels`` opens with
``use SolveMatrixEquation``; neither companion is a UMAT and neither was
acquired, so both sources reached Abaqus as a compile that aborted before the
analysis started -- which the ladder recorded as the ORIGINAL failing to run.

Nor is a ``.inp`` deck the only place an author publishes material constants.
Some publish them in a README, some in a parameter table, some in the script
that builds the model. A corpus that looked only at decks and then reported
``needs_material_data`` was reporting where it looked, not what exists.

So this makes a second pass over the same repositories, at a pinned commit, and
fetches two things:

* **companions** -- the files that satisfy a cached source's unresolved ``USE``
  and ``INCLUDE``. Resolved by what a file DECLARES, never by its name.
* **material-data candidates** -- decks not already cached, and the documents,
  tables and scripts that carry an Abaqus material keyword. Fetched so that a
  later pass can read constants from them; nothing here reads or accepts one.

Nothing acquired here is executed, and nothing is committed: the cache lives
outside the tree, as it did before. What is committed is this run's manifest --
repository, commit, path, blob digest, size and licence for every file, so any
constant later attributed to one of them can be traced to a published file.

    tools/acquire_companions.py --allow-network
    tools/acquire_companions.py --allow-network --only KnutAM --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.abaqus.companions import (needs, repository_files,  # noqa: E402
                                        resolve)
from umat_oti.corpus.acquire import (AcquisitionError, GitHubClient,  # noqa: E402
                                     RateLimited)

import urllib.error                                                  # noqa: E402
import urllib.parse                                                  # noqa: E402
import urllib.request                                                # noqa: E402


def raw_blob(owner: str, name: str, commit: str, path: str, *,
             timeout: int = 60) -> Optional[bytes]:
    """One file's bytes from raw.githubusercontent, which is not API-metered.

    The blob API costs one of the hour's 5000 requests per file, and this pass
    wants tens of thousands of them. Raw serves the same bytes at a pinned
    commit and does not spend the budget. ``None`` means it could not be
    fetched, and the caller falls back to the API rather than treating a
    transport failure as a file that does not exist.
    """
    quoted = urllib.parse.quote(path)
    url = (f"https://raw.githubusercontent.com/{owner}/{name}/{commit}/{quoted}")
    request = urllib.request.Request(url, headers={
        "User-Agent": "umat-oti-corpus",
        **({"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}
           if os.environ.get("GH_TOKEN") else {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO_ROOT.parent / "discovery_cache")
DEFAULT_MANIFEST = REPO_ROOT / "paper_results" / "corpus" / "companions.json"

#: Suffixes that can be compiled with, or included by, a UMAT.
COMPANION_SUFFIXES = (".f", ".for", ".f90", ".f95", ".f03", ".f08", ".ftn",
                      ".inc", ".h", ".hdr", ".fi", ".f77")

#: Suffixes that can carry material constants an author published. A deck is
#: first because it is the only one that carries them in a form a parser reads
#: without interpretation; the rest are fetched so a reader can be shown where
#: to look and so an absence can be stated as an absence rather than as "not
#: searched".
MATERIAL_SUFFIXES = (".inp", ".md", ".txt", ".rst", ".dat", ".csv", ".py",
                     ".m", ".json", ".yaml", ".yml", ".cae", ".pes")

#: Nothing above this is fetched. A mesh in an .inp can run to tens of
#: megabytes and carries no constants that the first hundred kilobytes do not.
MAX_BYTES = 4_000_000

#: Per repository, so one enormous repository cannot spend the whole budget.
MAX_FILES_PER_REPOSITORY = 250

#: Why a file was wanted, most important first. Fetching in this order means a
#: per-repository budget spent on a documentation tree cannot starve the
#: include a source will not compile without.
PRIORITY = ("satisfies an unresolved INCLUDE",
            "may define an unresolved module",
            "may publish material constants")


@dataclass
class RepositoryResult:
    repository: str
    commit: str = ""
    license_spdx: Optional[str] = None
    license_source: str = ""
    tree_files: int = 0
    wanted_modules: list = field(default_factory=list)
    wanted_includes: list = field(default_factory=list)
    fetched: list = field(default_factory=list)
    still_missing: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict:
        return {"repository": self.repository, "commit": self.commit,
                "license_spdx": self.license_spdx,
                "license_source": self.license_source,
                "tree_files": self.tree_files,
                "wanted_modules": sorted(self.wanted_modules),
                "wanted_includes": sorted(self.wanted_includes),
                "fetched": self.fetched, "still_missing": self.still_missing,
                "skipped": self.skipped[:20], "error": self.error}


def repositories_in(cache_root: Path) -> list[str]:
    """Every repository directory the cache holds, as ``owner__repo``."""
    return sorted(path.name for path in Path(cache_root).iterdir()
                  if path.is_dir())


def cached_sources(cache_root: Path, repository: str) -> list[Path]:
    root = Path(cache_root) / repository
    return sorted(path for path in root.rglob("*")
                  if path.is_file()
                  and path.suffix.lower() in COMPANION_SUFFIXES)


def unresolved(cache_root: Path, repository: str) -> tuple[set, set]:
    """What the repository's cached sources ask for and do not have."""
    modules: set = set()
    includes: set = set()
    for source in cached_sources(cache_root, repository):
        found = resolve(source, repository_files(source, cache_root))
        modules.update(found.missing_modules)
        includes.update(found.missing_includes)
    return modules, includes


def wanted_paths(tree: list, modules: set, includes: set) -> dict:
    """Which blobs in the tree to fetch, and why each one.

    A module's provider cannot be known without reading the file, so every
    Fortran file in the tree that is not already cached is a candidate when any
    module is missing -- bounded by size and by count. An include is matched on
    basename, which is what the compiler matches on.
    """
    wanted: dict = {}
    include_names = {Path(name).name.lower() for name in includes}
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        size = int(entry.get("size") or 0)
        if size > MAX_BYTES:
            continue
        suffix = Path(path).suffix.lower()
        why = ""
        if suffix in COMPANION_SUFFIXES:
            if Path(path).name.lower() in include_names:
                why = "satisfies an unresolved INCLUDE"
            elif modules:
                why = "may define an unresolved module"
        elif suffix in MATERIAL_SUFFIXES:
            why = "may publish material constants"
        if why:
            wanted[path] = {"sha": entry.get("sha", ""), "size": size,
                            "why": why}
    return wanted


def already_cached(cache_root: Path, repository: str, path: str) -> bool:
    return (Path(cache_root) / repository / path).is_file()


def run(client: GitHubClient, cache_root: Path, repository: str, *,
        dry_run: bool = False, budget: int = MAX_FILES_PER_REPOSITORY,
        pause: float = 0.0) -> RepositoryResult:
    result = RepositoryResult(repository=repository)
    owner, _, name = repository.partition("__")
    if not owner or not name:
        result.error = (f"{repository} is not an owner__repo directory, so the "
                        f"repository it came from cannot be named")
        return result
    modules, includes = unresolved(cache_root, repository)
    result.wanted_modules = sorted(modules)
    result.wanted_includes = sorted(includes)
    try:
        branch = client.default_branch(owner, name)
        result.commit = client.resolve_commit(owner, name, branch)
        result.license_spdx, result.license_source = client.license(owner, name)
        tree = client.tree(owner, name, result.commit)
    except RateLimited:
        raise
    except AcquisitionError as exc:
        result.error = f"{exc.code}: {exc.detail}"
        return result
    result.tree_files = sum(1 for e in tree if e.get("type") == "blob")

    candidates = wanted_paths(tree, modules, includes)
    order = sorted(candidates,
                   key=lambda p: (PRIORITY.index(candidates[p]["why"])
                                  if candidates[p]["why"] in PRIORITY else 9, p))
    for path in order:
        if already_cached(cache_root, repository, path):
            continue
        if len(result.fetched) >= budget:
            result.skipped.append({"path": path, "why": "per-repository budget"})
            continue
        entry = candidates[path]
        if dry_run:
            result.fetched.append({"path": path, "size": entry["size"],
                                   "why": entry["why"], "sha256": "",
                                   "written": False})
            continue
        payload = raw_blob(owner, name, result.commit, path)
        if payload is None:
            try:
                payload = client.blob(owner, name, entry["sha"])
            except RateLimited:
                raise
            except AcquisitionError as exc:
                result.skipped.append(
                    {"path": path, "why": f"{exc.code}: {exc.detail}"})
                continue
        target = Path(cache_root) / repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        result.fetched.append({
            "path": path, "size": len(payload), "why": entry["why"],
            "sha256": hashlib.sha256(payload).hexdigest(), "written": True,
            "url": (f"https://github.com/{owner}/{name}/blob/"
                    f"{result.commit}/{path}")})
        if pause:
            time.sleep(pause)

    if not dry_run:
        after_modules, after_includes = unresolved(cache_root, repository)
        result.still_missing = sorted(
            [f"module {n}" for n in after_modules]
            + [f"include {n}" for n in after_includes])
    return result


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-network", action="store_true",
                        help="required; without it nothing is fetched")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--only", default="",
                        help="substring of the repository directory name")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget", type=int, default=MAX_FILES_PER_REPOSITORY)
    parser.add_argument("--pause", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be fetched and write nothing")
    args = parser.parse_args(argv)

    if not args.allow_network and not args.dry_run:
        print("this reaches the public internet and needs --allow-network. "
              "Nothing was fetched.")
        return 2

    client = GitHubClient.discover()
    print(f"  auth: {client.auth_source}")
    repositories = [name for name in repositories_in(args.cache_dir)
                    if args.only.lower() in name.lower()]
    if args.limit:
        repositories = repositories[:args.limit]
    print(f"  {len(repositories)} repositories in {args.cache_dir}")

    results = []
    for index, repository in enumerate(repositories, start=1):
        try:
            result = run(client, args.cache_dir, repository,
                         dry_run=args.dry_run or not args.allow_network,
                         budget=args.budget, pause=args.pause)
        except RateLimited as limited:
            print(f"  rate limited after {index - 1} repositories; "
                  f"resets at {limited}")
            break
        results.append(result)
        note = (f"{len(result.fetched)} fetched"
                if not result.error else f"ERROR {result.error[:70]}")
        print(f"[{index}/{len(repositories)}] {repository}: {note}"
              + (f"; still missing {len(result.still_missing)}"
                 if result.still_missing else ""))

    manifest = {
        "what_this_is": (
            "a second acquisition pass over the same repositories, for the "
            "files a UMAT needs beside it and the files an author may have "
            "published material constants in. Every row names the repository, "
            "the commit it was read at, the path, and the digest of the bytes."),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # How the token was found, not where the binary lives: the manifest
        # is committed evidence and may not name a home directory.
        "auth": client.auth_source.split(" (")[0],
        "requests_made": client.requests_made,
        "cache_root_name": Path(args.cache_dir).name,
        "repositories": [r.as_dict() for r in results],
        "counts": dict(Counter(
            ["error" if r.error else "ok" for r in results])),
        "files_fetched": sum(len(r.fetched) for r in results),
        "still_missing": sum(len(r.still_missing) for r in results),
    }
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=1) + "\n",
                                   encoding="utf-8")
    print(f"  fetched {manifest['files_fetched']} files; "
          f"{manifest['still_missing']} needs remain unresolved")
    print(f"  wrote {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
