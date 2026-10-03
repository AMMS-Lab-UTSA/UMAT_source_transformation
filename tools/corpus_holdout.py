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
holds the template for Vera's review; acceptance is hers (R6.5). A template
with only 1-4 verified author-deck sources gets a FALSIFICATION-ONLY report
(Vera's ruling): a disagreement still withdraws it, and agreement accepts
nothing -- the report says "not withdrawn", never "held for review".

The author side is read from the CURRENT pass (``CURRENT_RECORDS``, pass21;
``--verification-records`` overrides), and a selected key that the current
registry does not carry (store keys move with the transform fingerprint) is
followed to its current key through the source the selection names.

TEMP and COORDS/NOEL/NPT reads are set to the REVIEWED value, as a council
row's are (D-21a (e), accepted overrides included): from a reviewed static
scan (``REVIEWED_SCANS``, ``--reviewed-scan``) where one names the source.
Without one, a flag is false only where a name scan finds no executable use
(a read must name the argument, so the scan cannot miss one); a name-scan hit
with no review leaves the hold-out incomplete (exit 2), never a refused plan. Q4: the gates
are independent of the inputs' origin, the inputs are not independent of the
council's choices -- only the hold-out and review validate those choices.

Selection file (written by Vera; JSON)::

    {"template": "<template>", "selected_by": "vera", "blind": true,
     "date": "YYYY-MM-DD", "keys": ["<registry key>", ...],
     "chosen": [{"key": ..., "source_id": ...}, ...]}   # 1-4 keys: falsification only

Run::

    PYTHONHASHSEED=0 PYTHONPATH=src python tools/corpus_cases.py holdout \\
        --template <template> --selection <vera_selection.json> \\
        [--out DIR] [--gates routine | --gates <verdicts.jsonl>] \\
        [--verification-records store_verification.jsonl] [--reviewed-scan FILE ...]

``--gates routine`` (default): the routine-level harness
(umat_oti.corpus_features: primal_stress_state and ddsdde cells), the gates a
council row runs through today (G8). ``--gates FILE``: verdicts produced by
another gate run (e.g. Abaqus), JSON lines ``{"key", "side": "author" |
"council", "set_id", "verdict"}``. Exit 0: held for review; 1: withdrawn;
2: the selection or the run is incomplete or invalid; 3: falsification-only
report with no disagreement (not withdrawn, nothing accepted).
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
#: a full hold-out (R6.3); 1..MIN_SOURCES-1 sources give a falsification-only report
MIN_SOURCES = 5
FALSIFICATION_ONLY = "falsification_only"
HOLDOUT = "holdout"
_WORKSPACE = Path(__import__("os").environ.get("UMAT_OTI_WORKSPACE")
                  or Path.home() / "softwarex_work")
#: the author side is the CURRENT pass's verification records (pass21)
CURRENT_RECORDS = _WORKSPACE / "corpus_run/pass21/results/store_verification.jsonl"
#: reviewed static scans (reads_temp / reads_coords_or_noel, notes, accepted
#: overrides), first match by key or source_id wins: the hold-out's own review
#: file, then the reviewed rows of the harvest and the council constants
REVIEWED_SCANS = (_WORKSPACE / "corpus_campaign/holdout/reviewed_scan.jsonl",
                  _WORKSPACE / "corpus_campaign/material_data/d19_harvest.jsonl",
                  _WORKSPACE / "corpus_campaign/material_data/d21_council_constants.jsonl")
REVIEWED_FIELDS = ("reads_temp", "reads_coords_or_noel", "reads_temp_note", "coords_note",
                   "static_scan_overrides", "placement")
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
    """Vera's blind selection, checked: her name, blind, this template, distinct keys.

    ``mode`` is ``holdout`` with >= MIN_SOURCES keys and ``falsification_only``
    with 1..MIN_SOURCES-1 (Vera's ruling for small templates); none is refused."""
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
    if not keys:
        problems.append("no source selected; there is nothing to falsify")
    if problems:
        raise SelectionError("; ".join(problems))
    mode = HOLDOUT if len(set(keys)) >= MIN_SOURCES else FALSIFICATION_ONLY
    return dict(selection, keys=keys, mode=mode)


def current_keys(selection: dict, registry: Optional[Path] = None) -> list:
    """``[(selected key, current key, source_id)]``: each selected key in the
    current registry, followed through the source the selection names when the
    store key moved with the transform fingerprint. The selection is unchanged."""
    from umat_oti.corpus_features import harness as H
    records = json.loads(Path(registry or H.REGISTRY).read_text())["records"]
    by_key = {r.get("key"): r for r in records if r.get("key")}
    by_source = {r["source_id"]: r for r in records}
    named = {str(c.get("key")): str(c.get("source_id") or "")
             for c in selection.get("chosen") or () if isinstance(c, dict)}
    out, problems = [], []
    for key in selection["keys"]:
        if key in by_key:
            out.append((key, key, by_key[key]["source_id"]))
            continue
        record = by_source.get(named.get(key, ""))
        if record is None or not record.get("key"):
            problems.append(f"{key} is not in the current registry and the selection names no "
                            "source that is")
            continue
        out.append((key, record["key"], record["source_id"]))
    if problems:
        raise SelectionError("; ".join(problems))
    return out


def _records_by_key(path: Path) -> dict:
    out = {}
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if row.get("key"):
                    out[str(row["key"])] = row
    return out


def author_side(key: str, verification_records: Optional[Path] = None) -> tuple:
    """``(registry record, author-deck manifest)`` of a VERIFIED author-deck source,
    the manifest read from the CURRENT pass's records (default ``CURRENT_RECORDS``)."""
    from umat_oti.corpus_features import harness as H
    records_file = Path(verification_records or CURRENT_RECORDS)
    if not records_file.is_file():
        raise SelectionError(f"no verification records at {records_file}")
    records = {r["key"]: r for r in json.loads(Path(H.REGISTRY).read_text())["records"]}
    record = records.get(key)
    if record is None:
        raise SelectionError(f"{key} is not in the registry")
    if record.get("terminal_state") != "fully_verified":
        raise SelectionError(f"{key} is {record.get('terminal_state')}, not a verified "
                             "author-deck source")
    if (Path(H.COUNCIL_PLANS) / key / "council_plan.json").is_file():
        raise SelectionError(f"{key} is a council row, not an author-deck source")
    verification = _records_by_key(records_file).get(key) or {}
    manifest = (verification.get("manifest")
                or (verification.get("experiment") or {}).get("manifest") or {})
    if not manifest:
        raise SelectionError(f"{key}: no author-deck manifest in {records_file}")
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


def load_reviewed(paths=None) -> dict:
    """Reviewed static scans by key and by source_id (first file, first row wins)."""
    out: dict = {}
    for path in (paths if paths is not None else REVIEWED_SCANS):
        if not Path(path).is_file():
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("reads_temp") is None and row.get("reads_coords_or_noel") is None:
                continue
            entry = dict({k: row.get(k) for k in REVIEWED_FIELDS}, file=str(path))
            for ident in (row.get("key"), row.get("source_id")):
                if ident:
                    out.setdefault(str(ident), entry)
    return out


def reviewed_reads(record: dict, body: str, reviewed: Optional[dict]) -> dict:
    """The TEMP and COORDS/NOEL flags to the reviewed standard of a council row."""
    from umat_oti.abaqus import experiment as X
    entry = (reviewed or {}).get(record.get("key")) or (reviewed or {}).get(record["source_id"])
    out: dict = {"basis": {}}
    for flag, pattern in (("reads_temp", X._TEMP_READ), ("reads_coords_or_noel", X._NOEL_READ)):
        named = sorted({m.upper() for m in pattern.findall(body)})
        if entry is not None and entry.get(flag) is not None:
            out[flag] = bool(entry[flag])
            out["basis"][flag] = f"reviewed static scan ({Path(entry['file']).name})"
        elif not named:
            out[flag] = False
            out["basis"][flag] = ("no executable use named (a read must name the argument); "
                                  "no reviewed scan needed")
        else:
            out[flag] = None
            out["basis"][flag] = (f"the name scan finds {', '.join(named)} and no reviewed "
                                  "static scan names this source")
    if entry is not None:
        for field in ("reads_temp_note", "coords_note", "static_scan_overrides", "placement"):
            if entry.get(field):
                out[field] = entry[field]
    return out


def holdout_row(record: dict, manifest: dict, source_text: str, family: str = "",
                reviewed: Optional[dict] = None) -> dict:
    """The author deck's constants as a harvest-format row (origin holdout_from_author_deck).

    ``reads_temp`` / ``reads_coords_or_noel`` follow the reviewed standard of a
    council row (``reviewed_reads``); ``None`` where a name-scan hit has no review."""
    from umat_oti.abaqus import experiment as X
    body = X._strip_header(X._executable(source_text))
    reads = reviewed_reads(record, body, reviewed)
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
        "reads_coords_or_noel": reads["reads_coords_or_noel"],
        "reads_temp": reads["reads_temp"],
        **{k: reads[k] for k in ("reads_temp_note", "coords_note", "static_scan_overrides",
                                 "placement") if k in reads},
        "reads_no_props": not constants, "mapping": None,
        "notes": (f"{ORIGIN}: R6.3 blind hold-out row; never counted. reads_temp: "
                  f"{reads['basis']['reads_temp']}; reads_coords_or_noel: "
                  f"{reads['basis']['reads_coords_or_noel']}."),
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


def prepare(keys: list, out: Path, verification_records: Optional[Path] = None,
            reviewed_scans=None) -> dict:
    """Rows, deckless cache and council plans for the selected (current) keys."""
    import corpus_cases as cc
    from umat_oti.corpus_features import harness as H
    out = Path(out)
    families = {}
    if Path(H.FAMILIES).is_file():
        families = {r["source_id"]: r.get("family", "")
                    for r in json.loads(Path(H.FAMILIES).read_text())["rows"]}
    reviewed = load_reviewed(reviewed_scans)
    rows, problems = [], []
    for key in keys:
        try:
            record, manifest = author_side(key, verification_records)
        except SelectionError as error:
            problems.append(str(error))
            continue
        source = Path(H.CACHE) / record["cache_path"]
        row = holdout_row(record, manifest, source.read_text(errors="replace"),
                          families.get(record["source_id"], ""), reviewed)
        unanswered = [f for f in ("reads_temp", "reads_coords_or_noel") if row[f] is None]
        if unanswered:
            problems.append(f"{key} ({record['source_id']}) needs a reviewed static scan for "
                            f"{', '.join(unanswered)}: {row['notes']}")
            continue
        rows.append(row)
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


def judge(template: str, keys: list, plans: Path, gate: Callable,
          mode: str = HOLDOUT) -> dict:
    """Compare council and author-deck verdicts on every selected source.

    ``mode`` ``falsification_only`` (1-4 sources): a disagreement withdraws the
    template, agreement only reports it not withdrawn -- it accepts nothing."""
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
    agreed = ("held_for_vera_review" if mode == HOLDOUT
              else "not_withdrawn_falsification_only")
    status = ("withdrawn" if disagree else "incomplete" if not_run else agreed)
    rule = ("R6.3: every council verdict must equal the author-deck verdict; one "
            "disagreement withdraws the template; agreement only holds it for Vera"
            if mode == HOLDOUT else
            f"falsification only ({len(keys)} source(s) < {MIN_SOURCES}; Vera's ruling): one "
            "disagreement withdraws the template; agreement does not accept it and does not "
            "hold it for acceptance")
    return {"tier": "holdout", "mode": mode, "template": template, "status": status,
            "disagreements": disagree, "not_run": not_run, "sources": sources,
            "rule": rule,
            "q4": "the gates are independent of the inputs' origin; the inputs are not "
                  "independent of the council's choices"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--template", required=True)
    parser.add_argument("--selection", required=True, type=Path, help="Vera's blind selection")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--gates", default="routine",
                        help="'routine' (the routine-level harness) or a verdicts JSONL file")
    parser.add_argument("--verification-records", type=Path, default=None,
                        help="the current pass's store_verification.jsonl (default: "
                             "CURRENT_RECORDS, pass21)")
    parser.add_argument("--reviewed-scan", type=Path, action="append", default=None,
                        help="reviewed static scan rows (JSON lines; key or source_id, "
                             "reads_temp, reads_coords_or_noel, overrides); default "
                             "REVIEWED_SCANS")
    args = parser.parse_args(argv)
    import corpus_cases as cc
    from umat_oti.corpus_features import harness as H
    records_file = (args.verification_records or CURRENT_RECORDS).resolve()
    # the routine gate resolves both sides from the same pass as the author side
    H.PASS16 = records_file
    slug = re.sub(r"[^A-Za-z0-9]+", "-", args.template).strip("-").lower()
    out = args.out or (cc.WORKSPACE / "corpus_campaign" / "holdout" / slug
                       / datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))
    try:
        selection = load_selection(args.selection, args.template)
        key_map = current_keys(selection)
        keys = [current for _selected, current, _source in key_map]
        prepared = prepare(keys, out, records_file, args.reviewed_scan)
    except SelectionError as error:
        print(f"hold-out not run: {error}")
        return 2
    print(prepared["printed"].strip())
    if not prepared["regenerates"]:
        print("hold-out not run: the hold-out plans do not regenerate byte for byte")
        return 2
    gate = (routine_gate(out / "work") if args.gates == "routine"
            else verdicts_gate(Path(args.gates)))
    report = judge(args.template, keys, prepared["plans"], gate, selection["mode"])
    report.update(selection={k: selection.get(k) for k in ("selected_by", "date", "blind")},
                  key_map=[{"selected": a, "current": b, "source_id": c}
                           for a, b, c in key_map],
                  verification_records=str(records_file),
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
    return {"held_for_vera_review": 0, "withdrawn": 1,
            "not_withdrawn_falsification_only": 3}.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
