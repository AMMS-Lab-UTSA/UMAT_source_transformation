#!/usr/bin/env python
"""Intake scanner: what a UMAT (and optionally a deck) already tells us.

    python tools/intake_scan.py UMAT.for [DECK.inp | FOLDER] [--out DIR]

Prints, deterministically and without asking anything, every item the
pipeline needs, each tagged

    FOUND     the file states it (the line is quoted)
    INFERRED  read off the code or the deck by a rule (the line is quoted)
    DEFAULT   nothing states it; a stated default is used and can be changed
    MISSING   nothing states it and there is no honest default

and which of them need the user, in plain language, with the default for each
(design: batches/B11/maya/design.md section 3.1). It writes ``intake.json``
(``material_config`` is the existing ``--material-config`` form, filled as far
as the files go) and ``intake.md`` into ``--out``.

Nothing here is inferred by new rules. Every answer comes from the code the
harness itself uses -- ``umat_oti.corpus.entry_routines.classify`` (which
interface the file presents), ``umat_oti.abaqus.deck_pairing`` (which deck
feeds this routine, what a routine demands of its material block, what it
calls its constants), ``umat_oti.abaqus.formulation.settle`` (the formulation:
element and tensor size, from the source and the deck),
``umat_oti.transform.dependency_resolution.resolve_closure`` (helpers) and
``umat_oti.transform.source_modules`` (modules). This file only gathers,
quotes the lines they stand on, and says it in words. Read-only: no transform,
no compile, no run, and no value is ever invented -- a number the files do not
give is MISSING, not defaulted.

Library use (the ``check`` wrapper): ``scan(umat, deck=None, ...) -> Intake``;
``Intake.items``, ``Intake.needs_user()``, ``Intake.as_dict()``,
``Intake.to_markdown()``, ``Intake.write(out_dir)``. The plain-language texts
come from ``NEEDS`` below, and are replaced key by key by ``NEEDS`` in
``umat_oti.app.intake_text`` when that module exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

SCHEMA = "umat-oti/intake/1"
FOUND, INFERRED, DEFAULT, MISSING = "FOUND", "INFERRED", "DEFAULT", "MISSING"
STATUSES = (FOUND, INFERRED, DEFAULT, MISSING)

#: What the pipeline's own generated experiment assumes when nothing says
#: otherwise (docs/CLI_GUIDE.md): listed so none of it is silent.
DEFAULT_TEMPERATURE = 293.15

#: Plain-language statements for the items that need the user. ``ask`` says
#: what is needed and why in one or two sentences; ``default`` says what will
#: be used if the user says nothing (or that nothing can be). ``{x}`` fields
#: are filled from the item's context. Iris replaces these key by key through
#: ``umat_oti.app.intake_text.NEEDS`` (same keys, same fields).
NEEDS: dict[str, dict[str, str]] = {
    "routine": {
        "ask": "This file does not present the Abaqus material routine (UMAT): {why}.",
        "default": "none: pick the file that defines SUBROUTINE UMAT.",
        "whose": "you or the author"},
    "ntens": {
        "ask": "The files do not say how many stress components the routine is called with.",
        "default": "6 (a solid three-dimensional element), which is the usual.",
        "whose": "you"},
    "element": {
        "ask": "This kind of material or element is not one I can run: {why}.",
        "default": "none: this is outside what is supported today.",
        "whose": "this program"},
    "props_values": {
        "ask": "I could not find the numbers this material needs: the values of "
               "{slots}, in the routine's order.",
        "default": "none: values are never guessed. Give a deck with *USER MATERIAL, "
                   "or type them (for example E=210000 nu=0.3).",
        "whose": "you"},
    "helpers": {
        "ask": "Your routine calls {names}, which are not in the files you gave me.",
        "default": "none: add the file that defines {names} next to the UMAT, or give "
                   "its folder.",
        "whose": "you"},
    "includes": {
        "ask": "Your routine includes {names}, which are not in the files you gave me.",
        "default": "none: add the file next to the UMAT, or give its folder.",
        "whose": "you"},
    "modules": {
        "ask": "Your routine uses the module {names}, which is not in the files you "
               "gave me.",
        "default": "none: add the file that defines the module next to the UMAT.",
        "whose": "you"},
    "temperature": {
        "ask": "The routine reads the temperature and the files do not state one.",
        "default": "293.15 (isothermal), the same for every increment.",
        "whose": "you"},
    "coordinates": {
        "ask": "The routine reads where its material point is (COORDS) and no deck "
               "gives a mesh.",
        "default": "0, 0, 0 (the origin); this is a placeholder and may not suit the "
                   "routine.",
        "whose": "you"},
    "fields": {
        "ask": "The routine reads field variables (PREDEF/DPRED) and no deck says what "
               "they are.",
        "default": "all zero.",
        "whose": "you"},
}


def _plain(key: str, texts: Optional[dict] = None) -> dict[str, str]:
    """The text for ``key``: the caller's ``texts``, then Iris's module, then ours."""
    if texts and key in texts:
        return {**NEEDS[key], **texts[key]}
    try:
        from umat_oti.app import intake_text
    except ImportError:                                     # the module is not there yet
        return NEEDS[key]
    return {**NEEDS[key], **getattr(intake_text, "NEEDS", {}).get(key, {})}


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------
@dataclass
class Item:
    key: str
    label: str
    status: str
    value: object = None
    evidence: list = field(default_factory=list)     # [{"file", "line", "text"}]
    note: str = ""
    needs_user: bool = False
    ask: str = ""
    default: str = ""
    whose: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "status": self.status,
                "value": self.value, "evidence": self.evidence, "note": self.note,
                "needs_user": self.needs_user, "ask": self.ask,
                "default": self.default, "whose": self.whose}


@dataclass
class Intake:
    umat: str
    sha256: str
    repository: str
    deck: str = ""
    items: list = field(default_factory=list)
    material_config: Optional[dict] = None
    pipeline_inputs: dict = field(default_factory=dict)
    #: The settled answers as plain values (None where MISSING), for callers
    #: that must not parse sentences: ntens, element, family, nstatv,
    #: props_count, kinematics, props_values_found, deck_found, entry_is_umat.
    facts: dict = field(default_factory=dict)

    def item(self, key: str) -> Item:
        return next(i for i in self.items if i.key == key)

    def needs_user(self) -> list:
        return [i for i in self.items if i.needs_user]

    def counts(self) -> dict:
        return {s: sum(1 for i in self.items if i.status == s) for s in STATUSES}

    def as_dict(self) -> dict:
        return {"schema": SCHEMA,
                "inputs": {"umat": self.umat, "umat_sha256": self.sha256,
                           "deck": self.deck, "repository": self.repository},
                "counts": self.counts(),
                "needs_user": [i.key for i in self.needs_user()],
                "items": [i.as_dict() for i in self.items],
                "facts": self.facts,
                "pipeline_inputs": self.pipeline_inputs,
                "material_config": self.material_config}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"

    def to_text(self) -> str:
        width = max(len(i.label) for i in self.items)
        lines = [f"Intake: {self.umat}" + (f"  +  {self.deck}" if self.deck else "")]
        lines.append("")
        for i in self.items:
            lines.append(f"  {i.status:<8} {i.label:<{width}}  "
                         f"{_show(i.value) if i.value is not None else 'not found'}")
            for e in i.evidence[:3]:
                where = f"{e['file']}:{e['line']}" if e["line"] else f"{e['file']} (rule)"
                lines.append(f"  {'':<8} {'':<{width}}  {where}: {e['text']}")
            if i.note:
                lines.append(f"  {'':<8} {'':<{width}}  ({i.note})")
        lines.append("")
        needed = self.needs_user()
        if needed:
            lines.append("Needs you:")
            for i in needed:
                lines.append(f"  - {i.ask}")
                lines.append(f"    If you say nothing: {i.default}")
        else:
            lines.append("Needs you: nothing. Every item above was found, inferred or "
                         "has a stated default.")
        c = self.counts()
        lines.append("")
        lines.append("Summary: " + ", ".join(f"{c[s]} {s.lower()}" for s in STATUSES))
        return "\n".join(lines) + "\n"

    def to_markdown(self) -> str:
        out = [f"# Intake: `{self.umat}`", ""]
        out.append(f"Source `{self.umat}` (sha256 `{self.sha256[:16]}`)"
                   + (f", deck `{self.deck}`" if self.deck else ", no deck given")
                   + f", searched in `{self.repository}`.")
        out.append("")
        out.append("Each item is **FOUND** (the file says it), **INFERRED** (read from "
                   "the code by a rule), **DEFAULT** (nothing says it; the default is "
                   "stated) or **MISSING** (nothing says it and there is no honest default).")
        out.append("")
        out.append("| Status | Item | What was found | Where |")
        out.append("|---|---|---|---|")
        for i in self.items:
            where = "<br>".join(
                (f"`{e['file']}:{e['line']}` " if e["line"] else f"`{e['file']}` (rule) ")
                + f"`{_md(e['text'])}`" for e in i.evidence[:2]) or ""
            note = f" ({_md(i.note)})" if i.note else ""
            out.append(f"| {i.status} | {i.label} | {_md(_show(i.value) if i.value is not None else 'not found')}{note} | {where} |")
        out.append("")
        needed = self.needs_user()
        out.append("## What I need from you" if needed else "## What I need from you: nothing")
        out.append("")
        for i in needed:
            out.append(f"- {i.ask}  \n  *If you say nothing:* {i.default}")
        assumed = [i for i in self.items if i.status == DEFAULT and not i.needs_user]
        if assumed:
            out.append("")
            out.append("## Assumed (defaults you can change)")
            out.append("")
            for i in assumed:
                out.append(f"- **{i.label}**: {_show(i.value)}")
        out.append("")
        return "\n".join(out)

    def write(self, out_dir) -> tuple:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        j, m = out_dir / "intake.json", out_dir / "intake.md"
        j.write_text(self.to_json(), encoding="utf-8")
        m.write_text(self.to_markdown(), encoding="utf-8")
        return j, m


def _show(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_show(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={_show(v)}" for k, v in value.items())
    return str(value)


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# quoting
# ---------------------------------------------------------------------------
def _quote(file: str, line: int, text: str) -> dict:
    return {"file": file, "line": int(line), "text": " ".join(str(text).split())[:140]}


def _find_line(text: str, pattern, start: int = 0, skip_comments: bool = True):
    """(1-based line, stripped text) of the first line matching ``pattern``."""
    rx = re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str) else pattern
    lines = text.splitlines()
    for number in range(start, len(lines)):
        raw = lines[number]
        if skip_comments and (raw[:1] in "cC*!" or raw.lstrip().startswith("!")):
            continue
        if rx.search(raw):
            return number + 1, raw.strip()
    return 0, ""


def _code_find(text: str, pattern):
    """Like ``_find_line`` but skips declarations, the routine header and the
    continuation of either, so a name in an argument list is not a use."""
    from umat_oti.abaqus.experiment import _DECLARATION

    rx = re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str) else pattern
    declaring = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw[:1] in "cC*!" or raw.lstrip().startswith("!") or not raw.strip():
            continue
        continued = (len(raw) > 5 and raw[:5].strip() == "" and raw[5:6] not in (" ", "")) \
            or raw.lstrip().startswith("&")
        if _DECLARATION.match(raw):
            declaring = True
            continue
        if declaring and continued:
            continue
        declaring = False
        if rx.search(raw.split("!")[0]):
            return number, raw.strip()
    return 0, ""


def _rel(path: Path, base: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve()))
    except ValueError:
        return Path(path).name


# ---------------------------------------------------------------------------
# deck line finders (quoting only; the values come from deck_pairing)
# ---------------------------------------------------------------------------
def _deck_lines(deck_text: str, material_name: str) -> dict:
    """Lines of ``*MATERIAL``'s own keywords, for quoting what DeckMaterial read."""
    found: dict = {}
    lines = deck_text.splitlines()
    wanted = (material_name or "").strip().upper()
    start = -1
    for n, raw in enumerate(lines):
        s = raw.strip()
        if s[:9].upper() == "*MATERIAL" and "NAME" in s.upper():
            name = re.search(r"NAME\s*=\s*([^,\s]+)", s, re.IGNORECASE)
            if name and (not wanted or name.group(1).strip().upper() == wanted):
                start = n
                break
    if start < 0:
        start = 0
    for n in range(start, len(lines)):
        s = lines[n].strip()
        up = s.upper()
        if n > start and up.startswith("*MATERIAL"):
            break
        if up.startswith("*DEPVAR") and "depvar" not in found:
            found["depvar"] = (n + 1, s)
            if n + 1 < len(lines):
                found["depvar_data"] = (n + 2, lines[n + 1].strip())
        elif up.startswith("*USER MATERIAL") and "user" not in found:
            found["user"] = (n + 1, s)
            data = []
            for m in range(n + 1, min(n + 5, len(lines))):
                if lines[m].strip().startswith("*"):
                    break
                data.append((m + 1, lines[m].strip()))
            found["user_data"] = data
    return found


