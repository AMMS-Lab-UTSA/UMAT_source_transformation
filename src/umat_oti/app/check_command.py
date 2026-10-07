"""``umat-oti check UMAT.for [DECK.inp | FOLDER]``: one verb for the user's goal.

A thin wrapper over the existing ``all`` pipeline
(:func:`umat_oti.services.complete_workflow.run_complete_workflow`). It adds what
a person needs around it and nothing the transformer decides:

* it reads the deck wherever it is (``--deck``, a second argument, or beside the
  UMAT) and says where each fact came from, with the file and line;
* it takes the constants and the loading directly (``--props "E=210000 nu=0.3"``,
  ``--peak 0.02``) and writes the existing material-settings JSON;
* with no deck and no constants it writes a commented template and says to
  re-run with ``--material-config``;
* on a refusal it prints the plain card (:mod:`umat_oti.app.refusal_cards`), never
  argparse or ``trial_deck`` usage, and keeps the raw JSON in a file.

The sentences a person reads here are in :data:`TEXT` so they can be reworded in
one place.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from umat_oti.app import check_intake as intake
from umat_oti.app.refusal_cards import card_for, state_after_reading

#: Everything this command says in its own words.
TEXT = {
    "reading": "Reading your files ...",
    "no_file": "I cannot find the file {path}.",
    "needs_you": "I NEED ONE THING FROM YOU",
    "template_written": "I wrote a template for the numbers I could not find: {path}",
    "template_next": "Fill it in (the comments say how), then run:  umat-oti check {source} --material-config {path}",
    "placeholder": "The material file {path} still has blanks (null) in its list of constant values (props_values). Fill in the numbers.",
    "working": "Working: converting, compiling, running both versions and comparing (about 1 to 3 minutes) ...",
    "where": "Everything the run recorded is in {path}",
}

_STATE_OF_STAGE = {"material_settings": "missing_material_data",
                   "dependencies": "external_dependency_unavailable",
                   "parameters": "transform_refused", "jacobian": "transform_refused",
                   "sensitivities": "tangent_not_verified", "abaqus": "transformed_job_failed"}


class PlainParser(argparse.ArgumentParser):
    """An argument parser that never prints a usage block: one plain line instead."""

    def error(self, message: str):                                 # noqa: D401
        raise UsageError(message)


class UsageError(Exception):
    pass


def build_parser() -> PlainParser:
    parser = PlainParser(prog="umat-oti check", add_help=False)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("target", nargs="?", type=Path)
    parser.add_argument("--deck", type=Path)
    parser.add_argument("--props")
    parser.add_argument("--peak", type=float)
    parser.add_argument("--material-config", type=Path)
    parser.add_argument("--dependency-root", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    return parser


HELP = """\
umat-oti check UMAT.for [DECK.inp | FOLDER] [options]

  Checks the derivatives of your UMAT's stress with respect to its constants.
  If an Abaqus input file (the deck) is given, or sits beside the UMAT, the
  constants and the loading are read from it.

  --deck FILE            the deck, wherever it is
  --props "E=210000 nu=0.3"   the constants, if there is no deck (names from the source, or in order)
  --peak 0.02            how far to strain the material (default 0.02 with --props)
  --material-config FILE a material file (a template is written when none is found)
  --dependency-root DIR  a folder with helper routines the UMAT calls
  --out DIR              where results go (default: <umat name>_check)
  --template             write a commented material file to fill in, when the constants are missing
  --details              print every item the files gave, with the lines quoted (always in intake.md)
