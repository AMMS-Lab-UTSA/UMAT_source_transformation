"""The first screen: what is here, what works, and what to press.

Everything on this page is measured. There is no field whose value is a
default, and no action whose availability is assumed -- a button that starts
Abaqus is offered only where a licence was actually obtained, and where it was
not, the button says why rather than failing after the user presses it.

The counts come from the run's own record, through
:mod:`umat_oti.app.corpus_view`. The tool reports come from
:mod:`umat_oti.environment`, which resolves each executable, runs a probe and
keeps its exit status -- "not installed" and "installed but unlicensed" lead to
different next actions and a boolean cannot tell them apart.

Nothing here starts anything. The page returns what the buttons WOULD do, so a
test can check an action's availability and its reason without running it.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from umat_oti.app.corpus_view import NOT_ESTABLISHED, RunView, load_run
from umat_oti.app.plain_language import (may_say_verified, plain_status,
                                         unmapped_stages)

__all__ = ["Availability", "Action", "HomeView", "availability",
           "residual_assembler_status", "home_view", "PRIMARY_ACTIONS"]


# ---------------------------------------------------------------------------
# what is installed, with the evidence for saying so
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Availability:
    """One capability, whether it is usable, and how that was established.

    ``usable`` is three-valued and ``None`` is not a synonym for ``False``: a
    probe that was never run has not established that a tool is missing. A
    page that renders an unprobed Abaqus as "unavailable" tells the user to
    install something they may already have.
    """

    name: str
    usable: Optional[bool]
    detail: str = ""
    version: str = ""
    #: What was actually executed to find out, so the claim can be checked.
    probe: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def word(self) -> str:
        if self.usable is None:
            return NOT_ESTABLISHED
        return "ready" if self.usable else "not available"

    def as_dict(self) -> dict:
        return {"name": self.name, "usable": self.usable, "state": self.word,
                "detail": self.detail, "version": self.version,
                "probe": self.probe, "evidence": dict(self.evidence)}


def _from_report(name: str, label: str, report: dict) -> Availability:
    probe = report.get("probe_command") or []
    return Availability(
        name=label,
        usable=bool(report.get("available")),
        detail=str(report.get("reason") or ""),
        version=str(report.get("version") or ""),
        probe=" ".join(str(p) for p in probe),
        evidence=report,
    )


def availability(*, probe: Optional[Callable[..., dict]] = None,
                 include_abaqus: bool = True) -> dict:
    """Abaqus, the Fortran compiler and the Residual Assembler, each measured.

    ``probe`` is injectable so a test can supply a toolchain rather than
    whatever happens to be on the machine running the suite. The default is
    the real detector.
    """
    if probe is None:
        from umat_oti.environment import detect_toolchain
        probe = detect_toolchain
    try:
        reports = probe(include_abaqus=include_abaqus) or {}
    except Exception as error:                     # pragma: no cover
        reports = {}
        note = f"{type(error).__name__}: {error}"
        return {
            "Abaqus": Availability("Abaqus", None,
                                   f"the check could not be run: {note}"),
            "Fortran compiler": Availability("Fortran compiler", None,
                                             f"the check could not be run: {note}"),
            "Residual Assembler": residual_assembler_status(),
        }

    found: dict[str, Availability] = {}
    if include_abaqus:
        if "abaqus" in reports:
            found["Abaqus"] = _from_report("abaqus", "Abaqus", reports["abaqus"])
        else:                                      # pragma: no cover
            found["Abaqus"] = Availability(
                "Abaqus", None, "this check did not run, so whether Abaqus is "
                                "usable here has not been established")
    else:
        found["Abaqus"] = Availability(
            "Abaqus", None, "this check was skipped, so whether Abaqus is "
                            "usable here has not been established")
    if "gfortran" in reports:
        found["Fortran compiler"] = _from_report(
            "gfortran", "Fortran compiler", reports["gfortran"])
    else:                                          # pragma: no cover
        found["Fortran compiler"] = Availability(
            "Fortran compiler", None, "this check did not run")
    found["Residual Assembler"] = residual_assembler_status()
    return found


def residual_assembler_status(*, module: str = "resasm_user") -> Availability:
    """Whether the Residual Assembler can be driven from here.

    Import-checked rather than assumed present, and reported as its own
    capability, because the workflow's last two steps live in it: a user who
    verifies a material and then finds they cannot use it has been walked into
    a dead end the first screen could have warned them about.
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return Availability(
            "Residual Assembler", False,
            "the Residual Assembler is not installed in this environment, so "
            "a verified material cannot be carried into a residual problem "
            "from here",
            probe=f"import {module}")
    return Availability(
        "Residual Assembler", True,
        "installed and importable; a verified material can be carried into a "
        "residual problem",
        probe=f"import {module}",
        evidence={"module": module, "location": str(spec.origin or "")})


# ---------------------------------------------------------------------------
# the five things a first-time user may press
# ---------------------------------------------------------------------------
#: Each primary action, and what has to be true before it can be offered.
#: ``needs`` names capabilities from :func:`availability`; an action whose
#: needs are not met is still SHOWN, disabled, with the reason -- a button
#: that vanishes teaches a user nothing.
PRIMARY_ACTIONS: tuple[dict, ...] = (
    {"key": "add_umat", "label": "Add a UMAT",
     "what it does": "Bring one material subroutine in from a file on this "
                     "machine and look at what it needs.",
     "needs": ()},
    {"key": "import_corpus", "label": "Import a collection",
     "what it does": "Bring in a whole directory of material subroutines at "
                     "once.",
     "needs": ()},
    {"key": "verify_umat", "label": "Transform and verify",
     "what it does": "Convert a material so its derivatives come out exactly, "
                     "then run both versions and check they agree.",
     "needs": ("Abaqus", "Fortran compiler")},
    {"key": "open_verified", "label": "Open a verified material",
     "what it does": "Look at what a verified material does and carry it into "
                     "a residual problem.",
     "needs": ()},
    {"key": "run_regression", "label": "Run the regression suite",
     "what it does": "Re-run everything that was verified before and check "
                     "nothing has changed.",
     "needs": ("Abaqus", "Fortran compiler")},
)


