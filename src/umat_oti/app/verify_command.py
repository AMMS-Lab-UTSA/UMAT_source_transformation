"""``umat-oti verify UMAT.for DECK.inp``: the six checks, for a file that is not in the corpus.

The six checks that make a file "verified" are made by ``tools/verify_store_in_abaqus.py`` on entries of a
transform store. A file of your own is in no store. This command builds a throwaway, self-contained scratch
corpus under an output folder (an isolated store, a one-row triage CSV, your file and your deck where the
tool looks for them) and runs the UNCHANGED tools against it, one after the other:

    tools/run_discovery_triage.py   reads the file and writes the one triage row
    tools/transform_all.py          converts it into the scratch store
    tools/verify_store_in_abaqus.py runs the original and the converted file in Abaqus and judges the six checks

Nothing is written to the real transform store, the discovery cache, ``discovery_triage.csv`` or the
corpus registry: every path the tools are given is under the scratch folder (a test checks the command
lines). No gate logic is here. The verdict is the verdict page's: green only if the gates the tool recorded
all read true (``may_say_verified``) and nothing else.

It stops politely, with a card that says whose move it is and one next step, when Abaqus is not installed,
when no deck is given, or when the deck gives no constants. A constant is never defaulted.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

#: The repository (folder) name the scratch corpus gives your files; the corpus identity is "<this>/<file>".
SCRATCH_REPOSITORY = "yourfiles"

HELP = """\
umat-oti verify UMAT.for DECK.inp [options]

  Runs the six checks that make a file "verified" on YOUR files, in Abaqus. It needs Abaqus (the `abaqus`
  command, with the Intel Fortran compiler it uses) and gfortran, and takes a few minutes: the same
  conversion, the same two Abaqus runs and the same comparison the corpus runs use, in a scratch folder.
  It never writes to a shared store, and the verdict is green only if all six checks hold.

  DECK.inp               the Abaqus input file that uses this material; the constants come from it
  --out DIR              the scratch folder (default: <umat name>_verify next to the UMAT)
  --dependency-root DIR  a folder (or file) with the extra subroutines the UMAT calls (repeatable)
  --timeout SECONDS      the longest one Abaqus job may take (default 3600)
  --keep-work            keep the Abaqus working folders (they are large) instead of deleting them
"""

STEPS = 4


class VerifyUsage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):                                  # noqa: D401
        raise VerifyUsage(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="umat-oti verify", add_help=False)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("target", nargs="?", type=Path)
    parser.add_argument("--deck", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dependency-root", type=Path, action="append", default=[])
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    return parser


# ---------------------------------------------------------------------------------------------- layout
class Layout:
    """Every path the tools are given: all of them under ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.cache = self.root / "corpus" / "cache"
        self.repository = self.cache / SCRATCH_REPOSITORY
        self.triage_work = self.root / "corpus" / "triage_work"
        self.triage = self.root / "corpus" / "triage"
        self.triage_csv = self.triage / "discovery_triage.csv"
        self.store = self.root / "corpus" / "store"
        self.transform_work = self.root / "corpus" / "transform_work"
        self.proposals = self.root / "corpus" / "proposals.json"
        self.work = self.root / "work"
        self.results = self.root / "results"
        self.logs = self.root / "logs"

    def all_paths(self) -> list:
        return [self.cache, self.triage_work, self.triage, self.triage_csv, self.store, self.transform_work,
                self.proposals, self.work, self.results, self.logs]


def commands(layout: Layout, source_name: str, tools: Path, timeout: int) -> list:
    """The three tool command lines, in order. Every path argument is under ``layout.root``."""
    py = sys.executable
    source_id = f"{SCRATCH_REPOSITORY}/{source_name}"
    return [
        ("reading your files", [py, str(tools / "run_discovery_triage.py"), "--cache-dir", str(layout.cache),
                                "--work-dir", str(layout.triage_work), "--results-dir", str(layout.triage)]),
        ("converting your file", [py, str(tools / "transform_all.py"), "--triage", str(layout.triage_csv),
                                  "--cache-dir", str(layout.cache), "--work-dir", str(layout.transform_work),
                                  "--store-root", str(layout.store), "--proposals", str(layout.proposals),
                                  "--only", source_id, "--jobs", "1"]),
        ("running both versions in Abaqus and comparing", [
            py, str(tools / "verify_store_in_abaqus.py"), "--store", str(layout.store), "--cache-dir", str(layout.cache),
            "--triage", str(layout.triage_csv), "--proposals", str(layout.proposals), "--work-dir", str(layout.work),
            "--results-dir", str(layout.results), "--only", source_id, "--jobs", "1", "--timeout", str(timeout)]),
    ]


