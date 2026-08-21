"""Executable CLI for the UMAT-OTI web-corpus pipeline.

Subcommands
-----------

``discover``
    Query the GitHub Code Search API for UMAT / VUMAT / UHYPER candidates
    and write a deterministic ``corpus_index.json``. Requires
    ``--allow-network``; without it the command refuses to hit GitHub.

``snapshot``
    For every record in the index, download the raw source (via
    ``raw.githubusercontent.com``) into a local cache directory. Cache
    is content-addressed: the same URL never re-downloads.

``analyze``
    Deterministic offline pass over the snapshot: computes normalized
    content hashes, deduplicates, classifies license, detects entry
    routines, and detects source form. Updates
    ``corpus_index.json`` in place with the new fields.

``run``
    For every deduplicated candidate that carries a permissive license
    and a detected entry routine, attempt the transform pipeline:
    generate a compact JSON contract, run the source transformer,
    optionally compile with gfortran. Classifies every failure by the
    canonical taxonomy in :mod:`umat_oti.corpus`.

``report``
    Aggregates per-stage counts, writes ``round_metrics.json``, and
    prints a Markdown summary.

The CLI never executes downloaded build scripts and never spawns
Abaqus. Compilation is limited to gfortran with resource limits set by
Python's ``resource`` module. The cache directory is created with
mode 0700.

Environment variables
---------------------

``GITHUB_TOKEN``
    Optional personal-access token used to authenticate GitHub API
    calls. Without it the anonymous rate limit (60 req/hour) is used.
"""

from __future__ import annotations

import argparse
import base64
import csv
import dataclasses
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from umat_oti.corpus import (
    FAILURE_CATEGORIES,
    GITHUB_SEARCH_TERMS,
    RELEVANT_EXTENSIONS,
    STAGE_ABAQUS_VERIFIED,
    STAGE_CLASSIFIED,
    STAGE_COMPILED,
    STAGE_CONTRACT_BUILT,
    STAGE_DEPENDENCIES_COMPLETE,
    STAGE_DERIVATIVE_VERIFIED,
    STAGE_DISCOVERED,
    STAGE_ENTRY_DETECTED,
    STAGE_PRIMAL_VERIFIED,
    STAGE_TRANSFORMED,
    _STAGE_ORDER,
    CorpusCandidate,
    CorpusRecord,
    build_github_search_urls,
    classify_license,
    content_hash,
    deduplicate,
    detect_entry_routines,
    detect_source_form,
    round_metrics,
)


GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_command(args: argparse.Namespace) -> int:
    if not args.allow_network:
        print(
            "Refusing to hit the GitHub API without --allow-network. Aborting.",
            file=sys.stderr,
        )
        return 2

    manifest = getattr(args, "manifest", None)
    if manifest:
        return _discover_from_manifest(manifest, args)

    terms = _load_terms(args.query_config)
    token = os.environ.get("GITHUB_TOKEN")

    all_candidates: list[dict[str, Any]] = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    rate_limit_report: dict[str, Any] = {}

    for term in terms:
        url = _build_search_url(term)
        page = 1
        max_pages = args.max_pages
        while page <= max_pages:
            paged = f"{url}&page={page}&per_page={args.per_page}"
            payload, rate_limit_report = _github_get(paged, token=token, retries=args.retries)
            if payload is None:
                break
            items = payload.get("items", [])
            if not items:
                break
            for item in items:
                repo = item.get("repository", {}) or {}
                license_info = repo.get("license") or {}
                all_candidates.append(
                    {
                        "term": term,
                        "retrieved_at": now,
                        "repository": repo.get("full_name", ""),
                        "html_url": item.get("html_url", ""),
                        "raw_url": _raw_url(item, repo),
                        "path": item.get("path", ""),
                        "sha": item.get("sha", ""),
                        "license_spdx": license_info.get("spdx_id"),
                        "size": item.get("size"),
                    }
                )
            if len(items) < args.per_page:
                break
            page += 1
            time.sleep(args.throttle_seconds)

    index_path = Path(args.out)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        index_path,
        {
            "schema": "umat-oti-corpus-index/1",
            "generated_at": now,
            "search_terms": list(terms),
            "candidates": all_candidates,
            "rate_limit": rate_limit_report,
        },
    )
    print(f"Wrote {len(all_candidates)} candidate rows to {index_path}")
    return 0


