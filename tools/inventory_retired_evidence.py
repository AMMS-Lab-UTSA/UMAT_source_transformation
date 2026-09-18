"""Inventory retained historical artifacts without modifying their evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path


SCOPES = {
    "UMAT": ("umat/", "tests/fixtures/", "paper_results/"),
    "RA": ("tests/fixtures/verified/",),
}


def generations(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if "fingerprint" in key and isinstance(child, str) and len(child) == 16:
                found.add(child)
            found.update(generations(child))
    elif isinstance(value, list):
        for child in value:
            found.update(generations(child))
    return found


def inventory(root: Path, scopes: tuple) -> list:
    names = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    ).decode().split("\0")
    artifacts = []
    for name in sorted(set(names)):
        if not name.startswith(scopes):
            continue
        path = root / name
        data = path.read_bytes()
        fingerprints = set()
        parse_error = ""
        try:
            if path.suffix == ".json":
                fingerprints.update(generations(json.loads(data)))
            elif path.suffix == ".jsonl":
                for line in data.splitlines():
                    if line.strip():
                        fingerprints.update(generations(json.loads(line)))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            parse_error = str(error)
        artifacts.append({
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "recorded_fingerprints": sorted(fingerprints),
            "parse_error": parse_error,
        })
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--umat", type=Path, required=True)
    parser.add_argument("--ra", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = {
        "schema": "recovery-retired-evidence-inventory/1",
        "status": "historical_only",
        "scope": "All tracked and nonignored files in the listed historical evidence trees, including supporting files without embedded generations. Hashes describe retained bytes, not current verification.",
        "repositories": {},
    }
    for label, root in (("UMAT", args.umat), ("RA", args.ra)):
        artifacts = inventory(root, SCOPES[label])
        payload["repositories"][label] = {"prefixes": SCOPES[label], "artifacts": artifacts}
        print(label, len(artifacts), dict(Counter(
            fingerprint for artifact in artifacts
            for fingerprint in artifact["recorded_fingerprints"])))
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()