def _deck_element_line(deck_text: str, elements) -> tuple:
    wanted = {e.upper() for e in elements}
    for n, raw in enumerate(deck_text.splitlines()):
        s = raw.strip()
        if s.upper().startswith("*ELEMENT") and not s.upper().startswith("*ELEMENT OUTPUT"):
            t = re.search(r"TYPE\s*=\s*([A-Za-z0-9]+)", s, re.IGNORECASE)
            if t and t.group(1).upper() in wanted:
                return n + 1, s
    return 0, ""


# ---------------------------------------------------------------------------
# the scan
# ---------------------------------------------------------------------------
def scan(umat, deck=None, *, repository=None, roots: Sequence = (),
         texts: Optional[dict] = None) -> Intake:
    """Scan ``umat`` (and a deck file or folder, if given). Read-only.

    ``texts`` replaces plain-language entries of ``NEEDS`` key by key.
    """
    from umat_oti.abaqus import deck_pairing
    from umat_oti.abaqus.coordinate_domain import reads_coordinates
    from umat_oti.abaqus.elements import UnsupportedElement, geometry_for
    from umat_oti.abaqus.experiment import _DFGRD, _executable
    from umat_oti.abaqus.formulation import settle, stated_temperature
    from umat_oti.corpus import entry_routines

    umat = Path(umat)
    text = umat.read_text(encoding="utf-8", errors="replace")
    deck_given = Path(deck) if deck else None
    if repository is None:
        repository = (deck_given if deck_given and deck_given.is_dir()
                      else (deck_given.parent if deck_given else umat.parent))
    repository = Path(repository)
    base = repository if repository in umat.resolve().parents or \
        repository.resolve() in umat.resolve().parents else umat.parent
    name = _rel(umat, base)

    intake = Intake(umat=name, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    repository=repository.name)
    add = intake.items.append

    def plain(key):
        return _plain(key, texts)

    # ---- the routine -------------------------------------------------------
    cls = entry_routines.classify(text, path=umat)
    if cls.is_umat:
        add(Item("routine", "Material routine", FOUND,
                 f"{cls.entry_routine} at line {cls.entry_line}",
                 [_quote(name, cls.entry_line, cls.entry_text)]))
    else:
        why = cls.reason or f"it presents {cls.kind}"
        p = plain("routine")
        add(Item("routine", "Material routine", MISSING, f"not a UMAT ({cls.kind})",
                 [_quote(name, cls.entry_line, cls.entry_text)] if cls.entry_line else [],
                 note=why[:200], needs_user=True, ask=p["ask"].format(why=why[:160]),
                 default=p["default"], whose=p["whose"]))

    # ---- the deck (which one feeds this routine) ---------------------------
    pairing = None
    material = None
    deck_text = ""
    deck_name = ""
    if deck_given is not None and deck_given.is_file():
        pool = deck_pairing.materials_in(deck_given)
        pairing = deck_pairing.pair(umat, deck_given.parent, source_text=text, pool=pool)
    else:
        search = deck_given if deck_given is not None else repository
        pairing = deck_pairing.pair(umat, search, source_text=text)
    if pairing.found:
        material = pairing.material
        deck_text = Path(material.deck).read_text(encoding="utf-8", errors="replace")
        deck_name = _rel(material.deck, base if base in Path(material.deck).resolve().parents
                         or base.resolve() in Path(material.deck).resolve().parents
                         else Path(material.deck).parent)
        intake.deck = deck_name
    dl = _deck_lines(deck_text, material.name) if material else {}

    if material is not None:
        ev = []
        if "user" in dl:
            ev.append(_quote(deck_name, *dl["user"]))
        add(Item("deck", "Deck that feeds this routine", FOUND,
                 f"{deck_name}, material {material.name or '(unnamed)'}", ev,
                 note=pairing.why[:200]))
    else:
        reason = {"no_deck_in_repository": "no deck with a *USER MATERIAL block was found "
                                           "next to the file",
                  "no_deck_names_this_source": "decks exist but none is named for this routine",
                  "author_block_rejected": "the deck beside it does not fit what the routine reads",
                  "author_deck_unresolved": "the deck beside it leaves its constants as "
                                            "placeholders"}.get(pairing.refusal_kind,
                                                                pairing.refusal[:120])
        add(Item("deck", "Deck that feeds this routine", MISSING, "none found",
                 note=reason))

    # ---- formulation: element and NTENS -----------------------------------
    temperature, _why = stated_temperature(deck_text) if deck_text else (None, "")
    settled = (settle(text, str(umat), deck_text, deck_name, material.name,
                      temperature=temperature) if material is not None
               else settle(text, str(umat)))
    element = settled.element
    ntens = None
    unsupported = ""
    if element:
        try:
            ntens = geometry_for(element).ntens
        except UnsupportedElement as error:
            unsupported = str(error)
    else:
        unsupported = settled.formulation.reason
    src = settled.source
    if unsupported:
        p = plain("element")
        add(Item("ntens", "Stress components (NTENS)", MISSING, None, note=unsupported[:200],
                 needs_user=True, ask=p["ask"].format(why=unsupported[:160]),
                 default=p["default"], whose=p["whose"]))
        add(Item("element", "Element / formulation", MISSING, None, note=unsupported[:200]))
    else:
        deck_element = bool(material is not None and material.elements)
        if deck_element:
            ln, tx = _deck_element_line(deck_text, material.elements)
            ev = [_quote(deck_name, ln, tx)] if ln else []
            status = FOUND
            ntens_note = settled.agreement[:200]
        elif src.known:
            ev = _source_evidence(text, name, src)
            status = INFERRED
            ntens_note = "read from what the routine does with its stress tensor"
        else:
            ev = []
            status = DEFAULT
            ntens_note = ("nothing in the files says; a solid three-dimensional "
                          "element (6 components) is the usual")
        add(Item("ntens", "Stress components (NTENS)", status, ntens, ev, note=ntens_note))
        add(Item("element", "Element / formulation", status,
                 f"{element} ({settled.formulation.family})", ev,
                 note=(f"verification element; the author's own: "
                       f"{', '.join(settled.formulation.author_elements)}"
                       if settled.formulation.author_elements else "")))

    # ---- geometry: small or finite strain ----------------------------------
    executable = _executable(text)
    reads_f = bool(_DFGRD.search(executable))
    nl_line = _deck_step_line(deck_text) if deck_text else (0, "", False)
    nlgeom = bool(material is not None and material.nlgeom)
    if nlgeom:
        add(Item("kinematics", "Geometric nonlinearity (NLGEOM)", FOUND, "yes: finite strain",
                 [_quote(deck_name, nl_line[0], nl_line[1])]))
    elif reads_f:
        ln, tx = _code_find(text, _DFGRD)
        add(Item("kinematics", "Geometric nonlinearity (NLGEOM)", INFERRED,
                 "yes: finite strain (the routine reads the deformation gradient)",
                 [_quote(name, ln, tx)]))
    elif material is not None:
        add(Item("kinematics", "Geometric nonlinearity (NLGEOM)", INFERRED, "no: small strain",
                 [_quote(deck_name, nl_line[0], nl_line[1])] if nl_line[0] else [],
                 note="no NLGEOM in the deck's steps, and the routine never reads DFGRD0/DFGRD1"))
    else:
        add(Item("kinematics", "Geometric nonlinearity (NLGEOM)", INFERRED,
                 "no: small strain", [],
                 note="the routine never reads DFGRD0/DFGRD1; no deck says otherwise"))
    finite = nlgeom or reads_f

    # ---- state variables ---------------------------------------------------
    demand = pairing.demand
    if material is not None and material.depvar:
        ev = [_quote(deck_name, *dl["depvar"])] if "depvar" in dl else []
        if "depvar_data" in dl:
            ev.append(_quote(deck_name, *dl["depvar_data"]))
        note = ""
        if demand.nstatv and material.depvar > demand.nstatv:
            note = f"the routine itself reaches STATEV({demand.nstatv})"
        add(Item("nstatv", "State variables (NSTATV / *DEPVAR)", FOUND, material.depvar,
                 ev, note=note))
        nstatv = material.depvar
    elif demand.nstatv:
        ln, tx = _code_find(text, rf"STATEV\s*\(\s*{demand.nstatv}\s*\)")
        add(Item("nstatv", "State variables (NSTATV / *DEPVAR)", INFERRED, demand.nstatv,
                 [_quote(name, ln, tx)] if ln else [],
                 note="the highest STATEV the routine names" + (
                     "; it also indexes STATEV by a variable, so this may be a minimum"
                     if not demand.statev_exact else "")))
        nstatv = demand.nstatv
    else:
        add(Item("nstatv", "State variables (NSTATV / *DEPVAR)", INFERRED, 1, [],
                 note="the routine never subscripts STATEV; 1 is the smallest the solver "
                      "allows"))
        nstatv = 1

    # ---- constants ---------------------------------------------------------
    names = _prop_names(text, name)
    if material is not None and material.constants:
        ev = [_quote(deck_name, *dl["user"])] if "user" in dl else []
        add(Item("props_count", "Constants (PROPS count)", FOUND, material.constants, ev,
                 note=f"the routine itself reaches PROPS({demand.nprops})" if demand.nprops
                 and demand.nprops != material.constants else ""))
        props_count = material.constants
    elif demand.nprops:
        ln, tx = _code_find(text, rf"PROPS\s*\(\s*{demand.nprops}\s*\)")
        add(Item("props_count", "Constants (PROPS count)", INFERRED, demand.nprops,
                 [_quote(name, ln, tx)] if ln else [],
                 note=("the highest PROPS the routine names (all of them, by literal "
                       "subscript)" if demand.props_exact else
                       "the highest literal PROPS subscript; the routine also indexes "
                       "PROPS by a variable, so there may be more")))
        props_count = demand.nprops
    else:
        add(Item("props_count", "Constants (PROPS count)", MISSING, None,
                 note="the routine names no PROPS slot and no deck gives a count"))
        props_count = 0

    if names:
        add(Item("props_names", "Constants (names)", FOUND,
                 {f"PROPS({i})": n for i, (n, _l, _t) in sorted(names.items())},
                 [_quote(name, l, t) for i, (n, l, t) in sorted(names.items())][:4]))
    else:
        slots = f"PROPS(1) to PROPS({props_count})" if props_count else "PROPS"
        add(Item("props_names", "Constants (names)", DEFAULT, slots,
                 note="the routine does not write NAME = PROPS(k) for its constants"))

    values_ok = bool(material is not None and material.usable)
    if values_ok:
        ev = [_quote(deck_name, *d) for d in dl.get("user_data", [])][:3]
        add(Item("props_values", "Constant values", FOUND, list(material.values), ev,
                 note=("read through *PARAMETER: " + ", ".join(material.substituted)
                       if material.substituted else "")))
    else:
        slots = (f"PROPS(1) to PROPS({props_count})" if props_count > 1
                 else "PROPS(1)" if props_count else "its constants")
        if names:
            slots += " (" + ", ".join(f"{n}" for _i, (n, _l, _t) in sorted(names.items())) + ")"
        why = ""
        if material is not None and material.unresolved:
            why = ("the deck leaves placeholders standing: "
                   + ", ".join(material.unresolved))
        elif material is not None and material.unresolved_includes:
            why = ("the deck defers its numbers to a file that is not there: "
                   + ", ".join(material.unresolved_includes))
        p = plain("props_values")
        add(Item("props_values", "Constant values", MISSING, None, note=why,
                 needs_user=True, ask=p["ask"].format(slots=slots),
                 default=p["default"], whose=p["whose"]))

    # ---- loading -----------------------------------------------------------
    if material is not None and material.steps:
        periods = ", ".join(f"{x:g}" for x in material.step_periods)
        ln, tx = nl_line[0], nl_line[1]
        add(Item("loading", "Loading", FOUND,
                 f"the deck's own {material.steps} step(s)" + (f", periods {periods}" if periods else ""),
                 [_quote(deck_name, ln, tx)] if ln else []))
    else:
        add(Item("loading", "Loading", DEFAULT,
                 "a generated path that makes the material do something, in unit time "
                 "increments", note="chosen by the program, not by you; zero initial "
                 "stress and state"))

    # ---- what the routine reads from its surroundings ---------------------
    flags = _reads(text, executable, reads_coordinates)
    stated_t = temperature if (deck_text and temperature is not None) else None
    if flags["temp"]:
        ln, tx = flags["temp"]
        if stated_t is not None:
            add(Item("temperature", "Reads temperature (TEMP/DTEMP)", FOUND,
                     f"yes; the deck states {stated_t:g}", [_quote(name, ln, tx)]))
        else:
            p = plain("temperature")
            add(Item("temperature", "Reads temperature (TEMP/DTEMP)", DEFAULT,
                     f"yes; using {DEFAULT_TEMPERATURE} (isothermal)", [_quote(name, ln, tx)],
                     needs_user=True, ask=p["ask"], default=p["default"], whose=p["whose"]))
    else:
        add(Item("temperature", "Reads temperature (TEMP/DTEMP)", FOUND, "no"))
    if flags["coords"]:
        ln, tx = flags["coords"]
        if material is not None:
            add(Item("coordinates", "Reads position (COORDS)", FOUND,
                     "yes; the deck's mesh supplies it", [_quote(name, ln, tx)]))
        else:
            p = plain("coordinates")
            add(Item("coordinates", "Reads position (COORDS)", DEFAULT,
                     "yes; using the origin", [_quote(name, ln, tx)], needs_user=True,
                     ask=p["ask"], default=p["default"], whose=p["whose"]))
    else:
        add(Item("coordinates", "Reads position (COORDS)", FOUND, "no"))
    if flags["noel"]:
        ln, tx = flags["noel"]
        label = material.first_element_label if material is not None else 0
        add(Item("element_number", "Reads element number (NOEL)",
                 FOUND if label else DEFAULT,
                 f"yes; element {label}" if label else "yes; using element 1",
                 [_quote(name, ln, tx)]))
    else:
        add(Item("element_number", "Reads element number (NOEL)", FOUND, "no"))
    if flags["fields"]:
        ln, tx = flags["fields"]
        p = plain("fields")
        add(Item("fields", "Reads field variables (PREDEF/DPRED)", DEFAULT,
                 "yes; using zeros", [_quote(name, ln, tx)], needs_user=material is None,
                 ask=p["ask"] if material is None else "", default=p["default"],
                 whose=p["whose"] if material is None else ""))
    else:
        add(Item("fields", "Reads field variables (PREDEF/DPRED)", FOUND, "no"))

    # ---- helpers, includes and modules ------------------------------------
    _helpers(intake, umat, text, name, repository, roots, add, plain)

    # ---- what will be differentiated --------------------------------------
    if props_count:
        add(Item("quantity", "What to differentiate", DEFAULT,
                 f"stress and tangent with respect to all {props_count} constant(s) the "
                 f"routine reads",
                 note="constants that are switches or flags are not worth differentiating; "
                      "say so if one is"))
    else:
        add(Item("quantity", "What to differentiate", DEFAULT,
                 "stress and tangent with respect to every constant the routine reads"))

    intake.facts = {
        "entry_is_umat": bool(cls.is_umat), "deck_found": material is not None,
        "ntens": ntens, "element": element or None,
        "family": settled.formulation.family or None, "nstatv": nstatv,
        "props_count": props_count or None,
        "kinematics": "finite" if finite else "small strain",
        "props_values_found": values_ok}

    # ---- hand-over to the pipeline ----------------------------------------
    config, complete, missing = _material_config(finite, ntens, nstatv, material, values_ok)
    intake.material_config = config
    intake.pipeline_inputs = {
        "umat": name, "deck": deck_name or None,
        "dependency_roots": sorted({str(_rel(Path(r), base)) for r in roots}),
        "material_config_needed": not (material is not None and material.usable),
        "material_config_complete": complete, "material_config_missing": missing}
    return intake


