"""One envelope every service returns, so the CLI and the GUI read the same thing.

The owner's requirement is that the interface calls reusable backend services
and does not duplicate verification logic. That only holds if a service returns
a *schema* rather than a dict of whatever fell out: the moment a caller has to
reach into an untyped payload and decide what a missing key means, the decision
has moved back into the caller, and the CLI and the GUI start disagreeing.

So every service returns a :class:`ServiceResult`. It carries:

``ok``
    whether the service *ran*. It is not a verdict about the science. A
    verification that ran perfectly and found the derivatives wrong is
    ``ok=True`` with a verdict of failure in ``data``.
``outcome``
    a short machine word for what happened, from that service's own vocabulary.
``problems``
    everything that went wrong, not just the first thing.
``provenance``
    the commit and the inputs, so a screenshot can be traced to a run.
``data``
    the typed payload, defined per service.
``evidence_paths``
    files a reader can open. Never a summary in place of the file.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "SCHEMA",
    "SEVERITIES",
    "Problem",
    "Provenance",
    "ServiceResult",
    "repo_commit",
]

SCHEMA = "umat-oti/service-result/1"

#: ``blocker`` stops the service producing a result at all; ``warning`` is a
#: result a reader must qualify; ``note`` is provenance worth carrying.
SEVERITIES = ("blocker", "warning", "note")


@dataclass
class Problem:
    """One thing that went wrong, with where it went wrong."""

    code: str
    message: str
    where: str = ""
    severity: str = "blocker"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Provenance:
    """Enough to tie a result to the code and the inputs that produced it."""

    commit: str = ""
    commit_dirty: Optional[bool] = None
    generated_at: str = ""
    service_version: str = "1"
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ServiceResult:
    """What every service in this package returns."""

    service: str
    outcome: str
    ok: bool = True
    schema: str = SCHEMA
    problems: list[Problem] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    data: Any = None
    evidence_paths: dict[str, str] = field(default_factory=dict)

    @property
    def blockers(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "blocker"]

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "warning"]

    def add(self, code: str, message: str, *, where: str = "",
            severity: str = "blocker") -> "ServiceResult":
        self.problems.append(Problem(code, message, where, severity))
        if severity == "blocker":
            self.ok = False
        return self

    def as_dict(self) -> dict:
        payload = self.data
        if hasattr(payload, "as_dict"):
            payload = payload.as_dict()
        elif isinstance(payload, list):
            payload = [p.as_dict() if hasattr(p, "as_dict") else p
                       for p in payload]
        return {
            "schema": self.schema,
            "service": self.service,
            "ok": self.ok,
            "outcome": self.outcome,
            "problems": [p.as_dict() for p in self.problems],
            "provenance": self.provenance.as_dict(),
            "data": payload,
            "evidence_paths": dict(self.evidence_paths),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True,
                          default=str) + "\n"


#: How long a commit/dirty reading is reused before git is asked again.
#: Every service stamps its provenance, and a GUI polling a running job would
#: otherwise run ``git status`` on a large repository on every tick. Short
#: enough that a commit made during a session is picked up within seconds;
#: long enough that provenance costs nothing to record.
COMMIT_CACHE_SECONDS = 5.0

_COMMIT_CACHE: dict[str, tuple[float, str, Optional[bool]]] = {}


def repo_commit(repo_root: Optional[Path]) -> tuple[str, Optional[bool]]:
    """``(commit, dirty)`` for a checkout, or ``("", None)`` when git cannot say.

    ``dirty`` stays ``None`` rather than ``False`` where the question could not
    be asked: "not known to be dirty" and "known to be clean" are different
    claims and only one of them belongs beside a published number.
    """
    if repo_root is None:
        return "", None
    key = str(repo_root)
    cached = _COMMIT_CACHE.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < COMMIT_CACHE_SECONDS:
        return cached[1], cached[2]
    try:
        head = subprocess.run(  # noqa: S603 - list form, fixed arguments
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False)
        if head.returncode != 0:
            return "", None
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30, check=False)
        dirty = None if status.returncode != 0 else bool(status.stdout.strip())
        commit = head.stdout.strip()
        _COMMIT_CACHE[key] = (now, commit, dirty)
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return "", None
