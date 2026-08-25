#!/usr/bin/env python
"""Acquire external UMAT sources live and write an immutable snapshot manifest.

Network access is opt-in. Without ``--allow-network`` this does nothing and says
so; it never silently falls back to a cached result and calls that a live round.

What it guarantees about its output:

* every accepted repository is pinned to a 40-character commit SHA, never to a
  branch, so an offline replay depends on content rather than on timing;
* a repository whose licence does not permit redistribution is recorded as
  metadata and nothing of it is cached;
* rate limiting, missing licences and network failures are recorded as
  themselves rather than collapsed into "unavailable";
* nothing acquired here is executed. The cache is input to the offline funnel,
  which does the compiling, and only after licence and dependency checks pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.corpus.acquire import (  # noqa: E402
    AcquisitionError, GitHubClient, RateLimited, acquire_repository,
)

DEFAULT_TARGETS = [
    ("jgomezc1", "ABAQUS-US"),
    ("ngrilli", "Oxford_Crystal_Plasticity"),
    ("bibekananda-datta", "Abaqus-UEL-Elasticity"),
    ("bibekananda-datta", "Abaqus-UEL-Hyperelasticity"),
]

OUT = REPO_ROOT / "paper_results" / "corpus"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--allow-network", action="store_true",
                        help="required; without it nothing is fetched")
    parser.add_argument("--repository", action="append", dest="repositories",
                        metavar="OWNER/REPO")
    parser.add_argument("--ref", default="HEAD",
                        help="ref to resolve; the repository's default branch by default")
    parser.add_argument("--cache-root", type=Path, default=None,
                        help="cache permissible sources here for offline replay")
    parser.add_argument("--out", type=Path, default=OUT / "live_acquisition.json")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)

    if not args.allow_network:
        print("live acquisition needs --allow-network. Nothing was fetched and no "
              "cached result was substituted: a live round that quietly replays a "
              "snapshot is not a live round.", file=sys.stderr)
        return 2

    targets = []
    for value in (args.repositories or []):
        if "/" not in value:
            parser.error(f"--repository expects OWNER/REPO, got {value!r}")
        owner, repo = value.split("/", 1)
        targets.append((owner, repo))
    targets = targets or DEFAULT_TARGETS

    client = GitHubClient.discover(timeout=args.timeout)
    print(f"authentication: {client.auth_source}", flush=True)

    snapshots = []
    for owner, repo in targets:
        print(f"[acquire] {owner}/{repo}", flush=True)
        try:
            snapshot = acquire_repository(client, owner, repo, ref=args.ref,
                                          cache_root=args.cache_root)
        except RateLimited as exc:
            print(f"  rate limited: {exc.detail}", file=sys.stderr)
            snapshots.append({"id": f"{owner}_{repo}", "url":
                              f"https://github.com/{owner}/{repo}.git",
                              "failures": [{"stage": "acquire", "code": exc.code,
                                            "detail": exc.detail}]})
            break
        except AcquisitionError as exc:
            snapshots.append({"id": f"{owner}_{repo}",
                              "url": f"https://github.com/{owner}/{repo}.git",
                              "failures": [{"stage": "acquire", "code": exc.code,
                                            "detail": exc.detail}]})
            continue
        payload = snapshot.as_dict()
        snapshots.append(payload)
        print(f"  {payload['requested_ref']} -> {payload['commit_sha']}  "
              f"licence {payload['license_spdx']}  "
              f"redistributable={payload['redistribution_permitted']}  "
              f"fortran={payload['fortran_file_count']}  "
              f"umat_entries={len(payload['umat_entry_files'])}", flush=True)

    moving = [s for s in snapshots
              if s.get("commit_sha") and len(s["commit_sha"]) != 40]
    assert not moving, "a snapshot escaped without a full commit SHA"

    payload = {
        "schema": "umat-oti-live-acquisition/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authentication": client.auth_source,
        "requests_made": client.requests_made,
        "rate_limit_remaining": client.rate_limit_remaining,
        "cache_root_used": str(args.cache_root) if args.cache_root else None,
        "policy": (
            "Every accepted repository is pinned to a 40-character commit SHA. "
            "Sources whose licence does not permit redistribution are recorded "
            "as metadata and never cached. Nothing acquired here is executed."),
        "repositories": snapshots,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    try:
        shown = args.out.relative_to(REPO_ROOT)
    except ValueError:
        shown = args.out
    print(f"\nwrote {shown}")
    failed = sum(1 for s in snapshots if s.get("failures"))
    print(f"{len(snapshots) - failed} of {len(snapshots)} repositories acquired "
          f"cleanly; {client.requests_made} API requests, "
          f"{client.rate_limit_remaining} remaining")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
