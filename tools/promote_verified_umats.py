"""Promote a verified material into the working ``umat/`` collection.

A material earns a place here by passing Abaqus verification: its original and
its OTI-converted build both ran in Abaqus on the same deck, their stress and
state histories agreed across the loading path, and the OTI tangent agreed
with a finite difference of the ORIGINAL implementation at several states.
Nothing else promotes it. Compiling does not, and neither does an offline
driver.

Each promoted material becomes one directory holding four things:

  contract.json      the verification manifest -- element, kinematics, tensor
                     shape, material constants and where they came from,
                     state count, orientation, unsymmetry, loading segments,
                     tolerances and step ladder. Enough to rebuild the run.
  results.json       what actually happened: both Abaqus executions, the
                     history comparison, and the tangent comparison at every
                     state, with step sizes and errors.
  verification/      the artifacts themselves -- the generated deck, both
                     probe histories, the finite-difference sweeps.
  README.md          what was tested and, just as important, what was not.

What is NOT here is the source. These are other people's UMATs, mirrored for
study; a public repository without an explicit licence grant is not permission
to redistribute. ``source.json`` records the upstream identity and the SHA-256
of the exact bytes that were verified, and ``materialize_umat_sources.py``
fetches them into an ignored directory on the machine that needs them. A
material whose source this project does own is the exception and says so in
its ``source.json``.

Baselines are written here and never rewritten by a regression run. Promotion
is deliberate: it happens when someone runs this tool.

And it is refused for a run that was not finite from end to end. What
gets promoted is the frozen experiment a regression replays, so a
contract built on a history that stopped being numbers part way through
would make every later run a comparison against that. Abaqus printing
THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement about the solver,
not about the constitutive routine it called: measured on
BodyForce-Growth-2Stages.for, where both builds "completed" 35
increments and both were non-finite from the third. The check is the same
one export_residual_fixture.py applies, held in one place so the two
artefacts cannot drift apart.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from export_residual_fixture import (REQUIRED_GATES,  # noqa: E402
                                     at_either_level, not_a_number)

VERIFIED = "verified"

#: What the tangent was held to. Recorded as a sentence rather than a number
#: because the number alone reads as the whole test, and it is not: the
#: plateau across step sizes is what does the work. See tangent_verdict.
TANGENT_TOLERANCE_NOTE = (
    "1e-6 relative at the best step, corroborated by at least two step sizes "
    "spanning a decade -- one step cannot separate truncation error from "
    "cancellation")

#: Repositories whose files this project may redistribute, because it wrote
#: them. Everything else is recorded by identity and fetched on demand.
OWN_SOURCES = ("UMATs/",)


def material_id(source_id: str) -> str:
    """A stable directory name for a source, unique across the corpus.

    Built from the repository and the file stem, with a short digest of the
    full path appended because one repository can ship the same file name in
    twenty example directories -- Jeff97 ships BodyForce-Growth-2Stages.for in
    nineteen of them, and a name collision would silently overwrite one
    material's evidence with another's.
    """
    path = Path(source_id)
    owner_repo = path.parts[0] if path.parts else "unknown"
    owner_repo = owner_repo.replace("__", "-")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()
    digest = hashlib.sha256(source_id.encode()).hexdigest()[:8]
    return f"{owner_repo.lower()}--{stem}--{digest}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def contract_from(row: dict) -> dict:
    """The manifest that would rebuild this run, out of the verified row.

    Every field carries its provenance where the row records one. A constant
    with no stated origin is worse than a missing one: it reads as established
    when nothing established it.
    """
    return {
        "schema": "umat-oti/verification-contract/1.0",
        "source_id": row.get("source"),
        "source_sha256": row.get("source_sha256"),
        "repository": row.get("repository"),
        "material_point": {
            "element_type": row.get("element_type"),
            "ntens": row.get("ntens"),
            "nstatv": row.get("nstatv"),
            "kinematics": row.get("kinematics"),
            "kinematics_provenance": row.get("kinematics_provenance"),
            "unsymmetric": row.get("unsymmetric"),
        },
        "material": {
            "block": row.get("material_block"),
            "props_count": row.get("props_count"),
            "provenance": row.get("material_provenance"),
            "deck": row.get("deck"),
            "deck_digest": row.get("deck_digest"),
            "meaning": ("not established: the deck gives values, not names. "
                        "The constants are the author's; what they mean is "
                        "not certified here."),
        },
        "loading": {
            "kind": "verification probe, chosen by this pipeline",
            "not_the_authors_history": (
                "This is a controlled probe -- an amplitude searched for on "
                "the ORIGINAL until the material did something, then shear, "
                "then a reversal, and a hold where the material turned out to "
                "care about time. NOT a reproduction of the author's own "
                "example. A result here says the conversion agrees with the "
                "original under this probe."),
            "chosen_amplitude": (row.get("discovery") or {}).get(
                "chosen_amplitude"),
            "search": (row.get("discovery") or {}).get("summary"),
            "time_dependence": ((row.get("discovery") or {}).get("time") or {}
                                ).get("reason"),
        },
        # The experiment itself, whole, so a later run can replay it rather
        # than search again. A regression that re-searched would be measuring
        # a different experiment, and a difference between two such runs says
        # nothing about the code that changed between them.
        "frozen_manifest": row.get("manifest"),
        "frozen_states": (row.get("tangent") or {}).get("chosen_states") or [],
        "frozen_tolerances": {
            "primal": (row.get("manifest") or {}).get("primal_tolerance"),
            "tangent": TANGENT_TOLERANCE_NOTE,
            "fd_steps": (row.get("manifest") or {}).get("fd_steps"),
        },
        "transform_fingerprint": row.get("fingerprint"),
        # Which of the six gates this verdict rests on, what the two histories
        # grouped into, and what the experiment stopped exercising in order to
        # become one that runs whole. A regression replays this contract, so a
        # reader of it is entitled to the same things a reader of the page is.
        "finite_verification_run": {
            "evidence": row.get("evidence") or {},
            "complete_finite_verification_run": at_either_level(
                row, "complete_finite_verification_run"),
            "history_grouping": at_either_level(row, "history_grouping"),
            "discovery_usable_prefix": at_either_level(
                row, "discovery_usable_prefix"),
            "safe_loading_reconstructed": at_either_level(
                row, "safe_loading_reconstructed"),
            "failure_mechanism": at_either_level(row, "failure_mechanism"),
            "segment_repair": at_either_level(row, "segment_repair"),
            "coverage_given_up": at_either_level(row, "coverage_given_up"),
            "time_scale_coverage": at_either_level(row, "time_scale_coverage"),
            "mechanically_informative": at_either_level(
                row, "mechanically_informative"),
        },
    }


class PromotionRefused(ValueError):
    """A material that may not be promoted, said in terms of what is wrong."""


def why_this_may_not_be_promoted(row: dict, work_root: Path) -> list:
    """Every reason this run may not become a frozen baseline.

    The record's own account -- the stage it reached, the gates that were
    measured, and the grouping that says where the first incomplete increment
    and the first value that is not a number are -- and then the two probe
    histories on disk, scanned number by number, because "this history was
    finite" and "these numbers are finite" are two different claims and a
    baseline is compared against the second.

    Returns the reasons. Empty means it may be promoted.
    """
    problems: list = []
    source = str(row.get("source") or "this material")
    if row.get("stage") != VERIFIED:
        problems.append(
            f"{source} settled at {row.get('stage')!r}, not {VERIFIED!r}")
    if at_either_level(row, "complete_finite_verification_run") is not True:
        problems.append(
            f"{source}: complete_finite_verification_run is "
            f"{at_either_level(row, 'complete_finite_verification_run')!r}")
    measured = row.get("evidence") or {}
    for gate in REQUIRED_GATES:
        if measured.get(gate) is not True:
            problems.append(
                f"{source}: evidence.{gate}="
                f"{measured.get(gate, 'not measured')!r}")
    grouping = at_either_level(row, "history_grouping") or {}
    for side in ("original", "transformed"):
        payload = grouping.get(side)
        if not isinstance(payload, dict):
            problems.append(
                f"{source}: no history grouping for the {side} build, so "
                f"nothing says its history was complete")
            continue
        incomplete = payload.get("first_incomplete_increment")
        if incomplete:
            problems.append(
                f"{source}: the {side} history's first incomplete increment "
                f"is {incomplete.get('increment')}")
        where = payload.get("first_non_finite_material_point")
        if where:
            problems.append(
                f"{source}: the {side} history stops being numbers at element "
                f"{where.get('element')} point {where.get('point')} of "
                f"increment {where.get('increment')}")
    job = Path(work_root) / str(row.get("key") or "")
    for side in ("original", "transformed"):
        path = job / side / f"{side}_history.json"
        if not path.is_file():
            continue
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:     # pragma: no cover
            problems.append(f"{source}: {path.name} could not be read: {error}")
            continue
        for record in history if isinstance(history, list) else ():
            for name in ("STRESS", "STATEV", "DDSDDE"):
                problems.extend(not_a_number(
                    record.get(name),
                    f"{side} increment {record.get('increment')} {name}"))
    return problems


def results_from(row: dict) -> dict:
    """What happened, kept apart by which question each answer belongs to."""
    tangent = row.get("tangent") or {}
    states = tangent.get("states") or []
    return {
        "schema": "umat-oti/verification-results/1.0",
        "stage": row.get("stage"),
        "reason": row.get("reason"),
        "abaqus_original": row.get("original"),
        "abaqus_converted": row.get("transformed"),
        "history_agreement": row.get("primal"),
        # Where the two histories did NOT agree outright, the CONTROL that
        # accounts for the difference, whole. Thirteen of the 55 are in that
        # shape and a contract that recorded only ``agrees: false`` beside a
        # verdict of verified would be unreadable: the raw comparison flag
        # never moves, and what lets the entry climb is a measured control --
        # the author's own declared precision, or how far this model moves
        # when its arithmetic is reordered. A contract resting on a control
        # has to carry the control.
        "history_difference_explained_by_a_measured_control": (
            None if (row.get("primal") or {}).get("agrees") is True else {
                "declared_precision": row.get("precision_control"),
                "operation_order": row.get("association_control"),
                # WHICH control decided, named rather than left to be worked
                # out from two blocks. Both are usually present and only one
                # of them ran: where the author's arithmetic was already
                # double there is nothing to widen, so precision_control is
                # recorded with ran=false and the association control is the
                # one that did the work.
                "which": (
                    "declared_precision"
                    if (row.get("primal") or {}).get(
                        "explained_by_declared_precision") else
                    "operation_order"
                    if (row.get("primal") or {}).get(
                        "explained_by_operation_order") else "none"),
                "verdict": (
                    "the author declares a variable at single precision and "
                    "the original with that declaration alone widened agrees "
                    "with the converted build"
                    if (row.get("primal") or {}).get(
                        "explained_by_declared_precision") else
                    "this model differs from ITSELF by more than the two "
                    "builds differ, when the same source is compiled so that "
                    "the same mathematics is computed differently"
                    if (row.get("primal") or {}).get(
                        "explained_by_operation_order") else
                    "no control accounts for the difference"),
            }),
        "tangent_agreement": {
            "states_checked": tangent.get("states_checked"),
            "states_agreeing": tangent.get("states_agreeing"),
            "fd_steps": tangent.get("fd_steps"),
            "driven_through": tangent.get("driven_through"),
            "worst_state": tangent.get("comparison"),
            "per_state": [
                {"increment": s.get("increment"),
                 "record_index": s.get("record_index"),
                 "verified": s.get("verified"),
                 "reason": s.get("reason"),
                 "perturbation_scale": s.get("perturbation_scale"),
                 "comparison": s.get("comparison")}
                for s in states],
        },
        "support_build": row.get("support"),
        "warnings": row.get("warnings"),
        "seconds": row.get("seconds"),
    }


def readme_for(row: dict, identifier: str) -> str:
    tangent = row.get("tangent") or {}
    primal = row.get("primal") or {}
    comparison = tangent.get("comparison") or {}
    states = tangent.get("states") or []
    best = comparison.get("best_relative")
    scope = primal.get("scope")

    lines = [
        f"# {identifier}",
        "",
        f"`{row.get('source')}`",
        "",
        "## What was established",
        "",
        "Both builds ran in Abaqus on the same generated deck, under the same",
        "physical conditions.",
        "",
        f"- **Original execution**: completed, "
        f"{(row.get('original') or {}).get('converged_records')} converged records.",
        f"- **Converted OTI execution**: completed, "
        f"{(row.get('transformed') or {}).get('converged_records')} converged records.",
        f"- **Stress and state history**: agreed to "
        f"{primal.get('worst_stress_relative'):.3e} on stress and "
        f"{primal.get('worst_state_relative'):.3e} on state, over "
        f"{primal.get('resolved_components')} resolved components."
        if isinstance(primal.get("worst_stress_relative"), float)
        else "- **Stress and state history**: agreed.",
        f"- **OTI tangent against a finite difference of the ORIGINAL**: "
        f"agreed at {tangent.get('states_agreeing')} of "
        f"{tangent.get('states_checked')} states along the loading path"
        + (f", worst {best:.3e}." if isinstance(best, float) else "."),
        "",
    ]
    if states:
        lines += ["| state | increment | best relative | verdict |",
                  "| --- | --- | --- | --- |"]
        for state in states:
            c = state.get("comparison") or {}
            value = c.get("best_relative")
            lines.append(
                f"| {state.get('record_index')} | {state.get('increment')} | "
                + (f"{value:.3e}" if isinstance(value, float) else "not measured")
                + f" | {'agreed' if state.get('verified') else 'did not agree'} |")
        lines.append("")

    lines += [
        "## What was NOT established",
        "",
        "- The loading is a **verification probe chosen by this pipeline** --",
        "  prescribed extension, then shear, then a reversal. It is not the",
        "  author's own example and a result here is not a reproduction of it.",
        "- The **meaning** of the material constants is not certified. The deck",
        "  gives values, not names.",
        "- Passing the tangent check does **not** verify parameter",
        "  sensitivities, higher orders, or loading regimes outside this probe.",
        "- Physical correctness of the model itself is not in question here.",
        "  What is established is that the conversion agrees with the original.",
        "",
    ]
    if scope:
        lines += ["## Scope limit recorded during the run", "", f"{scope}", ""]
    lines += [
        "## Files",
        "",
        "- `contract.json` — what was run, and where every input came from.",
        "- `results.json` — what happened, per Abaqus execution and per state.",
        "- `source.json` — upstream identity and the SHA-256 of the bytes verified.",
        "- `verification/` — the generated deck and both probe histories.",
        "",
        "The source itself is not committed here. See `umat/README.md`.",
        "",
    ]
    return "\n".join(lines)


def source_record(row: dict, cache: Path) -> dict:
    source_id = str(row.get("source") or "")
    own = any(source_id.startswith(prefix) for prefix in OWN_SOURCES)
    record = {
        "schema": "umat-oti/source-identity/1.0",
        "source_id": source_id,
        "sha256": row.get("source_sha256"),
        "repository": row.get("repository"),
        "upstream": f"https://github.com/{row.get('repository')}"
        if row.get("repository") else None,
        "redistributed_here": own,
        "why": ("this project's own file, distributed under the repository's "
                "licence" if own else
                "not redistributed: a public repository without an explicit "
                "licence grant is not permission to redistribute. Fetch it "
                "with tools/materialize_umat_sources.py"),
    }
    present = cache / source_id
    if present.is_file():
        record["verified_bytes_sha256"] = _sha256(present)
    return record


def copy_artifacts(row: dict, work_root: Path, into: Path) -> list[str]:
    """The deck and the probe histories, as they were when the run happened."""
    into.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    job = work_root / str(row.get("key") or "")
    wanted = [
        (job / "transformed" / "transformed.inp", "generated.inp"),
        (job / "original" / "original_history.json", "original_history.json"),
        (job / "transformed" / "transformed_history.json",
         "converted_history.json"),
    ]
    for source, name in wanted:
        if source.is_file():
            shutil.copyfile(source, into / name)
            written.append(name)
    return written


def promote(row: dict, root: Path, work_root: Path, cache: Path) -> dict:
    refusals = why_this_may_not_be_promoted(row, work_root)
    if refusals:
        raise PromotionRefused(
            f"{row.get('source')} may not be promoted:\n  - "
            + "\n  - ".join(refusals))
    identifier = material_id(str(row.get("source") or ""))
    folder = root / identifier
    folder.mkdir(parents=True, exist_ok=True)

    _json(folder / "contract.json", contract_from(row))
    _json(folder / "results.json", results_from(row))
    _json(folder / "source.json", source_record(row, cache))
    (folder / "README.md").write_text(readme_for(row, identifier),
                                      encoding="utf-8")
    artifacts = copy_artifacts(row, work_root, folder / "verification")

    tangent = row.get("tangent") or {}
    return {
        "id": identifier,
        "source_id": row.get("source"),
        "source_sha256": row.get("source_sha256"),
        "repository": row.get("repository"),
        "element_type": row.get("element_type"),
        "kinematics": row.get("kinematics"),
        "ntens": row.get("ntens"),
        "nstatv": row.get("nstatv"),
        "props_count": row.get("props_count"),
        "deck": row.get("deck"),
        "transform_fingerprint": row.get("fingerprint"),
        "states_checked": tangent.get("states_checked"),
        "states_agreeing": tangent.get("states_agreeing"),
        "worst_tangent_relative": (tangent.get("comparison") or {}).get(
            "best_relative"),
        "worst_stress_relative": (row.get("primal") or {}).get(
            "worst_stress_relative"),
        "artifacts": artifacts,
    }


class WithdrawalRefused(ValueError):
    """A withdrawal that would be taken on evidence that cannot support it."""


def standing_materials(root: Path) -> dict:
    """What the collection holds right now, by id.

    Read from ``registry.json`` where there is one, because that is what
    records the fingerprint each contract was frozen at; the directories are
    used only to notice a material the registry has lost track of, which is a
    contract standing with nothing at all saying what produced it.
    """
    standing: dict = {}
    registry = root / "registry.json"
    if registry.is_file():
        try:
            payload = json.loads(registry.read_text(encoding="utf-8"))
        except ValueError:                         # pragma: no cover - guard
            payload = {}
        for entry in payload.get("materials", []) or []:
            if entry.get("id"):
                standing[str(entry["id"])] = dict(entry)
    for folder in sorted(p for p in root.glob("*") if p.is_dir()):
        standing.setdefault(folder.name, {
            "id": folder.name,
            "source_id": "",
            "transform_fingerprint": "",
            "orphaned": "this directory is not in registry.json, so nothing "
                        "on disk says which run froze it",
        })
    return standing


def withdraw(identifier: str, folder: Path, standing: dict, reason: str,
             now_at: str, fingerprint: str) -> dict:
    """Take one contract down and write down why.

    A frozen contract is a claim: these numbers are what this material does,
    and a regression may be compared against them. It stops being one the
    moment it cannot be reproduced -- the recorded tangent was measured
    against a transform that no longer exists, so a later run agreeing with it
    would be agreeing with an artefact of the old conversion, and a later run
    disagreeing with it would be reported as a regression in code that is
    correct.

    Deleting it quietly would be worse than leaving it: a reader comparing an
    old paper against this collection has to be able to find out what happened
    to a material that used to be here. So the directory goes and the record
    stays, naming the fingerprint it was frozen at, the fingerprint that
    replaced it, and the rung it reaches now.
    """
    if not reason:                                 # pragma: no cover - guard
        raise WithdrawalRefused(
            f"{identifier} may not be withdrawn without a reason: a contract "
            f"removed with nothing recorded is indistinguishable from one "
            f"that was never there")
    was = dict(standing.get(identifier) or {})
    if folder.is_dir():
        shutil.rmtree(folder)
    return {
        "id": identifier,
        "source_id": was.get("source_id", ""),
        "repository": was.get("repository", ""),
        "frozen_at_fingerprint": was.get("transform_fingerprint", ""),
        "withdrawn_at_fingerprint": fingerprint,
        "reason": reason,
        "reaches_now": now_at,
        "recorded_numbers_that_are_no_longer_evidence": {
            "worst_tangent_relative": was.get("worst_tangent_relative"),
            "worst_stress_relative": was.get("worst_stress_relative"),
            "states_agreeing": was.get("states_agreeing"),
            "states_checked": was.get("states_checked"),
        },
    }


def withdrawals(root: Path, standing: dict, promoted_ids: set, rows: list,
                fingerprint: str, *, apply: bool = True) -> list:
    """Every contract that may no longer stand, with the reason for each.

    The reason is the entry's own current rung wherever the run produced one.
    Where it produced none, the reason is that and not a verdict: a source the
    pass never reached is not a source the pass refused, and withdrawing it as
    though the evidence had gone against it would invent a result.
    """
    by_source = {str(row.get("source") or ""): row for row in rows}
    taken: list = []
    for identifier, entry in sorted(standing.items()):
        if identifier in promoted_ids:
            continue
        source_id = str(entry.get("source_id") or "")
        row = by_source.get(source_id)
        frozen_at = str(entry.get("transform_fingerprint") or "")
        if row is None:
            now_at = "not attempted in this run"
            reason = (
                f"this contract was frozen at transform fingerprint "
                f"{frozen_at or 'an unrecorded one'} and the run at "
                f"{fingerprint} produced no row for "
                f"{source_id or 'the source it names'}, so nothing at the "
                f"current fingerprint reproduces it. It is withdrawn because "
                f"it cannot be reproduced, NOT because it was refused -- "
                f"no evidence in this run speaks against the material")
        else:
            now_at = str(row.get("stage") or "")
            reason = (
                f"this contract was frozen at transform fingerprint "
                f"{frozen_at or 'an unrecorded one'}; at {fingerprint} the "
                f"same source reaches {now_at!r}, not {VERIFIED!r}. "
                f"{str(row.get('reason') or '')[:400]}")
        if apply:
            taken.append(withdraw(identifier, root / identifier, standing,
                                  reason, now_at, fingerprint))
        else:
            taken.append({"id": identifier, "source_id": source_id,
                          "frozen_at_fingerprint": frozen_at,
                          "withdrawn_at_fingerprint": fingerprint,
                          "reason": reason, "reaches_now": now_at})
    return taken


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true",
                        help="say what the collection holds and exit")
    parser.add_argument("--results", type=Path,
                        help="a store_verification.jsonl from a batch run")
    parser.add_argument("--work-dir", type=Path,
                        help="that run's scratch, holding the decks and "
                             "probe histories to copy")
    parser.add_argument("--cache-dir", type=Path,
                        default=Path.home() / "softwarex_work" / "discovery_cache")
    parser.add_argument("--root", type=Path, default=REPO / "umat")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be promoted and write nothing")
    parser.add_argument("--keep-stale", action="store_true",
                        help="leave standing any contract this run does not "
                             "reproduce, instead of withdrawing it. Only for "
                             "inspecting a run: a contract frozen at a "
                             "transform fingerprint that no longer exists is "
                             "not evidence about anything")
    args = parser.parse_args(argv)

    if args.status:
        registry = args.root / "registry.json"
        if not registry.is_file():
            print("nothing has been promoted into umat/ yet")
            return 0
        payload = json.loads(registry.read_text(encoding="utf-8"))
        materials = payload.get("materials", [])
        print(f"{payload.get('count', len(materials))} verified materials in "
              f"{args.root}")
        for entry in materials[:12]:
            worst = entry.get("worst_tangent_relative")
            print(f"    {entry['id']}"
                  + (f"   tangent {worst:.2e}" if isinstance(worst, float) else ""))
        if len(materials) > 12:
            print(f"    ... and {len(materials) - 12} more")
        return 0

    if args.results is None or args.work_dir is None:
        parser.error("--results and --work-dir are required unless --status "
                     "is given")
    # One record per entry: the last one written. The results file is
    # append-only, so a resumed run that re-runs an entry appends a second
    # record rather than editing the first, and reading both would let a
    # superseded verdict promote a material the run that replaced it did not.
    latest: dict = {}
    for line in args.results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        latest[str(record.get("key") or record.get("source") or line)] = record
    rows = list(latest.values())
    verified = [row for row in rows if row.get("stage") == VERIFIED]
    if args.limit:
        verified = verified[:args.limit]

    print(f"{len(rows)} rows in the run; {len(verified)} reached '{VERIFIED}'")
    if not verified:
        print("nothing to promote: no material passed Abaqus verification")
        return 1
    if args.dry_run:
        for row in verified:
            print(f"  would promote {material_id(str(row['source']))}")
        return 0

    args.root.mkdir(parents=True, exist_ok=True)
    # What is standing BEFORE anything is written, so a contract that this run
    # replaces can still be told from one it has no evidence about.
    standing = standing_materials(args.root)
    fingerprints = {str(row.get("fingerprint") or "") for row in verified}
    fingerprint = sorted(fingerprints)[0] if len(fingerprints) == 1 else ""
    if len(fingerprints) > 1:
        print(f"  NOTE: this run's verified rows carry "
              f"{len(fingerprints)} different transform fingerprints "
              f"({', '.join(sorted(f or '(none)' for f in fingerprints))}); "
              f"no single fingerprint can be recorded for the collection")

    entries = []
    refused = 0
    for row in verified:
        try:
            entries.append(promote(row, args.root, args.work_dir, args.cache_dir))
        except PromotionRefused as refusal:
            print(f"  REFUSED {refusal}")
            refused += 1
    if refused:
        print(f"  {refused} of {len(verified)} verified entries were refused "
              f"promotion because the run behind them was not finite from end "
              f"to end")
    if not entries:
        print("nothing to promote: every verified entry was refused")
        return 1
    entries.sort(key=lambda entry: entry["id"])

    # Everything that was standing and is not in this run's promotions. A
    # partial run may not do this: it has looked at part of the corpus and
    # would take down contracts it simply did not consider.
    promoted_ids = {entry["id"] for entry in entries}
    taken: list = []
    contracts: list = []
    partial = bool(args.limit) or args.keep_stale
    if partial:
        would = withdrawals(args.root, standing, promoted_ids, rows,
                            fingerprint, apply=False)
        if would:
            print(f"  {len(would)} standing contract(s) are NOT reproduced by "
                  f"this run and are being LEFT STANDING because "
                  + ("--limit makes this a partial run" if args.limit
                     else "--keep-stale was given")
                  + ". A contract that cannot be reproduced at the current "
                    "fingerprint is not evidence; re-run without it to "
                    "withdraw them")
    else:
        taken = withdrawals(args.root, standing, promoted_ids, rows,
                            fingerprint)
        for entry in taken:
            print(f"  WITHDRAWN {entry['id']}: {entry['reaches_now']}")
        # The withdrawal record ACCUMULATES. A second promotion that took
        # nothing down used to rewrite the file as though nothing had ever
        # been withdrawn, which is how a collection loses the account of what
        # it used to claim -- the one thing a reader comparing an old paper
        # against it has to be able to find. A material that is withdrawn and
        # later promoted again drops out, because it stands once more.
        history: dict = {}
        existing = args.root / "withdrawn.json"
        if existing.is_file():
            try:
                for entry in (json.loads(existing.read_text(encoding="utf-8"))
                              .get("contracts") or []):
                    if entry.get("id"):
                        history[str(entry["id"])] = entry
            except ValueError:                     # pragma: no cover - guard
                pass
        history.update({entry["id"]: entry for entry in taken})
        for identifier in promoted_ids:
            history.pop(identifier, None)
        contracts = [history[key] for key in sorted(history)]
        # Written whenever the file exists, not only when it has contents: a
        # material that was withdrawn and is now promoted again STANDS, and
        # leaving it listed as withdrawn beside its own live directory is a
        # collection saying two things about the same material.
        if contracts or existing.is_file():
            _json(existing, {
                "schema": "umat-oti/withdrawn-contracts/1.0",
                "what_this_is": (
                    "Contracts that used to stand in this collection and were "
                    "taken down because they could not be reproduced at the "
                    "current transform fingerprint. A frozen contract is a "
                    "claim that a regression may be compared against; one "
                    "measured against a transform that no longer exists is "
                    "not. The numbers each carried are recorded here as what "
                    "they now are -- a record of what used to be claimed, not "
                    "evidence about the material."),
                "withdrawn_at_fingerprint": fingerprint,
                "count": len(contracts),
                "withdrawn_at_this_promotion": len(taken),
                "contracts": contracts,
            })
            print(f"  wrote {existing} with {len(contracts)} withdrawal(s), "
                  f"{len(taken)} of them taken now")

    _json(args.root / "registry.json", {
        "schema": "umat-oti/verified-registry/1.0",
        "what_this_is": (
            "Every material in this collection passed Abaqus verification: "
            "the original and the OTI-converted build both ran in Abaqus on "
            "the same deck, their stress and state histories agreed, and the "
            "OTI tangent agreed with a finite difference of the ORIGINAL "
            "implementation at several states along the loading path. "
            "Compiling is not verification and is not what put anything here."),
        "not_established": (
            "The loading is a probe chosen by this pipeline, not the author's "
            "own example. The meaning of the material constants is not "
            "certified. Parameter sensitivities and higher orders are not "
            "covered by a tangent check."),
        # The fingerprint everything here was frozen at. One number for the
        # whole collection, because that is the claim: these contracts are
        # reproducible against THIS transform. A collection carrying contracts
        # from several is a collection whose numbers cannot all be checked.
        "transform_fingerprint": fingerprint,
        "results_read": str(args.results.name),
        "count": len(entries),
        "materials": entries,
        "withdrawn": {
            "count": len(contracts),
            "at_this_promotion": [entry["id"] for entry in taken],
            "why": ("recorded in withdrawn.json: each was frozen at a "
                    "transform fingerprint that no longer exists, and its "
                    "recorded tangent was measured against generated Fortran "
                    "this repository no longer produces"),
        } if taken else {"count": 0, "at_this_promotion": [], "why": ""},
    })
    print(f"  wrote {args.root / 'registry.json'} with {len(entries)} materials")

    # The regression baseline IS the promoted set, and it is written here
    # because its own header says so: "written by promotion, never by a
    # regression run -- a gate that rewrites its own baseline cannot fail."
    # It was not being written by anything, and after a withdrawal that is not
    # a stale file, it is a gate that demands the re-verification of 29
    # materials this collection no longer holds and can therefore never pass.
    baseline = args.root / "baseline.json"
    if not partial:
        _json(baseline, {
            "schema": "umat-oti/regression-baseline/1.0",
            "what_this_is": (
                "The materials a regression run is required to re-verify. "
                "Written by promotion, never by a regression run: a gate that "
                "rewrites its own baseline cannot fail."),
            "promoted_from": (
                "an Abaqus verification batch; see each material's "
                "results.json"),
            "transform_fingerprint": fingerprint,
            "entries": [{"source": entry["source_id"],
                         "stage": VERIFIED,
                         "id": entry["id"],
                         "source_sha256": entry["source_sha256"]}
                        for entry in entries],
        })
        print(f"  wrote {baseline} with {len(entries)} entries")
    elif baseline.is_file():
        print(f"  LEFT {baseline.name} as it stands: a partial run must not "
              f"rewrite the gate it would be measured by")
    for entry in entries[:10]:
        print(f"    {entry['id']}")
    if len(entries) > 10:
        print(f"    ... and {len(entries) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
