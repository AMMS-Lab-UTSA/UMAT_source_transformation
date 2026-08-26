"""The frozen evidence must verify from a clean clone, not just here.

A snapshot is only useful if a reviewer who clones the repository can check
it. Verifying the working tree does not establish that: git can apply an
end-of-line filter when it writes the object, so the bytes a clone receives
differ from the bytes that were hashed. That happened once, silently, and the
working-tree check still passed -- so this test reads the committed blobs.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN = REPO_ROOT / "paper_results" / "frozen"


def _snapshots() -> list[Path]:
    if not FROZEN.is_dir():
        return []
    return sorted(p for p in FROZEN.iterdir() if (p / "SHA256SUMS").is_file())


def _blob(relative: str) -> bytes | None:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-p",
                          f"HEAD:{relative}"], capture_output=True)
    return out.stdout if out.returncode == 0 else None


@pytest.mark.parametrize("snapshot", _snapshots(), ids=lambda p: p.name)
def test_committed_snapshot_matches_its_checksums(snapshot: Path) -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout, so there are no committed blobs to read")

    prefix = snapshot.relative_to(REPO_ROOT).as_posix()
    entries = []
    for line in (snapshot / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        entries.append((digest, name.strip().lstrip("*")))
    assert entries, "the snapshot records no checksums"

    missing, wrong = [], []
    for digest, name in entries:
        data = _blob(f"{prefix}/{name}")
        if data is None:
            missing.append(name)
        elif hashlib.sha256(data).hexdigest() != digest:
            wrong.append(name)

    assert not missing, f"not committed: {missing}"
    assert not wrong, (
        f"committed bytes differ from the recorded digest: {wrong}. "
        "Check .gitattributes -- the frozen tree must be marked -text.")
