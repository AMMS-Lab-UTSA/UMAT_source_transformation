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
scan (``REVIEWED_SCANS``, ``--reviewed-scan``) where one names the source --
matched by ``registry_key`` (the current pass's key), ``key`` (the selection's)
or ``source_id`` -- and ONLY if Vera accepted that row (``vera_accepted: true``)
and its ``source_sha256``, where given, is the cached file's. A matching row
that is not accepted, or names other bytes, stops the run as incomplete
(exit 2) naming the row.

Picks that leave (decision D-22, recorded in the report's ``left``; the
selection file is never edited):

* R-H1: a pick whose source is not fully_verified at the pass the hold-out
  runs on. A replacement is due only when fewer than 5 picks remain AND the
  family's pool was stratified (``n_available`` > 5); the runner never picks
  it -- it reports the run incomplete until Vera's seeded order supplies one.
* R-H2: a pick whose council plan needs an input no template rule decides, or
  one the template refuses (plan refusals ``R_H2_REFUSALS``) -- "not a
  template test", never a disagreement. A COORDS/NOEL-reading pick with no
  reviewed placement is placed by G12 in the author's documented geometry:
  the box of the author deck's *NODE coordinates, clear of every zero
  coordinate plane, with NOEL = NPT = 1 (within ReadDetF's 3000 x 27).
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
                   "static_scan_overrides", "placement", "undefined_outputs")
#: council-plan refusals that mean the template refuses an input (D-22 R-H2)
R_H2_REFUSALS = ("needs_documented_temperature", "needs_documented_geometry", "body_force",
                 # Vera, D-22: a growth source whose clock needs a total time no
                 # template rule decides (mholla umat_iso_morph)
                 "growth_needs_total_time")
#: ReadDetF(3000, 27) in the Jeff97 growth sources (D-22 condition)
NOEL_NPT_BOUNDS = (3000, 27)

FEATURES = ("primal_stress_state", "ddsdde")
VERIFIED = "verified"
#: what a deckless copy keeps of a repository: the Fortran and its includes
FORTRAN = {".f", ".for", ".f90", ".f77", ".ftn", ".fpp", ".f95", ".f03", ".f08", ".inc",
           ".h", ".fi", ".fh", ".mod"}


class SelectionError(ValueError):
    """The selection is not a usable blind hold-out selection."""

class NotVerifiedHere(SelectionError):
    """The pick is not fully_verified at the run's pass (D-22 R-H1)."""


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


