"""Carrying a verified material into the Residual Assembler, and the guard on it.

The rule this module exists to enforce is the one the brief calls absolute:
**the interface must never let an unverified UMAT appear as verified in the
Residual Assembler.** An advanced user may run one experimentally, and when
they do the warning is explicit and travels with the selection rather than
being shown once and forgotten.

The mechanism is that :func:`offer` returns TWO lists and never one. The
verified list is what the picker shows by default. The experimental list is
behind a switch, every item in it carries the reason it is not verified, and
:func:`select` refuses to hand one back at all unless the caller passes
``experimental=True`` -- so a front end cannot select an unverified fixture by
forgetting a flag. It has to ask for it.

Nothing here evaluates a residual. The Residual Assembler's own public API --
``check_config`` and ``run_from_config`` -- is the service, and this module
prepares a call to it and reads its report back.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from umat_oti.app.plain_language import (Failure, failure_for,
                                         may_say_verified, plain_status)

__all__ = ["Fixture", "Selection", "offer", "select", "check_problem",
           "evaluate", "EXPERIMENTAL_WARNING"]


#: The sentence shown beside any unverified fixture, wherever it appears. One
#: string so it cannot be softened in one place and not another.
EXPERIMENTAL_WARNING = (
    "EXPERIMENTAL -- THIS MATERIAL IS NOT VERIFIED. Its conversion has not "
    "passed every check, so the residuals and derivatives you get from it are "
    "not backed by this program's verification. Do not report results from it "
    "as verified.")


@dataclass(frozen=True)
class Fixture:
    """One material offered to the Residual Assembler."""

    source_id: str
    key: str
    verified: bool
    #: Empty when ``verified``. Never empty otherwise: a fixture that is not
    #: verified always says which checks did not pass.
    why_not: str = ""
    label: str = ""
    material: str = ""
    formulation: str = ""
    #: Where the artefacts a residual run would need actually are, and which
    #: of them exist. Nothing is claimed to be present that was not found.
    artifacts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        record = {"source": self.source_id, "key": self.key,
                  "verified": self.verified, "label": self.label,
                  "material": self.material, "formulation": self.formulation,
                  "artifacts": dict(self.artifacts)}
        if not self.verified:
            record["why it is not verified"] = self.why_not
            record["warning"] = EXPERIMENTAL_WARNING
        return record


@lru_cache(maxsize=1)
def _eligibility_service():
    """Agent 5's ResidualAssemblyService where it is installed, else ``None``.

    Cached for the same reason the verification service is: a failed import
    repeated once per entry is the difference between a screen that draws and
    one that hangs.

    It reads ``REQUIRED_GATES`` from ``tools/export_residual_fixture.py``
    rather than copying it, which is the whole reason to prefer it: the gates
    a fixture must pass are defined by the exporter, and a picker that carried
    its own copy would keep offering fixtures the exporter had started to
    refuse.
    """
    try:
        from umat_oti.services.residual_assembly import (  # noqa: PLC0415
            ResidualAssemblyService)
    except Exception:
        try:
            from umat_oti.services import (  # noqa: PLC0415
                ResidualAssemblyService)
        except Exception:
            return None
    try:
        return ResidualAssemblyService()
    except Exception:                              # pragma: no cover
        return None


def _eligible(entry: Any) -> bool:
    """Whether this entry may be handed to the Residual Assembler.

    The service decides where it is installed. Where it is not, the six gates
    decide -- which is the rule the exporter itself enforces, so the fallback
    is conservative in the right direction: it can only ever refuse something
    the exporter would have taken, never offer something it would refuse.
    """
    # BOTH, never either. The six gates decide whether this material was
    # verified; the service decides whether a fixture can be frozen from it,
    # which is a WEAKER question -- the exporter needs a complete finite
    # history and asks three of the six. Taking the service's answer alone
    # offered 139 materials on a screen where only 42 are verified. The service
    # may therefore refuse something the gates admit, and may never admit
    # something the gates refuse.
    if not may_say_verified(entry):
        return False

    service = _eligibility_service()
    if service is None:
        return True
    raw = entry if isinstance(entry, dict) else getattr(entry, "raw", None)
    if not (isinstance(raw, dict) and raw):
        return True
    try:
        answer = service.eligible(raw)
    except Exception:                              # pragma: no cover
        return True
    verdict = _verdict_in(answer)
    return True if verdict is None else verdict


#: The names that carry the SERVICE'S ANSWER about one entry.
#:
#: ``ok`` is deliberately not among them. It is the envelope's flag, and it
#: means the service call itself succeeded -- which is true of every entry the
#: service managed to look at, including the ones it refuses. Reading it as the
#: verdict offered all 237 corpus entries to the Residual Assembler as
#: verified, among them entries at needs_material_data where every one of the
#: six gates reads "not established", while the service was returning
#: ``eligible=False`` with three named reasons. That is the one thing this
#: screen must never do.
VERDICT_FIELDS = ("eligible", "may_be_called_verified", "verified")


def _verdict_in(answer: Any) -> "bool | None":
    """The service's eligibility answer, or None if it did not give one.

    None rather than False, because "the service did not answer" and "the
    service said no" are different facts and only the caller knows what to do
    with the first. The payload may be a dict or a dataclass, so both are
    asked; an envelope is unwrapped once.
    """
    def _read(holder: Any) -> "bool | None":
        for name in VERDICT_FIELDS:
            value = (holder.get(name) if isinstance(holder, dict)
                     else getattr(holder, name, None))
            if isinstance(value, bool):
                return value
        return None

    if answer is None:
        return None
    found = _read(answer)
    if found is not None:
        return found
    payload = (answer.get("data") if isinstance(answer, dict)
               else getattr(answer, "data", None))
    return _read(payload) if payload is not None else None


def _fixture(entry: Any) -> Fixture:
    verified = _eligible(entry)
    status = plain_status(entry)
    manifest = getattr(entry, "manifest", None) or {}
    formulation = getattr(entry, "formulation", None) or {}
    source_id = str(getattr(entry, "source_id", "") or "")
    why_not = ""
    if not verified:
        failure = failure_for(entry)
        why_not = failure.what_failed + " -- " + failure.why if failure else ""
        if status.qualifier:
            why_not += " " + status.qualifier
    return Fixture(
        source_id=source_id,
        key=str(getattr(entry, "key", "") or ""),
        verified=verified,
        why_not=why_not.strip(),
        label=Path(source_id).name or source_id,
        material=str(manifest.get("material_block") or ""),
        formulation=str(formulation.get("family") or ""),
        artifacts=dict(getattr(entry, "artifacts", None) or {}),
    )


def offer(entries: Iterable[Any]) -> dict:
    """What the fixture picker may show, split so the two cannot be merged.

    Two keys, always both present. A caller that renders ``verified`` gets a
    list in which every item has passed every check. A caller that wants the
    rest has to reach for a differently named key and gets items that each
    carry their own reason and the standing warning.
    """
    verified, experimental = [], []
    for entry in entries:
        fixture = _fixture(entry)
        (verified if fixture.verified else experimental).append(fixture)
    verified.sort(key=lambda f: f.source_id)
    experimental.sort(key=lambda f: f.source_id)
    return {
        "verified": verified,
        "experimental": experimental,
        "warning for experimental": EXPERIMENTAL_WARNING,
        "counts": {"verified": len(verified),
                   "not verified": len(experimental)},
    }


@dataclass(frozen=True)
class Selection:
    """A fixture a user picked, and what must be shown alongside it."""

    fixture: Fixture
    experimental: bool
    warning: str = ""

    @property
    def may_be_reported_as_verified(self) -> bool:
        """The one question a report generator asks. Never a stage name."""
        return self.fixture.verified and not self.experimental

    def as_dict(self) -> dict:
        return {"fixture": self.fixture.as_dict(),
                "experimental": self.experimental,
                "warning": self.warning,
                "may be reported as verified":
                    self.may_be_reported_as_verified}


def select(entries: Iterable[Any], source_id: str, *,
           experimental: bool = False) -> Selection:
    """Pick one fixture, refusing an unverified one unless asked explicitly.

    The refusal is a raised error rather than a returned ``None``, because a
    front end that forgets to check a return value renders whatever it got --
    and what it got, in the case this guard exists for, is an unverified
    material in a picker labelled "verified materials".
    """
    catalogue = {f.source_id: f for f in
                 (_fixture(e) for e in entries)}
    fixture = catalogue.get(source_id)
    if fixture is None:
        raise KeyError(f"no material here is called {source_id!r}")
    if not fixture.verified and not experimental:
        raise ValueError(
            f"{source_id!r} is not verified and may not be used as a fixture. "
            f"{fixture.why_not} To run it anyway, ask for it explicitly as an "
            f"experimental fixture; it will be labelled as unverified "
            f"everywhere it appears, including in any report.")
    warning = "" if fixture.verified else EXPERIMENTAL_WARNING
    return Selection(fixture=fixture,
                     experimental=bool(not fixture.verified),
                     warning=warning)


# ---------------------------------------------------------------------------
# driving the Residual Assembler's own public API
# ---------------------------------------------------------------------------
def _resasm(module: str = "resasm_user"):
    try:
        return importlib.import_module(module)
    except ImportError as error:
        raise RuntimeError(
            "The Residual Assembler is not installed in this environment, so "
            "a residual problem cannot be evaluated from here. Install it and "
            "this screen will work: " + str(error)) from error


def check_problem(config_path: Path, *, module: str = "resasm_user") -> dict:
    """Ask the Residual Assembler whether a problem is ready, before running.

    Its own ``check_config`` decides; this wraps the answer so a failure
    arrives as the five fields every failure in this interface carries rather
    than as an exception the user has to read a traceback to understand.
    """
    try:
        resasm = _resasm(module)
        report = resasm.check_config(str(config_path))
    except Exception as error:
        return {
            "ready": False,
            "failure": Failure(
                what_failed="The residual problem could not be checked",
                why=("The Residual Assembler was asked whether this problem "
                     "is ready to run and could not answer."),
                evidence=[{"finding": "what it reported",
                           "result": f"{type(error).__name__}: {error}",
                           "where it was read": str(config_path)}],
                can_retry_automatically=False,
                what_you_must_provide="",
                whose_move="this program",
                full_log=f"{type(error).__name__}: {error}").as_dict(),
        }
    ok = bool(getattr(report, "ok", getattr(report, "passed", True)))
    return {
        "ready": ok,
        "messages": list(getattr(report, "messages", ()) or ()),
        "errors": list(getattr(report, "errors", ()) or ()),
        "warnings": list(getattr(report, "warnings", ()) or ()),
        "report": report,
    }


def evaluate(config_path: Path, selection: Selection, *,
             module: str = "resasm_user") -> dict:
    """Run one residual problem, carrying the fixture's verified status into it.

    The returned record says whether the result may be reported as verified,
    and where it may not, it carries the warning. That flag is computed from
    the SELECTION, not from whether the run succeeded: a residual evaluation
    that completes perfectly on an unverified material is a completed run of
    an unverified material.
    """
    result: dict = {
        "fixture": selection.fixture.as_dict(),
        "may be reported as verified": selection.may_be_reported_as_verified,
        "warning": selection.warning,
    }
    try:
        resasm = _resasm(module)
        run = resasm.run_from_config(str(config_path))
    except Exception as error:
        result["ok"] = False
        result["failure"] = Failure(
            what_failed="The residual problem did not run",
            why=("The Residual Assembler was given this problem and stopped "
                 "before producing a result."),
            evidence=[{"finding": "what it reported",
                       "result": f"{type(error).__name__}: {error}",
                       "where it was read": str(config_path)}],
            can_retry_automatically=False,
            whose_move="this program",
            full_log=f"{type(error).__name__}: {error}").as_dict()
        return result
    result["ok"] = True
    result["result"] = run
    output_dir = getattr(run, "output_dir", None)
    if output_dir:
        try:
            result["report"] = resasm.read_report(str(output_dir))
        except Exception as error:                 # pragma: no cover
            result["report_error"] = f"{type(error).__name__}: {error}"
    return result