def build_scratch(layout: Layout, source: Path, deck: Path, roots: Sequence[Path]) -> None:
    """Place the file, its deck and its extra subroutines where the tools look for them."""
    layout.repository.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, layout.repository / source.name)
    shutil.copy2(deck, layout.repository / deck.name)
    # files the source INCLUDEs, from beside it (Abaqus's own ABA_PARAM.INC is supplied by the tools)
    for name in re.findall(r"(?im)^\s*include\s+['\"]([^'\"]+)['\"]", source.read_text(errors="replace")):
        beside = source.parent / name
        if name.upper() != "ABA_PARAM.INC" and beside.is_file():
            shutil.copy2(beside, layout.repository / beside.name)
    for root in roots:
        files = [root] if Path(root).is_file() else sorted(p for p in Path(root).iterdir() if p.is_file())
        for path in files:
            if path.suffix.lower() in (".f", ".for", ".f90", ".f95", ".f03", ".inc", ".h") \
                    and not (layout.repository / path.name).exists():
                shutil.copy2(path, layout.repository / path.name)
    layout.proposals.parent.mkdir(parents=True, exist_ok=True)
    layout.proposals.write_text('{"entries": []}\n', encoding="utf-8")
    for folder in (layout.work, layout.results, layout.logs):
        folder.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------------------------- cards
def _banner(colour: str, text: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n{colour}: {text}\n{bar}")


def _card(colour: str, banner: str, next_step: str, what: str, whose: str) -> None:
    from umat_oti.app import check_command as check

    _banner(colour, banner)
    print(f"Next: {next_step}")
    print(what)
    print(f"Whose move: {whose}.")
    check._record_final(colour.lower(), what)


def no_abaqus_card() -> None:
    _card("BLUE", "I NEED ONE THING FROM YOU",
          "Run this command on a computer where Abaqus is installed (the `abaqus` command works in a terminal, "
          "with the Intel Fortran compiler Abaqus uses) and gfortran.",
          "The six checks run your material in Abaqus, and Abaqus was not found on this computer, so there is "
          "nothing to check yet. `umat-oti check` works without Abaqus but cannot call a file verified.", "you")


def no_deck_card() -> None:
    _card("BLUE", "I NEED ONE THING FROM YOU",
          "Give the Abaqus input file (the deck) that uses this material: umat-oti verify YOUR_UMAT.for YOUR_DECK.inp",
          "The six checks run your material in Abaqus on a deck, and the material's constants are read from that "
          "deck. None are guessed, and none are set to 0.", "you")


def deck_without_constants_card(reason: str) -> None:
    _card("BLUE", "I NEED ONE THING FROM YOU",
          "Put the material's numbers into the deck: a *USER MATERIAL block with a CONSTANTS= count and the values "
          "on the lines under it (eight per line).",
          f"The deck gives no usable constants: {reason}. None are guessed, and none are set to 0.", "you")


# ---------------------------------------------------------------------------------------------- the run
def _out_dir(source: Path, requested: Optional[Path]) -> Path:
    if requested is not None:
        return requested.expanduser().resolve()
    base = source.parent / f"{source.stem}_verify"
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = base.with_name(f"{base.name}_{n}")
    return candidate


def _run(step: int, name: str, command: list, log: Path, started: float) -> int:
    print(f"Step {step} of {STEPS}: {name} ...", flush=True)
    with log.open("w", encoding="utf-8") as handle:
        done = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, check=False)
    print(f"   done in {time.time() - started:.0f} s from the start (details: {log})", flush=True)
    return done.returncode


def _row_of(layout: Layout, source_name: str) -> Optional[dict]:
    import csv

    try:
        with layout.triage_csv.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("source", "").endswith(source_name):
                    return dict(row)
    except OSError:
        return None
    return None


def _record_of(layout: Layout) -> Optional[dict]:
    path = layout.results / "store_verification.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries") or []
    except (OSError, ValueError):
        return None
    return entries[0] if entries else None


_EXIT = {"green": 0, "amber": 1, "red": 2, "blue": 3}


