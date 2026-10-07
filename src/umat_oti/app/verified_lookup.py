"""What the corpus record already says about this exact file.

``umat-oti check`` cannot re-run the Abaqus checks that "verified" needs, so a file that was
verified in a corpus run comes out of ``check`` amber or blue. This module looks the file up by
content: the SHA-256 of the UMAT and, when a deck is given, of the deck. One byte of difference
and there is no match. The table it reads (``docs/evidence/verified_digests.json``, built from
the corpus registry by ``tools/build_verified_digest_table.py``) is small enough to ship.

A match is shown as a SEPARATE line. It is green only when the row's state is fully_verified AND
the verdict page's own rule (:func:`umat_oti.app.verdict_page.verdict_for`, which asks
``may_say_verified`` of the recorded gates) says green; every other row shows its state and its
card in the colour that card has. It never changes what ``check`` itself found.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from umat_oti.app.verdict_page import verdict_for

__all__ = ["Match", "lookup", "find_rows", "judge", "render", "table_path", "load_table", "record_of"]

_GATE_WORD = {"true": True, "false": False}
_COLOUR = {"green": "GREEN", "amber": "AMBER", "blue": "BLUE", "red": "RED"}


def table_path() -> Path:
    """The digest table of a checkout (``<root>/docs/evidence/verified_digests.json``)."""
    import umat_oti

    return Path(umat_oti.__file__).resolve().parents[2] / "docs" / "evidence" / "verified_digests.json"


_CACHE: dict = {}


def load_table(path: Optional[Path] = None) -> Optional[dict]:
    path = Path(path) if path is not None else table_path()
    key = str(path)
    if key not in _CACHE:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        _CACHE[key] = data
    return _CACHE[key]


def _digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_of(row: dict) -> dict:
    """The row as the verdict page reads a record: its terminal state, reason and six-gate block."""
    evidence = {name: _GATE_WORD.get(str(value).lower()) for name, value in (row.get("gates") or {}).items()}
    return {"terminal_state": row["state"], "reason": row.get("reason", ""), "evidence": evidence}


@dataclass
class Match:
    rows: list                 # the registry rows whose content matched
    deck_compared: bool        # the deck's bytes were compared too
    colour: str                # "green" only if EVERY matched row is green
    verdicts: list            # verdict_for of each row


def find_rows(table: dict, sha: str, deck_sha: Optional[str] = None) -> list:
    """The rows with this UMAT digest and, when ``deck_sha`` is given, this deck digest too."""
    rows = [r for r in table["rows"] if r["sha256"] == sha]
    if deck_sha is not None:
        rows = [r for r in rows if r.get("deck_sha256") and r["deck_sha256"] == deck_sha]
    return rows


def judge(rows: list, *, deck_compared: bool) -> Match:
    verdicts = [verdict_for(record_of(r)) for r in rows]
    # green only when every matched row is green AND says fully_verified: a row that is not
    # verified can never make the line green, however the others read
    all_green = all(v["colour"] == "green" and r["state"] == "fully_verified" for r, v in zip(rows, verdicts))
    colour = "green" if all_green else next((v["colour"] for v in verdicts if v["colour"] != "green"), "amber")
    return Match(rows=rows, deck_compared=deck_compared, colour=colour, verdicts=verdicts)


def lookup(umat: Path, deck: Optional[Path] = None, *, table: Optional[dict] = None) -> Optional[Match]:
    """The rows whose UMAT (and deck, when one is given) are byte for byte these files, or None."""
    table = table if table is not None else load_table()
    if not table:
        return None
    try:
        sha = _digest(umat)
        deck_sha = _digest(deck) if deck is not None else None
    except OSError:
        return None
    rows = find_rows(table, sha, deck_sha)
    if not rows:
        return None
    return judge(rows, deck_compared=deck_sha is not None)


def _date(table: dict) -> str:
    return str(table.get("registry_generated", ""))[:10]


def render(match: Match, *, table: Optional[dict] = None) -> list:
    """The lines to print, the first carrying the colour word."""
    table = table if table is not None else load_table()
    date = _date(table)
    word = _COLOUR[match.colour]
    rows, verdicts = match.rows, match.verdicts
    how = ("the UMAT and the deck match the record byte for byte" if match.deck_compared
           else "the UMAT matches the record byte for byte; no deck was given")
    if len(rows) == 1:
        row, verdict = rows[0], verdicts[0]
        if match.colour == "green":
            return [f"{word}: This exact file was verified on {date} in run {row['run']}: {row['state']}.",
                    f"  ({how}; verified there means all six Abaqus checks held, in that run's test only.)"]
        lines = [f"{word}: This exact file is in the corpus record (run {row['run']}, {date}) as {row['state']}, "
                 "not as verified.",
                 f"  {verdict['sentence']}",
                 f"  Whose move: {verdict['whose move']}.  Next: {verdict['next action']}",
                 f"  ({how}.)"]
        return lines
    states = sorted({r["state"] for r in rows})
    count = sum(1 for r in rows if r["state"] == "fully_verified")
    runs = ", ".join(sorted({r["run"] for r in rows}))
    if match.deck_compared:
        return [f"{word}: These exact files are in the corpus record {len(rows)} times, in different folders (run {runs}, {date}): "
                f"{count} verified, states: {', '.join(states)}.",
                f"  ({how}.)"]
    return [f"{word}: This exact UMAT file is in the corpus record {len(rows)} times (run {runs}, {date}), with different decks: "
            f"{count} verified, states: {', '.join(states)}.",
            "  Give the deck you use (it is compared byte for byte) to see which one applies.",
            f"  ({how}.)"]