def same_pass(registry: Path, verification_records: Path) -> None:
    """Refuse unless the registry (R-H1's terminal states) and the verification
    records (the author side) come from the same pass: the registry's recorded
    ``verification_results`` is the records file, and every record carries the
    registry's store and harness fingerprints."""
    inputs = (json.loads(Path(registry).read_text()).get("summary") or {}).get("inputs") or {}
    named = str(inputs.get("verification_results") or "")
    path = Path(verification_records).resolve().as_posix()
    problems = []
    if not named or not path.endswith("/" + named.lstrip("/")):
        problems.append(f"the registry was built from {named or 'no recorded records file'}, "
                        f"not {verification_records}")
    want = (str(inputs.get("store_fingerprint") or ""), str(inputs.get("harness_fingerprint") or ""))
    seen = set()
    for row in _records_by_key(verification_records).values():
        seen.add((str(row.get("fingerprint") or ""), str(row.get("harness_fingerprint") or "")))
    other = sorted(f for f in seen if f != want)
    if not all(want) or other:
        problems.append(f"the registry records store/harness {want[0] or '?'}/{want[1] or '?'} "
                        f"and the records carry {', '.join('/'.join(f) for f in other) or 'none'}")
    if problems:
        raise SelectionError("the registry and the verification records are not from the same "
                             "pass: " + "; ".join(problems))


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
        raise NotVerifiedHere(f"{key} is {record.get('terminal_state')}, not a verified "
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
    """Reviewed static scans by registry_key, key and source_id (first file, first
    row wins). Every row is kept, accepted or not: ``reviewed_reads`` decides use."""
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
            entry = dict({k: row.get(k) for k in REVIEWED_FIELDS}, file=str(path),
                         vera_accepted=row.get("vera_accepted") is True,
                         source_sha256=row.get("source_sha256"),
                         ident=str(row.get("registry_key") or row.get("key")
                                   or row.get("source_id")),
                         source_id=row.get("source_id"))
            for ident in (row.get("registry_key"), row.get("key"), row.get("source_id")):
                if ident:
                    out.setdefault(str(ident), entry)
    return out


def reviewed_reads(record: dict, body: str, reviewed: Optional[dict],
                   source_sha256: Optional[str] = None) -> dict:
    """The TEMP and COORDS/NOEL flags to the reviewed standard of a council row.

    Only a Vera-accepted row is used; a matching row that is not accepted, or
    that reviewed other bytes, leaves both flags None and says which row."""
    from umat_oti.abaqus import experiment as X
    entry = (reviewed or {}).get(record.get("key")) or (reviewed or {}).get(record["source_id"])
    out: dict = {"basis": {}}
    if entry is not None:
        name = f"{Path(entry['file']).name} row {entry['ident']} ({entry.get('source_id')})"
        why = ("is not accepted by Vera (vera_accepted is not true)"
               if not entry["vera_accepted"] else
               f"reviewed source_sha256 {str(entry['source_sha256'])[:12]}, not the cached "
               f"file's {str(source_sha256)[:12]}"
               if entry.get("source_sha256") and source_sha256
               and entry["source_sha256"] != source_sha256 else "")
        if why:
            for flag in ("reads_temp", "reads_coords_or_noel"):
                out[flag] = None
                out["basis"][flag] = f"the reviewed static scan {name} {why}"
            return out
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
        for field in ("reads_temp_note", "coords_note", "static_scan_overrides", "placement",
                      "undefined_outputs"):
            if entry.get(field):
                out[field] = entry[field]
    return out


def holdout_row(record: dict, manifest: dict, source_text: str, family: str = "",
                reviewed: Optional[dict] = None, source_sha256: Optional[str] = None) -> dict:
    """The author deck's constants as a harvest-format row (origin holdout_from_author_deck).

    ``reads_temp`` / ``reads_coords_or_noel`` follow the reviewed standard of a
    council row (``reviewed_reads``); ``None`` where a name-scan hit has no review."""
    from umat_oti.abaqus import experiment as X
    body = X._strip_header(X._executable(source_text))
    reads = reviewed_reads(record, body, reviewed, source_sha256)
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
                                 "placement", "undefined_outputs") if k in reads},
        "reads_no_props": not constants, "mapping": None,
        "notes": (f"{ORIGIN}: R6.3 blind hold-out row; never counted. reads_temp: "
                  f"{reads['basis']['reads_temp']}; reads_coords_or_noel: "
                  f"{reads['basis']['reads_coords_or_noel']}."),
    }


def author_mesh_placement(deck_text: str, deck_name: str) -> Optional[dict]:
    """G12 placement in the author's documented geometry (D-22 R-H2): the box of
    the deck's *NODE coordinates, avoiding every zero-coordinate plane inside it
    (no placed node or integration point at a zero coordinate)."""
    from umat_oti.abaqus.coordinate_domain import node_box
    box = node_box(deck_text)
    if len(box) != 3 or any(high <= low for low, high in box):
        return None
    avoid = {axis: 0.0 for axis, (low, high) in zip("xyz", box) if low <= 0.0 <= high}
    return {"box": [[low for low, _ in box], [high for _, high in box]], "avoid": avoid,
            "where": f"the author's mesh ({deck_name}): box of its *NODE coordinates "
                     "(G12, D-22 R-H2)",
            "origin": "author_published"}


def r_h2_leaves(plan: dict) -> str:
    """Why a council plan makes its pick "not a template test" (D-22 R-H2), or ''."""
    code = plan.get("refusal_code")
    if code in R_H2_REFUSALS:
        return (f"not a template test: the council plan is refused {code} "
                f"({str(plan.get('refusal'))[:200]})")
    return ""