# ---------------------------------------------------------------------------
# pieces
# ---------------------------------------------------------------------------
def _source_evidence(text: str, name: str, src) -> list:
    """Quote the line(s) ``formulation.from_source``'s evidence stands on.

    Its evidence is a sentence about a rule ("a DO loop bounded at 6 fills the
    whole of STRESS"); the number in it is matched back to the line it came
    from, and a code snippet it quotes in parentheses is looked up verbatim.
    Where no line can be matched the sentence itself is the evidence, with
    line 0 (no single line).
    """
    out = []
    tensors = r"(?:STRESS|DDSDDE|STRAN|DSTRAN|DDSDDT|DRPLDE)"
    for snippet in src.evidence[:2]:
        sentence = str(snippet)
        ln, tx = 0, ""
        code = re.search(r"\(((?:do|DO|Do)\s[^)]*)\)", sentence)
        loop = re.search(r"DO loop bounded at (\d+)", sentence)
        sub = re.search(r"literal subscript (\d+)", sentence)
        if code:
            ln, tx = _find_line(text, re.escape(code.group(1).strip()))
        if not ln and loop:
            ln, tx = _find_line(
                text, rf"^\s*(?:\d+\s+)?DO\s+(?:\d+\s*,?\s*)?\w+\s*=\s*\w+\s*,\s*{loop.group(1)}\b")
        if not ln and sub:
            ln, tx = _find_line(text, rf"\b{tensors}\s*\([^)]*\b{sub.group(1)}\b")
        out.append(_quote(name, ln, tx) if ln else
                   {"file": name, "line": 0, "text": " ".join(sentence.split())[:140]})
    return out


