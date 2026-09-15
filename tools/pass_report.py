"""The report every corpus pass owes, computed from two registries and nothing else.

A pass is reported against the pass before it: how many of the adequately
specified genuine UMATs clear every acceptance gate, which cases were gained and
which were lost, what the internal blockers are, and how the families and the
sensitivity coverage stand. Every number here is read from a registry that
``build_corpus_registry.py`` wrote from a real verification run; nothing is
carried forward by hand.

"Accepted" means the registry's ``verified_on_every_gate`` -- each gate in
``ACCEPTANCE_GATES`` explicitly True in the current row. An explained primal
mismatch is not accepted and is counted with the internal blockers.

Usage::

    python tools/pass_report.py --registry NEW.json --previous OLD.json \
        --families corpus_run/material_families.json \
        --label pass13 --json out.json --markdown out.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.abaqus.terminal_states import ACCEPTANCE_GATES  # noqa: E402

D2_DENOMINATOR = 260
EXCLUDED_DENOMINATOR = 131


def _records(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text())
    return {row["source_id"]: row for row in data["records"]}


def accepted(row: dict) -> bool:
    """Every acceptance gate explicitly true, as the registry recorded it.

    The registry writes each gate as the string ``"true"``, ``"false"`` or
    ``"not established"`` so the CSV and the JSON read alike; only ``"true"``
    passes, and the terminal state has to agree.
    """
    return (row.get("verified_on_every_gate") is True
            and row.get("terminal_state") == "fully_verified"
            and all(row.get(f"gate_{gate}") == "true" for gate in ACCEPTANCE_GATES))


def replayed(regression_rows: list[dict]) -> dict[str, dict]:
    """Rows of a regression run that replayed a frozen experiment, by source.

    A frozen replay is the regression fixture being executed: the experiment
    the material was promoted under, run again at the current transform. Only
    a row that carries ``frozen`` counts; a row that re-discovered its
    experiment measured something else.
    """
    return {str(row.get("source")): row for row in regression_rows
            if row.get("frozen")}


def sensitivity_rows(rows: list[dict]) -> int:
    """Verification rows that carry any measured parameter or state sensitivity."""
    return sum(1 for row in rows
               if any("sensitiv" in key.lower() for key in row))


def report(new: dict[str, dict], old: dict[str, dict] | None,
           families: dict[str, str], regression_rows: list[dict] | None = None,
           verification_rows: list[dict] | None = None) -> dict:
    d2 = {sid: row for sid, row in new.items() if row.get("adequately_specified") is True}
    excluded = {sid: row for sid, row in new.items() if row.get("adequately_specified") is not True}
    now = {sid for sid, row in d2.items() if accepted(row)}
    before = set()
    if old is not None:
        before = {sid for sid, row in old.items()
                  if row.get("adequately_specified") is True and accepted(row)}

    internal_d2 = Counter(row["terminal_state"] for sid, row in d2.items()
                          if sid not in now)
    kind_d2 = Counter(row.get("kind") for sid, row in d2.items() if sid not in now)
    partition = Counter(row.get("kind") for row in new.values())

    family_rows: dict[str, Counter] = {}
    for sid, row in d2.items():
        fam = families.get(sid, "not classified")
        family_rows.setdefault(fam, Counter())["accepted" if sid in now else "not_accepted"] += 1

    excluded_kinds = Counter(row.get("adequacy_kind") or "none" for row in excluded.values())
    excluded_terminal = Counter(row["terminal_state"] for row in excluded.values())
    excluded_not_external = sorted(
        sid for sid, row in excluded.items()
        if row.get("adequacy_kind") not in ("external", "duplicate"))

    replays = replayed(regression_rows or [])
    replay_verified = {
        sid for sid in now
        if sid in replays and replays[sid].get("stage") == "verified"
        and all((replays[sid].get("evidence") or {}).get(g) is True
                for g in ACCEPTANCE_GATES)
        and replays[sid].get("fingerprint") == new[sid].get("verification_fingerprint")}
    replay_elsewhere = sorted(
        sid for sid in now if sid in replays
        and replays[sid].get("fingerprint") != new[sid].get("verification_fingerprint"))
    replay_failed = sorted(sid for sid in now if sid in replays
                           and sid not in replay_verified and sid not in replay_elsewhere)
    replay_absent = sorted(sid for sid in now if sid not in replays)

    return {
        "acceptance_gates": list(ACCEPTANCE_GATES),
        "regression_replay": {
            "regression_rows_supplied": len(regression_rows or []),
            "accepted_and_frozen_replay_verified": len(replay_verified),
            "accepted_and_frozen_replay_not_verified": replay_failed,
            "accepted_but_replayed_at_a_different_fingerprint": replay_elsewhere,
            "accepted_with_no_frozen_replay_in_the_supplied_run": replay_absent,
        },
        "sensitivity": {
            "verification_rows": len(verification_rows or []),
            "rows_carrying_parameter_or_state_sensitivity_evidence":
                sensitivity_rows(verification_rows or []),
        },
        "d2_count": len(d2),
        "d2_count_is_260": len(d2) == D2_DENOMINATOR,
        "accepted_of_d2": len(now),
        "accepted_previous_of_d2": len(before) if old is not None else None,
        "change": (len(now) - len(before)) if old is not None else None,
        "gained": sorted(now - before) if old is not None else None,
        "lost": sorted(before - now) if old is not None else None,
        "d2_not_accepted_by_terminal_state": dict(internal_d2.most_common()),
        "d2_not_accepted_by_owner": dict(kind_d2.most_common()),
        "d2_not_accepted_but_owner_external": sorted(
            sid for sid, row in d2.items() if sid not in now and row.get("kind") == "external"),
        "all_391_partition": dict(partition.most_common()),
        "all_391_partition_sums": sum(partition.values()),
        "all_391_terminal_state": dict(Counter(r["terminal_state"] for r in new.values()).most_common()),
        "excluded_count": len(excluded),
        "excluded_by_kind": dict(excluded_kinds.most_common()),
        "excluded_by_terminal_state": dict(excluded_terminal.most_common()),
        "excluded_without_an_external_or_duplicate_basis": excluded_not_external,
        "families_d2": {fam: dict(c) for fam, c in sorted(family_rows.items())},
        "families_basis": "keyword markers in corpus_run/material_families.json (not a physics review)",
    }


def markdown(label: str, r: dict) -> str:
    lines = [f"# {label}", "",
             f"Accepted (every one of {', '.join(r['acceptance_gates'])} explicitly true): "
             f"**{r['accepted_of_d2']} / {r['d2_count']}**"]
    if r["change"] is not None:
        lines.append(f"Previous: {r['accepted_previous_of_d2']}; change {r['change']:+d}; "
                     f"gained {len(r['gained'])}; lost {len(r['lost'])}")
        for name in ("gained", "lost"):
            for sid in r[name]:
                lines.append(f"- {name}: {sid}")
    rr = r["regression_replay"]
    lines += ["", f"Frozen regression replay (from {rr['regression_rows_supplied']} regression rows): "
              f"{rr['accepted_and_frozen_replay_verified']} accepted cases replayed and verified; "
              f"{len(rr['accepted_and_frozen_replay_not_verified'])} replayed and not verified; "
              f"{len(rr['accepted_but_replayed_at_a_different_fingerprint'])} replayed at a different transform fingerprint (not counted); "
              f"{len(rr['accepted_with_no_frozen_replay_in_the_supplied_run'])} with no replay in the run"]
    sv = r["sensitivity"]
    lines += [f"Parameter/state sensitivity evidence: "
              f"{sv['rows_carrying_parameter_or_state_sensitivity_evidence']} of "
              f"{sv['verification_rows']} verification rows carry any"]
    lines += ["", "## Not accepted within the 260, by terminal state", ""]
    lines += [f"- {k}: {v}" for k, v in r["d2_not_accepted_by_terminal_state"].items()]
    lines += ["", f"By owner: {r['d2_not_accepted_by_owner']}"]
    if r["d2_not_accepted_but_owner_external"]:
        lines.append("Inside the 260 yet labelled external (must be proven or moved): "
                     + ", ".join(r["d2_not_accepted_but_owner_external"]))
    lines += ["", f"## All 391: {r['all_391_partition']} (sums to {r['all_391_partition_sums']})",
              "", f"## Excluded {r['excluded_count']}: {r['excluded_by_kind']}",
              f"Terminal states of the excluded: {r['excluded_by_terminal_state']}"]
    if r["excluded_without_an_external_or_duplicate_basis"]:
        lines.append("Excluded without an external or duplicate basis: "
                     + ", ".join(r["excluded_without_an_external_or_duplicate_basis"]))
    lines += ["", f"## Families within the 260 ({r['families_basis']})", ""]
    for fam, c in r["families_d2"].items():
        lines.append(f"- {fam}: {c.get('accepted', 0)} accepted of "
                     f"{c.get('accepted', 0) + c.get('not_accepted', 0)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--families", type=Path)
    parser.add_argument("--regression", type=Path,
                        help="store_verification.jsonl of a --mode regression run")
    parser.add_argument("--verification", type=Path,
                        help="store_verification.jsonl the registry was built from")
    parser.add_argument("--label", default="corpus pass")
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    families = {}
    if args.families:
        families = {row["source_id"]: row["family"]
                    for row in json.loads(args.families.read_text())["rows"]}
    def jsonl(path):
        return [json.loads(line) for line in path.read_text().splitlines()
                if line.strip()] if path else None
    r = report(_records(args.registry),
               _records(args.previous) if args.previous else None, families,
               jsonl(args.regression), jsonl(args.verification))
    text = markdown(args.label, r)
    if args.json_path:
        args.json_path.write_text(json.dumps(r, indent=2) + "\n")
    if args.markdown:
        args.markdown.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