"""


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    print("Example:  umat-oti check my_umat.for my_deck.inp   (or: umat-oti check --help)",
          file=sys.stderr)
    return 2


def _new_out_dir(source: Path, requested: Optional[Path]) -> Path:
    if requested is not None:
        return requested.expanduser().resolve()
    base = Path.cwd() / f"{source.stem}_check"
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = base.with_name(f"{base.name}_{n}")
    return candidate


def _free_name(path: Path) -> Path:
    candidate, n = path, 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
    return candidate


def print_card(state: str, reason: str, *, header: str = "REFUSED") -> None:
    card = card_for(state, reason)
    bar = "=" * 70
    print(f"\n{bar}\n{header}\n{bar}")
    print(card.sentence)
    print(f"Whose move: {card.whose_move}.")
    print(f"Next: {card.next_action}")


def resolve_deck(source: Path, target: Optional[Path], deck_flag: Optional[Path]) -> tuple:
    """(deck path or None, how it was found, candidates when ambiguous)."""
    explicit = deck_flag or (target if target is not None else None)
    if explicit is not None:
        explicit = explicit.expanduser().resolve()
        if explicit.is_file():
            return explicit, "given", []
        if explicit.is_dir():
            found = intake.decks_in(explicit)
            if len(found) == 1:
                return found[0], f"the only deck with a *USER MATERIAL block in {explicit.name}/", []
            return None, "folder", found
        return None, "missing", [explicit]
    beside = intake.decks_in(source.parent)
    if len(beside) == 1:
        return beside[0], "beside the UMAT", []
    return None, ("ambiguous" if beside else "none"), beside


def _describe_source(facts: intake.SourceFacts, source: Path) -> list:
    lines = [f"  UMAT          {source.name}, subroutine UMAT at line {facts.umat_line}  [found]"]
    if facts.props_max:
        names = ", ".join(f"{facts.props_names[k].value}" if k in facts.props_names else f"constant {k}"
                          for k in range(1, facts.props_max + 1))
        lines.append(f"  Constants     the routine reads {facts.props_max}: {names}  [found in the source]")
    return lines


def _describe_deck(deck: Path, facts: intake.DeckFacts) -> list:
    lines = []
    materials = facts.user_materials()
    if len(materials) == 1:
        name, constants, depvar = materials[0]
        lines.append(f"  Constants     {len(constants.value)} values from {constants.where()} "
                     f"(*USER MATERIAL" + (f", material {name}" if name else "") + ")  [found]")
        if depvar is not None:
            lines.append(f"  State vars    {depvar.value} (the material's memory between increments) from {depvar.where()} (*DEPVAR)  [found]")
    elif materials:
        lines.append(f"  Constants     {len(materials)} materials with *USER MATERIAL in {deck.name}; "
                     "the one that matches the UMAT is chosen by the pipeline  [found]")
    if facts.steps:
        lines.append(f"  Loading       the deck's own {len(facts.steps)} step(s) "
                     f"(first at line {facts.steps[0].line})  [found]")
    lines.append("  Geometry      " + ("nonlinear (NLGEOM=YES)" if facts.nlgeom else "small strain (no NLGEOM)")
                 + (f", element {', '.join(facts.element_types)}" if facts.element_types else "") + "  [found]")
    return lines


def _stage_deck(deck: Path, folder: Path) -> Path:
    """A folder holding only this deck, so ``--deck`` works from any path and a
    folder of other decks cannot be mistaken for it."""
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(deck, folder / deck.name)
    return folder


def _discover_workflow(source: Path, deck_dir: Path, work: Path) -> tuple:
    """Run the pipeline's own material discovery; ``(settings dict, error text)``."""
    work.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [sys.executable, "-m", "umat_oti.abaqus.trial_deck", "--discover-workflow",
         "--source", str(source), "--ntens", "6", "--out", str(work),
         "--discovery-root", str(deck_dir)], capture_output=True, text=True, check=False)
    path = work / "material_workflow.json"
    if done.returncode or not path.is_file():
        return None, (done.stderr or done.stdout).strip()
    return json.loads(path.read_text(encoding="utf-8")), ""


def clean_reason(text: str) -> str:
    """The pipeline's error text without an internal script's usage block
    (``usage: trial_deck.py [-h] ... trial_deck.py: error: <the message>``)."""
    return re.sub(r"usage:\s*\w+\.py.*?\w+\.py: error:\s*", "", str(text or ""), flags=re.S).strip()


