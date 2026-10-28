"""Write SHA256SUMS for every archived file under evidence/<commit>/ (Ada, 2026-10-27).

Usage: python refreeze/scripts/hash_evidence.py <sha7> [<sha7> ...]
Skips caches. Paths in the sums file are relative to evidence/<sha7>/.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
SKIP = {".pytest_cache", "__pycache__"}


def main(argv: list[str]) -> int:
    for sha in argv:
        root = WS / "evidence" / sha
        lines = []
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.name == "SHA256SUMS" or SKIP.intersection(p.parts):
                continue
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{digest}  {p.relative_to(root).as_posix()}")
        # LF line endings, so `sha256sum -c SHA256SUMS` works (Vera O2: CRLF broke it).
        (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(sha, len(lines), "files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
