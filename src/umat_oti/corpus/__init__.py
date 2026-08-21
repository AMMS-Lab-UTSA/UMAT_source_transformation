"""Corpus discovery + regression toolkit for the SoftwareX pipeline.

The SoftwareX task describes an end-to-end web-scraping / corpus regression
pipeline. The full pipeline requires network access and a long-running
sandbox; that is intentionally kept out of the offline test suite.

This module provides the *deterministic* pieces of that pipeline so they can
be exercised offline:

* :class:`CorpusCandidate` and :class:`CorpusRecord` describe a single
  discovered UMAT candidate (provenance + license classification + pipeline
  stage).
* :func:`classify_license` maps SPDX-style license identifiers to a
  redistribution category ('permissive', 'copyleft', 'unknown').
* :func:`content_hash` and :func:`deduplicate` implement the deterministic
  deduplication rule (SHA-256 of a normalized text form).
* :func:`build_github_search_urls` returns the well-known GitHub Code
  Search endpoints for the required UMAT search terms. Network access is
  never triggered from this module; callers must opt in explicitly.
* :func:`round_metrics` produces the per-round metrics table honestly from
  a list of :class:`CorpusRecord` values -- no hard-coded numbers.

Discovery via the live GitHub API is optional and gated behind an explicit
``allow_network`` flag; a small requests-based helper lives in
:func:`discover_via_github_api`. It is *not* exercised by the offline tests.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# License classification
# ---------------------------------------------------------------------------

_PERMISSIVE_LICENSES = {
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "ISC",
    "Zlib",
}

_COPYLEFT_LICENSES = {
    "GPL-2.0",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "AGPL-3.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "LGPL-2.1",
    "LGPL-3.0",
    "MPL-2.0",
}


def classify_license(spdx_id: Optional[str]) -> str:
    """Return the redistribution category for an SPDX license id.

    Categories:

    * ``"permissive"`` — safe to redistribute in the corpus.
    * ``"copyleft"`` — reference only; must not be linked into a permissive
      framework distribution.
    * ``"unknown"`` — non-SPDX / missing / bespoke; treated as reference only.
    """
    if not spdx_id:
        return "unknown"
    token = spdx_id.strip()
    if token in _PERMISSIVE_LICENSES:
        return "permissive"
    if token in _COPYLEFT_LICENSES:
        return "copyleft"
    return "unknown"


def is_redistributable(spdx_id: Optional[str]) -> bool:
    return classify_license(spdx_id) == "permissive"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

STAGE_DISCOVERED = "discovered"
STAGE_CLASSIFIED = "license_classified"
STAGE_ENTRY_DETECTED = "entry_routine_detected"
STAGE_DEPENDENCIES_COMPLETE = "dependencies_complete"
STAGE_CONTRACT_BUILT = "contract_built"
STAGE_TRANSFORMED = "transformed"
STAGE_COMPILED = "generated_source_compiled"
STAGE_PRIMAL_VERIFIED = "primal_parity_verified"
STAGE_DERIVATIVE_VERIFIED = "derivatives_numerically_verified"
STAGE_ABAQUS_VERIFIED = "abaqus_verified"

_STAGE_ORDER = (
    STAGE_DISCOVERED,
    STAGE_CLASSIFIED,
    STAGE_ENTRY_DETECTED,
    STAGE_DEPENDENCIES_COMPLETE,
    STAGE_CONTRACT_BUILT,
    STAGE_TRANSFORMED,
    STAGE_COMPILED,
    STAGE_PRIMAL_VERIFIED,
    STAGE_DERIVATIVE_VERIFIED,
    STAGE_ABAQUS_VERIFIED,
)


FAILURE_CATEGORIES = (
    "not_a_umat",
    "input_deck_only",
    "helper_or_dependency_only",
    "missing_dependency",
    "incomplete_repository_snapshot",
    "unsupported_license",
    "contract_generation_failure",
    "dimension_inference_failure",
    "custom_operator_or_generic_parser_gap",
    "unsupported_fortran_construct",
    "generated_code_compile_failure",
    "original_umat_compile_failure",
    "primal_parity_failure",
    "derivative_validation_failure",
    "abaqus_deck_or_environment_failure",
    "confirmed_transformation_defect",
)


@dataclass
class CorpusCandidate:
    """Provenance record for a discovered candidate."""

    repository: str
    file_path: str
    commit_sha: str
    retrieved_at: str
    license_spdx: Optional[str]
    license_category: str = ""
    detected_entry_routines: tuple[str, ...] = ()
    source_form: str = "unknown"       # "fixed", "free", "unknown"
    file_extension: str = ""
    raw_url: str = ""
    normalized_hash: str = ""
    provenance_note: str = ""

    def classify(self) -> "CorpusCandidate":
        return dataclasses.replace(
            self, license_category=classify_license(self.license_spdx)
        )


@dataclass
class CorpusRecord:
    """A candidate plus its current pipeline stage and outcome."""

    candidate: CorpusCandidate
    stage: str = STAGE_DISCOVERED
    outcome: str = "pending"
    failure_category: Optional[str] = None
    failure_message: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def advance_to(self, stage: str, *, outcome: str = "pending") -> "CorpusRecord":
        if stage not in _STAGE_ORDER:
            raise ValueError(f"unknown corpus stage {stage!r}")
        return dataclasses.replace(self, stage=stage, outcome=outcome)

    def fail_at(self, stage: str, *, category: str, message: str) -> "CorpusRecord":
        if category not in FAILURE_CATEGORIES:
            raise ValueError(f"unknown failure category {category!r}")
        return dataclasses.replace(
            self,
            stage=stage,
            outcome="failed",
            failure_category=category,
            failure_message=message,
        )


# ---------------------------------------------------------------------------
# Content hashing + dedup
# ---------------------------------------------------------------------------

_NORMALIZE_WS = re.compile(r"[\r\t ]+")


def content_hash(text: str) -> str:
    """Deterministic SHA-256 over a normalized text form.

    Normalization strips trailing whitespace per line, collapses runs of
    horizontal whitespace, drops blank lines, and uppercases identifiers.
    This is a "coarse" hash meant to match near-duplicate copies of the
    same UMAT across forks; it is not a code-equality proof.
    """
    lines = []
    for raw in text.splitlines():
        stripped = raw.rstrip()
        stripped = _NORMALIZE_WS.sub(" ", stripped).strip()
        if not stripped:
            continue
        lines.append(stripped.upper())
    body = "\n".join(lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def deduplicate(records: Iterable[CorpusRecord]) -> list[CorpusRecord]:
    """Deduplicate records by ``candidate.normalized_hash``.

    Order-preserving: the first occurrence wins; later duplicates are
    dropped. Records whose hash is empty are always kept.
    """
    seen: set[str] = set()
    out: list[CorpusRecord] = []
    for record in records:
        h = record.candidate.normalized_hash
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Entry-routine detection
# ---------------------------------------------------------------------------

_ENTRY_ROUTINE_RE = re.compile(
    r"^\s*SUBROUTINE\s+(UMAT|VUMAT|UHYPER|UEL|USDFLD|URDFIL|UEXPAN)\b",
    re.IGNORECASE | re.MULTILINE,
)


def detect_entry_routines(source: str) -> tuple[str, ...]:
    matches = _ENTRY_ROUTINE_RE.findall(source)
    return tuple(sorted({m.upper() for m in matches}))


def detect_source_form(source: str) -> str:
    """Best-effort fixed/free-form detection.

    Signals used:

    * A single-character ``C``, ``c``, or ``*`` in column 1 is a strong
      fixed-form comment marker.
    * Six blank / digit columns followed by a statement letter is a strong
      fixed-form statement marker.
    * A ``!`` starting a line, or a statement starting in column 1 with a
      letter that is not a fixed-form comment marker, is a free-form signal.
    """
    fixed_hits = 0
    free_hits = 0
    for raw in source.splitlines()[:400]:
        if not raw:
            continue
        first = raw[0]
        if first in ("C", "c", "*") and (len(raw) == 1 or raw[1] in (" ", "\t", "!")):
            fixed_hits += 3
            continue
        if first == "!":
            free_hits += 2
            continue
        prefix = raw[:6]
        if len(raw) > 6 and all(ch in " \t0123456789" for ch in prefix):
            # 6-column label/blank followed by a statement is fixed-form.
            if raw[6].isalpha():
                fixed_hits += 2
                continue
        # Statement starting in column 1 with a letter (not a fixed comment
        # marker) is a free-form indicator.
        if first.isalpha() and first not in ("C", "c"):
            free_hits += 1
            continue
    if fixed_hits > free_hits:
        return "fixed"
    if free_hits > 0:
        return "free"
    return "unknown"


# ---------------------------------------------------------------------------
# GitHub-API discovery (opt-in, network-gated)
# ---------------------------------------------------------------------------

GITHUB_SEARCH_TERMS: tuple[str, ...] = (
    '"SUBROUTINE UMAT"',
    '"Abaqus UMAT"',
    '"VUMAT"',
    '"UHYPER"',
    '"DDSDDE"',
    '"STATEV"',
    "user material Fortran",
)

RELEVANT_EXTENSIONS: tuple[str, ...] = (".f", ".for", ".f90", ".F", ".F90", ".inc", ".inp")


def build_github_search_urls(terms: Iterable[str] = GITHUB_SEARCH_TERMS) -> list[str]:
    """Build the well-known GitHub Code Search API URLs for the search terms.

    Callers with an API token can hit these directly; the offline tests
    never touch the network.
    """
    urls: list[str] = []
    for term in terms:
        params = {"q": f"{term} language:Fortran"}
        urls.append("https://api.github.com/search/code?" + urllib.parse.urlencode(params))
    return urls


def discover_via_github_api(
    *,
    token: Optional[str],
    allow_network: bool,
    terms: Iterable[str] = GITHUB_SEARCH_TERMS,
) -> list[CorpusCandidate]:
    """Live GitHub-API discovery. Explicit opt-in via ``allow_network=True``.

    This function is a thin wrapper around ``urllib.request`` that emits
    :class:`CorpusCandidate` entries for the top hits per search term. It
    is intentionally minimal (no pagination beyond the first page); a real
    scraper run should use a proper GitHub client library with backoff.
    """
    if not allow_network:
        raise RuntimeError(
            "GitHub API discovery requires 'allow_network=True'. Refusing to "
            "make a network call implicitly."
        )
    import urllib.request as _u  # local import so offline callers never touch it

    candidates: list[CorpusCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for url in build_github_search_urls(terms):
        req = _u.Request(url, headers={"Accept": "application/vnd.github+json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with _u.urlopen(req, timeout=30) as fh:  # noqa: S310  (explicit opt-in)
            payload = json.loads(fh.read().decode("utf-8"))
        for item in payload.get("items", []):
            repo = item.get("repository", {})
            candidates.append(
                CorpusCandidate(
                    repository=repo.get("full_name", ""),
                    file_path=item.get("path", ""),
                    commit_sha=item.get("sha", ""),
                    retrieved_at=now,
                    license_spdx=(repo.get("license") or {}).get("spdx_id"),
                    file_extension=_ext(item.get("path", "")),
                    raw_url=item.get("html_url", ""),
                )
            )
    return candidates


def _ext(path: str) -> str:
    if not path:
        return ""
    idx = path.rfind(".")
    return path[idx:] if idx >= 0 else ""


# ---------------------------------------------------------------------------
# Round metrics
# ---------------------------------------------------------------------------

@dataclass
class RoundMetrics:
    corpus_size: int
    unique_umat_count: int
    transform_success: int
    compile_success: int
    numerical_validation_success: int
    failure_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_size": self.corpus_size,
            "unique_umat_count": self.unique_umat_count,
            "transform_success": self.transform_success,
            "compile_success": self.compile_success,
            "numerical_validation_success": self.numerical_validation_success,
            "failure_counts": dict(self.failure_counts),
        }


def round_metrics(records: Iterable[CorpusRecord]) -> RoundMetrics:
    records = list(records)
    hashes = {r.candidate.normalized_hash for r in records if r.candidate.normalized_hash}
    transform_ok = sum(
        1 for r in records if _passed_at_or_after(r.stage, STAGE_TRANSFORMED) and r.outcome != "failed"
    )
    compile_ok = sum(
        1 for r in records if _passed_at_or_after(r.stage, STAGE_COMPILED) and r.outcome != "failed"
    )
    verified_ok = sum(
        1
        for r in records
        if _passed_at_or_after(r.stage, STAGE_DERIVATIVE_VERIFIED) and r.outcome != "failed"
    )
    counter = Counter(
        r.failure_category for r in records if r.outcome == "failed" and r.failure_category
    )
    return RoundMetrics(
        corpus_size=len(records),
        unique_umat_count=len(hashes),
        transform_success=transform_ok,
        compile_success=compile_ok,
        numerical_validation_success=verified_ok,
        failure_counts=dict(counter),
    )


def _passed_at_or_after(current_stage: str, target: str) -> bool:
    if current_stage not in _STAGE_ORDER or target not in _STAGE_ORDER:
        return False
    return _STAGE_ORDER.index(current_stage) >= _STAGE_ORDER.index(target)


__all__ = [
    "CorpusCandidate",
    "CorpusRecord",
    "FAILURE_CATEGORIES",
    "GITHUB_SEARCH_TERMS",
    "RELEVANT_EXTENSIONS",
    "RoundMetrics",
    "STAGE_COMPILED",
    "STAGE_CONTRACT_BUILT",
    "STAGE_DERIVATIVE_VERIFIED",
    "STAGE_DISCOVERED",
    "STAGE_ENTRY_DETECTED",
    "STAGE_PRIMAL_VERIFIED",
    "STAGE_TRANSFORMED",
    "build_github_search_urls",
    "classify_license",
    "content_hash",
    "deduplicate",
    "detect_entry_routines",
    "detect_source_form",
    "discover_via_github_api",
    "is_redistributable",
    "round_metrics",
]