def failure_state(summary: dict) -> tuple:
    """(terminal state, reason text) the pipeline's refusal stands for."""
    stage = str(summary.get("failed_stage") or "")
    reason = str(summary.get("error") or "")
    if not reason:
        for stage_name, body in (summary.get("stages") or {}).items():
            if isinstance(body, dict) and body.get("blockers"):
                reason = "; ".join(map(str, body["blockers"]))
    reason = clean_reason(reason)
    return state_after_reading(_STATE_OF_STAGE.get(stage, "transform_refused"), reason), reason


def load_scanner():
    """Ada's intake scanner (``tools/intake_scan.py`` of the checkout), loaded by path
    because ``tools/`` is not a package; ``None`` when this is an installed copy
    without it, and ``check`` then reads the files with :mod:`check_intake`."""
    import importlib.util

    import umat_oti

    path = Path(umat_oti.__file__).resolve().parents[2] / "tools" / "intake_scan.py"
    if not path.is_file():
        return None
    name = "umat_oti_intake_scan"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def print_corpus_line(source: Path, deck: Optional[Path]) -> None:
    """A separate line when these exact files (UMAT, and deck if given) are in the corpus record.

    Never changes what this command found, and never raises: a missing table or an unreadable
    file just means no line.
    """
    try:
        from umat_oti.app import verified_lookup

        match = verified_lookup.lookup(source, deck)
        if match is not None:
            for line in verified_lookup.render(match):
                print(line)
    except Exception:                                   # a lookup must never stop a check
        return


def blocking_items(found, *, constants_supplied: bool) -> list:
    """The items the scanner could not settle and that stop the run: MISSING, and
    needing the user. The constants are not blocking when the user has just supplied
    them (``--props`` or ``--material-config``)."""
    blocking = [i for i in found.needs_user()
                if i.status == "MISSING" and not (i.key == "props_values" and constants_supplied)]
    # The routine before the material (Nico, B11): a helper or module nobody supplied is why
    # the material question is moot, so it is asked first; the constants come last.
    order = ("routine", "element", "helpers", "includes", "modules", "ntens")
    return sorted(blocking, key=lambda i: order.index(i.key) if i.key in order else len(order))