def main(argv: Optional[Sequence[str]] = None) -> int:
    from umat_oti.app import check_command as check
    from umat_oti.app import front_door

    check._RUN.clear()
    args_in = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(args_in)
    except VerifyUsage as error:
        return check._fail(f"umat-oti verify: {error}.")
    if args.help or args.source is None:
        print(HELP)
        return 0 if args.help else 2
    source = args.source.expanduser().resolve()
    if not source.is_file():
        return check._fail(check.TEXT["no_file"].format(path=source))
    front_door.make_this_code_visible_to_children()

    from umat_oti.app import check_intake as intake

    facts = intake.scan_source(source)
    if not facts.has_umat:
        check.print_card("not_a_umat", f"this file is {facts.other_kind}, not a UMAT" if facts.other_kind
                         else "no SUBROUTINE UMAT in this file")
        return 2
    deck = (args.deck or args.target)
    if deck is None:
        no_deck_card()
        return 3
    deck = deck.expanduser().resolve()
    if not deck.is_file():
        return check._fail(f"I cannot find the deck {deck}.")
    note, unusable = check.deck_note(deck)
    if note:
        print(note)
    if unusable or not intake.contains_user_material(deck):
        deck_without_constants_card("the deck is empty" if unusable else "it has no *USER MATERIAL block")
        return 3
    roots = [d.expanduser().resolve() for d in args.dependency_root]
    # the constants must be readable card by card, as Abaqus reads them; never a default
    scanner = check.load_scanner()
    if scanner is not None:
        found = scanner.scan(source, deck, roots=roots)
        stop = [i for i in check.blocking_items(found, constants_supplied=False) if i.key == "props_values"]
        if stop:
            from umat_oti.app.check_compact import amber_notes

            for line in amber_notes(found):
                print(line)
            deck_without_constants_card(str(stop[0].note or "the numbers could not be read as Abaqus reads them"))
            return 3
    if shutil.which("abaqus") is None:
        no_abaqus_card()
        return 3
    if shutil.which("gfortran") is None:
        _card("BLUE", "I NEED ONE THING FROM YOU", "Install gfortran (for example `apt install gfortran`) and run again.",
              "gfortran is needed to compile and replay the original routine.", "you")
        return 3
    import umat_oti

    tools = Path(umat_oti.__file__).resolve().parents[2] / "tools"
    if not (tools / "verify_store_in_abaqus.py").is_file():
        _card("BLUE", "I NEED ONE THING FROM YOU",
              "Run this from a checkout of umat-oti (the folder that has a tools/ folder): python umat-oti verify ...",
              "This installed copy has no tools/ folder, which holds the six checks.", "you")
        return 3

    out = _out_dir(source, args.out)
    layout = Layout(out)
    started = time.time()
    print("This runs the six checks that make a file verified, on your files, in Abaqus, in a scratch folder.")
    print(f"Scratch folder: {out}   (nothing is written to any shared store or to the corpus)")
    build_scratch(layout, source, deck, roots)
    check._RUN.update(source=source, deck=deck, out=out, roots=roots)

    steps = commands(layout, source.name, tools, args.timeout)
    codes = []
    for number, (name, command) in enumerate(steps, start=1):
        codes.append(_run(number, name, command, layout.logs / f"step{number}.log", started))
        if number == 1 and codes[-1] != 0:
            break
        if number == 2:
            row = _row_of(layout, source.name)
            if row is not None and row.get("stage") not in ("transformed",):
                state = "not_a_umat" if row.get("stage") == "not_a_umat" else "transform_refused"
                check.print_card(state, row.get("blocker") or row.get("stage") or "")
                _cleanup(layout, args.keep_work)
                return 2
            if codes[-1] != 0:
                break
    record = _record_of(layout)
    if record is None:
        check.print_card("harness_error", "no result was recorded; see " + str(layout.logs))
        _cleanup(layout, args.keep_work)
        return 2

    from umat_oti.app.verdict_page import render_verdict, verdict_for

    verdict = verdict_for(record)
    print("\n" + render_verdict(record))
    print(f"\nWhat was run: {SCRATCH_REPOSITORY}/{source.name} with {deck.name}, in {time.time() - started:.0f} s.")
    print(f"The full record of the six checks: {layout.results / 'store_verification.json'}")
    _cleanup(layout, args.keep_work)
    return _EXIT.get(verdict["colour"], 1)


def _cleanup(layout: Layout, keep_work: bool) -> None:
    """The Abaqus working folders are large; the results, the logs and the small scratch corpus stay."""
    if not keep_work:
        shutil.rmtree(layout.work, ignore_errors=True)
        shutil.rmtree(layout.triage_work, ignore_errors=True)
        shutil.rmtree(layout.transform_work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