def _deck_step_line(deck_text: str) -> tuple:
    first = (0, "", False)
    for n, raw in enumerate(deck_text.splitlines(), start=1):
        s = raw.strip()
        if s.upper().startswith("*STEP"):
            if not first[0]:
                first = (n, s, False)
            if re.search(r"NLGEOM\s*=\s*YES|NLGEOM\s*(,|$)", s, re.IGNORECASE):
                return (n, s, True)
    return first


def _prop_names(text: str, name: str) -> dict:
    """{slot: (NAME, line, text)}, by the same rule ``named_constants`` uses."""
    from umat_oti.abaqus.deck_pairing import _NAMED_PROP, named_constants

    wanted = named_constants(text)
    out: dict = {}
    for n, raw in enumerate(text.splitlines(), start=1):
        if raw[:1] in "cC*!" or raw.lstrip().startswith("!"):
            continue
        m = _NAMED_PROP.match(raw.split("!")[0])
        if m and int(m.group(2)) in wanted and int(m.group(2)) not in out:
            out[int(m.group(2))] = (wanted[int(m.group(2))], n, raw.strip())
    return out


def _reads(text: str, executable: str, reads_coordinates) -> dict:
    out: dict = {"temp": None, "coords": None, "noel": None, "fields": None}
    assigned_temp = re.search(r"^\s*(?:\d+\s+)?(?:D?TEMP)\s*=", executable,
                              re.IGNORECASE | re.MULTILINE)
    if re.search(r"\bD?TEMP\b", executable, re.IGNORECASE) and not assigned_temp:
        out["temp"] = _code_find(text, r"\bD?TEMP\b")
    if reads_coordinates(text):
        out["coords"] = _code_find(text, r"\bCOORDS\s*\(") or None
    if re.search(r"\bNOEL\b", executable, re.IGNORECASE):
        out["noel"] = _code_find(text, r"\bNOEL\b")
    if re.search(r"\b(PREDEF|DPRED)\s*\(", executable, re.IGNORECASE):
        out["fields"] = _code_find(text, r"\b(PREDEF|DPRED)\s*\(")
    for key in out:
        if out[key] and not out[key][0]:
            out[key] = None
    return out