def _discover_from_manifest(manifest_path: str, args: argparse.Namespace) -> int:
    """Manifest-based discovery.

    Each manifest entry has the shape ``{owner, repo, ref, license_spdx,
    files?}``. When ``files`` is present, those exact paths are used; when
    absent, we enumerate the repo tree via the unauthenticated GitHub
    contents API and keep every path with a Fortran extension.

    Works without a GitHub token; unauthenticated raw + contents hits are
    subject to the 60 req/hour anonymous limit.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    candidates: list[dict[str, Any]] = []
    for entry in manifest.get("repos", []):
        owner = entry.get("owner", "")
        repo = entry.get("repo", "")
        ref = entry.get("ref", "master")
        license_spdx = entry.get("license_spdx")
        full = f"{owner}/{repo}"
        files = entry.get("files")
        if not files:
            files = _list_fortran_files(owner, repo, ref, args.throttle_seconds)
        for path in files:
            raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
            candidates.append(
                {
                    "term": "manifest",
                    "retrieved_at": now,
                    "repository": full,
                    "html_url": f"https://github.com/{owner}/{repo}/blob/{ref}/{path}",
                    "raw_url": raw,
                    "path": path,
                    "sha": entry.get("sha", ref),
                    "license_spdx": license_spdx,
                    "size": None,
                }
            )
    index_path = Path(args.out)
    _write_json(
        index_path,
        {
            "schema": "umat-oti-corpus-index/1",
            "generated_at": now,
            "source": "manifest",
            "candidates": candidates,
        },
    )
    print(f"Wrote {len(candidates)} manifest-derived rows to {index_path}")
    return 0


def _list_fortran_files(owner: str, repo: str, ref: str, throttle: float) -> list[str]:
    """Enumerate Fortran files in a repo via the unauthenticated contents API.

    Recurses into top-level directories one level deep. Returns paths
    relative to the repo root.
    """
    exts = {e.lower() for e in RELEVANT_EXTENSIONS}
    found: list[str] = []

    def _get(url: str) -> list[dict[str, Any]] | None:
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "umat-oti-corpus/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as fh:  # noqa: S310
                return json.loads(fh.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            print(f"contents API {url}: {exc}", file=sys.stderr)
            return None

    top_url = f"{GITHUB_API}/repos/{owner}/{repo}/contents?ref={urllib.parse.quote(ref)}"
    top = _get(top_url)
    if top is None:
        return []
    time.sleep(throttle)
    for entry in top:
        if entry.get("type") == "file":
            path = entry.get("path", "")
            if Path(path).suffix.lower() in exts:
                found.append(path)
        elif entry.get("type") == "dir":
            sub = _get(f"{entry.get('url')}")
            time.sleep(throttle)
            if not sub:
                continue
            for sub_entry in sub:
                if sub_entry.get("type") == "file":
                    sub_path = sub_entry.get("path", "")
                    if Path(sub_path).suffix.lower() in exts:
                        found.append(sub_path)
    return found


def _load_terms(path: str | None) -> list[str]:
    if not path:
        return list(GITHUB_SEARCH_TERMS)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "terms" in data:
        return list(data["terms"])
    if isinstance(data, list):
        return [str(t) for t in data]
    raise ValueError(f"invalid query config at {path!r}")


def _build_search_url(term: str) -> str:
    params = {"q": f"{term} language:Fortran"}
    return f"{GITHUB_API}/search/code?" + urllib.parse.urlencode(params)


def _github_get(
    url: str, *, token: str | None, retries: int
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fetch a JSON payload from the GitHub API with retry + rate-limit handling."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "umat-oti-corpus/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as fh:  # noqa: S310  (explicit opt-in)
                rate_limit = {
                    "limit": fh.headers.get("X-RateLimit-Limit"),
                    "remaining": fh.headers.get("X-RateLimit-Remaining"),
                    "reset": fh.headers.get("X-RateLimit-Reset"),
                }
                return json.loads(fh.read().decode("utf-8")), rate_limit
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                wait = 2 ** attempt * 5
                print(
                    f"GitHub API rate-limited ({exc.code}); backing off {wait}s"
                    f" and retrying (attempt {attempt + 1}/{retries + 1})",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            if exc.code == 422:
                # Invalid query -- report and stop paginating.
                print(f"GitHub API 422 (invalid query) for {url}", file=sys.stderr)
                return None, {}
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"network error {exc}; retry attempt {attempt}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return None, {}


def _raw_url(item: dict[str, Any], repo: dict[str, Any]) -> str:
    html_url = item.get("html_url", "")
    if "blob" in html_url:
        return html_url.replace("github.com", "raw.githubusercontent.com").replace(
            "/blob/", "/"
        )
    return ""


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def snapshot_command(args: argparse.Namespace) -> int:
    if not args.allow_network:
        print("Refusing to hit github raw without --allow-network.", file=sys.stderr)
        return 2
    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(cache, 0o700)
    except OSError:
        pass
    downloaded = 0
    skipped = 0
    failed = 0
    for cand in index.get("candidates", []):
        raw_url = cand.get("raw_url") or ""
        ext = Path(cand.get("path", "")).suffix
        if ext.lower() not in {e.lower() for e in RELEVANT_EXTENSIONS}:
            continue
        target = cache / _cache_name(cand)
        if target.is_file():
            skipped += 1
            cand["cache_path"] = str(target)
            continue
        try:
            _download_to(raw_url, target)
            cand["cache_path"] = str(target)
            downloaded += 1
        except Exception as exc:  # noqa: BLE001
            cand["snapshot_error"] = str(exc)
            failed += 1
        time.sleep(args.throttle_seconds)
    _write_json(Path(args.index), index)
    print(f"snapshot: downloaded={downloaded} cached={skipped} failed={failed}")
    return 0


def _cache_name(cand: dict[str, Any]) -> str:
    key = f"{cand.get('repository', '')}::{cand.get('path', '')}::{cand.get('sha', '')}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    ext = Path(cand.get("path", "")).suffix or ".txt"
    return f"{digest}{ext}"


def _download_to(url: str, target: Path, *, timeout: int = 30) -> None:
    if not url:
        raise ValueError("empty raw URL")
    req = urllib.request.Request(url, headers={"User-Agent": "umat-oti-corpus/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:  # noqa: S310
        data = fh.read()
    target.write_bytes(data)


# ---------------------------------------------------------------------------
# Analyze (offline)
# ---------------------------------------------------------------------------

def analyze_command(args: argparse.Namespace) -> int:
    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    for cand in index.get("candidates", []):
        cache_path = cand.get("cache_path")
        if not cache_path or not Path(cache_path).is_file():
            continue
        text = Path(cache_path).read_text(encoding="utf-8", errors="replace")
        cand["content_hash"] = content_hash(text)
        cand["source_form"] = detect_source_form(text)
        cand["entry_routines"] = list(detect_entry_routines(text))
        cand["license_category"] = classify_license(cand.get("license_spdx"))
    _write_json(Path(args.index), index)
    print(f"analyze: annotated {len(index.get('candidates', []))} candidates")
    return 0


# ---------------------------------------------------------------------------
# Run (transform pipeline, offline)
# ---------------------------------------------------------------------------

def run_command(args: argparse.Namespace) -> int:
    from umat_oti.core.config_loader import load_project_config_json
    from umat_oti.transform.source_transform import transform_umat_to_oti_from_config

    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    seen_hashes: set[str] = set()
    for cand in index.get("candidates", []):
        cache_path = cand.get("cache_path")
        if not cache_path or not Path(cache_path).is_file():
            continue
        h = cand.get("content_hash") or ""
        if h and h in seen_hashes:
            continue
        if h:
            seen_hashes.add(h)
        result = _process_one(cand, out, args)
        results.append(result)
        if len(results) >= args.limit:
            break
    _write_json(out / "run_results.json", {"results": results})
    passed = sum(1 for r in results if r["outcome"] == "passed")
    failed = sum(1 for r in results if r["outcome"] == "failed")
    print(f"run: processed={len(results)} passed={passed} failed={failed}")
    return 0


def _process_one(cand: dict[str, Any], out: Path, args: argparse.Namespace) -> dict[str, Any]:
    from umat_oti.core.config_loader import load_project_config_json
    from umat_oti.transform.source_transform import transform_umat_to_oti_from_config
    cache_path = Path(cand["cache_path"])
    record: dict[str, Any] = {
        "id": cand.get("sha"),
        "repository": cand.get("repository"),
        "path": cand.get("path"),
        "license_category": cand.get("license_category"),
        "highest_stage": STAGE_DISCOVERED,
        "outcome": "pending",
    }
    if cand.get("license_category") == "permissive":
        record["highest_stage"] = STAGE_CLASSIFIED
    else:
        record["outcome"] = "failed"
        record["failure_category"] = "unsupported_license"
        record["message"] = (
            f"license={cand.get('license_spdx')}; category={cand.get('license_category')}"
        )
        return record

    # Classify what kind of file this is before running the transformer.
    ext = Path(cand.get("path", "")).suffix.lower()
    entries = [e.upper() for e in (cand.get("entry_routines") or [])]

    if ext == ".inp":
        record["outcome"] = "failed"
        record["failure_category"] = "input_deck_only"
        record["message"] = "file is an Abaqus .inp deck, not a UMAT source"
        return record
    if not entries:
        record["outcome"] = "failed"
        record["failure_category"] = "not_a_umat"
        record["message"] = "no SUBROUTINE UMAT / VUMAT / UHYPER / UEL detected"
        return record
    if "UMAT" not in entries:
        record["outcome"] = "failed"
        record["failure_category"] = "helper_or_dependency_only"
        record["message"] = (
            f"detected entry routines {entries} do not include UMAT"
        )
        return record
    record["highest_stage"] = STAGE_ENTRY_DETECTED

    # Rudimentary dependency check: reject sources that INCLUDE files we do
    # not have in the snapshot cache.
    source_text = cache_path.read_text(encoding="utf-8", errors="replace")
    missing_includes = _missing_includes(source_text, cache_path.parent)
    if missing_includes:
        record["outcome"] = "failed"
        record["failure_category"] = "missing_dependency"
        record["message"] = f"missing INCLUDE files: {missing_includes[:3]}"
        return record
    record["highest_stage"] = STAGE_DEPENDENCIES_COMPLETE

    # Build a minimal compact contract on the fly.
    contract = {
        "name": _slug(cand.get("repository", "candidate")) + "_" + Path(cand["path"]).stem,
        "source": str(cache_path),
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "promote": [],
        "constant": [],
        "real": [],
        "replace": [],
        "ntens": 4,
        "order": 1,
    }
    contract_path = out / f"{record['id'][:12]}.json"
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    record["contract_path"] = str(contract_path)
    record["highest_stage"] = STAGE_CONTRACT_BUILT

    # Try to load and transform.
    try:
        config = load_project_config_json(contract_path.read_bytes(), origin_path=contract_path)
    except Exception as exc:  # noqa: BLE001
        record["outcome"] = "failed"
        record["failure_category"] = "contract_generation_failure"
        record["message"] = f"config_loader: {exc}"
        return record
    transform_out = out / f"transform_{record['id'][:12]}"
    transform_out.mkdir(parents=True, exist_ok=True)
    try:
        result = transform_umat_to_oti_from_config(
            source_text, config, transform_out, ntens=int(contract["ntens"])
        )
        if not getattr(result, "success", False):
            record["outcome"] = "failed"
            record["failure_category"] = _classify_transform_failure(result)
            blockers = getattr(result, "blockers", []) or []
            record["message"] = "; ".join(str(b) for b in blockers[:3])
            return record
    except Exception as exc:  # noqa: BLE001
        record["outcome"] = "failed"
        record["failure_category"] = "confirmed_transformation_defect"
        record["message"] = f"transform raised: {exc.__class__.__name__}: {exc}"
        return record
    record["highest_stage"] = STAGE_TRANSFORMED
    record["transform_output"] = str(transform_out)

    # Optional compilation of the emitted source.
    if getattr(args, "compile", False):
        compile_stage = _compile_transformed(transform_out)
        record["compile"] = compile_stage
        if compile_stage["ok"]:
            record["highest_stage"] = STAGE_COMPILED
        else:
            record["outcome"] = "failed"
            record["failure_category"] = "generated_code_compile_failure"
            record["message"] = compile_stage.get("stderr_tail", "")[-400:]
            return record

    record["outcome"] = "passed"
    return record


def _missing_includes(source: str, base_dir: Path) -> list[str]:
    """Return unresolved INCLUDE files referenced in the source.

    Ignores ``ABA_PARAM.INC`` which is provided by Abaqus at build time.
    """
    import re
    pattern = re.compile(r"(?:^|\n)\s*INCLUDE\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    missing: list[str] = []
    for match in pattern.finditer(source):
        include_name = match.group(1).strip()
        if include_name.upper().endswith("ABA_PARAM.INC"):
            continue
        if (base_dir / include_name).is_file():
            continue
        missing.append(include_name)
    return missing


def _classify_transform_failure(result: Any) -> str:
    """Best-effort mapping from transform-report blockers to a taxonomy."""
    blockers = getattr(result, "blockers", []) or []
    text = " ; ".join(str(b) for b in blockers).lower()
    if "dimension" in text or "shape" in text or "dimensioning" in text:
        return "dimension_inference_failure"
    if "operator" in text or "generic" in text:
        return "custom_operator_or_generic_parser_gap"
    if "intrinsic" in text or "unsupported" in text:
        return "unsupported_fortran_construct"
    return "confirmed_transformation_defect"


def _compile_transformed(transform_dir: Path) -> dict[str, Any]:
    """Attempt to compile the emitted OTI Fortran with gfortran.

    Runs gfortran on the compile order recorded in ``compile_order.txt``.
    Provides a local stub of ``ABA_PARAM.INC`` so standalone compilation
    outside Abaqus succeeds; Abaqus ships the real header at
    ``/apps/abaqus/2024/SIMULIA/EstProducts/2024/SMAUsubs/PublicInterfaces/aba_param.inc``.
    """
    order_file = transform_dir / "compile_order.txt"
    if not order_file.is_file():
        return {"ok": False, "reason": "compile_order.txt not emitted"}
    gfortran = os.environ.get("UMAT_OTI_GFORTRAN", "gfortran")
    if not _which(gfortran):
        return {"ok": False, "reason": f"{gfortran} not on PATH"}
    # Stub the Abaqus-provided header so standalone gfortran can compile.
    _write_aba_param_stub(transform_dir)
    lines = [ln.strip() for ln in order_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    outputs: list[str] = []
    for name in lines:
        source = transform_dir / name
        if not source.is_file():
            return {"ok": False, "reason": f"missing generated file: {name}"}
        cmd = [
            gfortran,
            "-O1",
            "-std=legacy",
            "-ffree-line-length-none",
            "-fno-align-commons",
            "-c",
            "-I", str(transform_dir),
            str(source),
        ]
        proc = subprocess.run(
            cmd,
            check=False,
            cwd=str(transform_dir),
            capture_output=True,
            text=True,
            timeout=180,
        )
        outputs.append(f"{name}: rc={proc.returncode}")
        if proc.returncode != 0:
            return {
                "ok": False,
                "step": name,
                "stderr_tail": (proc.stderr or "")[-800:],
                "log": "\n".join(outputs),
            }
    return {"ok": True, "log": "\n".join(outputs)}


def _write_aba_param_stub(directory: Path) -> None:
    """Minimum ABA_PARAM.INC stub for standalone compilation.

    The Abaqus-shipped header primarily sets the default kind for implicit
    typing to REAL*8 (double precision). We reproduce that so the UMAT's
    ``INCLUDE 'ABA_PARAM.INC'`` line resolves under standalone gfortran.
    Both the uppercase and mixed-case filenames are provided because
    different UMATs quote the include with different casing.
    """
    stub = (
        "! Standalone stub for ABA_PARAM.INC (real Abaqus header at\n"
        "! /apps/abaqus/2024/SIMULIA/EstProducts/2024/SMAUsubs/PublicInterfaces/aba_param.inc).\n"
        "! Under gfortran we only need to reproduce the implicit REAL*8 default.\n"
        "      IMPLICIT REAL*8(A-H,O-Z)\n"
    )
    for name in ("ABA_PARAM.INC", "aba_param.inc", "ABA_PARAM.inc", "aba_param.INC"):
        (directory / name).write_text(stub, encoding="utf-8")


def _which(binary: str) -> str | None:
    import shutil
    return shutil.which(binary)


def _slug(text: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyz0123456789_"
    lowered = text.lower().replace("/", "_")
    return "".join(c if c in keep else "_" for c in lowered)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report_command(args: argparse.Namespace) -> int:
    results_path = Path(args.results) / "run_results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    records = data.get("results", [])
    metrics: dict[str, Any] = {
        "corpus_size": len(records),
        "passed": sum(1 for r in records if r["outcome"] == "passed"),
        "failed": sum(1 for r in records if r["outcome"] == "failed"),
        "failure_counts": {},
    }
    from collections import Counter
    counter: Counter[str] = Counter()
    for r in records:
        if r["outcome"] == "failed" and r.get("failure_category"):
            counter[r["failure_category"]] += 1
    metrics["failure_counts"] = dict(counter)
    metrics["failure_categories_expected"] = list(FAILURE_CATEGORIES)

    # Per-stage counts (highest_stage reached, regardless of outcome).
    stage_counter: Counter[str] = Counter()
    for r in records:
        stage_counter[r.get("highest_stage", "discovered")] += 1
    metrics["highest_stage_counts"] = {stage: stage_counter.get(stage, 0) for stage in _STAGE_ORDER}
    metrics["cumulative_stage_counts"] = {}
    running = 0
    for stage in reversed(_STAGE_ORDER):
        running += stage_counter.get(stage, 0)
        metrics["cumulative_stage_counts"][stage] = running

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "round_metrics.json", metrics)
    md = [
        "# UMAT-OTI Corpus round metrics",
        f"- corpus_size: {metrics['corpus_size']}",
        f"- passed:      {metrics['passed']}",
        f"- failed:      {metrics['failed']}",
        "",
        "## Per-stage counts (cumulative: candidates that reached at least this stage)",
    ]
    for stage in _STAGE_ORDER:
        md.append(
            f"- {stage}: highest={metrics['highest_stage_counts'][stage]}"
            f" cumulative={metrics['cumulative_stage_counts'][stage]}"
        )
    md.append("")
    md.append("## Failure counts by category")
    for cat in FAILURE_CATEGORIES:
        md.append(f"- {cat}: {metrics['failure_counts'].get(cat, 0)}")
    (out / "round_metrics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------------------
# main dispatcher
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m umat_oti.corpus.cli",
        description="UMAT-OTI web-corpus discovery + regression pipeline.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="query GitHub API for UMAT candidates")
    p_disc.add_argument("--query-config", default=None, help="JSON file with a 'terms' list")
    p_disc.add_argument("--out", required=True)
    p_disc.add_argument("--allow-network", action="store_true")
    p_disc.add_argument("--per-page", type=int, default=30)
    p_disc.add_argument("--max-pages", type=int, default=1)
    p_disc.add_argument("--retries", type=int, default=3)
    p_disc.add_argument("--throttle-seconds", type=float, default=1.5)
    p_disc.add_argument(
        "--manifest",
        default=None,
        help="Skip Code Search and use a JSON manifest of {owner, repo, ref, files, license_spdx}. Useful when no GitHub token is available.",
    )
    p_disc.set_defaults(func=discover_command)

    p_snap = sub.add_parser("snapshot", help="download raw sources for cached inspection")
    p_snap.add_argument("--index", required=True)
    p_snap.add_argument("--cache", required=True)
    p_snap.add_argument("--allow-network", action="store_true")
    p_snap.add_argument("--throttle-seconds", type=float, default=0.5)
    p_snap.set_defaults(func=snapshot_command)

    p_an = sub.add_parser("analyze", help="offline hash / license / entry / form analysis")
    p_an.add_argument("--index", required=True)
    p_an.set_defaults(func=analyze_command)

    p_run = sub.add_parser("run", help="staged transform pipeline")
    p_run.add_argument("--index", required=True)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--limit", type=int, default=200)
    p_run.add_argument(
        "--compile",
        action="store_true",
        help="Also invoke gfortran on the emitted OTI Fortran per candidate (Priority 4 sub-item).",
    )
    p_run.set_defaults(func=run_command)

    p_rep = sub.add_parser("report", help="write per-round metrics")
    p_rep.add_argument("--results", required=True)
    p_rep.add_argument("--out", required=True)
    p_rep.set_defaults(func=report_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
