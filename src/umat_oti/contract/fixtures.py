"""Regression fixtures, and the fingerprint that says whether one still counts.

A regression fixture is what later runs are compared against, so anything
wrong inside it is wrong in every comparison made against it afterwards,
silently. The specific way it goes wrong here is not a NaN -- the exporter
already refuses those -- it is a fixture that was perfectly correct when it was
frozen and stopped being evidence when the transform changed underneath it.

That has happened. The frozen collection was found to hold 67 materials whose
tangent numbers predated a correction; they looked exactly like the others.

So a fixture carries the TRANSFORM FINGERPRINT it was produced at, and a
consumer must be able to refuse one built at a different fingerprint from the
store it is being read beside. :func:`check_fingerprint` is that refusal, and
it is three-state: a fixture that carries no fingerprint at all is NOT
ESTABLISHED -- not stale, and not current either.

Measured, on both fixture sets that exist
----------------------------------------
Four fixtures were frozen at ``transform_fingerprint = ff94800b1884bcc0``; the
frozen store and the current transform are at ``b0d27ee53c630500``, so those
four are STALE by this rule and the contract refuses them as regression
baselines rather than letting an assembler difference against numbers a
transform that has since changed produced. Ten have since been re-frozen at
the current generation and the same rule accepts them unchanged.

Which set is on disk is a fact about a run, so nothing here asserts a count or
a particular fingerprint: the current one is read from
``schemas/transform_generation.json``, which both repositories read and neither
writes down twice.

Refusing a fixture as a BASELINE is not deleting it. These fixtures are the
only end-to-end evidence that the assembler consumes what the pipeline emits,
and the answer to a stale one is "not current", not "not a fixture".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from .identity import UmatIdentity
from .tristate import NOT_ESTABLISHED, Tri

__all__ = ["FixtureReference", "FixtureFingerprintError", "check_fingerprint",
           "FIXTURE_SCHEMA", "read_fixture_reference", "CURRENT_FIXTURES_ROOT"]

#: The schema name the exporter writes into every fixture it freezes.
FIXTURE_SCHEMA = "umat-oti/residual-fixture/1"

#: Where fixtures are published, relative to the Residual_Assembler root.
#: Part of the contract: the consumer must not have to be told the path.
CURRENT_FIXTURES_ROOT = "tests/fixtures/verified"


class FixtureFingerprintError(ValueError):
    """A fixture whose numbers were produced by a different transform."""


@dataclass(frozen=True)
class FixtureReference:
    """One frozen fixture, by path, identity and the fingerprint it was cut at."""

    path: str
    identity: Optional[UmatIdentity] = None
    transform_fingerprint: str = ""
    schema: str = FIXTURE_SCHEMA
    deck_digest: str = ""
    increments_carried: Optional[int] = None
    claims_checked: tuple = ()
    claims_not_carried: tuple = ()
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"path": self.path,
                "identity": self.identity.as_dict() if self.identity else None,
                "transform_fingerprint": self.transform_fingerprint,
                "schema": self.schema, "deck_digest": self.deck_digest,
                "increments_carried": self.increments_carried,
                "claims_checked": list(self.claims_checked),
                "claims_not_carried": list(self.claims_not_carried),
                "evidence": dict(self.evidence)}

    def agrees_with_store(self, store_fingerprint: str) -> Tri:
        """Three-state: current, stale, or carrying no fingerprint at all."""
        return check_fingerprint(self.transform_fingerprint, store_fingerprint,
                                 where=self.path)


def check_fingerprint(fixture_fingerprint: Any, store_fingerprint: Any, *,
                      where: str = "this fixture") -> Tri:
    """Is this fixture's transform the one the store was produced at?

    TRUE when the two fingerprints are equal. FALSE when both are present and
    differ -- the fixture's numbers were produced by a transform that has
    since changed, and differencing against them proves nothing about the
    current one. NOT ESTABLISHED when either side does not carry one, which is
    a third answer and not a pass: a fixture with no fingerprint might be
    current and might predate a correction, and nothing on disk says which.
    """
    theirs = str(fixture_fingerprint or "").strip()
    mine = str(store_fingerprint or "").strip()
    if not theirs:
        return Tri(None, f"{where} carries no transform_fingerprint, so "
                         f"whether its numbers predate a correction to the "
                         f"transform is not established -- it is not current "
                         f"by default")
    if not mine:
        return Tri(None, f"no store fingerprint was supplied to compare "
                         f"{where} against")
    if theirs == mine:
        return Tri(True, f"{where} was frozen at {mine}, the fingerprint the "
                         f"store was produced at")
    return Tri(False,
               f"{where} was frozen at transform fingerprint {theirs}, and "
               f"the store it is being read beside was produced at {mine}. "
               f"The fixture's stress, state and tangent were computed by a "
               f"transform that has since changed, so a comparison against "
               f"them is evidence about the old transform and not the current "
               f"one. Re-freeze the fixture at {mine}, or read it only as "
               f"history.")


def require_current(fixture_fingerprint: Any, store_fingerprint: Any, *,
                    where: str = "this fixture") -> None:
    """:func:`check_fingerprint`, raising on anything but TRUE.

    NOT ESTABLISHED raises too. A consumer about to rest a regression on a
    fixture needs the fixture to be known-current; "nothing said" is not
    known-current, and treating it as one is the null-reads-as-a-pass defect.
    """
    answer = check_fingerprint(fixture_fingerprint, store_fingerprint,
                               where=where)
    if answer.is_true():
        return
    raise FixtureFingerprintError(answer.why)


def read_fixture_reference(path: Any) -> FixtureReference:
    """Read a frozen fixture file's contract header. Does not load its arrays."""
    file = Path(path)
    payload = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise FixtureFingerprintError(
            f"{file}: a fixture must be a JSON object; found "
            f"{type(payload).__name__}")
    schema = str(payload.get("schema") or "")
    if schema != FIXTURE_SCHEMA:
        raise FixtureFingerprintError(
            f"{file}: schema is {schema!r}, not {FIXTURE_SCHEMA!r}. A reader "
            f"that guessed here would be reading a different layout's keys "
            f"by the same names.")
    identity: Optional[UmatIdentity]
    try:
        identity = UmatIdentity.of(payload.get("source_id"),
                                   payload.get("source_sha256"),
                                   repository=payload.get("repository", ""))
    except ValueError as exc:
        raise FixtureFingerprintError(
            f"{file}: {exc}") from exc
    history = payload.get("finite_history")
    history = history if isinstance(history, Mapping) else {}
    evidence = history.get("evidence")
    return FixtureReference(
        path=str(file),
        identity=identity,
        transform_fingerprint=str(payload.get("transform_fingerprint") or ""),
        schema=schema,
        deck_digest=str(payload.get("deck_digest") or ""),
        increments_carried=history.get("increments_carried"),
        claims_checked=tuple(payload.get("claims_checked") or ()),
        claims_not_carried=tuple(payload.get("claims_not_carried") or ()),
        evidence=dict(evidence) if isinstance(evidence, Mapping) else {})


