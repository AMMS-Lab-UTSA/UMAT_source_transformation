"""Can the routine be converted at all? Asked first, before any material question.

``umat-oti all`` asks for the material data first and the routine second, so a
UMAT that calls a helper nobody supplied failed with "no deck with a *USER
MATERIAL block" -- true, and not the reason it could not be checked (Nico, B11:
``jacojvr umat_iso.f``, ``mrkearden UMAT.F90``). ``check`` runs the transformer's
own dependency discovery and anchor location (the first, fast half of the
``jacobian`` step; no compile) before it reads or asks for a single constant, so
the first refusal a person sees is the real one.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

from umat_oti.app.check_intake import SourceFacts

_MISSING = re.compile(r"dependency_roots do not resolve the closure of [^:]+: missing ([^;]+)")


def normalise(text: str) -> str:
    """The pipeline's wording, put in the form the refusal cards recognise."""
    found = _MISSING.search(text or "")
    if found:
        names = [n.strip() for n in found.group(1).split(",") if n.strip()]
        return ("Helper lifting requires source definitions for ["
                + ", ".join(repr(n) for n in names) + "]")
    return text or ""


def unresolved_modules(facts: SourceFacts, roots: Sequence[Path], source: Path) -> list:
    """Modules the source USEs that no file beside it or in the roots defines."""
    defined = {m.lower() for m in facts.modules_defined}
    pattern = re.compile(r"(?im)^\s*module\s+(?!procedure\b)(\w+)\s*$")
    for folder in [source.parent, *roots]:
        folder = Path(folder)
        files = [folder] if folder.is_file() else [
            p for p in folder.rglob("*") if p.suffix.lower() in (".f", ".for", ".f90", ".f95", ".inc")
        ][:400]
        for file in files:
            try:
                defined |= {m.lower() for m in pattern.findall(file.read_text(errors="replace"))}
            except OSError:
                continue
    return [m for m in facts.modules_used if m.lower() not in defined]


def refusal_from_summary(summary: dict, *, exit_code: int = 1, succeeded: bool = False,
                         facts: Optional[SourceFacts] = None, roots: Sequence[Path] = (),
                         source: Optional[Path] = None) -> Optional[tuple]:
    """``(terminal state, reason)`` for what a ``jacobian`` transformation's summary
    says went wrong, or ``None`` when it did not. Shared by ``check``'s preflight
    and by the front door's card for ``umat-oti jacobian``."""
    if summary.get("error"):
        text = normalise(str(summary["error"]))
        state = ("external_dependency_unavailable" if "source definitions" in text
                 else "transform_refused")
        return state, text
    blockers = [str(b) for b in summary.get("blockers") or []]
    if blockers:
        return "transform_refused", "; ".join(blockers)
    if exit_code and not succeeded:
        issues = [str(i.get("kind")) for i in summary.get("completion_issues") or []
                  if isinstance(i, dict)]
        reason = "anchors not located: " + ", ".join(dict.fromkeys(issues) or ["unknown"])
        missing = unresolved_modules(facts, roots, source) if facts is not None and source else []
        if missing:
            reason += (f"; a name appears as NAME(...) on the stress path but is not declared "
                       f"anywhere in this source, which USEs {', '.join(missing)} without "
                       f"defining it")
        return "transform_refused", reason
    return None


def preflight(source: Path, facts: SourceFacts, roots: Sequence[Path], work: Path) -> Optional[tuple]:
    """``None`` when the routine's dependencies resolve and the stress/stiffness
    block can be located; else ``(terminal state, reason text)`` for a card."""
    from umat_oti.services.jacobian_request import run_jacobian_transform

    try:
        run = run_jacobian_transform(source, work, ntens=6, discover_dependencies=True,
                                     dependency_roots=list(roots))
    except (ValueError, OSError) as error:
        return "transform_refused", normalise(str(error))
    return refusal_from_summary(run.summary, exit_code=run.exit_code, succeeded=run.succeeded,
                                facts=facts, roots=roots, source=source)
