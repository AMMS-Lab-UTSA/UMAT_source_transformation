#!/usr/bin/env python3
"""Blind hold-out of a council experiment template (D-19a rev 2 R6.3; package A-2).

Tier ``holdout``. For one template (an experiment family of R3), Vera picks
blind at least five sources that are VERIFIED with their author's deck. This
runner never picks them: it takes her list. For each source it

1. converts the verified author deck's constants (the pass record's
   manifest: PROPS, NSTATV, initial state, element, kinematics) into a
   harvest-format row with ``material_data_origin = holdout_from_author_deck``
   (an origin the harvest schema does not admit, so a hold-out row can never be
   merged into the harvest or counted);
2. lays out a DECKLESS copy of the source's repository (its Fortran files
   only), so the pairing finds no author deck and the source takes the council
   route (``no_deck_in_repository``), and runs ``plan_council`` through
   ``tools/make_council_deck.py`` into a hold-out folder -- never into
   corpus_campaign/council_plans;
3. runs the SAME gates on the council experiment (every set) and on the
   author-deck experiment, and compares the verdicts.

Every verdict must equal the author-deck verdict. ONE disagreement (a refused
council plan included) withdraws the template. Agreement on every source only
holds the template for Vera's review; acceptance is hers (R6.5). Q4: the gates
are independent of the inputs' origin, the inputs are not independent of the
council's choices -- only the hold-out and review validate those choices.

Selection file (written by Vera; JSON)::

    {"template": "<template>", "selected_by": "vera", "blind": true,
     "date": "YYYY-MM-DD", "keys": ["<registry key>", ...]}   # >= 5 keys

Run::

    PYTHONHASHSEED=0 PYTHONPATH=src python tools/corpus_cases.py holdout \\
        --template <template> --selection <vera_selection.json> \\
        [--out DIR] [--gates routine | --gates <verdicts.jsonl>] \\
        [--verification-records store_verification.jsonl]

``--gates routine`` (default): the routine-level harness
(umat_oti.corpus_features: primal_stress_state and ddsdde cells), the gates a
council row runs through today (G8). ``--gates FILE``: verdicts produced by
another gate run (e.g. Abaqus), JSON lines ``{"key", "side": "author" |
"council", "set_id", "verdict"}``. Exit 0: held for review; 1: withdrawn;
2: the selection or the run is incomplete or invalid.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

ORIGIN = "holdout_from_author_deck"
MIN_SOURCES = 5
FEATURES = ("primal_stress_state", "ddsdde")
VERIFIED = "verified"
#: what a deckless copy keeps of a repository: the Fortran and its includes
FORTRAN = {".f", ".for", ".f90", ".f77", ".ftn", ".fpp", ".f95", ".f03", ".f08", ".inc",
           ".h", ".fi", ".fh", ".mod"}


class SelectionError(ValueError):
    """The selection is not a usable blind hold-out selection."""


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def load_selection(path: Path, template: str) -> dict:
    """Vera's blind selection, checked: her name, blind, this template, >= 5 distinct keys."""
    selection = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    if selection.get("template") != template:
        problems.append(f"the selection is for template {selection.get('template')!r}, "
                        f"not {template!r}")
    if "vera" not in str(selection.get("selected_by", "")).lower():
        problems.append("the selection is not Vera's (selected_by)")
    if selection.get("blind") is not True:
        problems.append("the selection does not state blind: true")
    keys = [str(k) for k in selection.get("keys") or ()]
    if len(set(keys)) != len(keys):
        problems.append("a key is listed twice")
    if len(set(keys)) < MIN_SOURCES:
        problems.append(f"{len(set(keys))} source(s); the hold-out needs at least {MIN_SOURCES}")
    if problems:
        raise SelectionError("; ".join(problems))
    return dict(selection, keys=keys)