def _helpers(intake: Intake, umat: Path, text: str, name: str, repository: Path,
             roots: Sequence, add, plain) -> None:
    from umat_oti.corpus import entry_routines  # noqa: F401  (kept for symmetry)
    from umat_oti.fortran.normalize import detect_source_form
    from umat_oti.fortran.parser import logical_lines_from_text
    from umat_oti.transform.dependency_bundle import (case_insensitive_file,
                                                      is_runtime_header)
    from umat_oti.transform.dependency_resolution import (DependencyResolutionError,
                                                          FORTRAN_SUFFIXES,
                                                          resolve_closure)
    from umat_oti.transform.routine_typing import INTRINSIC_MODULES
    from umat_oti.transform.source_modules import _USE, source_modules

    search = [umat.parent, *[Path(r) for r in roots]]
    entry = "UMAT"
    try:
        graph = resolve_closure(umat, entry=entry, roots=search)
    except DependencyResolutionError as error:
        add(Item("helpers", "Helper routines it calls", MISSING, None, note=str(error)[:200]))
        return
    external = sorted(graph.resolved.keys() - {entry})
    resolved = sorted({d.name for d in graph.resolved.values() if d.name.upper() != entry})
    if graph.missing:
        names = [m.symbol for m in graph.missing]
        ev = []
        for m in graph.missing[:3]:
            ln, tx = _find_line(text, rf"\bCALL\s+{re.escape(m.symbol)}\b")
            if ln:
                ev.append(_quote(name, ln, tx))
        p = plain("helpers")
        add(Item("helpers", "Helper routines it calls", MISSING,
                 {"present": resolved, "missing": names}, ev,
                 note=("; ".join(f"{m.symbol}: did you mean {', '.join(m.near_misses)}?"
                                 for m in graph.missing if m.near_misses))[:200],
                 needs_user=True, ask=p["ask"].format(names=", ".join(names)),
                 default=p["default"].format(names=", ".join(names)), whose=p["whose"]))
    elif resolved:
        where = sorted({_rel(d.path, repository) for d in graph.external_definitions})
        add(Item("helpers", "Helper routines it calls", FOUND,
                 {"present": resolved, "files": where} if where else {"present": resolved},
                 note="all defined in the files given"))
    else:
        add(Item("helpers", "Helper routines it calls", FOUND, "none needed"))

    # includes: the solver's own header needs no file
    missing_inc = []
    for inc in graph.includes:
        if is_runtime_header(inc):
            continue
        hit = any((Path(r) / inc).is_file() or case_insensitive_file(Path(r) / inc)
                  for r in search)
        if not hit:
            missing_inc.append(inc)
    if missing_inc:
        p = plain("includes")
        ev = []
        for inc in missing_inc[:3]:
            ln, tx = _find_line(text, rf"INCLUDE\s*['\"]{re.escape(inc)}")
            if ln:
                ev.append(_quote(name, ln, tx))
        add(Item("includes", "Files it INCLUDEs", MISSING,
                 {"missing": missing_inc}, ev, needs_user=True,
                 ask=p["ask"].format(names=", ".join(missing_inc)), default=p["default"],
                 whose=p["whose"]))
    else:
        have = [i for i in graph.includes if not is_runtime_header(i)]
        add(Item("includes", "Files it INCLUDEs", FOUND,
                 have if have else "none needed",
                 note="ABA_PARAM.INC is supplied by the solver" if any(
                     is_runtime_header(i) for i in graph.includes) else ""))

    # modules: used by the entry file, defined in the files given
    defined: set = set()
    for root in search:
        files = ([root] if Path(root).is_file() else
                 sorted(f for f in Path(root).rglob("*")
                        if f.is_file() and f.suffix in FORTRAN_SUFFIXES))
        for f in files[:400]:
            try:
                t = f.read_text(encoding="utf-8", errors="replace")
                form = detect_source_form(f, t)
                defined |= set(source_modules(logical_lines_from_text(t, form)))
            except OSError:
                continue
    used = []
    for raw in text.splitlines():
        m = _USE.match(raw.split("!")[0].strip())
        if m and m.group(1).upper() not in used:
            used.append(m.group(1).upper())
    unresolved = [u for u in used if u not in INTRINSIC_MODULES and u not in defined]
    if unresolved:
        p = plain("modules")
        ev = []
        for u in unresolved[:3]:
            ln, tx = _find_line(text, rf"^\s*USE\s+{re.escape(u)}\b")
            if ln:
                ev.append(_quote(name, ln, tx))
        add(Item("modules", "Modules it USEs", MISSING,
                 {"missing": unresolved,
                  "present": [u for u in used if u not in unresolved]}, ev,
                 needs_user=True, ask=p["ask"].format(names=", ".join(unresolved)),
                 default=p["default"], whose=p["whose"]))
    else:
        add(Item("modules", "Modules it USEs", FOUND, used if used else "none needed"))


