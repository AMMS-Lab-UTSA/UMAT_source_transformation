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

__all__ = ["Match", "lookup", "find_rows", "judge", "render", "verified_elsewhere", "table_path", "load_table", "record_of"]

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


def verified_elsewhere(match: Optional[Match]) -> Optional[str]:
    """The run id when EVERY matched row is fully verified (green by the verdict rule), else None."""
    if match is not None and match.colour == "green":
        return ", ".join(sorted({r["run"] for r in match.rows})) or None
    return None


def _clause(text: str, limit: int = 170) -> str:
    """The first sentence of ``text``, lower-cased at its start, for a muted line."""
    first = str(text or "").strip().split(". ")[0].rstrip(".")
    first = first[:1].lower() + first[1:] if first else first
    return first[:limit]


def render(match: Match, *, final: Optional[str] = None, why: str = "", table: Optional[dict] = None) -> list:
    """The record line, printed AFTER the verdict of this run and never as a verdict.

    It carries no colour word: the colour of ``check`` is the one on the verdict banner. ``final``
    is the colour of that verdict (``None`` when there was none), ``why`` the reason this run
    could not repeat a verified result.
    """
    table = table if table is not None else load_table()
    date = _date(table)
    rows, verdicts = match.rows, match.verdicts
    runs = ", ".join(sorted({r["run"] for r in rows}))
    how = ("the UMAT and the deck match the record byte for byte" if match.deck_compared
           else "the UMAT matches the record byte for byte; no deck was given")
    if len(rows) == 1:
        row, verdict = rows[0], verdicts[0]
        if match.colour == "green":
            if final == "green":
                return [f"On record: this exact file was also verified earlier (run {row['run']}, {date}); {how}."]
            reason = _clause(why) or "this quick check does not run the Abaqus checks"
            return [f"On record: this exact file was verified earlier (run {row['run']}, {date}: {row['state']}). "
                    f"This run could not repeat it: {reason}.",
                    f"  ({how}.)"]
        return [f"On record: this exact file ended as {row['state']} in run {row['run']} ({date}), not as verified. "
                f"{verdict['sentence']}",
                f"  ({how}.)"]
    states = sorted({r["state"] for r in rows})
    count = sum(1 for r in rows if r["state"] == "fully_verified")
    if match.deck_compared:
        head = (f"On record: these exact files appear {len(rows)} times in the corpus record, in different folders "
                f"(run {runs}, {date}): {count} verified, states: {', '.join(states)}.")
    else:
        head = (f"On record: this exact UMAT file appears {len(rows)} times in the corpus record (run {runs}, {date}), "
                f"with different decks: {count} verified, states: {', '.join(states)}. "
                "Give the deck you use (it is compared byte for byte) to see which one applies.")
    if match.colour == "green" and final != "green":
        head += f" This run could not repeat it: {_clause(why) or 'this quick check does not run the Abaqus checks'}."
    return [head, f"  ({how}.)"]
