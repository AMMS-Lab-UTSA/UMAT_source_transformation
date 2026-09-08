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

VERIFIED = "verified"

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
                "This is a controlled probe -- prescribed extension, then "
                "shear, then a reversal -- and NOT a reproduction of the "
                "author's own example. A result here says the conversion "
                "agrees with the original under this probe."),
        },
        "transform_fingerprint": row.get("fingerprint"),
    }


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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, required=True,
                        help="a store_verification.jsonl from a batch run")
    parser.add_argument("--work-dir", type=Path, required=True,
                        help="that run's scratch, holding the decks and "
                             "probe histories to copy")
    parser.add_argument("--cache-dir", type=Path,
                        default=Path.home() / "softwarex_work" / "discovery_cache")
    parser.add_argument("--root", type=Path, default=REPO / "umat")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be promoted and write nothing")
    args = parser.parse_args(argv)

    rows = [json.loads(line) for line in
            args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
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
    entries = [promote(row, args.root, args.work_dir, args.cache_dir)
               for row in verified]
    entries.sort(key=lambda entry: entry["id"])

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
        "count": len(entries),
        "materials": entries,
    })
    print(f"  wrote {args.root / 'registry.json'} with {len(entries)} materials")
    for entry in entries[:10]:
        print(f"    {entry['id']}")
    if len(entries) > 10:
        print(f"    ... and {len(entries) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