def author_side(key: str) -> tuple:
    """``(registry record, author-deck manifest)`` of a VERIFIED author-deck source."""
    from umat_oti.corpus_features import harness as H
    records = {r["key"]: r for r in json.loads(Path(H.REGISTRY).read_text())["records"]}
    record = records.get(key)
    if record is None:
        raise SelectionError(f"{key} is not in the registry")
    if record.get("terminal_state") != "fully_verified":
        raise SelectionError(f"{key} is {record.get('terminal_state')}, not a verified "
                             "author-deck source")
    if (Path(H.COUNCIL_PLANS) / key / "council_plan.json").is_file():
        raise SelectionError(f"{key} is a council row, not an author-deck source")
    verification = H._pass16_record(key) or {}
    manifest = (verification.get("manifest")
                or (verification.get("experiment") or {}).get("manifest") or {})
    if not manifest:
        raise SelectionError(f"{key}: no author-deck manifest in {H.PASS16}")
    return record, manifest


# ---------------------------------------------------------------------------
# the hold-out row
# ---------------------------------------------------------------------------

def _statement(manifest: dict) -> str:
    element = str(manifest.get("element_type") or "").upper()
    ntens = int(manifest.get("ntens") or 0)
    if element.startswith("CPS"):
        word = "plane stress"
    elif element.startswith(("CPE", "CPEG")):
        word = "plane strain"
    elif element.startswith("CAX"):
        word = "axisymmetric"
    elif element.startswith("C3D") or ntens == 6:
        word = "3D, NTENS=6"
    else:
        word = ""
    finite = str(manifest.get("kinematics") or "").startswith("finite")
    return (f"{word}{', finite strain' if finite else ''} (element {element or '?'} of the "
            f"verified author deck; {ORIGIN})").strip()


def holdout_row(record: dict, manifest: dict, source_text: str, family: str = "") -> dict:
    """The author deck's constants as a harvest-format row (origin holdout_from_author_deck)."""
    from umat_oti.abaqus import experiment as X
    body = X._strip_header(X._executable(source_text))
    where = ("verified author deck: "
             + str(manifest.get("material_provenance") or record.get("source_id"))[:300])
    constants = []
    for index, value in enumerate(manifest.get("props") or (), start=1):
        token = repr(float(value))
        constants.append({"index": index, "name": None,
                          "raw": {"tokens": {"x": token}, "unit": None},
                          "value": float(value), "unit": "unstated", "rule": "literal",
                          "confidence": "exact", "never_count_reason": None,
                          "where": where, "line_or_page": f"PROPS({index})",
                          "quote": f"PROPS({index}) = {token}"})
    initial = [float(v) for v in manifest.get("initial_statev") or ()]
    return {
        "schema_version": 1, "source_id": record["source_id"], "key": record["key"],
        "family": family, "duplicate_of": None,
        "repository": str(record.get("repository") or ""),
        "commit": str(record.get("commit") or ""),
        "status": "COMPLETE", "eligible": True, "material_data_origin": ORIGIN,
        "unit_system": {"value": "the author deck's (unstated)", "stated": False,
                        "where": None, "line_or_page": None, "quote": None},
        "constants": constants, "missing": [],
        "nstatv": {"value": int(manifest.get("nstatv") or 0), "rule": "stated",
                   "where": "verified author-deck manifest", "line_or_page": None,
                   "quote": None},
        "initial_statev": ({"value": initial, "rule": "stated",
                            "where": "verified author-deck manifest", "line_or_page": None,
                            "quote": None} if any(initial) else None),
        "formulation_statement": _statement(manifest),
        "documented_domain": {k: None for k in ("strain_max", "stretch_max", "temperature",
                                                 "rate_or_period", "total_time", "geometry")},
        "documented_domain_present": False,
        "reads_coords_or_noel": bool(X._NOEL_READ.search(body)),
        "reads_temp": bool(X._TEMP_READ.search(body)),
        "reads_no_props": not constants, "mapping": None,
        "notes": (f"{ORIGIN}: R6.3 blind hold-out row; never counted. reads_* come from a "
                  "name scan of the executable text, not a reviewed scan."),
    }


