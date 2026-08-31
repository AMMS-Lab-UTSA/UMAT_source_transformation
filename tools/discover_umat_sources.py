#!/usr/bin/env python3
"""Search for externally authored UMAT sources and report what may be used.

The corpus round replays a pinned snapshot; ``umat_oti.corpus.acquire`` fetches
a repository someone has already named. This is the step before either: find
repositories nobody named, and decide -- before anything is cached, compiled or
counted -- which of them this project is allowed to redistribute and which are
genuinely new.

It decides nothing about correctness. A source that survives every check here
has been shown to be a distinct, permissively licensed Fortran file containing
a UMAT entry point, and nothing else. Whether its derivatives can be recovered
is what the corpus round is for.

Four rules, the same ones acquisition already follows:

**Nothing moving survives.** Every accepted repository is pinned to the
40-character commit its default branch resolved to at the moment it was read.

**Nothing is cached before its licence is cleared.** The licence is read first;
a repository whose licence is missing, unrecognised or outside
``REDISTRIBUTABLE_SPDX`` is recorded with that reason and its files are never
written to disk.

**A source already in the collection is not a new one.** Candidates are
content-hashed with the same normalisation the identity registry uses, so a
file that is the same implementation under a different name, or the same file
found twice, is reported as a duplicate rather than inflating a count.

**Failures are recorded as themselves.** Rate limiting, a missing licence, a
file with no UMAT entry and a network error are four outcomes, not one.

    python tools/discover_umat_sources.py --out-dir paper_results/discovery
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.corpus.acquire import (  # noqa: E402
    REDISTRIBUTABLE_SPDX, AcquisitionError, GitHubClient, RateLimited,
)
from umat_oti.corpus.identity import (  # noqa: E402
    content_identity, normalise_source, strip_comments,
)

DEFAULT_OUT = REPO_ROOT / "paper_results" / "discovery"
GENERALITY_MATRIX = REPO_ROOT / "paper_results" / "generality" / "generality_matrix.csv"

#: What a UMAT entry point looks like, independent of spacing and case.
_UMAT_ENTRY = "SUBROUTINEUMAT("

#: Extensions the search may return that are Fortran.
_FORTRAN_SUFFIXES = (".f", ".for", ".f90", ".f95", ".f03", ".ftn", ".fpp")

COLUMNS = (
    "repository", "commit", "license_spdx", "license_evidence", "path",
    "bytes", "content_sha256", "code_only_sha256", "outcome", "reason",
    "cached_as",
)


@dataclass
class Discovery:
    """Everything decided about one candidate file, including the refusals."""

    repository: str = ""
    commit: str = ""
    license_spdx: str = ""
    license_evidence: str = ""
    path: str = ""
    bytes: int = 0
    content_sha256: str = ""
    code_only_sha256: str = ""
    outcome: str = ""
    reason: str = ""
    cached_as: str = ""

    def row(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in COLUMNS}


@dataclass
class Survey:
    rows: list[Discovery] = field(default_factory=list)
    searched_pages: int = 0
    search_total_reported: int = 0

    def add(self, row: Discovery) -> None:
        self.rows.append(row)


def known_identities(snapshot_root: Path | None = None) -> dict[str, str]:
    """Hash -> the name this collection already knows that implementation by.

    Hashed from the source files themselves rather than read out of the
    identity registry, which records a derived ``canonical_source_id`` and not
    the raw digests. Reading the registry's columns silently produced an empty
    set, and an empty set means every file already in the corpus is reported
    as a new discovery -- the one error this step exists to prevent.
    """
    known: dict[str, str] = {}
    if not GENERALITY_MATRIX.is_file():
        return known
    with GENERALITY_MATRIX.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            relative = (row.get("source_path") or "").strip()
            if not relative:
                continue
            # A corpus row's path is relative to the pinned snapshot root,
            # which lives outside the repository; a benchmark row's is
            # relative to the repository. Resolving against only one of them
            # silently found nothing for the corpus, and an empty known-set
            # reports every source already in the collection as a discovery.
            roots = [REPO_ROOT] + ([snapshot_root] if snapshot_root else [])
            source = next((root / relative for root in roots
                           if (root / relative).is_file()), None)
            if source is None:
                continue
            name = row.get("identity") or row.get("canonical_source_id") or relative
            try:
                identity = content_identity(source)
            except OSError:
                continue
            known.setdefault(identity.content_sha256, name)
            known.setdefault(identity.code_only_sha256, name)
    return known


def _hashes(text: str, path: str) -> tuple[str, str]:
    """(content hash, comment-stripped hash), exactly as content_identity does.

    Including its fixed-form decision, which is taken from the suffix: hashing
    a .for file as though it were free-form gives a different digest for the
    same bytes and the duplicate is missed.
    """
    fixed = Path(path).suffix.lower() in {".for", ".f", ".f77"}
    content = hashlib.sha256(normalise_source(text).encode("utf-8")).hexdigest()
    code_only = hashlib.sha256(
        strip_comments(text, fixed_form=fixed).encode("utf-8")).hexdigest()
    return content, code_only


def _has_umat_entry(text: str) -> bool:
    """Does the file declare a UMAT, however the declaration is laid out?

    Continuation markers are removed before the whitespace is squeezed, so a
    header split across lines -- legal Fortran, and present in the corpus --
    is still found. Erring toward detection is the right direction here: a
    false positive is examined and rejected downstream, a false negative is a
    source that silently never gets considered.
    """
    squeezed = "".join(text.upper().split()).replace("&", "")
    return _UMAT_ENTRY in squeezed


def search_repositories(client: GitHubClient, *, pages: int,
                        per_page: int = 100,
                        query: str = '"SUBROUTINE UMAT" language:Fortran',
                        pause: float = 2.0) -> tuple[list[str], int, int]:
    """Repository full names the code search returns, most-hits first.

    GitHub's code search is capped and rate limited, so this reports how many
    pages it actually read alongside the total the API claims. A count of
    repositories found is a statement about this search, not about the world,
    and the manifest says so.
    """
    seen: dict[str, int] = {}
    matched_paths: dict[str, set[str]] = {}
    total_reported = 0
    read = 0
    for page in range(1, pages + 1):
        url = ("https://api.github.com/search/code?q="
               + urllib.parse.quote(query, safe="")
               + f"&per_page={per_page}&page={page}")
        try:
            payload = client._get(url)
        except RateLimited:
            break
        except AcquisitionError:
            break
        total_reported = int(payload.get("total_count") or total_reported)
        items = payload.get("items") or []
        if not items:
            break
        read += 1
        for item in items:
            name = (item.get("repository") or {}).get("full_name")
            if name:
                seen[name] = seen.get(name, 0) + 1
                path = str(item.get("path") or "")
                if path:
                    matched_paths.setdefault(name, set()).add(path)
        if len(items) < per_page:
            break
        time.sleep(pause)
    ordered = sorted(seen, key=lambda n: (-seen[n], n))
    return ordered, total_reported, read, matched_paths



#: Repositories that are this project itself, or its sibling. A corpus of
#: externally authored sources exists to show the transformer works on code
#: nobody here wrote; admitting the authoring project's own repository would
#: make the corpus partly a mirror of the thing being measured. The search
#: query finds them because they legitimately contain UMAT sources, so the
#: exclusion has to be explicit. Matched on the full owner/name,
#: case-insensitively. A fork under a different owner is not caught here
#: and does not need to be: it carries the same file contents, so the
#: content-hash dedup reports it as a duplicate. Matching on the bare
#: repository name instead would refuse an unrelated project that happens
#: to have chosen the same name.
OWN_REPOSITORIES = frozenset({
    "amms-lab-utsa/umat_source_transformation",
    "amms-lab-utsa/residual_assembler",
})


def is_own_repository(full_name: str) -> bool:
    """Whether this repository is the project being validated."""
    return full_name.strip().lower() in OWN_REPOSITORIES


def survey_repository(client: GitHubClient, full_name: str,
                      known: dict[str, str], survey: Survey,
                      *, max_files: int, matched: set[str] | None = None,
                      cache_dir: Path | None = None, max_decks: int = 40) -> None:
    owner, _, repo = full_name.partition("/")
    row = Discovery(repository=full_name)

    if is_own_repository(full_name):
        row.outcome = "own_repository"
        row.reason = ("this is the project being validated; its sources and "
                      "decks are not external evidence about itself")
        survey.add(row)
        return

    try:
        spdx, evidence = client.license(owner, repo)
    except RateLimited:
        survey.add(Discovery(repository=full_name, outcome="rate_limited",
                             reason="the licence could not be read before the "
                                    "rate limit was reached"))
        raise
    except AcquisitionError as exc:
        survey.add(Discovery(repository=full_name, outcome="unreadable",
                             reason=f"licence lookup failed: {exc}"))
        return

    row.license_spdx = spdx or ""
    row.license_evidence = evidence or ""
    if not spdx:
        row.outcome = "licence_absent"
        row.reason = ("no licence is declared, so nothing may be redistributed "
                      "from it; recorded and not fetched")
        survey.add(row)
        return
    if spdx not in REDISTRIBUTABLE_SPDX:
        row.outcome = "licence_incompatible"
        row.reason = (f"{spdx} is outside the set this project may "
                      "redistribute; recorded and not fetched")
        survey.add(row)
        return

    try:
        branch = client.default_branch(owner, repo)
        commit = client.resolve_commit(owner, repo, branch)
        entries = client.tree(owner, repo, commit)
    except RateLimited:
        raise
    except AcquisitionError as exc:
        row.outcome = "unreadable"
        row.reason = f"contents could not be listed: {exc}"
        survey.add(row)
        return

    row.commit = commit
    fortran = [e for e in entries
               if str(e.get("path", "")).lower().endswith(_FORTRAN_SUFFIXES)]
    # The search already said which files matched. Reading those first spends
    # the per-repository budget on the files that prompted the hit instead of
    # on whatever the tree happens to list alphabetically -- a repository
    # whose UEL directory sorts before its UMATS directory was otherwise
    # surveyed without a single UMAT being read.
    if matched:
        fortran.sort(key=lambda e: str(e.get("path", "")) not in matched)
    if not fortran:
        clone = Discovery(**{**row.row(), "outcome": "no_fortran",
                             "reason": "the search matched this repository but "
                                       "its tree lists no Fortran file"})
        survey.add(clone)
        return

    # Decks first, when anything is being cached. A source without a material
    # vector cannot be verified, and for these repositories the deck the
    # author shipped is the only place one is written down. The licence has
    # already cleared, so caching them is permitted by the same rule that
    # permits caching the sources.
    if cache_dir is not None:
        decks = [e for e in entries
                 if str(e.get("path", "")).lower().endswith(".inp")]
        for deck in decks[:max_decks]:
            try:
                blob = client.blob(owner, repo, str(deck.get("sha", "")))
            except RateLimited:
                raise
            except AcquisitionError:
                continue
            target = (Path(cache_dir) / full_name.replace("/", "__")
                      / str(deck.get("path", "")))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)

    examined = 0
    for entry in fortran:
        if examined >= max_files:
            survey.add(Discovery(
                **{**row.row(), "outcome": "not_examined",
                   "reason": f"stopped after {max_files} files from this "
                             f"repository; {len(fortran) - examined} not read"}))
            break
        try:
            blob = client.blob(owner, repo, str(entry.get("sha", "")))
        except RateLimited:
            raise
        except AcquisitionError as exc:
            survey.add(Discovery(**{**row.row(), "path": str(entry.get("path", "")),
                                    "outcome": "unreadable",
                                    "reason": f"blob could not be read: {exc}"}))
            continue
        examined += 1
        text = blob.decode("utf-8", errors="replace")
        candidate = Discovery(**row.row())
        candidate.path = str(entry.get("path", ""))
        candidate.bytes = len(blob)
        if not _has_umat_entry(text):
            candidate.outcome = "no_umat_entry"
            candidate.reason = "Fortran, but it declares no SUBROUTINE UMAT"
            survey.add(candidate)
            continue
        content, code_only = _hashes(text, candidate.path)
        candidate.content_sha256 = content
        candidate.code_only_sha256 = code_only
        already = known.get(code_only) or known.get(content)
        if already:
            candidate.outcome = "already_known"
            candidate.reason = (f"the same implementation as {already}, which "
                                "this collection already counts")
            survey.add(candidate)
            continue
        if code_only in {r.code_only_sha256 for r in survey.rows
                         if r.outcome == "candidate"}:
            candidate.outcome = "duplicate_within_search"
            candidate.reason = "the same implementation as an earlier hit"
            survey.add(candidate)
            continue
        candidate.outcome = "candidate"
        candidate.reason = ("distinct, permissively licensed, declares a UMAT "
                            "entry point; not yet transformed or verified")
        if cache_dir is not None:
            # Written only now, after the licence cleared and the file proved
            # distinct. Laid out as <owner>__<repo>/<path> so a cached file
            # still says where it came from without consulting the manifest.
            target = (Path(cache_dir) / full_name.replace("/", "__")
                      / candidate.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            # Relative to the cache root, which the summary names. An absolute
            # path in published evidence records this machine's home
            # directory, which means nothing anywhere else and is what
            # audit_repository_standards refuses.
            candidate.cached_as = str(target.relative_to(Path(cache_dir)))
        survey.add(candidate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pages", type=int, default=3,
                        help="code-search pages to read (100 hits each)")
    parser.add_argument("--max-repositories", type=int, default=40)
    parser.add_argument("--max-files-per-repository", type=int, default=25)
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="write accepted candidates here, after their "
                             "licence has cleared and they proved distinct")
    parser.add_argument("--snapshot-root", type=Path,
                        default=Path(
                            os.environ.get("UMAT_OTI_CORPUS_ROOT")
                            or REPO_ROOT.parent / "Residual_Assembler" / "sources"),
                        help="where the pinned corpus snapshot lives, so "
                             "sources already in it are not rediscovered")
    args = parser.parse_args(argv)

    try:
        client = GitHubClient.discover()
    except AcquisitionError as exc:
        print(f"no usable GitHub credentials: {exc}")
        return 2
    print(f"  authenticated via {client.auth_source}")

    names, total, pages_read, matched_paths = search_repositories(
        client, pages=args.pages)
    survey = Survey(searched_pages=pages_read, search_total_reported=total)
    print(f"  code search: {total} hits reported, {pages_read} page(s) read, "
          f"{len(names)} distinct repositories")

    known = known_identities(args.snapshot_root)
    print(f"  {len(known)} digests for implementations already in the collection")
    if not known:
        print("  refusing to run with an empty known-set: every source already "
              "in the collection would be reported as a new discovery")
        return 2

    stopped_early = ""
    for index, name in enumerate(names[:args.max_repositories], start=1):
        print(f"[{index}/{min(len(names), args.max_repositories)}] {name}", flush=True)
        try:
            survey_repository(client, name, known, survey,
                              max_files=args.max_files_per_repository,
                              matched=matched_paths.get(name),
                              cache_dir=args.cache_dir)
        except RateLimited:
            stopped_early = (f"the GitHub rate limit was reached after "
                             f"{index - 1} repositories; the rest were not read")
            print(f"    {stopped_early}", flush=True)
            break

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "discovered_sources.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(row.row() for row in survey.rows)

    outcomes: dict[str, int] = {}
    for row in survey.rows:
        outcomes[row.outcome] = outcomes.get(row.outcome, 0) + 1
    candidates = [r for r in survey.rows if r.outcome == "candidate"]
    summary = {
        "query": '"SUBROUTINE UMAT" language:Fortran',
        "search_total_reported_by_github": total,
        "search_pages_read": pages_read,
        "distinct_repositories_seen": len(names),
        "repositories_surveyed": min(len(names), args.max_repositories),
        "stopped_early": stopped_early,
        "files_examined": len(survey.rows),
        "outcomes": outcomes,
        "new_candidates": len(candidates),
        "new_candidate_repositories": sorted({r.repository for r in candidates}),
        "cached": sum(1 for r in candidates if r.cached_as),
        "cache_root_name": args.cache_dir.name if args.cache_dir else "",
        "cache_root_note": ("cached_as in the CSV is relative to the cache "
                            "directory the search was given; where that "
                            "directory lives is a property of the machine "
                            "that ran it, not of the evidence"),
        "licences_seen": sorted({r.license_spdx for r in survey.rows if r.license_spdx}),
        "caveat": (
            "A candidate here is a distinct, permissively licensed Fortran file "
            "declaring a UMAT entry point. Nothing has been transformed, "
            "compiled or verified, and no count in the paper may cite this "
            "file. The corpus round is what turns a candidate into evidence."),
    }
    (args.out_dir / "discovered_sources.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
