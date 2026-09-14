"""Shared plumbing for the services: where the repo is, and how to reach tools/.

Two facts make this module necessary.

The **import trap**: the editable install points at a different checkout, so
``Path(umat_oti.__file__)`` and "the repository" are not automatically the same
tree. Everything here derives the root from *this file*, so a service always
reads the tree it was itself loaded from.

**Heavy logic lives in ``tools/``**, which is not a package:
``verify_store_in_abaqus.py`` is 4859 lines and ``export_residual_fixture.py``
owns the fixture rules. Re-implementing either inside a service is exactly the
duplication the architecture requirement forbids, so the services load those
modules by path and call them. If a tool is missing the service says so and
returns a refusal; it does not fall back to a second copy of the rules.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

__all__ = ["REPO_ROOT", "TOOLS", "load_tool", "ToolUnavailable",
           "read_jsonl", "ensure_src_on_path"]

#: services/ -> umat_oti/ -> src/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"


class ToolUnavailable(ImportError):
    """A ``tools/`` module a service delegates to could not be loaded."""


def ensure_src_on_path() -> str:
    """Put *this* tree's ``src`` first, ahead of any editable install."""
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return src


def load_tool(name: str):
    """Import ``tools/<name>.py`` as a module, or raise :class:`ToolUnavailable`.

    Cached in ``sys.modules`` under a prefixed name so two services loading the
    same tool get the same module object and the tool's own module-level state
    is not duplicated.
    """
    key = f"_umat_oti_tool_{name}"
    if key in sys.modules:
        return sys.modules[key]
    path = TOOLS / f"{name}.py"
    if not path.is_file():
        raise ToolUnavailable(
            f"{path} is not present, so this service cannot delegate to it. "
            f"The rules it owns are not reimplemented here on purpose: two "
            f"copies of a verification rule is how they drift apart.")
    ensure_src_on_path()
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise ToolUnavailable(f"{path} could not be loaded as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as error:
        del sys.modules[key]
        raise ToolUnavailable(f"{path} failed to import: "
                              f"{type(error).__name__}: {error}") from error
    return module


def read_jsonl(path: Path) -> Iterator[dict]:
    """Every object in a JSON-lines file.

    A line that will not parse is yielded as ``{"unparseable": <line>}`` rather
    than skipped: a run whose results file has a torn line has fewer records
    than rows, and silently dropping one makes every count downstream wrong by
    an amount nobody can see.
    """
    path = Path(path)
    if not path.is_file():
        return
    with open(path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                yield {"unparseable": line}