def deckless_copy(source_id: str, cache: Path, into: Path) -> Path:
    """The source's repository with only its Fortran files: no deck can pair."""
    repository = str(source_id).split("/")[0]
    origin = Path(cache) / repository
    for path in sorted(origin.rglob("*")):
        if path.is_file() and (path.suffix.lower() in FORTRAN
                               or path == Path(cache) / source_id):
            target = Path(into) / repository / path.relative_to(origin)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return Path(into)


def prepare(keys: list, out: Path) -> dict:
    """Rows, deckless cache and council plans for the selected keys."""
    import corpus_cases as cc
    from umat_oti.corpus_features import harness as H
    out = Path(out)
    families = {}
    if Path(H.FAMILIES).is_file():
        families = {r["source_id"]: r.get("family", "")
                    for r in json.loads(Path(H.FAMILIES).read_text())["rows"]}
    rows, problems = [], []
    for key in keys:
        try:
            record, manifest = author_side(key)
        except SelectionError as error:
            problems.append(str(error))
            continue
        source = Path(H.CACHE) / record["cache_path"]
        rows.append(holdout_row(record, manifest, source.read_text(errors="replace"),
                                families.get(record["source_id"], "")))
        deckless_copy(record["cache_path"], Path(H.CACHE), out / "cache")
    if problems:
        raise SelectionError("; ".join(problems))
    rows_file = out / "holdout_rows.jsonl"
    rows_file.parent.mkdir(parents=True, exist_ok=True)
    rows_file.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
                         encoding="utf-8")
    plans = out / "council_plans"
    common = ["--rows", rows_file, "--out", plans, "--cache", out / "cache"]
    rc, printed = cc.run_make_council_deck(common)
    rc_check, checked = cc.run_make_council_deck(common + ["--check"])
    return {"rows_file": rows_file, "plans": plans, "printed": printed + checked,
            "regenerates": rc == 0 and rc_check == 0}


# ---------------------------------------------------------------------------
# gates and verdicts
# ---------------------------------------------------------------------------

def routine_gate(work: Path) -> Callable:
    """The routine-level harness, run the same way on both sides. ``gate(key,
    plans)``: ``plans`` None = the author-deck experiment; else the council
    experiment of ``key#set`` from that plans folder."""
    import corpus_cases as cc
    from umat_oti.corpus_features import harness as H
    from umat_oti.corpus_features.cells import fold

    def gate(key: str, plans: Optional[Path]) -> dict:
        saved = H.COUNCIL_PLANS
        if plans is not None:
            H.COUNCIL_PLANS = Path(plans)
        try:
            entry = H.resolve_entry(key)
        finally:
            H.COUNCIL_PLANS = saved
        council = bool(entry.provenance.get("council_plan"))
        if council != (plans is not None):
            return {"verdict": "not_run", "why": f"{key} resolved to the "
                    f"{'council' if council else 'author-deck'} experiment"}
        side = "council" if council else "author"
        place = Path(work) / side / re.sub(r"[^A-Za-z0-9]+", "_", key)
        if entry.store_dir is None:
            out_dir, meta = cc.regenerate(entry.original_source, entry.source_id,
                                          cc.sha256_file(entry.original_source), entry.ntens,
                                          place / "transform")
            if out_dir is None:
                return {"verdict": "not_run", "why": str(meta.get("reason"))[:300]}
            entry.store_dir = out_dir
        records = H.run_entry(entry, place / "harness", features=FEATURES)
        cells = fold(records, evidence=f"holdout:{key}")
        statuses = {f: next((c["status"] for c in cells if c["feature"] == f), "not_attempted")
                    for f in FEATURES}
        return {"verdict": VERIFIED if all(s == VERIFIED for s in statuses.values())
                else "not_verified", "statuses": statuses}
    return gate


def verdicts_gate(path: Path) -> Callable:
    """Verdicts another gate run produced (JSON lines key/side/set_id/verdict)."""
    table = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            table[(str(row["key"]), str(row.get("side")), str(row.get("set_id") or ""))] = row

    def gate(key: str, plans: Optional[Path]) -> dict:
        base, _hash, set_id = key.partition("#")
        row = table.get((base, "council" if plans is not None else "author", set_id))
        return {"verdict": row["verdict"]} if row else {"verdict": "not_run",
                                                         "why": f"no verdict in {path}"}
    return gate