def _material_config(finite: bool, ntens, nstatv, material, values_ok: bool):
    """The existing ``--material-config`` form, as far as the files fill it.

    That form accepts small strain with ntens 6 only, and an explicit
    check_path; when the deck supplies the material the pipeline needs no such
    file at all (it reads the deck itself), and this says so.
    """
    config = {"kinematics": "finite_strain" if finite else "small_strain",
              "ntens": ntens, "nstatev": nstatv,
              "props_values": list(material.values) if values_ok else None,
              "check_path": None}
    missing = []
    if finite:
        missing.append("this input form supports small strain only")
    if ntens != 6:
        missing.append("this input form supports ntens=6 only")
    if not values_ok:
        missing.append("props_values")
    missing.append("check_path (the pipeline generates one when it reads a deck)")
    complete = not [m for m in missing if not m.startswith("check_path")]
    return config, complete, missing


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Say what a UMAT (and deck) already tell us, and what needs you. "
                    "Reads only; asks nothing.")
    parser.add_argument("umat", type=Path, help="the UMAT source file")
    parser.add_argument("deck", type=Path, nargs="?",
                        help="an Abaqus input file or a folder holding one (optional)")
    parser.add_argument("--out", type=Path, default=Path("."),
                        help="where to write intake.json and intake.md (default: here)")
    parser.add_argument("--repository", type=Path, default=None,
                        help="the folder to search for decks and helpers "
                             "(default: the UMAT's folder, or the deck folder)")
    parser.add_argument("--dependency-root", type=Path, action="append", default=[],
                        help="another folder to search for helper files (repeatable)")
    parser.add_argument("--no-write", action="store_true", help="print only")
    args = parser.parse_args(argv)
    if not args.umat.is_file():
        print(f"intake: {args.umat} is not a file", file=sys.stderr)
        return 3
    roots = list(args.dependency_root)
    if args.deck is not None and args.deck.is_dir():
        roots.append(args.deck)
    result = scan(args.umat, args.deck, repository=args.repository, roots=roots)
    sys.stdout.write(result.to_text())
    if not args.no_write:
        j, m = result.write(args.out)
        print(f"\nWrote {j} and {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