# ---------------------------------------------------------------------------
# which generation of the contract a fixture speaks
# ---------------------------------------------------------------------------
#: A fixture does not carry a contract version -- it predates the contract --
#: so which generation it speaks is read off its own shape. That derivation is
#: made once, here, rather than by each consumer guessing from whichever field
#: it happened to look for first.
IDENTITY_1X = "1.x: rows named by (increment, time)"
IDENTITY_2X = "2.x: rows named by (element, point, step, increment, time)"


def fixture_generation(payload: Mapping[str, Any]) -> dict:
    """Which generation a fixture speaks, and what a consumer may do with it.

    Returns ``{"identity", "has_counts", "usable_for_boundary_conditions",
    "reason"}``. Deliberately not a boolean: a 1.x fixture is not broken and
    is not current either, and the two things a consumer might want from it --
    numbers to difference against, and enough identity to rebuild the loading
    -- have different answers.
    """
    rows = payload.get("original") or []
    first = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    five = all(field in first for field in
               ("element", "point", "step", "increment", "time"))
    history = payload.get("finite_history")
    history = history if isinstance(history, Mapping) else {}
    counts = all(history.get(name) is not None for name in
                 ("records_carried", "increments_carried",
                  "material_points_per_increment"))
    if five:
        reason = ("rows carry all five identity fields, so a consumer can "
                  "group them into increments and say which *BOUNDARY block "
                  "was in force")
    else:
        absent = [f for f in ("element", "point", "step", "increment", "time")
                  if f not in first]
        reason = (
            f"rows carry no {', '.join(absent)}. Abaqus restarts increment "
            f"numbering in every step, so a consumer rebuilding the loading "
            f"from what is here cannot tell which step a row belongs to; "
            f"doing it anyway was wrong by 3.0 relative, which is a different "
            f"deformation and not a tolerance. This fixture may still be "
            f"differenced against -- its numbers are its numbers -- but the "
            f"loading behind them may not be reconstructed from it.")
    return {
        "identity": IDENTITY_2X if five else IDENTITY_1X,
        "has_counts": counts,
        "usable_for_boundary_conditions": five,
        "reason": reason,
    }


def require_five_field_identity(payload: Mapping[str, Any], *,
                                where: str = "this fixture") -> None:
    """Refuse a fixture whose rows cannot be told apart, by name.

    For a consumer that has to rebuild the loading. A consumer that only
    differences stored numbers does not need this and should not call it --
    refusing a usable fixture is its own kind of wrong answer.
    """
    generation = fixture_generation(payload)
    if generation["usable_for_boundary_conditions"]:
        return
    raise FixtureFingerprintError(f"{where}: {generation['reason']}")