def judge(template: str, keys: list, plans: Path, gate: Callable) -> dict:
    """Compare council and author-deck verdicts on every selected source."""
    sources = []
    for key in keys:
        plan = json.loads((Path(plans) / key / "council_plan.json").read_text())
        author = gate(key, None)
        if plan.get("refusal") or plan.get("refusal_code"):
            council = {"verdict": f"refused:{plan.get('refusal_code')}",
                       "why": str(plan.get("refusal"))[:300], "sets": {}}
        else:
            sets = {str(s["set_id"]): gate(f"{key}#{s['set_id']}", Path(plans))
                    for s in plan["sets"]}
            verdicts = [v["verdict"] for v in sets.values()]
            council = {"sets": sets, "verdict": (
                "not_run" if "not_run" in verdicts else
                VERIFIED if verdicts and all(v == VERIFIED for v in verdicts)
                else "not_verified")}
        ran = "not_run" not in (author["verdict"], council["verdict"])
        sources.append({"key": key, "source_id": plan.get("row_ref", "").partition(":")[2],
                        "route": plan.get("route"),
                        "author": author, "council": council,
                        "agree": (author["verdict"] == council["verdict"]) if ran else None})
    disagree = [s["key"] for s in sources if s["agree"] is False]
    not_run = [s["key"] for s in sources if s["agree"] is None]
    status = ("withdrawn" if disagree else "incomplete" if not_run
              else "held_for_vera_review")
    return {"tier": "holdout", "template": template, "status": status,
            "disagreements": disagree, "not_run": not_run, "sources": sources,
            "rule": "R6.3: every council verdict must equal the author-deck verdict; one "
                    "disagreement withdraws the template; agreement only holds it for Vera",
            "q4": "the gates are independent of the inputs' origin; the inputs are not "
                  "independent of the council's choices"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--template", required=True)
    parser.add_argument("--selection", required=True, type=Path, help="Vera's blind selection")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--gates", default="routine",
                        help="'routine' (the routine-level harness) or a verdicts JSONL file")
    parser.add_argument("--verification-records", type=Path, default=None)
    args = parser.parse_args(argv)
    import corpus_cases as cc
    from umat_oti.corpus_features import harness as H
    if args.verification_records is not None:
        H.PASS16 = args.verification_records.resolve()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", args.template).strip("-").lower()
    out = args.out or (cc.WORKSPACE / "corpus_campaign" / "holdout" / slug
                       / datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))
    try:
        selection = load_selection(args.selection, args.template)
        prepared = prepare(selection["keys"], out)
    except SelectionError as error:
        print(f"hold-out not run: {error}")
        return 2
    print(prepared["printed"].strip())
    if not prepared["regenerates"]:
        print("hold-out not run: the hold-out plans do not regenerate byte for byte")
        return 2
    gate = (routine_gate(out / "work") if args.gates == "routine"
            else verdicts_gate(Path(args.gates)))
    report = judge(args.template, selection["keys"], prepared["plans"], gate)
    report.update(selection={k: selection.get(k) for k in ("selected_by", "date", "blind")},
                  selection_file=str(args.selection),
                  selection_sha256=cc.sha256_file(args.selection),
                  rows_file=str(prepared["rows_file"]), gates=args.gates,
                  fingerprints=cc.fingerprints(),
                  date=datetime.datetime.now().isoformat(timespec="seconds"))
    cc.write_json(out / "holdout_report.json", json.loads(json.dumps(report, default=str)))
    for s in report["sources"]:
        print(f"{'AGREE   ' if s['agree'] else 'DISAGREE' if s['agree'] is False else 'NOT RUN '}"
              f" {s['key']} author {s['author']['verdict']} / council {s['council']['verdict']}")
    print(f"template {args.template}: {report['status'].upper()} -> {out / 'holdout_report.json'}")
    return {"held_for_vera_review": 0, "withdrawn": 1}.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
