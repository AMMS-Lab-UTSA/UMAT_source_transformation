#!/usr/bin/env python3
"""Search for externally authored UMAT sources and report what may be used.

The corpus round replays a pinned snapshot; ``umat_oti.corpus.acquire`` fetches
a repository someone has already named. This is the step before either: find
repositories nobody named, and decide -- before anything is cached, compiled or
counted -- which of them this project is allowed to redistribute and which are
genuinely new.

It decides nothing about correctness. A source that survives every check here
has been shown to be a distinct file containing a UMAT entry point, under a
licence this project may redistribute, and nothing else. Whether its
derivatives can be recovered is what the corpus round is for.

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

How far it reaches is set by the questions, not the budget. GitHub caps any
single code-search query at 1000 results, so reading more pages of one query
cannot see past that cap -- which is why one query saw 105 repositories and
stopped. ``CODE_QUERIES`` asks a dozen differently-shaped questions (a
signature, an include file, an argument list, a file extension), and
``--repository-search`` adds ``REPOSITORY_QUERIES``, which reaches projects
code search structurally cannot return: it indexes only the default branch and
drops repositories above its size limit. Every formulation is reported in the
manifest with what it contributed, so a query that found nothing is visible as
a query that found nothing.

Widening the questions does not widen the gate. ``REDISTRIBUTABLE_SPDX`` is
unchanged; a repository with no LICENSE file is refused rather than assumed;
and every refusal is written into the manifest with the repository, the
evidence and the reason, because a refusal that is only a number in a
histogram cannot be audited.

    python tools/discover_umat_sources.py --out-dir paper_results/discovery \
        --repository-search --known-cache <existing cache>
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

#: A VUMAT is a different interface with a different argument list and is out
#: of scope. It is named here so a file that declares both is still read for
#: its UMAT rather than skipped, and so the exclusion is a stated rule rather
#: than an accident of ``SUBROUTINEUMAT(`` not being a substring of
#: ``SUBROUTINEVUMAT(``.
_VUMAT_ENTRY = "SUBROUTINEVUMAT("

#: Extensions the search may return that are Fortran. ``.f77``, ``.f08`` and
#: ``.f18`` were absent, so a repository that uses them had its UMAT listed in
#: the tree and never read. Widening this costs a blob fetch on a file that
#: turns out not to declare a UMAT; omitting it costs the source entirely.
_FORTRAN_SUFFIXES = (".f", ".for", ".f77", ".f90", ".f95", ".f03", ".f08",
                     ".f15", ".f18", ".ftn", ".fpp")

#: Suffixes that are documentation, markup or data rather than source. The
#: relaxation below reads a file the search matched whatever its extension,
#: which is how a UMAT shipped as ``.inc`` becomes reachable -- and, on the
#: first run of it, how six README and docs files were admitted as candidates.
#: A markdown page that quotes ``SUBROUTINE UMAT(`` in a fenced code block
#: satisfies every content check this tool makes, because the quotation is
#: real Fortran; what disqualifies it is the file it sits in. Every suffix in
#: the name is tested, not only the last, because ``umat.rst.txt`` is Sphinx
#: output whose final suffix is innocent.
_DOCUMENTATION_SUFFIXES = frozenset({
    ".md", ".markdown", ".rst", ".adoc", ".tex", ".html", ".htm", ".xml",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".tsv",
    ".ipynb", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".zip",
    ".gz", ".tar", ".odt", ".doc", ".docx", ".bib", ".log", ".out",
})

#: Extensions that name another language, or a solver's own data format. A file
#: like these can contain the exact string "SUBROUTINE UMAT" and still not be a
#: UMAT: tests/test_umat_gen.py is a Python generator that WRITES that line,
#: uhyper.pyf is an f2py interface DESCRIBING one, and
#: MainCalculiXProgram.model is a solver input deck. All three were admitted as
#: Fortran sources, because the relaxation below asks only whether the suffix
#: looks like a word. Writing about Fortran is not being Fortran.
_FOREIGN_LANGUAGE_SUFFIXES = frozenset({
    ".py", ".pyf", ".pyx", ".pyi", ".ipynb",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx",
    ".java", ".cs", ".js", ".ts", ".rs", ".go", ".rb", ".pl", ".php",
    ".m", ".mlx", ".r", ".jl", ".lua", ".tcl",
    ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1", ".mk", ".cmake",
    # Solver artefacts, not source. ".dat" is deliberately absent: it is an
    # Abaqus output file far more often than not, but the relaxation was
    # written to reach a UMAT shipped under an odd extension and a test pins
    # ".dat" as one of those shapes. Nothing observed has been admitted
    # wrongly under it, and the UMAT-entry check stands behind this one.
    ".model", ".inp", ".msg", ".sta", ".odb", ".env",
})

#: Directory names that, by convention, hold an Abaqus deck beside the source
#: it drives. A deck found here is recorded against the candidate rather than
#: being one of the first forty ``.inp`` files in the tree.
_EXAMPLE_DIR_HINTS = ("exampleinputfiles", "example", "examples", "input",
                      "inputfiles", "inp", "test", "tests", "verification",
                      "benchmark", "benchmarks", "demo", "demos", "case",
                      "cases", "run", "runs")

#: SPDX identifiers inside ``REDISTRIBUTABLE_SPDX`` that carry a copyleft
#: obligation. The gate itself is ``REDISTRIBUTABLE_SPDX`` and is not narrowed
#: here -- this repository is GPL-3.0-only, so a GPL-3.0 source is one it may
#: redistribute. What this adds is that the obligation is *recorded* per row,
#: so a reader who needs a permissive-only subset can take one from the
#: evidence instead of having to re-derive it from licence names.
_COPYLEFT_SPDX = frozenset({
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
    "LGPL-3.0", "LGPL-3.0-only", "AGPL-3.0", "AGPL-3.0-only",
})

#: Code-search formulations, run in order. GitHub caps any single code-search
#: query at 1000 results, so one query cannot reach further than that however
#: many pages are read: the way to see more repositories is to ask differently,
#: not to ask again. Each entry is (name, query) and every one is reported in
#: the manifest with what it contributed, so a query that finds nothing is
#: visible as a query that found nothing rather than as an absence.
#:
#: ``language:Fortran`` is deliberately not on all of them. GitHub classifies a
#: UMAT shipped as ``.inc``, ``.txt`` or with no extension at all as something
#: other than Fortran, and those files were unreachable while every query
#: carried the filter.
CODE_QUERIES: tuple[tuple[str, str], ...] = (
    ("subroutine_umat_fortran", '"SUBROUTINE UMAT" language:Fortran'),
    ("subroutine_umat_ddsdde", '"SUBROUTINE UMAT" DDSDDE'),
    ("aba_param_include", '"ABA_PARAM.INC"'),
    ("ddsdde_statev_nprops", 'DDSDDE STATEV NPROPS'),
    ("umat_signature_ddsdde_sse", '"UMAT(STRESS,STATEV,DDSDDE,SSE"'),
    ("umat_extension_for", '"SUBROUTINE UMAT" extension:for'),
    ("umat_extension_f", '"SUBROUTINE UMAT" extension:f'),
    ("umat_extension_f90", '"SUBROUTINE UMAT" extension:f90'),
    ("umat_extension_inc", '"SUBROUTINE UMAT" extension:inc'),
    ("umat_extension_txt", '"SUBROUTINE UMAT" extension:txt'),
    ("umat_ddsdde_ntens", '"DDSDDE(NTENS,NTENS)"'),
    ("umat_props_dstran", '"PROPS(NPROPS)" "DSTRAN(NTENS)"'),
)

#: Repository-search formulations. Code search only indexes the default branch
#: and drops repositories it considers too large, so a repository whose UMAT it
#: never returns is still findable by name, description or topic. These produce
#: repository names only; every one is then put through the same licence gate
#: and the same tree walk as a code-search hit.
REPOSITORY_QUERIES: tuple[tuple[str, str], ...] = (
    ("repo_umat_abaqus", "UMAT abaqus"),
    ("repo_umat_subroutine", "UMAT subroutine fortran"),
    ("repo_abaqus_user_material", "abaqus user material subroutine"),
    ("repo_topic_umat", "topic:umat"),
    ("repo_topic_abaqus_fortran", "topic:abaqus language:Fortran"),
    ("repo_constitutive_abaqus", "constitutive model abaqus umat"),
)

COLUMNS = (
    "repository", "commit", "license_spdx", "license_class", "license_evidence",
    "path", "bytes", "content_sha256", "code_only_sha256", "outcome", "reason",
    "found_by", "cached_as", "decks",
)


@dataclass
class Discovery:
    """Everything decided about one candidate file, including the refusals."""

    repository: str = ""
    commit: str = ""
    license_spdx: str = ""
    license_class: str = ""
    license_evidence: str = ""
    path: str = ""
    bytes: int = 0
    content_sha256: str = ""
    code_only_sha256: str = ""
    outcome: str = ""
    reason: str = ""
    found_by: str = ""
    cached_as: str = ""
    decks: str = ""

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


def cache_identities(*cache_roots: Path | None) -> dict[str, str]:
    """Hash -> name, for every Fortran source already sitting in a cache.

    ``known_identities`` reads the generality matrix, which lists the sources
    the *corpus round* has processed. It does not list what a previous
    discovery run cached, and those are two different sets: at the time this
    was written the matrix held 43 rows and the discovery cache held 71
    candidates, with no digest in common. A second run therefore re-admitted
    all 71 as new discoveries -- the same files, fetched again, counted again,
    and reported as having widened the corpus.

    A cached file is named by its path relative to the cache root it was found
    under, never absolutely: the name is written into the manifest's reasons,
    and an absolute path there records this machine's home directory.
    """
    known: dict[str, str] = {}
    for root in cache_roots:
        if root is None:
            continue
        root = Path(root)
        if not root.is_dir():
            continue
        for source in sorted(root.rglob("*")):
            if not source.is_file():
                continue
            if source.suffix.lower() not in _FORTRAN_SUFFIXES:
                continue
            try:
                text = source.read_text(errors="replace")
            except OSError:
                continue
            content, code_only = _hashes(text, str(source))
            name = f"{root.name}/{source.relative_to(root)}"
            known.setdefault(content, name)
            known.setdefault(code_only, name)
    return known


#: How many nearby decks are recorded against one source. A cap, so a
#: repository with hundreds of decks does not write a kilobyte of paths into
#: one CSV cell.
_DECKS_PER_SOURCE = 8


def _licence_class(spdx: str | None) -> str:
    """permissive, copyleft, or the empty string when nothing was declared.

    This classifies; it does not gate. ``REDISTRIBUTABLE_SPDX`` is the gate and
    is unchanged: this repository is GPL-3.0-only, so a GPL-3.0 source is one
    it may lawfully redistribute, and dropping the fifteen GPL-3.0 sources
    already in the collection would delete published evidence rather than
    tighten a rule. What this adds is that the obligation is written down per
    row, so a reader who needs a permissive-only subset can filter the evidence
    instead of re-deriving licence names by hand.
    """
    if not spdx:
        return ""
    return "copyleft" if spdx in _COPYLEFT_SPDX else "permissive"


def _may_be_source(path: str) -> bool:
    """Could this path hold source, as opposed to writing about it?

    Applied only to a file the search matched under a non-Fortran extension.
    Two things disqualify it: a documentation or data suffix anywhere in the
    name, and a suffix that is not a word -- ``astest/umat001a.22`` is a
    Code_Aster reference result, and a numeric extension has never named a
    Fortran source file. A file with no extension at all is allowed, because
    that is one of the shapes this relaxation exists to reach.
    """
    name = Path(path).name
    suffixes = [s.lower() for s in Path(name).suffixes]
    if any(s in _DOCUMENTATION_SUFFIXES for s in suffixes):
        return False
    if any(s in _FOREIGN_LANGUAGE_SUFFIXES for s in suffixes):
        return False
    if not suffixes:
        return True
    last = suffixes[-1].lstrip(".")
    return bool(last) and last.isalnum() and not last.isdigit()


def _declares_vumat_only(text: str) -> bool:
    """A VUMAT and no UMAT. Out of scope, and said so rather than filed as noise.

    ``SUBROUTINEUMAT(`` is not a substring of ``SUBROUTINEVUMAT(``, so a VUMAT
    was already excluded -- but it was excluded silently, under the same
    "declares no SUBROUTINE UMAT" reason as a file of pure utility routines.
    Naming it separates a file that is the wrong interface from a file that is
    not a material subroutine at all.
    """
    squeezed = "".join(text.upper().split()).replace("&", "")
    return _VUMAT_ENTRY in squeezed and _UMAT_ENTRY not in squeezed


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


def _search_code_once(client: GitHubClient, query: str, *, pages: int,
                      per_page: int, pause: float
                      ) -> tuple[dict[str, int], dict[str, set[str]], int, int]:
    """One code-search formulation, paged until it stops giving new hits."""
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
            if not name:
                continue
            seen[name] = seen.get(name, 0) + 1
            path = str(item.get("path") or "")
            if path:
                matched_paths.setdefault(name, set()).add(path)
        if len(items) < per_page:
            break
        time.sleep(pause)
    return seen, matched_paths, total_reported, read


def _search_repositories_once(client: GitHubClient, query: str, *, pages: int,
                              per_page: int, pause: float
                              ) -> tuple[list[str], int, int]:
    """Repository names for one repository-search formulation.

    Repository search answers a question code search cannot: which projects
    *say* they are about UMATs. Code search indexes only the default branch and
    silently omits repositories above its size limit, so a repository whose
    UMAT it never returns is still reachable by name, description or topic.
    No file is read here -- this produces names, which then go through exactly
    the same licence gate and tree walk as a code-search hit.
    """
    names: list[str] = []
    total_reported = 0
    read = 0
    for page in range(1, pages + 1):
        url = ("https://api.github.com/search/repositories?q="
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
            name = item.get("full_name")
            if name:
                names.append(str(name))
        if len(items) < per_page:
            break
        time.sleep(pause)
    return names, total_reported, read


def search_repositories(client: GitHubClient, *, pages: int,
                        per_page: int = 100,
                        query: str | None = None,
                        code_queries: Iterable[tuple[str, str]] | None = None,
                        repository_queries: Iterable[tuple[str, str]] | None = None,
                        repository_pages: int = 2,
                        pause: float = 2.0):
    """Every repository the search formulations reach, most-hits-first.

    GitHub caps a single code-search query at 1000 results. Reading more pages
    of one query therefore cannot reach further than that cap, which is why the
    previous single-query search saw 105 repositories and stopped: the limit
    was the question, not the budget. Several differently-shaped questions --
    a signature, an include file, an argument list, a file extension -- reach
    overlapping but not identical sets, and repository search reaches a third
    set that code search structurally cannot return.

    Returns (ordered names, total reported across queries, pages read, matched
    paths per repository, per-query provenance, which query first named each
    repository). A repository named by more than one query is surveyed once.
    """
    if code_queries is None:
        code_queries = (CODE_QUERIES if query is None
                        else (("query", query),))
    if repository_queries is None:
        repository_queries = ()

    seen: dict[str, int] = {}
    matched_paths: dict[str, set[str]] = {}
    found_by: dict[str, str] = {}
    provenance: list[dict[str, Any]] = []
    total_reported = 0
    pages_read = 0

    for index, (name, formulation) in enumerate(code_queries):
        # Between formulations as well as between pages. GitHub allows ten
        # code searches a minute; twelve formulations fired back to back are
        # rate limited part way through, and a rate-limited query reports zero
        # repositories, which is indistinguishable in the manifest from a
        # query that genuinely found none.
        if index:
            time.sleep(pause)
        hits, matched, reported, read = _search_code_once(
            client, formulation, pages=pages, per_page=per_page, pause=pause)
        fresh = [r for r in hits if r not in seen]
        for repository, count in hits.items():
            seen[repository] = seen.get(repository, 0) + count
            found_by.setdefault(repository, name)
        for repository, paths in matched.items():
            matched_paths.setdefault(repository, set()).update(paths)
        total_reported += reported
        pages_read += read
        provenance.append({
            "name": name, "kind": "code", "query": formulation,
            "total_reported_by_github": reported, "pages_read": read,
            "repositories": len(hits),
            "repositories_first_seen_here": len(fresh),
        })
        print(f"    code/{name}: {reported} reported, {read} page(s), "
              f"{len(hits)} repositories, {len(fresh)} new", flush=True)

    for index, (name, formulation) in enumerate(repository_queries):
        if index:
            time.sleep(pause)
        hits, reported, read = _search_repositories_once(
            client, formulation, pages=repository_pages, per_page=per_page,
            pause=pause)
        fresh = [r for r in hits if r not in seen]
        for repository in hits:
            # A repository-search hit carries no file path and no hit count.
            # It is ranked below every code-search hit rather than being given
            # a fabricated one: the code search demonstrated a UMAT is in the
            # file it named, and this only demonstrates the project says it is
            # about UMATs.
            seen.setdefault(repository, 0)
            found_by.setdefault(repository, name)
        total_reported += reported
        pages_read += read
        provenance.append({
            "name": name, "kind": "repository", "query": formulation,
            "total_reported_by_github": reported, "pages_read": read,
            "repositories": len(hits),
            "repositories_first_seen_here": len(fresh),
        })
        print(f"    repo/{name}: {reported} reported, {read} page(s), "
              f"{len(hits)} repositories, {len(fresh)} new", flush=True)

    ordered = sorted(seen, key=lambda n: (-seen[n], n))
    return ordered, total_reported, pages_read, matched_paths, provenance, found_by


def _decks_near(entries: list[dict[str, Any]], source_path: str) -> list[str]:
    """Deck paths that belong to one source, nearest first.

    An ``ExampleInputFiles/`` directory beside a UMAT is the only place these
    repositories write down a material vector, and a source without one cannot
    be verified. Previously every ``.inp`` in the tree was cached, in tree
    order, up to a fixed cap -- so a repository with sixty decks in an
    unrelated directory could exhaust the cap before reaching the one deck that
    drives the UMAT, and nothing recorded which deck went with which source.

    Nearest first means: the source's own directory, then a sibling whose name
    is one of the conventional example-directory names, then the parent
    directory, then anything else. This records a *proximity*, not a verified
    pairing; whether the deck actually drives that source is the corpus round's
    question, not this one.
    """
    source_dir = str(Path(source_path).parent).strip(".")
    parent_dir = str(Path(source_dir).parent).strip(".") if source_dir else ""
    ranked: list[tuple[int, str]] = []
    for entry in entries:
        path = str(entry.get("path", ""))
        if not path.lower().endswith(".inp"):
            continue
        deck_dir = str(Path(path).parent).strip(".")
        parts = [part.lower() for part in Path(path).parts[:-1]]
        if deck_dir == source_dir:
            rank = 0
        elif source_dir and deck_dir.startswith(source_dir + "/"):
            rank = 1
        elif any(part in _EXAMPLE_DIR_HINTS for part in parts) and (
                not parent_dir or deck_dir.startswith(parent_dir)):
            rank = 2
        elif parent_dir and deck_dir.startswith(parent_dir):
            rank = 3
        elif any(part in _EXAMPLE_DIR_HINTS for part in parts):
            rank = 4
        else:
            rank = 5
        ranked.append((rank, path))
    ranked.sort()
    return [path for rank, path in ranked if rank < 5]



#: Repositories that are this project itself, or its sibling. A corpus of
#: externally authored sources exists to show the transformer works on code
#: nobody here wrote; admitting the authoring project's own repository would
#: make the corpus partly a mirror of the thing being measured. The widened
#: query set finds them because they legitimately contain UMAT sources, so the
#: exclusion has to be explicit. Matched on the full owner/name,
#: case-insensitively. A fork under a different owner is not caught here and
#: does not need to be: it carries the same file contents, so the content-hash
#: dedup reports it as a duplicate. Matching on the bare repository name
#: instead would refuse an unrelated project that happens to share it.
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
                      cache_dir: Path | None = None, max_decks: int = 40,
                      found_by: str = "") -> None:
    owner, _, repo = full_name.partition("/")
    row = Discovery(repository=full_name, found_by=found_by)

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
    row.license_class = _licence_class(spdx)
    if not spdx:
        row.outcome = "licence_absent"
        row.reason = ("no licence is declared, so nothing may be redistributed "
                      "from it; a repository without a LICENSE file is refused, "
                      "not assumed permissive; recorded and not fetched")
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
    matched = matched or set()
    # A file the search itself matched is read even without a Fortran
    # extension. Abaqus does not require one: a UMAT is routinely shipped as
    # ``.inc``, as ``.txt``, or with no extension at all, and every one of
    # those was unreachable while the tree walk filtered on a Fortran suffix.
    #
    # The relaxation needs its own guard. Read literally it admitted six
    # README and docs files, because a markdown page quoting a UMAT signature
    # in a code block contains a genuine ``SUBROUTINE UMAT(`` and passes every
    # content check there is. ``_may_be_source`` refuses the file on its name
    # instead. Directories and anything over 512 kB are excluded too -- a UMAT
    # is not a megabyte.
    fortran = [e for e in entries
               if e.get("type", "blob") == "blob"
               and (str(e.get("path", "")).lower().endswith(_FORTRAN_SUFFIXES)
                    or (str(e.get("path", "")) in matched
                        and _may_be_source(str(e.get("path", "")))
                        and int(e.get("size") or 0) <= 512_000))]
    # The search already said which files matched. Reading those first spends
    # the per-repository budget on the files that prompted the hit instead of
    # on whatever the tree happens to list alphabetically -- a repository
    # whose UEL directory sorts before its UMATS directory was otherwise
    # surveyed without a single UMAT being read.
    if matched:
        fortran.sort(key=lambda e: str(e.get("path", "")) not in matched)
    if not fortran:
        clone = Discovery(**{**row.row(), "outcome": "no_fortran",
                             "reason": "its tree lists no Fortran file and no "
                                       "file the search matched"})
        survey.add(clone)
        return

    admitted: list[Discovery] = []
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
            candidate.reason = (
                "declares a VUMAT and no UMAT; the explicit interface is out "
                "of scope" if _declares_vumat_only(text)
                else "Fortran, but it declares no SUBROUTINE UMAT")
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
        candidate.reason = (
            f"distinct, licensed {candidate.license_spdx} "
            f"({candidate.license_class}), declares a UMAT entry point; "
            "not yet transformed or verified")
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
        # Which decks sit with this source, nearest first. Recorded whether or
        # not anything is cached, because the pairing is the finding: a UMAT
        # with a deck beside it has a material vector written down somewhere,
        # and a UMAT without one does not.
        near = _decks_near(entries, candidate.path)
        candidate.decks = ";".join(near[:_DECKS_PER_SOURCE])
        admitted.append(candidate)
        survey.add(candidate)

    # Decks last, and only the ones that sit with a source this survey
    # admitted. Caching every ``.inp`` in tree order up to a fixed cap meant a
    # repository with sixty decks in an unrelated directory could exhaust the
    # cap before reaching the one deck that drives its UMAT. The licence
    # cleared before any of this, so caching a deck is permitted by the same
    # rule that permits caching the source it belongs to.
    # Only for a repository that contributed a source. A deck is evidence
    # about the source it drives; on its own it is an input file for a model
    # this collection does not have. The previous pass cached decks from every
    # repository whose licence cleared, which is how the cache came to hold
    # 670 decks against 71 sources, most of them belonging to nothing here.
    if cache_dir is not None and admitted:
        by_path = {str(e.get("path", "")): e for e in entries}
        wanted: list[str] = []
        for candidate in admitted:
            for deck in candidate.decks.split(";"):
                if deck and deck not in wanted:
                    wanted.append(deck)
        # Then any remaining deck, so a repository whose decks live nowhere
        # near its sources still contributes them, just not at the expense of
        # the ones that do.
        for path in by_path:
            if len(wanted) >= max_decks:
                break
            if path.lower().endswith(".inp") and path not in wanted:
                wanted.append(path)
        for path in wanted[:max_decks]:
            entry = by_path.get(path)
            if entry is None:
                continue
            try:
                blob = client.blob(owner, repo, str(entry.get("sha", "")))
            except RateLimited:
                raise
            except AcquisitionError:
                continue
            target = (Path(cache_dir) / full_name.replace("/", "__") / path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pages", type=int, default=3,
                        help="code-search pages to read (100 hits each)")
    # Raised with the search. Forty was sized for a single query that reached
    # 105 repositories; the widened formulations reach several times that, and
    # leaving the cap where it was would have made the extra queries visible in
    # the manifest and invisible in the result.
    parser.add_argument("--max-repositories", type=int, default=150)
    parser.add_argument("--max-files-per-repository", type=int, default=25)
    parser.add_argument("--max-decks-per-repository", type=int, default=40,
                        help="decks nearest an admitted source are taken first")
    parser.add_argument("--search-pause", type=float, default=7.0,
                        help="seconds between search requests; GitHub allows "
                             "ten code searches a minute")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="write accepted candidates here, after their "
                             "licence has cleared and they proved distinct")
    parser.add_argument("--known-cache", type=Path, action="append", default=[],
                        help="an existing cache root whose sources are already "
                             "counted; may be repeated. --cache-dir is always "
                             "treated as one of these, so a re-run never "
                             "re-admits what it admitted last time.")
    parser.add_argument("--repository-search", action="store_true",
                        help="also run repository search, which reaches "
                             "projects code search structurally cannot return")
    parser.add_argument("--repository-pages", type=int, default=2)
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

    names, total, pages_read, matched_paths, provenance, found_by = \
        search_repositories(
            client, pages=args.pages,
            repository_queries=(REPOSITORY_QUERIES
                                if args.repository_search else ()),
            repository_pages=args.repository_pages,
            pause=args.search_pause)
    survey = Survey(searched_pages=pages_read, search_total_reported=total)
    print(f"  search complete: {total} hits reported across "
          f"{len(provenance)} formulations, {pages_read} page(s) read, "
          f"{len(names)} distinct repositories")

    known = known_identities(args.snapshot_root)
    from_matrix = len(known)
    # Every cache root, including the one about to be written into. The
    # generality matrix lists what the corpus round processed; it does not
    # list what a previous discovery run cached, and without this a re-run
    # re-admitted every source it had already admitted.
    cache_roots = list(args.known_cache)
    if args.cache_dir is not None and args.cache_dir not in cache_roots:
        cache_roots.append(args.cache_dir)
    cached_known = cache_identities(*cache_roots)
    for digest, name in cached_known.items():
        known.setdefault(digest, name)
    print(f"  {from_matrix} digests from the collection, "
          f"{len(cached_known)} from {len(cache_roots)} cache root(s), "
          f"{len(known)} in total")
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
                              cache_dir=args.cache_dir,
                              max_decks=args.max_decks_per_repository,
                              found_by=found_by.get(name, ""))
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
    # Every repository that was looked at and not used, with the reason. A
    # refusal that is only a number in a histogram cannot be audited: a reader
    # checking licence discipline needs to see which repository was refused and
    # on what evidence, and a reader checking coverage needs to see that a
    # repository was refused rather than never reached.
    refused_outcomes = ("licence_absent", "licence_incompatible", "unreadable",
                        "no_fortran", "rate_limited")
    refusals = [
        {"repository": r.repository, "outcome": r.outcome,
         "license_spdx": r.license_spdx, "license_evidence": r.license_evidence,
         "path": r.path, "reason": r.reason, "found_by": r.found_by}
        for r in survey.rows if r.outcome in refused_outcomes]
    refused_repositories = sorted({r["repository"] for r in refusals})
    licence_classes: dict[str, int] = {}
    for row in candidates:
        key = row.license_class or "undeclared"
        licence_classes[key] = licence_classes.get(key, 0) + 1
    summary = {
        "queries": [dict(entry) for entry in provenance],
        "repository_search_run": bool(args.repository_search),
        "search_total_reported_by_github": total,
        "search_pages_read": pages_read,
        "distinct_repositories_seen": len(names),
        "repositories_surveyed": min(len(names), args.max_repositories),
        "stopped_early": stopped_early,
        "files_examined": len(survey.rows),
        "outcomes": outcomes,
        "new_candidates": len(candidates),
        "new_candidate_repositories": sorted({r.repository for r in candidates}),
        "new_candidates_by_licence_class": licence_classes,
        "new_candidates_with_a_deck_beside_them": sum(
            1 for r in candidates if r.decks),
        "known_digests_from_collection": from_matrix,
        "known_digests_from_caches": len(cached_known),
        "known_cache_root_names": [Path(root).name for root in cache_roots],
        "refused_repositories": refused_repositories,
        "refused_repository_count": len(refused_repositories),
        "refusals": refusals,
        "refusal_note": (
            "A repository with no LICENSE file is refused, not assumed: "
            "licence_absent means nothing was fetched from it and nothing "
            "cached. licence_incompatible means a licence was declared and is "
            "outside REDISTRIBUTABLE_SPDX. Neither was read beyond its licence."),
        "licence_gate": sorted(REDISTRIBUTABLE_SPDX),
        "licence_gate_note": (
            "The gate is REDISTRIBUTABLE_SPDX and this run did not change it. "
            "It admits copyleft licences compatible with this repository's own "
            "GPL-3.0-only terms; license_class records which admitted sources "
            "carry a copyleft obligation so a permissive-only subset can be "
            "taken from the evidence."),
        "cached": sum(1 for r in candidates if r.cached_as),
        "cache_root_name": args.cache_dir.name if args.cache_dir else "",
        "cache_root_note": ("cached_as in the CSV is relative to the cache "
                            "directory the search was given; where that "
                            "directory lives is a property of the machine "
                            "that ran it, not of the evidence"),
        "licences_seen": sorted({r.license_spdx for r in survey.rows if r.license_spdx}),
        "caveat": (
            "A candidate here is a distinct file declaring a UMAT entry point "
            "under a licence inside REDISTRIBUTABLE_SPDX; license_class says "
            "whether that licence is permissive or copyleft, because not every "
            "admitted licence is permissive and calling them all that was "
            "wrong. Nothing has been transformed, compiled or verified, and no "
            "count in the paper may cite this file. The corpus round is what "
            "turns a candidate into evidence."),
    }
    (args.out_dir / "discovered_sources.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