def print_need(item, *, extra: str = "") -> None:
    """The scanner's own plain ask for one blocking item, with who has to move."""
    mine = item.whose in ("you", "")
    header = "I NEED ONE THING FROM YOU" if mine else "REFUSED"
    bar = "=" * 70
    print(f"\n{bar}\n{header}\n{bar}")
    print(item.ask)
    print(f"Whose move: {item.whose or 'you'}.")
    default = str(item.default)
    if extra and extra in default:
        extra = ""
    print(f"Next: {default}" + (f" {extra}" if extra else ""))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(args_in)
    except UsageError as error:
        return _fail(f"umat-oti check: {error}.")
    if args.help or args.source is None:
        print(HELP)
        return 0 if args.help else 2
    source = args.source.expanduser().resolve()
    if not source.is_file():
        return _fail(TEXT["no_file"].format(path=source))
    from umat_oti.app.front_door import make_this_code_visible_to_children

    make_this_code_visible_to_children()
    print(TEXT["reading"])
    facts = intake.scan_source(source)
    if not facts.has_umat:
        reason = (f"this file is {facts.other_kind}, not a UMAT" if facts.other_kind
                  else "no SUBROUTINE UMAT in this file")
        print_card("not_a_umat", reason)
        return 2

    out = _new_out_dir(source, args.out)
    inputs = out.with_name(out.name + "_input")
    inputs.mkdir(parents=True, exist_ok=True)
    roots = [d.expanduser().resolve() for d in args.dependency_root]

    deck, how, candidates = resolve_deck(source, args.target, args.deck)
    if deck is None and how in ("ambiguous", "folder"):
        listing = "; ".join(str(c) for c in candidates[:6])
        print(f"  Deck          several candidates: {listing}  [ask: give one with --deck FILE]")
        return _fail("More than one input file could be the deck. Say which with --deck FILE.")
    if deck is None and how == "missing":
        return _fail(f"I cannot find the deck {candidates[0]}.")

    # What the files already say, item by item, each with the line it stands on (Ada's scanner).
    scanner = load_scanner()
    found = None
    if scanner is not None:
        found = scanner.scan(source, deck, roots=roots)
        if args.details:
            from umat_oti.app.check_compact import amber_notes

            sys.stdout.write(found.to_text())
            for note in amber_notes(found):
                print(note)
        else:
            from umat_oti.app.check_compact import compact_intake

            sys.stdout.write(compact_intake(found))
        found.write(inputs)
        print(f"(The same, with the lines quoted: {inputs / 'intake.md'}, {inputs / 'intake.json'})")
        print_corpus_line(source, deck)
        stop = blocking_items(found, constants_supplied=bool(args.props or args.material_config))
        if stop:
            names = " ".join(f"{k}=<value>" for k in
                              [str(v.value) for _, v in sorted(facts.props_names.items())]) or "<name>=<value>"
            if stop[0].key == "props_values":
                extra = (f"Type them:  umat-oti check {source.name} --props \"{names}\"  "
                         "(or add --template for a file to fill in).")
                if args.template:
                    template = intake.template_material(facts, nstatev=found.facts.get("nstatv"))
                    path = _free_name(Path.cwd() / f"{source.stem}_material.json")
                    path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
                    extra = TEXT["template_written"].format(path=path) + " " + TEXT["template_next"].format(
                        source=source.name, path=path.name)
            else:
                extra = ("(Give the folder with --dependency-root FOLDER.)"
                         if stop[0].key in ("helpers", "includes", "modules")
                         and "--dependency-root" not in str(stop[0].default) else "")
            print_need(stop[0], extra=extra)
            return 3 if (stop[0].whose or "you") == "you" else 2
    else:
        for line in _describe_source(facts, source):
            print(line)
        print_corpus_line(source, deck)

    # The routine first, the material second: the real blocker is the message.
    from umat_oti.app.check_preflight import preflight

    blocked = preflight(source, facts, roots, inputs / "preflight")
    if blocked is not None:
        print_card(*blocked)
        print(TEXT["where"].format(path=inputs / "preflight"))
        return 2
    print("  Conversion    the routine's helpers resolve and I can find where it sets "
          "stress and stiffness  [ok]")

    deck_facts = None
    if deck is not None:
        deck_facts = intake.scan_deck(deck)
        if found is None:
            print(f"  Deck          {deck}  [{how}]")
            for line in _describe_deck(deck, deck_facts):
                print(line)
    elif found is None:
        print("  Deck          none found beside the UMAT  [missing]")

    material_config: Optional[Path] = None
    discovery_root: Optional[Path] = None
    nstatev = _state_count(found, deck_facts, facts)

    if args.material_config is not None:
        path = args.material_config.expanduser().resolve()
        if not path.is_file():
            return _fail(f"I cannot find the material file {path}.")
        settings = json.loads(path.read_text(encoding="utf-8"))
        if any(v is None for v in settings.get("props_values") or []):
            print_card("missing_material_data", "the material file still has blanks")
            print(TEXT["placeholder"].format(path=path))
            return 2
        material_config = inputs / "material_clean.json"
        material_config.write_text(json.dumps(intake.strip_comments(settings), indent=2) + "\n",
                                   encoding="utf-8")
        print(f"  Constants     from {path.name}  [material file]")
    elif args.props is not None:
        count = _constant_count(found, deck_facts, facts)
        if not count:
            return _fail("I cannot tell how many constants this routine has; "
                         "use --material-config with a material file.")
        values, _, problems = intake.parse_props(args.props, facts.props_names, count)
        if problems:
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return _fail("The constants you typed are not complete.")
        peak = args.peak if args.peak is not None else 0.02
        settings = intake.material_config(props=values, nstatev=nstatev or 0,
                                          check_path=intake.out_back_path(peak))
        material_config = inputs / "material_check.json"
        material_config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        print(f"  Constants     {count} typed with --props"
              + ("; the deck's own constants are not used" if deck is not None else "")
              + "  [typed]")
        print(f"  Loading       out to +{peak:g}, back to -{peak:g}, unloaded to 0 "
              f"({len(settings['check_path']['increments'])} increments)  "
              f"[{'--peak' if args.peak is not None else 'default'}]")
    elif deck is not None:
        discovery_root = _stage_deck(deck, inputs / "deck")
        if args.peak is not None:
            settings, error = _discover_workflow(source, discovery_root, inputs / "discovery")
            if settings is None:
                print_card("missing_material_data", error)
                return 2
            settings["check_path"] = intake.out_back_path(args.peak)
            material_config = inputs / "material_check.json"
            material_config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            print(f"  Loading       out to +{args.peak:g}, back to -{args.peak:g}, unloaded to 0  [--peak]")
    else:
        template = intake.template_material(facts, nstatev=nstatev)
        path = _free_name(Path.cwd() / f"{source.stem}_material.json")
        path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        print_card("missing_material_data", "no deck with a *USER MATERIAL block was found")
        print(TEXT["template_written"].format(path=path))
        print(TEXT["template_next"].format(source=source.name, path=path.name))
        print('Or type the constants:  umat-oti check ' + source.name + ' --props "<name>=<value> ..."')
        return 3

    print(TEXT["working"])
    from umat_oti.services.complete_workflow import run_complete_workflow

    summary = run_complete_workflow(source, material_config, out,
                                    dependency_roots=roots,
                                    material_discovery_root=discovery_root)
    return finish(summary, out)


