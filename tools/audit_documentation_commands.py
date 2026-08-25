#!/usr/bin/env python
"""Check that documented commands and links actually resolve.

Documentation that names a script, module or file which does not exist is worse
than no documentation: a reviewer follows it, it fails, and they cannot tell
whether the software is broken or the instructions are stale. This audit
resolves what it can statically:

- ``python -m <module>`` -- the module must be importable
- ``python tools/<script>`` / ``./scripts/<script>`` -- the file must exist
- ``make <target>`` -- the target must exist in the Makefile
- markdown links to repository-relative paths -- the path must exist

It does not execute anything. Commands whose effect needs a compiler, a network
or Abaqus are proven by the reproduction profiles and the clean-clone script,
not here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DOC_GLOBS = ("*.md", "docs/*.md")

_FENCE = re.compile(r"```(?:bash|sh|console)?\n(.*?)```", re.DOTALL)
_PY_MODULE = re.compile(r"python[0-9.]*\s+-m\s+([A-Za-z_][\w.]*)")
_PY_SCRIPT = re.compile(r"python[0-9.]*\s+((?:tools|scripts|src)/[\w./-]+\.py)")
_SH_SCRIPT = re.compile(r"(?:^|\s)(\./(?:scripts|tools)/[\w./-]+\.sh)")
_MAKE = re.compile(r"(?:^|\s)make\s+([a-z][\w-]*)")
_LINK = re.compile(r"\[[^\]]*\]\(([^)#:]+?)(?:#[^)]*)?\)")

#: Modules named in documentation that are third-party or standard-library
#: rather than part of this package.
EXTERNAL_MODULES = {"venv", "pip", "pytest", "build", "twine"}


def doc_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True)
    return [REPO_ROOT / name for name in out.stdout.split("\0") if name]


def _make_targets() -> set[str]:
    path = REPO_ROOT / "Makefile"
    if not path.is_file():
        return set()
    return set(re.findall(r"^([a-z][\w-]*):", path.read_text(encoding="utf-8"),
                          re.MULTILINE))


def audit() -> list[dict]:
    problems: list[dict] = []
    targets = _make_targets()

    for doc in doc_files():
        relative = doc.relative_to(REPO_ROOT)
        text = doc.read_text(encoding="utf-8", errors="replace")

        for link in _LINK.finditer(text):
            target = link.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (doc.parent / target).resolve()
            if not resolved.exists():
                problems.append({"doc": str(relative), "kind": "broken_link",
                                 "detail": target})

        for block in _FENCE.findall(text):
            for module in _PY_MODULE.findall(block):
                root = module.split(".")[0]
                if root in EXTERNAL_MODULES:
                    continue
                if importlib.util.find_spec(module) is None:
                    problems.append({"doc": str(relative), "kind": "missing_module",
                                     "detail": f"python -m {module}"})
            for script in _PY_SCRIPT.findall(block):
                if not (REPO_ROOT / script).is_file():
                    problems.append({"doc": str(relative), "kind": "missing_script",
                                     "detail": script})
            for script in _SH_SCRIPT.findall(block):
                candidate = REPO_ROOT / script.lstrip("./")
                if not candidate.is_file():
                    problems.append({"doc": str(relative), "kind": "missing_script",
                                     "detail": script})
                elif not candidate.stat().st_mode & 0o111:
                    problems.append({"doc": str(relative), "kind": "script_not_executable",
                                     "detail": script})
            for target in _MAKE.findall(block):
                if targets and target not in targets:
                    problems.append({"doc": str(relative), "kind": "missing_make_target",
                                     "detail": f"make {target}"})
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(REPO_ROOT / "src"))
    problems = audit()
    if args.json:
        print(json.dumps({"problems": problems}, indent=2))
    elif problems:
        for problem in problems:
            print(f"[FAIL] {problem['doc']}: {problem['kind']}: {problem['detail']}")
        print(f"\n{len(problems)} documentation problems")
    else:
        print(f"[PASS] every documented command, script and link resolves "
              f"({len(doc_files())} documents checked)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
