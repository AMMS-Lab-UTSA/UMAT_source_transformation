#!/usr/bin/env python3
"""Turn a batch run's three reports into evidence the repository can keep.

The transform store, the offline gate's report and the Abaqus batch's results
all live outside the repository: the store because most of these sources carry
no licence and a transformed source is a derivative of one, the reports because
they are written wherever the batch was run. What belongs in the tree is the
part a reader needs and the part a reviewer can check -- counts, provenance,
digests and the exact commands -- with no machine paths and no source text.

Three things this refuses to do:

*Pool the stages.* Each is reported under its own name. "Verified" means the
last rung of the Abaqus ladder and nothing else; an entry that agreed in the
offline gate has earned a place in the queue and is reported as that.

*Move the denominator.* Every count is out of the whole selection. A source
with no material data, a build that would not compile and a run this machine
broke are all in it, because an agreement rate over the rows that happened to
work is not a statement about the corpus.

*Publish a rate without its caveat.* 144 of the 158 paired sources take their
constants from a deck another source also uses, and every pairing is marked
`proposed_needs_review` by the tool that made it. Both numbers travel with the
result, so an agreement rate cannot be read as "verified against the author's
own material".

  tools/record_batch_evidence.py --transform transform_batch.json \\
      --gate offline_store_gate.json --abaqus store_verification.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovery_triage import without_machine_paths  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "paper_results" / "store_verification"


def _load_json(path: Optional[Path]) -> Optional[dict]:
    if path is None or not Path(path).is_file():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return None


def _load_jsonl(path: Optional[Path]) -> list[dict]:
    if path is None or not Path(path).is_file():
        return []
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def transform_summary(report: Optional[dict]) -> dict[str, Any]:
    """What the batch transform did, with cached work kept apart from new work."""
    if not report:
        return {"available": False}
    summary = report.get("summary") or report
    return {
        "available": True,
        "selected": summary.get("selected") or summary.get("attempted"),
        "transformed_now": summary.get("transformed_now") or summary.get("transformed"),
        "already_in_the_store": summary.get("reused_from_store")
        or summary.get("already_in_the_store") or 0,
        "failed": summary.get("failed"),
        "not_in_the_cache": summary.get("not_in_cache"),
        "fingerprint": summary.get("fingerprint") or report.get("fingerprint"),
        "note": ("a stored entry means the transform ran and, where the metadata "
                 "says so, that the generated Fortran compiled. Compiling is not "
                 "verification: nothing here was executed against a material "
                 "vector and nothing was compared against anything"),
    }


def gate_summary(report: Optional[dict]) -> dict[str, Any]:
    """What the offline stress-parity gate decided, and what it is not."""
    if not report:
        return {"available": False}
    summary = report.get("summary") or {}
    return {
        "available": True,
        "entries": summary.get("entries"),
        "by_outcome": summary.get("by_outcome"),
        "agreed": summary.get("agreed"),
        "disagreed": summary.get("disagreed"),
        "undecided": summary.get("undecided"),
        "worst_relative_difference_among_agreeing":
            summary.get("worst_relative_difference_among_agreeing"),
        "resolved_components_total": summary.get("resolved_components_total"),
        "unresolved_components_total": summary.get("unresolved_components_total"),
        "non_finite_components_total": summary.get("non_finite_components_total"),
        "rows_on_a_shared_deck": summary.get("rows_on_a_shared_deck"),
        "rows_on_an_unreviewed_pairing": summary.get("rows_on_an_unreviewed_pairing"),
        "with_blocking_statements": summary.get("with_blocking_statements"),
        "what_this_is": report.get("what_this_is") or (
            "an offline stress-parity gate, not Abaqus verification. It compares "
            "the stress two standalone drivers compute from one declared "
            "starting state. It runs no solver, drives no loading history and "
            "does not examine DDSDDE. An agreeing row has earned a place in the "
            "Abaqus queue and nothing more"),
    }


def abaqus_summary(rows: list[dict]) -> dict[str, Any]:
    """How far each entry got up the Abaqus ladder, by stage."""
    if not rows:
        return {"available": False}
    stages = Counter(str(row.get("stage") or "harness_error") for row in rows)
    verified = [row for row in rows if row.get("stage") == "verified"]
    return {
        "available": True,
        "attempted": len(rows),
        "by_stage": dict(stages.most_common()),
        "verified": len(verified),
        "verified_sources": sorted(
            str(row.get("source") or row.get("key") or "") for row in verified),
        "note": ("only the last rung is 'verified': the original and the "
                 "transformed source both ran in Abaqus over one manifest, "
                 "their stress and state histories agreed, and the OTI tangent "
                 "matched a centred difference of the original replayed offline. "
                 "A harness_error is a statement about this run, not about the "
                 "model, and a resumed batch does it again"),
    }


def build(transform: Optional[dict], gate: Optional[dict],
          abaqus: list[dict]) -> dict[str, Any]:
    return {
        "what_this_is": (
            "the state of the transform store and what has been established "
            "about it, in three stages. Nothing here is pooled: an entry that "
            "compiled, an entry that agreed at one material point offline, and "
            "an entry verified in Abaqus are three different claims."),
        "transform": transform_summary(transform),
        "offline_gate": gate_summary(gate),
        "abaqus": abaqus_summary(abaqus),
        "caveats": [
            "Material constants come from a deck in the same repository as the "
            "source, matched deterministically on the constant count. 144 of "
            "the 158 paired sources share their deck with another source, and "
            "every pairing is marked proposed_needs_review by the tool that "
            "made it. Both builds are handed the same constants, so a parity "
            "result holds regardless; but an agreement rate is not 'verified "
            "against the author's own material'.",
            "Neither the sources nor their transforms are committed here. Most "
            "carry no licence, and a public repository without one is not "
            "permission to redistribute. The store keeps them outside the tree "
            "and this record keeps digests and counts.",
            "Abaqus 2021 on this installation aborts in its post-analysis "
            "wrap-up after writing that the analysis completed, with no user "
            "subroutine at all. The exit code is preserved as a warning and is "
            "never the verdict.",
        ],
        "reproduce": [
            "make batch-transform   # fills the store; re-runs everything when "
            "the transform fingerprint changes",
            "make batch-offline     # the fast stress-parity gate",
            "make batch-abaqus      # the paired Abaqus verification",
            "make batch             # all three, in order",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transform", type=Path)
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--abaqus", type=Path,
                        help="the batch's store_verification.jsonl")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    record = build(_load_json(args.transform), _load_json(args.gate),
                   _load_jsonl(args.abaqus))
    # Scrubbed unconditionally: this file is committed, and evidence must not
    # name the machine it was produced on.
    text = without_machine_paths(json.dumps(record, indent=1, allow_nan=False))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / "store_verification_summary.json"
    path.write_text(text + "\n", encoding="utf-8")

    print(f"wrote {path.relative_to(REPO_ROOT)}")
    for stage, block in (("transform", record["transform"]),
                         ("offline gate", record["offline_gate"]),
                         ("abaqus", record["abaqus"])):
        if not block.get("available"):
            print(f"  {stage:<14} (no report given)")
            continue
        if stage == "abaqus":
            print(f"  {stage:<14} {block['attempted']} attempted, "
                  f"{block['verified']} verified")
            for name, count in block["by_stage"].items():
                print(f"      {name:<26} {count}")
        elif stage == "offline gate":
            print(f"  {stage:<14} {block['entries']} entries, "
                  f"{block['agreed']} agreed, {block['disagreed']} disagreed, "
                  f"{block['undecided']} undecided")
        else:
            print(f"  {stage:<14} {block['transformed_now']} transformed now, "
                  f"{block['failed']} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