def _constant_count(found, deck_facts, facts) -> int:
    """How many constants a typed ``--props`` must supply.

    The routine's own highest PROPS index first; then the number of slots the
    deck WRITES, read card by card as Abaqus reads it (the scanner's reading).
    The older reader of :mod:`check_intake` joins every number of a block into
    one list, so a block of 1,2,3,4, then 5,6 counted 6 where Abaqus has 10
    slots; it is used only when the scanner is not there (an installed copy).
    """
    if found is not None:
        if found.facts.get("props_count"):
            return int(found.facts["props_count"])
        item = found.item("props_values")
        if item is not None and item.value:
            return len(item.value)
        return int(facts.props_max or 0)
    if deck_facts and len(deck_facts.user_materials()) == 1:
        return len(deck_facts.user_materials()[0][1].value)
    return int(facts.props_max or 0)


def _state_count(found, deck_facts, facts):
    """How many state variables: the scanner's reading of the deck, else the routine's own highest STATEV index."""
    if found is not None:
        value = found.facts.get("nstatv")
        return value if value is not None else (facts.statev_max or None)
    if (deck_facts and len(deck_facts.user_materials()) == 1
            and deck_facts.user_materials()[0][2] is not None):
        return deck_facts.user_materials()[0][2].value
    return facts.statev_max or None


def finish(summary: dict, out: Path) -> int:
    """What a person is told when the pipeline has finished: the one-page verdict,
    the headline numbers, and where the readable table and the full record are."""
    from umat_oti.app import check_summary

    code = int(summary.get("exit_code", 1))
    if code == 0:
        text = check_summary.render(summary, out)
    else:
        state, reason = failure_state(summary)
        text = check_summary.render({k: v for k, v in summary.items() if k not in ("error", "stages")},
                                    out, state=state, reason=reason,
                                    stage=str(summary.get("failed_stage") or ""))
    print("\n" + text)
    try:
        (Path(out) / "check_summary.txt").write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