@dataclass(frozen=True)
class Action:
    """One button, whether it can be pressed, and why not where it cannot."""

    key: str
    label: str
    what_it_does: str
    enabled: bool
    reason: str = ""
    #: Capabilities that are not established either way. Distinct from a
    #: capability measured missing: "we could not tell" is not "it is absent",
    #: and an action is not offered on the strength of an unmeasured one.
    unestablished: tuple = ()

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "what it does": self.what_it_does, "enabled": self.enabled,
                "reason": self.reason,
                "not established": list(self.unestablished)}


def _action(spec: dict, capabilities: dict, verified_count: int) -> Action:
    missing, unknown = [], []
    for need in spec["needs"]:
        capability = capabilities.get(need)
        if capability is None or capability.usable is None:
            unknown.append(need)
        elif not capability.usable:
            missing.append(need)

    if spec["key"] == "open_verified" and verified_count == 0:
        return Action(spec["key"], spec["label"], spec["what it does"], False,
                      "Nothing here has been verified yet. Verify a material "
                      "first and it will appear here.")
    if spec["key"] == "run_regression" and verified_count == 0 and not missing:
        return Action(spec["key"], spec["label"], spec["what it does"], False,
                      "There is nothing to re-run: no material here has been "
                      "verified yet, so there is no earlier result to compare "
                      "against.", tuple(unknown))
    if missing:
        detail = "; ".join(
            f"{name} is not available"
            + (f" ({capabilities[name].detail})" if capabilities[name].detail
               else "")
            for name in missing)
        return Action(spec["key"], spec["label"], spec["what it does"], False,
                      "This needs something that is not ready on this "
                      "machine: " + detail, tuple(unknown))
    if unknown:
        return Action(
            spec["key"], spec["label"], spec["what it does"], False,
            "This program could not establish whether "
            + " and ".join(unknown) + " is usable here, and it will not start "
            "a run on an assumption. Re-run the checks on this page.",
            tuple(unknown))
    return Action(spec["key"], spec["label"], spec["what it does"], True)


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HomeView:
    """Everything the first screen shows, measured, with nothing started."""

    counts: dict
    capabilities: dict
    actions: tuple
    #: Stages present in the record that no part of the interface can name.
    #: Empty is the normal answer; anything in it is shown as a warning rather
    #: than hidden, because a state nobody can name is not a state to render
    #: with a default.
    untranslated_stages: tuple = ()
    results_dir: str = ""

    def as_dict(self) -> dict:
        return {
            "counts": dict(self.counts),
            "capabilities": {k: v.as_dict()
                             for k, v in self.capabilities.items()},
            "actions": [a.as_dict() for a in self.actions],
            "untranslated stages": list(self.untranslated_stages),
            "results directory": self.results_dir,
        }


def home_view(results_dir: Optional[Path] = None,
              work_dir: Optional[Path] = None, *,
              probe: Optional[Callable[..., dict]] = None,
              include_abaqus: bool = True,
              run: Optional[RunView] = None) -> HomeView:
    """The first screen, for a given run directory and this machine.

    The verified count is :func:`~umat_oti.app.plain_language.may_say_verified`
    applied to every entry, NOT a count of entries at the stage ``verified``.
    On pass11 those two numbers are 42 and 55, and the larger one is the one
    that would put thirteen materials whose stresses disagreed in front of a
    user as finished work.
    """
    if run is None:
        run = (load_run(Path(results_dir), Path(work_dir) if work_dir else None)
               if results_dir is not None else None)

    entries = list(getattr(run, "entries", ()) or ())
    verified = [e for e in entries if may_say_verified(e)]
    at_stage_verified = [e for e in entries
                         if str(getattr(e, "stage", "")) == "verified"]

    needs_you: list = []
    ours: list = []
    theirs: list = []
    for entry in entries:
        if may_say_verified(entry):
            continue
        status = plain_status(entry)
        if status.whose_move == "you":
            needs_you.append(entry)
        elif status.whose_move == "this program":
            ours.append(entry)
        elif status.whose_move == "the author of this UMAT":
            theirs.append(entry)

    counts = {
        "materials here": len(entries),
        "verified": len(verified),
        # Carried beside the verified count and never instead of it. The gap
        # between the two is a real finding about this run, and a page that
        # showed only the larger number would be claiming thirteen
        # verifications that the gates do not support.
        "reached the last stage": len(at_stage_verified),
        "reached the last stage but not every check passed":
            len(at_stage_verified) - len(verified),
        "waiting on something you can supply": len(needs_you),
        "waiting on work in this program": len(ours),
        "answered by the published file itself": len(theirs),
    }

    capabilities = availability(probe=probe, include_abaqus=include_abaqus)
    actions = tuple(_action(spec, capabilities, len(verified))
                    for spec in PRIMARY_ACTIONS)
    untranslated = tuple(unmapped_stages(
        str(getattr(e, "stage", "")) for e in entries))

    return HomeView(counts=counts, capabilities=capabilities, actions=actions,
                    untranslated_stages=untranslated,
                    results_dir=str(results_dir or ""))