def placement_problems(plan: dict) -> list:
    """D-22 conditions on a placed plan: no zero node coordinate, NOEL/NPT in bounds."""
    placement = plan.get("placement") or {}
    out = []
    for council_set in plan.get("sets") or ():
        manifest = ((council_set.get("plan") or {}).get("experiment") or {}).get("manifest") or {}
        for node in manifest.get("node_coordinates") or ():
            if any(float(c) == 0.0 for c in list(node)[1:]):
                out.append(f"set {council_set.get('set_id')}: node {node[0]} has a zero "
                           "coordinate")
    point = placement.get("driver_point") or {}
    if point and (int(point.get("noel", 1)) > NOEL_NPT_BOUNDS[0]
                  or int(point.get("npt", 1)) > NOEL_NPT_BOUNDS[1]):
        out.append(f"driver point NOEL/NPT {point.get('noel')}/{point.get('npt')} outside "
                   f"{NOEL_NPT_BOUNDS}")
    return out


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
    import hashlib
    reviewed = load_reviewed(reviewed_scans)
    records_file = Path(verification_records or CURRENT_RECORDS)
    if not records_file.is_file():
        raise SelectionError(f"no verification records at {records_file}")
    same_pass(Path(H.REGISTRY), records_file)
    rows, problems, left = [], [], []
    for key in keys:
        try:
            record, manifest = author_side(key, verification_records)
        except NotVerifiedHere as error:
            left.append({"key": key, "rule": "R-H1", "why": str(error)})
            continue
        except SelectionError as error:
            problems.append(str(error))
            continue
        source = Path(H.CACHE) / record["cache_path"]
        row = holdout_row(record, manifest, source.read_text(errors="replace"),
                          families.get(record["source_id"], ""), reviewed,
                          hashlib.sha256(source.read_bytes()).hexdigest())
        if row["reads_coords_or_noel"] and not row.get("placement"):
            deck = str((_records_by_key(records_file).get(key) or {}).get("deck") or "")
            deck_file = Path(H.CACHE) / deck
            placement = (author_mesh_placement(deck_file.read_text(errors="replace"),
                                               deck_file.name)
                         if deck and deck_file.is_file() else None)
            if placement:
                row["placement"] = placement
        unanswered = [f for f in ("reads_temp", "reads_coords_or_noel") if row[f] is None]
        if unanswered:
            problems.append(f"{key} ({record['source_id']}) needs a Vera-accepted reviewed "
                            f"static scan for {', '.join(unanswered)}: {row['notes']}")
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
    kept = []
    for row in rows:
        plan_file = plans / row["key"] / "council_plan.json"
        plan = json.loads(plan_file.read_text()) if plan_file.is_file() else {}
        why = r_h2_leaves(plan)
        if why:
            left.append({"key": row["key"], "rule": "R-H2", "why": why})
            continue
        bad = placement_problems(plan) if plan.get("placement") else []
        if bad:
            problems.append(f"{row['key']}: placement breaks the D-22 conditions: "
                            + "; ".join(bad))
        kept.append(row["key"])
    if problems:
        raise SelectionError("; ".join(problems))
    return {"rows_file": rows_file, "plans": plans, "printed": printed + checked,
            "regenerates": rc == 0 and rc_check == 0, "kept": kept, "left": left}


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
        kept = prepared["kept"]
        if not kept:
            raise SelectionError("every pick left the selection: " + "; ".join(
                f"{x['key']} ({x['rule']})" for x in prepared["left"]))
        pool = int(selection.get("n_available") or len(selection["keys"]))
        if prepared["left"] and len(kept) < MIN_SOURCES and pool > MIN_SOURCES:
            raise SelectionError(
                f"{len(kept)} pick(s) remain of a stratified pool of {pool}: D-22 R-H1 asks "
                "for a replacement from Vera's seeded order, which this runner never picks "
                "(left: " + "; ".join(f"{x['key']} {x['rule']}" for x in prepared["left"])
                + ")")
    except SelectionError as error:
        print(f"hold-out not run: {error}")
        return 2
    print(prepared["printed"].strip())
    if not prepared["regenerates"]:
        print("hold-out not run: the hold-out plans do not regenerate byte for byte")
        return 2
    gate = (routine_gate(out / "work") if args.gates == "routine"
            else verdicts_gate(Path(args.gates)))
    mode = HOLDOUT if len(kept) >= MIN_SOURCES else FALSIFICATION_ONLY
    report = judge(args.template, kept, prepared["plans"], gate, mode)
    selected = {b: (a, c) for a, b, c in key_map}
    report["left"] = [dict(x, selected=selected.get(x["key"], ("", ""))[0],
                           source_id=selected.get(x["key"], ("", ""))[1])
                      for x in prepared["left"]]
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
