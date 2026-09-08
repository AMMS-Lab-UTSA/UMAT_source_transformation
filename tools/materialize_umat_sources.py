"""Fetch the sources behind the ``umat/`` collection onto this machine.

The collection records what was verified and what happened, but not the UMATs
themselves. They are other people's files, mirrored for study, and a public
repository without an explicit licence grant is not permission to redistribute
them. What is committed is each material's identity: the upstream repository,
the path within it, and the SHA-256 of the exact bytes that were verified.

This puts those bytes back on the machine that needs them, under
``umat/materialized/`` -- an ignored directory -- and refuses anything whose
digest does not match what was verified. A file that has changed upstream is
not the file the evidence is about, and quietly using it would attach an old
verdict to new bytes.

The usual source is the local discovery mirror, which already holds them. The
``--allow-network`` path clones from upstream for a machine that has no
mirror, and is off by default because a verification run should not depend on
the network being up or on upstream still existing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "umat"
MATERIALIZED = "materialized"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _from_mirror(source_id: str, cache: Path) -> Optional[Path]:
    candidate = cache / source_id
    return candidate if candidate.is_file() else None


def _from_upstream(source_id: str, repository: str, into: Path) -> Optional[Path]:
    """Clone the repository shallowly and take the one file out of it."""
    if not repository:
        return None
    with tempfile.TemporaryDirectory() as scratch:
        clone = Path(scratch) / "clone"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet",
             f"https://github.com/{repository}.git", str(clone)],
            capture_output=True, text=True, timeout=600)
        if result.returncode:
            return None
        # The mirror flattens the owner and repository into the first path
        # component; upstream does not have it.
        inside = Path(*Path(source_id).parts[1:])
        found = clone / inside
        if not found.is_file():
            return None
        into.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found, into)
        return into


def materialize(root: Path, cache: Path, allow_network: bool) -> dict:
    registry_path = root / "registry.json"
    if not registry_path.is_file():
        raise SystemExit(
            f"no registry at {registry_path}. Nothing has been promoted yet; "
            f"run tools/promote_verified_umats.py first.")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    target_root = root / MATERIALIZED
    target_root.mkdir(parents=True, exist_ok=True)
    counts = {"already_present": 0, "from_mirror": 0, "from_upstream": 0,
              "digest_mismatch": 0, "not_found": 0}
    mismatched: list[str] = []
    missing: list[str] = []

    for entry in registry.get("materials", []):
        source_id = str(entry.get("source_id") or "")
        expected = str(entry.get("source_sha256") or "")
        target = target_root / source_id
        if target.is_file() and expected and _sha256(target) == expected:
            counts["already_present"] += 1
            continue

        found = _from_mirror(source_id, cache)
        origin = "from_mirror"
        if found is None and allow_network:
            found = _from_upstream(source_id, str(entry.get("repository") or ""),
                                   target)
            origin = "from_upstream"
        if found is None:
            counts["not_found"] += 1
            missing.append(source_id)
            continue

        if expected and _sha256(found) != expected:
            # Not the bytes the evidence is about. Refused rather than used.
            counts["digest_mismatch"] += 1
            mismatched.append(source_id)
            if origin == "from_upstream" and target.is_file():
                target.unlink()
            continue

        if origin == "from_mirror":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(found, target)
        counts[origin] += 1

    return {"counts": counts, "mismatched": mismatched, "missing": missing,
            "root": str(target_root), "materials": len(registry.get("materials", []))}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--cache-dir", type=Path,
                        default=Path.home() / "softwarex_work" / "discovery_cache",
                        help="the local discovery mirror, tried first")
    parser.add_argument("--allow-network", action="store_true",
                        help="clone from upstream for anything the mirror "
                             "does not hold. Off by default: a verification "
                             "run should not depend on the network being up.")
    args = parser.parse_args(argv)

    report = materialize(args.root, args.cache_dir, args.allow_network)
    counts = report["counts"]
    print(f"{report['materials']} materials in the registry")
    for name, value in counts.items():
        if value:
            print(f"  {value:>4}  {name.replace('_', ' ')}")
    if report["mismatched"]:
        print("\nREFUSED -- the file no longer has the digest that was verified:")
        for source_id in report["mismatched"][:10]:
            print(f"    {source_id}")
        print("  These are not the bytes the evidence is about. Attaching the "
              "old verdict to them would be wrong.")
    if report["missing"]:
        print(f"\nnot found ({len(report['missing'])}): no mirror copy"
              + (" and no upstream match" if args.allow_network else
                 ", and --allow-network was not given"))
        for source_id in report["missing"][:10]:
            print(f"    {source_id}")
    print(f"\nmaterialized under {report['root']} (git-ignored)")
    return 1 if (report["mismatched"] or report["missing"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
